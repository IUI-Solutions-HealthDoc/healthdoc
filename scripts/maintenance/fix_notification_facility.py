#!/usr/bin/env python3
"""notification_history has no facility_id. Add it, backfill it, populate it.

Run from the repo root on a branch off staging. Idempotent.

WHY
---
notification_history stores event_type, payload and a NULLABLE department_id.
There is no facility column, so there is no way to answer "which facility does
this row belong to" for a row whose department_id is NULL, and no way to scope
a read query at all.

Nothing exposes it yet — app/notifications/router.py is still a /ping stub —
so this is latent rather than live. That is exactly why now is the moment:
issue #230 (notification history API + per-role preferences) is assigned and
unstarted, and the first query written against this table will either be
facility-scoped or will leak every facility's notifications to every reader.

§3 doesn't specify facility_id either, so this is a spec gap rather than an
implementation deviation. §3 is updated alongside.

THE APPEND-ONLY TRIGGER
-----------------------
0020 installs trg_notification_history_block_update, which raises on UPDATE or
DELETE. A backfill is an UPDATE, so the trigger has to come off, the backfill
run, and the trigger go back on — in that order, in one migration. Adding the
column without that would mean either a permanently nullable facility_id or a
migration that fails on any database with rows in it.

NUMBERING
---------
0038 is Aditya's doctor_reviews (#361 — written, ready, keeps the slot).
0039 is this. guardian_verification moves 0038 -> 0040; it is still unwritten,
and ready work takes the number.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
if not (ROOT / "backend/migrations/versions").is_dir():
    sys.exit("run me from the repo root")

changed = []

# --------------------------------------------------------------- migration
MIGRATION = ROOT / "backend/migrations/versions/0039_notification_history_facility_id.py"
MIGRATION_BODY = '''"""0039 notification_history.facility_id

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-11

notification_history had event_type, payload and a nullable department_id, and
no facility column at all. A row whose department_id is NULL could not be
attributed to a facility, and no read query could be scoped to one.

Nothing reads the table yet — app/notifications/router.py is a /ping stub — so
nothing has leaked. The fix lands now because #230 (notification history API)
is assigned and unstarted, and the first SELECT written against this table
either scopes by facility or serves every facility's notifications to every
reader. Adding the column after that endpoint exists means fixing an endpoint
as well as a table.

department_id stays nullable on purpose. A facility-wide announcement has a
facility and no department; a queue event has both. Making department_id NOT
NULL would rule out the first case. facility_id is NOT NULL because there is
no notification that belongs to no facility.

The backfill has to fight 0020's append-only trigger, which raises on UPDATE.
It comes off, the backfill runs, it goes back on. SET NOT NULL is deliberately
the last step and is deliberately not defensive: if any row survives the
backfill with a NULL facility_id, that means a notification exists that cannot
be attributed to a facility, and this migration should fail loudly rather than
leave the column nullable and the question open.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The trigger raises on UPDATE, and the backfill below is an UPDATE.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notification_history_block_update "
        "ON notification_history"
    )

    op.add_column(
        "notification_history",
        sa.Column("facility_id", UUID(as_uuid=True), nullable=True),
    )

    # Every existing row was written by the queue or pathology path, and both
    # set department_id, so departments is a complete source for them.
    op.execute(
        """
        UPDATE notification_history AS n
           SET facility_id = d.facility_id
          FROM departments AS d
         WHERE d.id = n.department_id
           AND n.facility_id IS NULL
        """
    )

    # Fails if anything is left NULL. That is the intent: an unattributable
    # notification is a bug to surface, not a NULL to tolerate.
    op.alter_column("notification_history", "facility_id", nullable=False)

    op.create_foreign_key(
        "fk_notification_history_facility_id",
        "notification_history", "facilities",
        ["facility_id"], ["id"], ondelete="RESTRICT",
    )
    # (facility_id, created_at): every read of this table is "recent
    # notifications for my facility", which is what #230 will ask for.
    op.create_index(
        "ix_notification_history_facility_id_created_at",
        "notification_history", ["facility_id", "created_at"],
    )

    op.execute(
        """
        CREATE TRIGGER trg_notification_history_block_update
        BEFORE UPDATE OR DELETE ON notification_history
        FOR EACH ROW EXECUTE FUNCTION trg_notification_history_block_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notification_history_block_update "
        "ON notification_history"
    )
    op.drop_index(
        "ix_notification_history_facility_id_created_at",
        table_name="notification_history",
    )
    op.drop_constraint(
        "fk_notification_history_facility_id",
        "notification_history", type_="foreignkey",
    )
    op.drop_column("notification_history", "facility_id")
    op.execute(
        """
        CREATE TRIGGER trg_notification_history_block_update
        BEFORE UPDATE OR DELETE ON notification_history
        FOR EACH ROW EXECUTE FUNCTION trg_notification_history_block_update()
        """
    )
'''

if MIGRATION.exists():
    print("~ 0039 migration already exists")
else:
    MIGRATION.write_text(MIGRATION_BODY)
    changed.append(str(MIGRATION))
    print("+ wrote 0039_notification_history_facility_id.py")


def patch(path, old, new, label):
    p = ROOT / path
    if not p.exists():
        print(f"! {path} missing"); return False
    t = p.read_text()
    if new in t:
        print(f"~ {label}: already applied"); return True
    if old not in t:
        print(f"! {label}: pattern not found — apply by hand"); return False
    p.write_text(t.replace(old, new, 1))
    changed.append(path)
    print(f"+ {label}: patched")
    return True


ok = True

# ------------------------------------------------------------------- model
ok &= patch(
    "backend/app/notifications/models.py",
    '    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)',
    '    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)\n'
    '    # NOT NULL: every notification belongs to a facility. department_id stays\n'
    '    # nullable because a facility-wide announcement has no department.\n'
    '    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=False)',
    "notifications/models.py",
)

# ----------------------------------------------------------- queue writer
ok &= patch(
    "backend/app/queue/service.py",
    '    db.add(NotificationHistory(\n'
    '        id=uuid.uuid4(),\n'
    '        event_type="token_called",\n'
    '        payload=payload,\n'
    '        department_id=queue.department_id,\n'
    '    ))',
    '    db.add(NotificationHistory(\n'
    '        id=uuid.uuid4(),\n'
    '        event_type="token_called",\n'
    '        payload=payload,\n'
    '        department_id=queue.department_id,\n'
    '        # The queue\'s facility, not the caller\'s — an admin acting across\n'
    '        # facilities must not file this row under their own.\n'
    '        facility_id=queue.facility_id,\n'
    '    ))',
    "queue/service.py token_called",
)

# ------------------------------------------------------- pathology writer
ok &= patch(
    "backend/app/pathology/router.py",
    '    notification = NotificationHistory(\n'
    '        event_type="lab_critical_result",\n'
    '        payload={\n'
    '            "lab_order_item_id": str(item.id),\n'
    '            "accession_number": item.accession_number,\n'
    '            "flagged_field_count": len(flagged_fields),\n'
    '        },\n'
    '        department_id=item.department_id,\n'
    '    )',
    '    # facility comes off the order, not the caller and not the department:\n'
    '    # lab_order_items.department_id is nullable, orders.facility_id is not\n'
    '    # (0022). A critical-result alert belongs to the facility that ran the\n'
    '    # test, whoever happens to be entering the result.\n'
    '    from app.orders.models import Order\n'
    '    order = await db.get(Order, item.order_id)\n'
    '\n'
    '    notification = NotificationHistory(\n'
    '        event_type="lab_critical_result",\n'
    '        payload={\n'
    '            "lab_order_item_id": str(item.id),\n'
    '            "accession_number": item.accession_number,\n'
    '            "flagged_field_count": len(flagged_fields),\n'
    '        },\n'
    '        department_id=item.department_id,\n'
    '        facility_id=order.facility_id,\n'
    '    )',
    "pathology/router.py lab_critical_result",
)

# -------------------------------------------------------------- docs §2/§3
DOC = ROOT / "docs/database-schema.md"
if DOC.exists():
    t = DOC.read_text()
    before = t

    old_row = re.search(r"^\| 0038 \| guardian_verification \|.*$", t, re.M)
    if old_row and "| 0039 | notification_history_facility_id" not in t:
        t = t.replace(
            old_row.group(0),
            "| 0038 | doctor_reviews | doctor_reviews | B3 (W4) — #361, written against this number |\n"
            "| 0039 | notification_history_facility_id | ALTER notification_history: facility_id NOT NULL | B4 — no facility column meant no way to scope #230's read API |\n"
            "| 0040 | guardian_verification | ALTER patients: is_minor, guardian_verified, guardian_verification_method | B2 (W3) — moved from 0038; ready work takes the number |",
            1,
        )
        print("+ §2 map: 0038 doctor_reviews, 0039 this, guardian -> 0040")

    # §2 names doctor_reviews, so §3 must define it or spec_check fails. The
    # block is transcribed from #361's migration, not designed here — that PR
    # owns the table and should adjust this if it changes.
    DR_ANCHOR = "\n## 4. API field contract (backend → frontend)"
    DR_BLOCK = '''
### 0038 — doctor_reviews (B3, W4)

**doctor_reviews** (0038, B3) — doctor sign-off on an encounter and on individual
lab/radiology results. Transcribed from #361; that PR owns this table.
```
encounter_id UUID NOT NULL → encounters
reviewed_by UUID NOT NULL → users
lab_order_item_id UUID NULL → lab_order_items
radiology_order_item_id UUID NULL → radiology_order_items
status varchar(50) NOT NULL DEFAULT 'pending'   -- pending|reviewed|signed_off
notes text · signed_off_at timestamptz
```
Both result FKs are nullable: a review can cover the encounter as a whole, or one
specific result. `signed_off_at` is separate from `status` because the timestamp is
the auditable fact — NABH asks when a result was seen, not what a column says now.

### 0039 — notification_history.facility_id (B4)

```
ALTER notification_history ADD facility_id UUID NOT NULL → facilities
INDEX ix_notification_history_facility_id_created_at (facility_id, created_at)
```
The table had no facility column, so a row with a NULL `department_id` could not be
attributed and no read could be scoped. Added before #230 builds the read API rather
than after, because the alternative is fixing an endpoint as well as a table.

'''
    if "**doctor_reviews**" not in t and DR_ANCHOR in t:
        t = t.replace(DR_ANCHOR, DR_BLOCK + DR_ANCHOR, 1)
        print("+ §3 blocks added for doctor_reviews (0038) and 0039")

    old_block = ("department_id UUID NULL → departments\n"
                 "```\n"
                 "Append-only by convention (internal writes only; no update endpoint).")
    new_block = ("department_id UUID NULL → departments\n"
                 "facility_id UUID NOT NULL → facilities        -- added 0039\n"
                 "```\n"
                 "Append-only by convention (internal writes only; no update endpoint).\n"
                 "`facility_id` is NOT NULL and `department_id` is not: a facility-wide\n"
                 "announcement has no department, but no notification belongs to no facility.\n"
                 "**Every read of this table must filter on `facility_id`** — the payloads are\n"
                 "operational detail about one hospital's queues and results.")
    if new_block not in t and old_block in t:
        t = t.replace(old_block, new_block, 1)
        print("+ §3 notification_history block updated")

    if t != before:
        DOC.write_text(t)
        changed.append(str(DOC))
else:
    print("! docs/database-schema.md missing")

print()
print("changed:" if changed else "nothing changed")
for c in changed:
    print("   ", c)
sys.exit(0 if ok else 1)
