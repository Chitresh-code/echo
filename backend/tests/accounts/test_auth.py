"""Sign-in against a stand-in Microsoft: the tenant metadata and the code exchange are stubbed, but
the ID token is a real signed JWT, so Authlib's signature, audience, expiry, issuer and nonce checks run."""

import sqlite3
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.integrations.starlette_client import StarletteOAuth2App
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from core.config import get_settings
from core.db import db_path
from tests.conftest import TEST_ENV

TENANT = TEST_ENV["ECHO_MS_TENANT_ID"]
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})


@pytest.fixture
def microsoft(monkeypatch):
    """Answers the code exchange with an ID token built from `claims`, signed by `key`."""
    state = {"claims": {}, "key": KEY}

    async def metadata(self):
        return {
            "issuer": ISSUER,
            "authorization_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
            "token_endpoint": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            "jwks": KeySet([KEY]).as_dict(private=False),
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    async def exchange(self, **params):
        state["exchange"] = params
        return {"access_token": "at", "token_type": "Bearer", "id_token": jwt.encode({"alg": "RS256", "kid": "k1"}, state["claims"], state["key"])}

    monkeypatch.setattr(StarletteOAuth2App, "load_server_metadata", metadata)
    monkeypatch.setattr(StarletteOAuth2App, "fetch_access_token", exchange)
    return state


def claims(nonce, **overrides):
    now = int(time.time())
    return {
        "iss": ISSUER, "aud": TEST_ENV["ECHO_MS_CLIENT_ID"], "iat": now, "nbf": now, "exp": now + 3600,
        "sub": "pairwise-sub", "tid": TENANT, "oid": "33333333-3333-3333-3333-333333333333",
        "nonce": nonce, "name": "Ada Lovelace", "email": "ada@example.com", **overrides,
    }


def sign_in(client, microsoft, **overrides):
    login = client.get("/api/auth/login", follow_redirects=False)
    query = parse_qs(urlsplit(login.headers["location"]).query)
    microsoft["claims"] = claims(**{"nonce": query["nonce"][0], **overrides})
    return client.get(f"/api/auth/callback?code=the-code&state={query['state'][0]}", follow_redirects=False)


def error_of(response):
    assert response.status_code == 302
    return parse_qs(urlsplit(response.headers["location"]).query).get("error", [None])[0]


def test_login_redirects_to_the_tenant_with_pkce(client, microsoft):
    location = client.get("/api/auth/login", follow_redirects=False).headers["location"]
    url = urlsplit(location)
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    assert query["client_id"] == [TEST_ENV["ECHO_MS_CLIENT_ID"]] and query["scope"] == ["openid profile email"]
    assert query["redirect_uri"] == ["http://testserver/api/auth/callback"]
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] and query["nonce"]


def test_sign_in_creates_a_user_and_a_session(client, microsoft):
    r = sign_in(client, microsoft)
    assert r.status_code == 302 and r.headers["location"] == "/"
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("echo_session="))
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Secure" not in cookie
    # The PKCE verifier went to the token exchange.
    assert microsoft["exchange"]["code_verifier"]
    me = client.get("/api/auth/me").json()["data"]
    assert me["name"] == "Ada Lovelace" and me["email"] == "ada@example.com" and len(me["id"]) == 32

    # Only the hash of the token is stored.
    token = client.cookies["echo_session"]
    with sqlite3.connect(db_path(get_settings().data_dir)) as conn:
        assert token not in str(conn.execute("select * from sessions").fetchall())


def test_the_same_entra_user_keeps_one_account_and_email_is_not_the_key(client, microsoft):
    first = (sign_in(client, microsoft), client.get("/api/auth/me").json()["data"])[1]
    second = (sign_in(client, microsoft, email="renamed@example.com", name="Ada"), client.get("/api/auth/me").json()["data"])[1]
    assert second == {"id": first["id"], "name": "Ada", "email": "renamed@example.com"}
    # Another user with the first user's old email is a different account.
    sign_in(client, microsoft, oid="44444444-4444-4444-4444-444444444444", email="ada@example.com")
    assert client.get("/api/auth/me").json()["data"]["id"] != first["id"]


def test_secure_cookie_when_served_over_https(monkeypatch, microsoft):
    from fastapi.testclient import TestClient

    from main import create_app

    monkeypatch.setenv("ECHO_PUBLIC_URL", "https://testserver")
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="https://testserver") as client:
        r = sign_in(client, microsoft)
    assert "Secure" in next(c for c in r.headers.get_list("set-cookie") if c.startswith("echo_session="))


@pytest.mark.parametrize("overrides,code", [
    ({"tid": "99999999-9999-9999-9999-999999999999"}, "wrong_tenant"),
    ({"iss": "https://login.microsoftonline.com/99999999-9999-9999-9999-999999999999/v2.0"}, "sign_in_failed"),
    ({"nonce": "not-the-nonce"}, "sign_in_failed"),
    ({"aud": "some-other-app"}, "sign_in_failed"),
    ({"exp": int(time.time()) - 3600}, "sign_in_failed"),
    ({"oid": None}, "sign_in_failed"),
])
def test_bad_tokens_are_refused(client, microsoft, overrides, code):
    r = sign_in(client, microsoft, **overrides)
    assert error_of(r) == code and "echo_session" not in client.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_token_signed_by_another_key_is_refused(client, microsoft):
    microsoft["key"] = OTHER_KEY
    assert error_of(sign_in(client, microsoft)) == "sign_in_failed"


def test_callback_without_a_started_sign_in_is_refused(client, microsoft):
    microsoft["claims"] = claims("whatever")
    assert error_of(client.get("/api/auth/callback?code=c&state=forged", follow_redirects=False)) == "sign_in_failed"


def test_provider_error_is_not_passed_on(client, microsoft):
    client.get("/api/auth/login", follow_redirects=False)
    r = client.get("/api/auth/callback?error=access_denied&error_description=AADSTS50105+secret+detail", follow_redirects=False)
    assert error_of(r) == "sign_in_failed" and "AADSTS" not in r.headers["location"]


def test_me_without_a_session_is_401(client):
    body = client.get("/api/auth/me").json()
    assert body["error"]["code"] == "not_signed_in"


def test_logout_ends_the_session(client, microsoft):
    sign_in(client, microsoft)
    token = client.cookies["echo_session"]
    r = client.post("/api/auth/logout")
    assert r.json()["data"] == {"signed_out": True}
    assert any(c.startswith('echo_session=""') or "Max-Age=0" in c for c in r.headers.get_list("set-cookie"))
    # The old token no longer works even if a copy of the cookie is kept.
    client.cookies.clear()
    client.cookies.set("echo_session", token)
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_401(client, microsoft):
    sign_in(client, microsoft)
    with sqlite3.connect(db_path(get_settings().data_dir)) as conn:
        conn.execute("update sessions set expires_at = '2000-01-01 00:00:00.000000'")
    assert client.get("/api/auth/me").status_code == 401
