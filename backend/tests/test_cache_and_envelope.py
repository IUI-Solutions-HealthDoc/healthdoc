from app.common.cache import _key


def test_cache_key_is_stable_and_prefixed():
    k1 = _key("caps", ("a", 1), {"x": 2})
    k2 = _key("caps", ("a", 1), {"x": 2})
    assert k1 == k2
    assert k1.startswith("cache:caps:")


def test_cache_key_varies_with_args():
    assert _key("caps", ("a",)) != _key("caps", ("b",))
