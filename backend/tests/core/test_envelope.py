import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from core.errors import GENERIC_MESSAGE, AppError
from core.log_config import mask


class Item(BaseModel):
    name: str


@pytest.fixture
def routes(app):
    @app.get("/t/app-error")
    def app_error():
        raise AppError(409, "chat_busy", "This chat is already running a turn.")

    @app.get("/t/http")
    def http():
        raise HTTPException(404, "No such thing.")

    @app.post("/t/validate")
    def validate(item: Item) -> Item:
        return item

    @app.get("/t/boom")
    def boom():
        raise RuntimeError("provider said: key sk-secret-abcdef123456 is invalid at /data/x")

    return app


def test_success_envelope(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"success": True, "data": {"status": "ok"}, "meta": {"request_id": r.headers["x-request-id"]}}


def test_app_error(routes, client):
    r = client.get("/t/app-error")
    assert r.status_code == 409
    assert r.json()["error"] == {"code": "chat_busy", "message": "This chat is already running a turn.", "details": None}
    assert r.json()["success"] is False
    assert r.json()["meta"]["request_id"] == r.headers["x-request-id"]


def test_http_exception(routes, client):
    r = client.get("/t/http")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert r.json()["error"]["message"] == "No such thing."


def test_unknown_route(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["success"] is False


def test_validation_error_lists_fields_not_input(routes, client):
    r = client.post("/t/validate", json={"name": 123456789, "other": "secret-value"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"]["errors"][0]["field"] == "body.name"
    assert "123456789" not in r.text


def test_unexpected_exception_is_generic(routes, client, caplog):
    r = client.get("/t/boom")
    assert r.status_code == 500
    assert r.json()["error"] == {"code": "internal_error", "message": GENERIC_MESSAGE, "details": None}
    assert "sk-secret" not in r.text and "/data/x" not in r.text
    assert r.json()["meta"]["request_id"] == r.headers["x-request-id"]


def test_mask_hides_provider_keys():
    out = mask("key sk-ant-api03-abcdefghijklmnop and Bearer xyz.abc and api_key=hunter2 and AIzaSyA1234567890abcdefghijk")
    assert "abcdefghijklmnop" not in out and "xyz.abc" not in out and "hunter2" not in out and "1234567890abc" not in out
