def test_guide_index_and_pages(client):
    r = client.get("/docs/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for page in ("getting-started.html", "workspaces.html", "chat.html"):
        assert client.get(f"/docs/{page}").status_code == 200
    assert client.get("/docs/style.css").status_code == 200


def test_guide_missing_page_is_html_404(client):
    r = client.get("/docs/nope.html")
    assert r.status_code == 404 and "Page not found" in r.text


def test_guide_cannot_escape_its_folder(client):
    r = client.get("/docs/..%2f..%2fbackend%2fmain.py")
    assert r.status_code == 404 and "DOCS_DIR" not in r.text
