import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

PAGES = (
    "first-agent.html",
    "teaching.html",
    "chatting.html",
    "files.html",
    "keys.html",
    "mcp.html",
    "approvals.html",
    "usage.html",
    "install.html",
    "data.html",
    "api.html",
)


def test_guide_index_and_pages(client):
    r = client.get("/docs/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for page in PAGES:
        assert client.get(f"/docs/{page}").status_code == 200
    for asset in ("style.css", "guide.js", "logo.svg", "fonts/inter-latin-400-normal.woff2"):
        r = client.get(f"/docs/{asset}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.inline_scripts = [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.links += [v for k, v in attrs.items() if k in ("href", "src") and v]
        if tag == "script" and "src" not in attrs:
            self.inline_scripts += 1
        if "style" in attrs:
            self.inline_scripts += 1  # the CSP blocks style attributes too


def test_guide_links_resolve_and_respect_the_csp(client):
    # Every page and the fonts its stylesheet names must exist, so moving a page cannot leave a dead link.
    for page in ("", *PAGES, "404.html"):
        url = f"/docs/{page}"
        parser = _Links()
        parser.feed(client.get(url).text)
        assert parser.inline_scripts == 0, url
        for link in parser.links:
            target = urlsplit(urljoin(url, link))
            if target.scheme or not target.path.startswith("/docs/"):
                continue
            assert client.get(target.path).status_code == 200, f"{url} -> {link}"
            if target.fragment and target.path == url:
                assert f'id="{target.fragment}"' in client.get(url).text, f"{url} -> {link}"
    css = client.get("/docs/style.css").text
    for font in re.findall(r"url\((fonts/[^)]+)\)", css):
        assert client.get(f"/docs/{font}").status_code == 200, font


def test_failed_sign_in_lands_on_a_guide_page(client):
    from apps.accounts.routers.auth_router import SIGN_IN_FAILED

    assert client.get(SIGN_IN_FAILED).status_code == 200


def test_guide_missing_page_is_html_404(client):
    r = client.get("/docs/nope.html")
    assert r.status_code == 404 and "Page not found" in r.text


def test_guide_cannot_escape_its_folder(client):
    r = client.get("/docs/..%2f..%2fbackend%2fmain.py")
    assert r.status_code == 404 and "DOCS_DIR" not in r.text
