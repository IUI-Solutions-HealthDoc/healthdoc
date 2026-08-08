"""Blocker 5 (PR review, patients module): a half-merge is more dangerous
than no merge — this test turns a silently-missing repoint into a red
build. It needs no database connection; it inspects SQLAlchemy metadata
directly, so it works even without the async-Postgres fixture (see
conftest.py discussion in review)."""
import app.main  # noqa: F401  ensures every model module is imported and
                  # registered on Base.metadata before we inspect it
from app.patients.service import REPOINTED_ON_MERGE, AUDIT_TABLES_EXEMPT_FROM_REPOINTING, PENDING_REPOINT_OTHER_MODULES, _tables_with_fk_to_patients


def test_repointing_covers_every_patient_fk():
    referencing_tables = _tables_with_fk_to_patients()
    missing = referencing_tables - REPOINTED_ON_MERGE - AUDIT_TABLES_EXEMPT_FROM_REPOINTING - PENDING_REPOINT_OTHER_MODULES
    assert not missing, (
        f"{sorted(missing)} have a foreign key to patients.id but are not in "
        f"REPOINTED_ON_MERGE (backend/app/patients/service.py). Either add "
        f"repointing logic for them in approve_merge and add them to that set, "
        f"or confirm approve_merge still raises NotImplementedError while they "
        f"remain unhandled — this test existing and failing is the point, not "
        f"a bug to silence."
    )
