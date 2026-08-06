"""Async client for the self-hosted WHO ICD-11 API container (B3 consumes this).

Endpoints used (local container, no auth):
  GET /icd/release/11/{release}/{linearization}/search?q=...
  GET /icd/release/11/{release}/{linearization}/codeinfo/{code}

Results feed the doctor's diagnosis search; selections are stored on `diagnoses`
(icd_version='icd11', icd_code=stem, icd_uri, post_coordinated_code) and upserted
into the local `icd_codes` catalog for offline re-display.
"""
from typing import Any

import httpx

from app.common.config import get_settings

_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en",
    "API-Version": "v2",
}


class ICD11Client:
    def __init__(self) -> None:
        s = get_settings()
        self._base = f"{s.icd11_base_url.rstrip('/')}/icd/release/11/{s.icd11_release}/{s.icd11_linearization}"

    async def search(self, query: str, *, flat: bool = True, limit: int = 20) -> list[dict[str, Any]]:
        """Search the MMS linearization. Returns simplified entities for the UI."""
        params = {
            "q": query,
            "useFlexisearch": "true",
            "flatResults": str(flat).lower(),
            "highlightingEnabled": "false",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/search", params=params, headers=_HEADERS)
            resp.raise_for_status()
            entities = resp.json().get("destinationEntities", [])[:limit]
        return [
            {
                "code": e.get("theCode"),
                "title": _strip_tags(e.get("title", "")),
                "icd_uri": e.get("id"),                      # Foundation URI — permanent
                "is_postcoordinable": bool(e.get("postcoordinationAvailability")),
                "score": e.get("score"),
            }
            for e in entities
            if e.get("theCode")
        ]

    async def code_info(self, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/codeinfo/{code}", headers=_HEADERS)
            resp.raise_for_status()
            return resp.json()


def _strip_tags(value: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", value)
