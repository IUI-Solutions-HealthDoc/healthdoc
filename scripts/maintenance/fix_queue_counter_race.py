#!/usr/bin/env python3
"""Fix the queue token allocator's race. Run from the repo root. Idempotent.

_allocate_token_number() did SELECT ... FOR UPDATE, and when the row didn't
exist yet, INSERT with an IntegrityError fallback that called db.rollback().

FOR UPDATE cannot lock a row that does not exist, so the first allocation of
each day for each department races. That much was survivable. The damage is
the fallback: db.rollback() ends the CALLER's transaction, not just the failed
INSERT. Anything the caller had already done is silently discarded, and the
next statement raises "Can't operate on closed transaction".

create_token() calls this after locking the queue and reading the department,
so in production the failure is: two patients take a token at the same moment
on the first token of the day, one request 500s, and the queue row lock is
dropped mid-flight.

Same bug and same fix as accession numbers (app/common/accession.py) and
billing's _allocate_billing_number. accession.py's docstring already spells
out why: "FOR UPDATE can only lock a row that already exists, which leaves
the first allocation of each day racing on the INSERT."
"""
import pathlib
import re
import sys

SVC = pathlib.Path("backend/app/queue/service.py")
if not SVC.exists():
    sys.exit("run me from the repo root")

text = SVC.read_text()
before = text

OLD = '''async def _allocate_token_number(db: AsyncSession, department_id: uuid.UUID, business_date: date) -> int:
    counter = (
        await db.execute(
            select(QueueCounter)
            .where(QueueCounter.department_id == department_id, QueueCounter.counter_date == business_date)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if counter is None:
        counter = QueueCounter(
            id=uuid.uuid4(), department_id=department_id, counter_date=business_date, last_value=0
        )
        db.add(counter)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            counter = (
                await db.execute(
                    select(QueueCounter)
                    .where(QueueCounter.department_id == department_id, QueueCounter.counter_date == business_date)
                    .with_for_update()
                )
            ).scalar_one()

    counter.last_value += 1
    await db.flush()
    return counter.last_value'''

NEW = '''async def _allocate_token_number(db: AsyncSession, department_id: uuid.UUID, business_date: date) -> int:
    """Allocate the next token number for a department on a business date.

    One statement, no read-then-write. SELECT ... FOR UPDATE cannot lock a row
    that does not exist, so the first allocation of each day was a genuine race
    — and the IntegrityError fallback called db.rollback(), which ends the
    *caller's* transaction, not just the failed INSERT. create_token() calls
    this holding a lock on the queue row, so the observable failure was: two
    patients take the first token of the day at the same moment, one request
    500s, and that request's earlier work is discarded.

    Same pattern as app/common/accession.py and billing's
    _allocate_billing_number. Not gapless, and not required to be — a token
    number is a display label, not a financial document.
    """
    upsert = (
        pg_insert(QueueCounter.__table__)
        .values(department_id=department_id, counter_date=business_date, last_value=1)
        .on_conflict_do_update(
            constraint="uq_queue_counter_department_date",
            set_={"last_value": QueueCounter.__table__.c.last_value + 1},
        )
        .returning(QueueCounter.__table__.c.last_value)
    )
    return (await db.execute(upsert)).scalar_one()'''

# The file carries trailing spaces on some blank lines, so match the whole
# function by its boundaries rather than by exact text.
FUNC = re.compile(
    r"^async def _allocate_token_number\(.*?\n(?:.*?\n)*?    return counter\.last_value$",
    re.M,
)

if "pg_insert(QueueCounter" in text:
    print("~ allocator already fixed")
elif FUNC.search(text):
    body = FUNC.search(text).group(0)
    for required in ("with_for_update", "db.rollback()", "IntegrityError"):
        if required not in body:
            sys.exit(f"! matched a function that lacks {required!r} — refusing to touch it")
    text = FUNC.sub(lambda _: NEW, text, count=1)
    print("+ _allocate_token_number rewritten as an upsert")
else:
    sys.exit("! _allocate_token_number does not match the expected shape — fix by hand")

IMP_OLD = "from sqlalchemy.exc import IntegrityError\nfrom sqlalchemy.ext.asyncio import AsyncSession"
IMP_NEW = ("from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
           "from sqlalchemy.ext.asyncio import AsyncSession")
if "pg_insert" not in text.split("PRIORITY_RANK")[0]:
    if IMP_OLD in text:
        text = text.replace(IMP_OLD, IMP_NEW, 1)
        print("+ imported pg_insert; dropped the now-unused IntegrityError import")
    else:
        print("! import block not as expected — add pg_insert by hand")

# Is IntegrityError still genuinely used, or does it only survive in prose?
# The replacement docstring names it, so a bare substring test says "yes" and
# leaves a dead import behind.
uses = re.findall(r"except\s+IntegrityError|raise\s+IntegrityError|IntegrityError\s*\(", text)
if uses:
    print(f"~ IntegrityError still used ({len(uses)} site(s)), import kept")
elif "from sqlalchemy.exc import IntegrityError\n" in text:
    text = text.replace("from sqlalchemy.exc import IntegrityError\n", "", 1)
    print("+ removed the now-dead IntegrityError import")

if text != before:
    SVC.write_text(text)
    print("\nwrote backend/app/queue/service.py")
else:
    print("\nnothing changed.")
