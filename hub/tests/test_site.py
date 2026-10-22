"""The evilgate site (`web/site`) served by hub-api as the site root.

Every test here points `HUB_SITE` (or relies on the default sibling path) at
the merged project's site directory. They run only when the site exists — a
hub checked out on its own skips them, because a standalone install has no
site and keeps its own landing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from hub.api import create_app
from hub.store import Store

#: `tests/test_site.py` → `hub/` → the merged repo root, then the site.
SITE_DIR = Path(__file__).resolve().parents[2] / "web" / "site"

pytestmark = pytest.mark.skipif(
    not (SITE_DIR / "index.html").is_file(), reason="site not in checkout"
)


@pytest.fixture()
def site_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SITE", str(SITE_DIR))
    app = create_app(store=Store(tmp_path))
    return TestClient(app)


def test_the_root_serves_the_site_index(site_client):
    """`/` is the evilgate page, not the hub's old landing.

    The merge puts the unified site at the root. Pinned by brand and by copy
    so a regression to the old surface is a failing test, not a surprise.
    """
    response = site_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "evilgate" in response.text
    assert "Прокси" in response.text


def test_every_site_page_serves(site_client):
    """All six pages answer 200 — a 404 between pages breaks navigation."""
    for page in ("vpn", "proxy", "verify", "premium", "status"):
        assert site_client.get(f"/{page}").status_code == 200, page
        assert site_client.get(f"/{page}.html").status_code == 200, page


def test_none_of_the_site_pages_index_as_operator_panels(site_client):
    """The site is the product story; nothing here must say «нет такого файла».

    A copy of a design-directory message on a public page means the site
    route fell back to the design resolver — which adds the `noindex` header
    and would silently de-index the product.
    """
    for page in ("", "/vpn", "/proxy.html", "/status"):
        response = site_client.get(f"/{page}" if page else "/")
        assert response.status_code == 200
        assert "нет такого файла" not in response.text
        assert response.headers.get("x-robots-tag") is None


def test_site_pages_are_not_cached(site_client):
    """Fresh markup beside a cached stylesheet is the bug class `/design/` had.

    The unification pass edits page markup in place; a browser holding the
    old CSS would render the new page broken and the review would blame the
    markup.
    """
    for path in ("/", "/vpn", "/proxy.html", "/system.css"):
        assert site_client.get(path).headers["cache-control"] == "no-cache", path


def test_site_assets_serve_with_their_types(site_client):
    """The stylesheet fonts load, or the page renders unstyled."""
    css = site_client.get("/system.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert len(css.content) > 400

    font = site_client.get("/fonts/intertight-cyrillic.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert len(font.content) > 1000


def test_a_page_miss_is_a_plain_404(site_client):
    """Unknown paths stay 404s, never a directory listing."""
    response = site_client.get("/not-one")
    assert response.status_code == 404
    assert "нет такой страницы" in response.text


def test_a_traversal_attempt_is_not_a_file(site_client):
    """`resolve()`-then-containment: `..` cannot walk out of the site tree."""
    escaped = site_client.get("/../hub/pyproject.toml")
    assert escaped.status_code == 404


def test_api_routes_do_not_conflict_with_the_site(site_client):
    """Existing surfaces keep their handlers even though a `{path}` route exists.

    The catch-all was registered last on purpose; an `/api/v1/stats` JSON
    body that ever came back as a page would be a routing regression, not a
    content one.
    """
    response = site_client.get("/api/v1/stats")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
