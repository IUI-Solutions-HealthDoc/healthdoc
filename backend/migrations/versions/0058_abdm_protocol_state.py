"""0058 durable correlation and pagination for ABDM v3 callbacks.

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "abdm_care_context_links", sa.Column("transaction_id", sa.String(120), nullable=True)
    )
    op.add_column(
        "abdm_care_context_links",
        sa.Column(
            "care_context_references",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index("ix_abdm_links_transaction", "abdm_care_context_links", ["transaction_id"])

    op.add_column(
        "abdm_received_bundles",
        sa.Column("page_number", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "abdm_received_bundles",
        sa.Column("entry_index", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "abdm_received_bundles",
        sa.Column(
            "media_type", sa.String(100), nullable=False, server_default="application/fhir+json"
        ),
    )
    op.add_column(
        "abdm_received_bundles", sa.Column("declared_checksum", sa.String(128), nullable=True)
    )
    op.create_unique_constraint(
        "uq_abdm_received_bundle_page_entry",
        "abdm_received_bundles",
        ["hi_request_id", "page_number", "entry_index"],
    )
    op.add_column(
        "abdm_hiu_hi_requests", sa.Column("expected_page_count", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "abdm_hiu_hi_requests",
        sa.Column(
            "received_pages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("abdm_hiu_hi_requests", "received_pages")
    op.drop_column("abdm_hiu_hi_requests", "expected_page_count")
    op.drop_constraint(
        "uq_abdm_received_bundle_page_entry", "abdm_received_bundles", type_="unique"
    )
    op.drop_column("abdm_received_bundles", "declared_checksum")
    op.drop_column("abdm_received_bundles", "media_type")
    op.drop_column("abdm_received_bundles", "entry_index")
    op.drop_column("abdm_received_bundles", "page_number")
    op.drop_index("ix_abdm_links_transaction", table_name="abdm_care_context_links")
    op.drop_column("abdm_care_context_links", "care_context_references")
    op.drop_column("abdm_care_context_links", "transaction_id")
