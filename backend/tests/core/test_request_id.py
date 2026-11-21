def test_generated_when_absent(client):
    r = client.get("/api/health")
    assert len(r.headers["x-request-id"]) == 32


def test_inbound_id_is_echoed(client):
    r = client.get("/api/health", headers={"X-Request-ID": "trace-abc.123"})
    assert r.headers["x-request-id"] == "trace-abc.123"
    assert r.json()["meta"]["request_id"] == "trace-abc.123"


def test_unsafe_inbound_id_is_replaced(client):
    r = client.get("/api/health", headers={"X-Request-ID": "bad id\r\nx" + "a" * 70})
    assert r.headers["x-request-id"] != "bad id"
    assert len(r.headers["x-request-id"]) == 32


def test_api_reference_lists_health(client):
    assert "/api/health" in client.get("/api/openapi.json").json()["paths"]
    assert client.get("/api/docs").status_code == 200
