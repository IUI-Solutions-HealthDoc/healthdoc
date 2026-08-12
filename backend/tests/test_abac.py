from app.common.abac import _condition_holds


def test_same_facility_allows_matching():
    assert _condition_holds({"same_facility": True}, "F1", {"facility_id": "F1"}) is True


def test_same_facility_blocks_mismatch():
    assert _condition_holds({"same_facility": True}, "F2", {"facility_id": "F1"}) is False


def test_no_condition_passes():
    assert _condition_holds(None, None, {}) is True


def test_unevaluable_condition_returns_none():
    """Missing required attrs → unevaluable → None (enforce treats as deny)."""
    assert _condition_holds({"same_facility": True}, None, {"facility_id": "F1"}) is None
    # both missing
    assert _condition_holds({"same_facility": True}, None, {}) is None


def test_unknown_condition_denies_as_unevaluable():
    assert _condition_holds({"same_department": True}, "F1", {"facility_id": "F1"}) is None
