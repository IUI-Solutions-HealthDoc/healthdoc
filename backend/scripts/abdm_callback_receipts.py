"""Local operator-only receipt inspection. No HTTP endpoint or clinical payload export.

Requires existing host/container database and crypto access. Default output is
metadata only; --details requires an exact receipt ID and decrypts ONLY the
privacy-minimised body/header/IP snapshot. No bearer/link tokens can be exported.
"""

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.common.db import SessionLocal
from app.common.security import decrypt_pii
from app.integrations.abdm.callback_evidence import AbdmCallbackReceipt, aad


async def inspect_receipts(ident=None, request_id=None, details=False, limit=20):
    if details and ident is None:
        raise ValueError("--details requires --id")
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        query = select(AbdmCallbackReceipt).where(AbdmCallbackReceipt.expires_at > datetime.now(UTC))
        if ident:
            query = query.where(AbdmCallbackReceipt.id == ident)
        if request_id:
            query = query.where(
                (AbdmCallbackReceipt.request_id == request_id)
                | (AbdmCallbackReceipt.response_request_id == request_id)
            )
        rows = (await db.execute(query.order_by(AbdmCallbackReceipt.received_at.desc()).limit(limit))).scalars()
        output = []
        for row in rows:
            item = {key: getattr(row, key) for key in (
                "id", "received_at", "completed_at", "expires_at", "request_id",
                "response_request_id", "path", "method", "status_code", "request_bytes",
            )}
            item["nha_origin_verified"] = False
            if details:
                item["redacted_evidence"] = json.loads(decrypt_pii(
                    row.evidence_encrypted, associated_data=aad(row.id)))
            output.append(item)
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=uuid.UUID)
    parser.add_argument("--request-id", type=uuid.UUID)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    args = parser.parse_args()
    if args.details and args.id is None:
        parser.error("--details requires --id")
    print(json.dumps(asyncio.run(inspect_receipts(
        args.id, args.request_id, args.details, args.limit)), default=str, indent=2))
