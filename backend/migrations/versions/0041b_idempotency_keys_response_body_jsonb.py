"""0041b_idempotency_keys_response_body_jsonb

Revision ID: 0041b
Revises: 0041a
Create Date: 2026-08-14

Fixes a fourth schema gap found via #243. IdempotencyKey model
(app/common/idempotency_models.py) declares response_body as JSONB
(Mapped[dict | None]), but the real idempotency_keys table has it as
plain text (confirmed via \\d idempotency_keys). On idempotency replay,
the cached response is returned as a raw JSON string instead of a
parsed dict, which then fails FastAPI response_model validation with
"Input should be a valid dictionary or object to extract fields from."
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041b"
down_revision = "0041a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE idempotency_keys "
        "ALTER COLUMN response_body TYPE jsonb USING response_body::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE idempotency_keys "
        "ALTER COLUMN response_body TYPE text USING response_body::text"
    )