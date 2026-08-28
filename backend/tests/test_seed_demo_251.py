"""Safety and determinism contracts for the #251 demo seed."""

from types import SimpleNamespace

import pytest

from app.common.db import Base
from app.consent.models import ConsentRecord
from scripts import seed_demo_251


@pytest.mark.parametrize("environment", ["dev", "demo", "local", "test"])
def test_demo_seed_accepts_only_explicit_demo_environments(monkeypatch, environment: str) -> None:
    monkeypatch.setattr(
        "app.common.config.get_settings",
        lambda: SimpleNamespace(environment=environment),
    )
    seed_demo_251._refuse_outside_demo()


def test_demo_seed_refuses_production(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.common.config.get_settings",
        lambda: SimpleNamespace(environment="production"),
    )
    with pytest.raises(SystemExit, match="Refusing to seed fabricated clinical data"):
        seed_demo_251._refuse_outside_demo()


def test_demo_seed_ids_are_stable_and_unique() -> None:
    ids = {
        value
        for name, value in vars(seed_demo_251).items()
        if name.endswith("_ID") and name != "FACILITY_ID"
    }
    assert len(ids) == 13


def test_demo_seed_registers_the_consent_manager_fk_target() -> None:
    assert "consent_managers" in Base.metadata.tables


@pytest.mark.asyncio
async def test_demo_seed_never_rewrites_an_existing_consent_record() -> None:
    existing = SimpleNamespace(status="granted", granted_at="original evidence")

    class SessionStub:
        added = None
        flushed = False

        async def get(self, model, row_id):
            assert model is ConsentRecord
            assert row_id == seed_demo_251.CONSENT_ID
            return existing

        def add(self, row) -> None:
            self.added = row

        async def flush(self) -> None:
            self.flushed = True

    session = SessionStub()
    result = await seed_demo_251._insert_consent_if_missing(
        session,
        status="revoked",
        granted_at="replacement evidence",
    )

    assert result is existing
    assert existing.status == "granted"
    assert existing.granted_at == "original evidence"
    assert session.added is None
    assert session.flushed is False
