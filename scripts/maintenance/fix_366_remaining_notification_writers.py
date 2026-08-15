#!/usr/bin/env python3
"""Set facility_id on the notification_history writers #366 didn't know about.

Run from the repo root on fix/notification-history-facility-id. Idempotent.

WHY
---
0039 makes notification_history.facility_id NOT NULL. #366 updated the two
writers that existed when it was written — queue's token_called and
pathology's lab_critical_result. Three more landed on staging afterwards:

  queue/service.py    roster_availability_changed   (#356)
  queue/service.py    queue_paused / queue_resumed  (#356)
  pharmacy/service.py pharmacy_substitution         (raw SQL, #277)

Each takes facility_id from the RESOURCE, never from the caller:
  * roster    -> department.facility_id  (already fetched to authorize)
  * queue     -> queue.facility_id
  * pharmacy  -> encounters.facility_id, added to the SELECT that already
                 joins prescriptions to encounters for the doctor id

That distinction is the whole point of 0039. An admin acting across
facilities must not file another facility's notification under their own.
"""
import pathlib
import sys

ROOT = pathlib.Path(".")
if not (ROOT / "backend/app").is_dir():
    sys.exit("run me from the repo root")

changed = []


def patch(rel, old, new, label):
    p = ROOT / rel
    if not p.exists():
        print(f"! {rel} missing"); return False
    t = p.read_text()
    if new in t:
        print(f"~ {label}: already applied"); return True
    if old not in t:
        print(f"! {label}: pattern not found — apply by hand"); return False
    p.write_text(t.replace(old, new, 1))
    changed.append(rel)
    print(f"+ {label}")
    return True


ok = True

# ------------------------------------------- 1. roster availability changed
ok &= patch(
    "backend/app/queue/service.py",
    '''        db.add(NotificationHistory(
            id=uuid.uuid4(),
            event_type="roster_availability_changed",
            payload=payload,
            department_id=entry.department_id,
        ))''',
    '''        db.add(NotificationHistory(
            id=uuid.uuid4(),
            event_type="roster_availability_changed",
            payload=payload,
            department_id=entry.department_id,
            # The department's facility, not the caller's — an admin may act
            # across facilities and must not file this under their own.
            facility_id=department.facility_id,
        ))''',
    "queue: roster_availability_changed",
)

# ------------------------------------------------- 2. queue paused/resumed
ok &= patch(
    "backend/app/queue/service.py",
    '''    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type=event_type,
        payload=payload,
        department_id=queue.department_id,
    ))''',
    '''    db.add(NotificationHistory(
        id=uuid.uuid4(),
        event_type=event_type,
        payload=payload,
        department_id=queue.department_id,
        facility_id=queue.facility_id,
    ))''',
    "queue: queue_paused / queue_resumed",
)

# ------------------------------------------------ 3. pharmacy substitution
ok &= patch(
    "backend/app/pharmacy/service.py",
    """async def _write_notification(
    db: AsyncSession, *, recipient_user_id: UUID, notification_type: str,
    title: str, body: str, reference_type: str, reference_id: str,
) -> None:""",
    """async def _write_notification(
    db: AsyncSession, *, recipient_user_id: UUID, notification_type: str,
    title: str, body: str, reference_type: str, reference_id: str,
    facility_id: UUID,
) -> None:""",
    "pharmacy: _write_notification signature",
)

ok &= patch(
    "backend/app/pharmacy/service.py",
    """                INSERT INTO notification_history
                    (id, event_type, payload)
                VALUES
                    (:id, :event_type, CAST(:payload AS jsonb))""",
    """                INSERT INTO notification_history
                    (id, event_type, payload, facility_id)
                VALUES
                    (:id, :event_type, CAST(:payload AS jsonb), :facility_id)""",
    "pharmacy: INSERT columns",
)

ok &= patch(
    "backend/app/pharmacy/service.py",
    """                "id": str(uuid4()),
                "event_type": notification_type,""",
    """                "id": str(uuid4()),
                "event_type": notification_type,
                "facility_id": str(facility_id),""",
    "pharmacy: INSERT params",
)

# The SELECT already joins prescriptions to encounters for the doctor id, so
# the facility comes along for free — and from the encounter, which is the
# prescription's facility rather than whoever is dispensing.
ok &= patch(
    "backend/app/pharmacy/service.py",
    """            SELECT e.provider_user_id AS doctor_id
            FROM prescriptions p
            JOIN encounters e ON e.id = p.encounter_id
            WHERE p.id = :id""",
    """            SELECT e.provider_user_id AS doctor_id,
                   e.facility_id AS facility_id
            FROM prescriptions p
            JOIN encounters e ON e.id = p.encounter_id
            WHERE p.id = :id""",
    "pharmacy: SELECT facility_id",
)

ok &= patch(
    "backend/app/pharmacy/service.py",
    """        await _write_notification(
            db, recipient_user_id=row["doctor_id"], notification_type="pharmacy_substitution",
            title=title, body=body, reference_type="pharmacy_dispense_items",
            reference_id=reference_id,
        )""",
    """        await _write_notification(
            db, recipient_user_id=row["doctor_id"], notification_type="pharmacy_substitution",
            title=title, body=body, reference_type="pharmacy_dispense_items",
            reference_id=reference_id, facility_id=row["facility_id"],
        )""",
    "pharmacy: pass facility_id at the call site",
)

# --------------------------------------------------- 4. break-glass notify
# caller["facility_id"] is safe here specifically because the handler has
# already refused unless the patient belongs to that facility — so it is the
# patient's facility, not merely the caller's.
ok &= patch(
    "backend/app/security_audit/breakglass.py",
    """            INSERT INTO notification_history (id, event_type, payload, created_at)
            VALUES (uuid_generate_v4(), 'break_glass_used',
                    CAST(:p AS jsonb), :ts)""",
    """            INSERT INTO notification_history
                (id, event_type, payload, facility_id, created_at)
            VALUES (uuid_generate_v4(), 'break_glass_used',
                    CAST(:p AS jsonb), :fid, :ts)""",
    "breakglass: INSERT columns",
)

ok &= patch(
    "backend/app/security_audit/breakglass.py",
    """                               "expires_at": expires.isoformat()}),
               "ts": now})""",
    """                               "expires_at": expires.isoformat()}),
               "fid": caller["facility_id"],
               "ts": now})""",
    "breakglass: INSERT params",
)

print()
if changed:
    print("changed:")
    for c in dict.fromkeys(changed):
        print("   ", c)
else:
    print("nothing changed")

# Prove no writer was missed.
print("\nnotification_history writers still lacking facility_id:")
import re
missed = 0
for p in (ROOT / "backend/app").rglob("*.py"):
    src = p.read_text()
    flat = re.sub(r"\s*\n\s*", " ", src)
    for m in re.finditer(r"NotificationHistory\((?:[^()]|\([^()]*\))*?\)", flat):
        if "facility_id" not in m.group(0):
            print(f"   {p} :: {m.group(0)[:70]}"); missed += 1
    for m in re.finditer(r"INSERT INTO notification_history[^\"']{0,160}", flat):
        if "facility_id" not in m.group(0):
            print(f"   {p} :: {m.group(0)[:70]}"); missed += 1
if not missed:
    print("   none")

sys.exit(0 if ok else 1)
