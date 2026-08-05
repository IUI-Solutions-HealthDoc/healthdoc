from app.auth.deps import AuthUser
from app.common.abac import _condition_holds


def test_same_facility_allows_matching():
    u = AuthUser(sub="s", username="u", roles=["doctor"])
    attrs = {"facility_id": "F1", "user_facility_id": "F1"}
    assert _condition_holds({"same_facility": True}, u, attrs) is True


def test_same_facility_blocks_mismatch():
    u = AuthUser(sub="s", username="u", roles=["doctor"])
    attrs = {"facility_id": "F1", "user_facility_id": "F2"}
    assert _condition_holds({"same_facility": True}, u, attrs) is False


def test_no_condition_passes():
    u = AuthUser(sub="s", username="u", roles=["doctor"])
    assert _condition_holds(None, u, {}) is True


def test_unevaluable_condition_returns_none():
    """Missing required attrs → unevaluable → None (enforce treats as deny)."""
    u = AuthUser(sub="s", username="u", roles=["doctor"])
    # facility_id present but user_facility_id missing
    assert _condition_holds({"same_facility": True}, u, {"facility_id": "F1"}) is None
    # both missing
    assert _condition_holds({"same_facility": True}, u, {}) is None
