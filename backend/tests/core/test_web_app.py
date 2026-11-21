from fastapi.testclient import TestClient


def make_client(tmp_path, built=True):
    from main import create_app

    web = tmp_path / "dist"
    if built:
        (web / "assets").mkdir(parents=True)
        (web / "index.html").write_text("<!doctype html><div id=root></div>")
        (web / "assets" / "app-abc123.js").write_text("console.log(1)")
    return TestClient(create_app(web_dir=web))


def test_pages_load_the_app_and_assets_are_cached(tmp_path, fake_runner):
    with make_client(tmp_path) as client:
        for path in ("/", "/agents/abc", "/credentials"):
            r = client.get(path)
            assert r.status_code == 200 and "id=root" in r.text, path
            assert r.headers["cache-control"] == "no-cache"
            assert "script-src 'self'" in r.headers["content-security-policy"]
            assert r.headers["x-content-type-options"] == "nosniff"
        r = client.get("/assets/app-abc123.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert client.get("/assets/missing.js").status_code == 404


def test_api_and_guide_keep_their_own_answers(tmp_path, fake_runner):
    with make_client(tmp_path) as client:
        r = client.get("/api/nope")
        assert r.status_code == 404 and r.json()["success"] is False
        assert client.get("/api").status_code == 404
        assert "content-security-policy" not in client.get("/api/health").headers
        assert client.get("/api/health").json()["data"] == {"status": "ok"}
        guide = client.get("/docs/")
        assert guide.status_code == 200 and "id=root" not in guide.text and guide.headers["content-security-policy"]


def test_without_a_build_nothing_is_served(tmp_path, fake_runner):
    with make_client(tmp_path, built=False) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200
