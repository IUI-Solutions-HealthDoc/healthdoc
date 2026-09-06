"""Free beds held by synthetic e2e admissions, and re-mirror any that drifted.

`frontend/e2e/workflows.smoke.mjs` admits a patient and discharges them again,
so a completed run leaves the ward as it found it. A run that FAILS between
those two steps does not, and after a few such runs the ward is full and every
later run fails at "no vacant bed" — which looks like a product defect and is
not one.

Run inside the backend container:

    docker compose -f infra/docker-compose.yml exec -e PYTHONPATH=/code backend \
        python /scripts/maintenance/discharge_synthetic_admissions.py

The repo's scripts/ is mounted read-only at /scripts, and running a file by
path puts that directory on sys.path instead of the app's, hence PYTHONPATH.

Discharges only patients whose names carry the e2e prefixes. It will not touch
a seeded demo patient or anything a human entered. Development only.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

# Importing the app registers every model, so the cross-module foreign keys
# resolve before the first query is compiled.
import app.main  # noqa: F401
from app.admissions.models import Admission, Bed
from app.admissions.service import discharge_patient
from app.common.db import SessionLocal
from app.patients.models import Patient
from app.users.models import User

#: Names the browser workflows generate. Anything else is left alone.
SYNTHETIC_PREFIXES = ("Ward Test ", "Journey Test ", "Browser Test ")


async def main() -> None:
    async with SessionLocal() as db:
        actor = (await db.execute(select(User).limit(1))).scalars().first()
        if actor is None:
            raise SystemExit("No user to attribute the discharge to; seed the stack first.")

        rows = (
            await db.execute(
                select(Admission, Patient, Bed)
                .join(Patient, Patient.id == Admission.patient_id)
                .join(Bed, Bed.id == Admission.bed_id)
                .where(Admission.status == "admitted")
            )
        ).all()

        freed = 0
        remirrored = 0
        for admission, patient, bed in rows:
            if patient.full_name.startswith(SYNTHETIC_PREFIXES):
                # Through the service, so beds.status is maintained in the same
                # transaction rather than hand-patched in two places.
                await discharge_patient(
                    db,
                    admission,
                    discharge_type="discharged",
                    created_by=actor.id,
                    discharge_summary="Cleanup of a synthetic e2e admission.",
                )
                freed += 1
                print(f"discharged {patient.full_name!r} from bed {bed.bed_number}")
            elif bed.status != "occupied":
                # admissions is authoritative and beds.status is its mirror --
                # see admissions.service.reconcile_bed_status, which reports
                # this disagreement rather than resolving it.
                print(f"re-mirroring bed {bed.bed_number}: {bed.status} -> occupied")
                bed.status = "occupied"
                remirrored += 1

        await db.commit()
        print(f"{freed} bed(s) freed, {remirrored} mirror(s) corrected.")


if __name__ == "__main__":
    asyncio.run(main())
