"""ICD-11 search with graceful degradation (B3 consumes this).

Three supported deployment modes (schema §3, ICD-11 edge footprint):
  1. local WHO ICD-API container   — full search + post-coordination
  2. shared district instance      — same, over the LAN/WAN (ICD11_BASE_URL points at it)
  3. catalog-only                  — NO container at all; search falls back to the seeded
                                     `icd_codes` table

Mode 3 matters: the `icd11` service runs behind a Docker Compose **profile**, so at a PHC
(or any dev machine that didn't opt in) the container simply is not there. Without the
fallback below, a doctor searching for a diagnosis mid-consultation gets a 500 — the
consultation flow breaks over an optional dependency. It must degrade, never fail.
"""
import logging
import re
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings

log = logging.getLogger("healthdoc.icd11")

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en",
    "API-Version": "v2",
}
TIMEOUT = 5.0  # a doctor is waiting; fail fast to the catalog rather than hang


class ICD11Client:
    def __init__(self) -> None:
        s = get_settings()
        self._base = (
            f"{s.icd11_base_url.rstrip('/')}"
            f"/icd/release/11/{s.icd11_release}/{s.icd11_linearization}"
        )
        self._degraded = False  # set once the container proves unreachable

    @property
    def degraded(self) -> bool:
        """True when running catalog-only (no ICD-API container reachable)."""
        return self._degraded

    async def search(
        self,
        query: str,
        *,
        db: AsyncSession | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search ICD-11. Returns {"items": [...], "source": "who_api"|"local_catalog"}.

        Never raises on an unreachable container — falls back to the local catalog so
        the doctor can still code the diagnosis.
        """
        if not self._degraded:
            try:
                return {"items": await self._search_who(query, limit), "source": "who_api"}
            except httpx.HTTPStatusError as exc:
                # The service answered but refused — do NOT latch degraded; it may recover.
                log.warning("ICD-11 API returned %s — using local catalog", exc.response.status_code)
            except Exception as exc:  # noqa: BLE001
                # Deliberately broad: connection refused, DNS failure, TLS/proxy
                # misconfiguration, unexpected client errors. A doctor is mid-consultation;
                # an optional dependency must never surface as a 500 here.
                self._degraded = True
                log.warning(
                    "ICD-11 API unavailable (%s: %s) — falling back to the local icd_codes "
                    "catalog. Search still works; post-coordination lookup does not.",
                    exc.__class__.__name__, exc,
                )

        if db is None:
            # No DB session to fall back to — return empty rather than 500 the consultation.
            return {"items": [], "source": "unavailable"}
        return {"items": await self._search_catalog(db, query, limit), "source": "local_catalog"}

    async def _search_who(self, query: str, limit: int) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "useFlexisearch": "true",
            "flatResults": "true",
            "highlightingEnabled": "false",
        }
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{self._base}/search", params=params, headers=_HEADERS)
            resp.raise_for_status()
            entities = resp.json().get("destinationEntities", [])[:limit]
        return [
            {
                "code": e.get("theCode"),
                "title": _strip_tags(e.get("title", "")),
                "icd_uri": e.get("id"),  # Foundation URI — permanent
                "is_postcoordinable": bool(e.get("postcoordinationAvailability")),
                "version": "icd11",
            }
            for e in entities
            if e.get("theCode")
        ]

    async def _search_catalog(
        self, db: AsyncSession, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Offline fallback: prefix/substring search over the seeded icd_codes table.

        Covers both ICD-11 and ICD-10 rows so a facility in catalog-only mode can still
        code — it just loses live post-coordination lookup from the WHO API.
        """
        rows = await db.execute(
            text(
                """
                SELECT code, title, icd_uri, is_postcoordinable, version
                FROM icd_codes
                WHERE is_active
                  AND (title ILIKE :like OR code ILIKE :prefix)
                ORDER BY (code ILIKE :prefix) DESC, version DESC, code
                LIMIT :lim
                """
            ),
            {"like": f"%{query}%", "prefix": f"{query}%", "lim": limit},
        )
        return [dict(r) for r in rows.mappings().all()]

    async def code_info(self, code: str) -> dict[str, Any] | None:
        """Post-coordination detail. Returns None in catalog-only mode (caller must
        handle it — the UI hides the post-coordination panel rather than erroring)."""
        if self._degraded:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(f"{self._base}/codeinfo/{code}", headers=_HEADERS)
                resp.raise_for_status()
                return resp.json()
        except Exception:  # noqa: BLE001 — same rule: degrade, never break the consultation
            self._degraded = True
            return None

    async def health(self) -> str:
        """'ok' | 'catalog_only' — surfaced by /health/deep so operators see the mode."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self._base}/search", params={"q": "a"}, headers=_HEADERS)
                return "ok" if r.status_code < 500 else "catalog_only"
        except Exception:  # noqa: BLE001 — any failure means we run catalog-only
            return "catalog_only"


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)
