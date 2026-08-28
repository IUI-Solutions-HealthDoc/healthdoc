"""The platform workspace is useful without crossing into facility clinical data."""

import uuid

import pytest

from app.auth.deps import AuthUser
from app.platform.router import list_platform_facilities
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def test_platform_lists_only_facility_metadata(db) -> None:
    facility = Facility(
        id=uuid.uuid4(),
        code=f"P{uuid.uuid4().hex[:5].upper()}",
        name="Platform Test Hospital",
        state_code="TS",
    )
    db.add(facility)
    await db.flush()

    result = await list_platform_facilities(
        _user=AuthUser(sub="platform-sub", roles=["superadmin"]),
        db=db,
        search="Platform Test",
        page=1,
        page_size=50,
    )

    assert result.total == 1
    assert result.items[0].id == facility.id
    assert "patient" not in result.items[0].model_dump()
    assert "clinical" not in result.items[0].model_dump()
