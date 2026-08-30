def test_health_envelope(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["error"] is None
    assert "request_id" in body["meta"]


def test_module_stub_mounted(client):
    """The patients module is mounted, and its stub is not public.

    This asserted an unauthenticated 200 until the /ping stubs were gated on
    `admin`. Updated rather than loosened, and the new assertion is the
    stronger one for what this test is actually for: 401 says the route EXISTS
    and refused the caller, where 404 would say it was never mounted. A test
    that accepted "not 200" would pass on an unmounted module and stop proving
    the thing it is named after.
    """
    resp = client.get("/api/v1/patients/ping")
    assert resp.status_code == 401, (
        f"expected 401 (mounted, gated); got {resp.status_code}. "
        "404 means the patients router is not mounted at all."
    )
