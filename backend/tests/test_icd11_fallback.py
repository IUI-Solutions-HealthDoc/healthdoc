import pytest
from app.integrations.icd11.client import ICD11Client


@pytest.mark.asyncio
async def test_search_degrades_instead_of_raising_when_container_absent():
    """The icd11 container runs behind a Compose profile — when it's absent the
    doctor's diagnosis search must still return, never 500."""
    c = ICD11Client()
    c._base = "http://127.0.0.1:59999/icd/release/11/2025-01/mms"  # nothing listening
    out = await c.search("diabetes", db=None)
    assert out["source"] == "unavailable"
    assert out["items"] == []
    assert c.degraded is True


@pytest.mark.asyncio
async def test_code_info_returns_none_when_degraded():
    c = ICD11Client()
    c._base = "http://127.0.0.1:59999/icd/release/11/2025-01/mms"
    assert await c.code_info("5A11") is None
    assert c.degraded is True


@pytest.mark.asyncio
async def test_health_reports_catalog_only():
    c = ICD11Client()
    c._base = "http://127.0.0.1:59999/icd/release/11/2025-01/mms"
    assert await c.health() == "catalog_only"
