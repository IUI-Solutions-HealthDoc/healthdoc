"""Register only explicitly selected, finalized historical ABDM documents.

Privileged maintenance command, not a browser authorization interface. Database
access authorizes execution; operator_id records attribution, not a role check.
Preview is the default. Apply requires the manifest's facility UUID again.
No gateway requests, patient linking, or consent changes are performed here.
Created contexts enqueue notifications: keep the delivery worker stopped until
the facility has approved sending them. See docs/abdm-historical-backfill.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from pydantic import ValidationError

import app.main  # noqa: F401 -- register models before resolving foreign keys
from app.common.db import SessionLocal
from app.integrations.abdm.hip.historical import (
    HistoricalManifest,
    HistoricalRefused,
    register_historical_documents,
)

MAX_MANIFEST_BYTES = 128 * 1024


def load_manifest(path: Path) -> HistoricalManifest:
    # Bound the actual read, not only stat(): the file can grow after stat().
    with path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise HistoricalRefused("manifest_too_large")
    return HistoricalManifest.model_validate_json(raw)


async def execute(manifest: HistoricalManifest, *, apply: bool) -> list[dict]:
    async with SessionLocal() as db:
        try:
            results = await register_historical_documents(db, manifest, apply=apply)
            output = [result.model_dump(mode="json") for result in results]
            if apply:
                await db.commit()
            else:
                await db.rollback()
            return output
        except BaseException:
            await db.rollback()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-facility", type=uuid.UUID)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.apply and args.confirm_facility != manifest.facility_id:
            raise HistoricalRefused("apply_requires_matching_facility_confirmation")
        items = asyncio.run(execute(manifest, apply=args.apply))
    except HistoricalRefused as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except (ValidationError, OSError):
        # Validation errors may echo clinical input, file contents, or paths.
        print(json.dumps({"error": "invalid_or_unreadable_manifest"}))
        return 2
    except Exception:
        # Driver errors can contain SQL parameters. A commit connection failure
        # can also have an uncertain outcome; never promise that nothing committed.
        print(json.dumps({"error": "transaction_not_confirmed_preview_before_retry"}))
        return 1
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "preview",
                "items": items,
                "delivery": "queued_only_worker_approval_required"
                if args.apply
                else "not_started",
            },
            indent=2,
        )
    )
    return 2 if any(item["status"] == "refused" for item in items) else 0


if __name__ == "__main__":
    raise SystemExit(main())
