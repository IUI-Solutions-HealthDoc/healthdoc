def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert "request_id" in body["meta"]


def test_openapi_lists_b1_routes(client):
    spec = client.get("/api/v1/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/health" in paths
    # B1 routers are mounted
    assert any("/break-glass" in p for p in paths)
    assert any("/abdm/abha/link" in p for p in paths)
