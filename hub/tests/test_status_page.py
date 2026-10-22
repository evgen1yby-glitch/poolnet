"""The public status page: aggregate pool health, and nothing else.

This page is the counterpart to the operator panel and the opposite of it in
every respect that matters. It is public, it needs no secret, and it is meant to
be linked to and quoted. That makes what it *omits* the load-bearing part — the
same rule `/api/v1/stats` follows, for the same reason: the moment it returns
rows from `nodes` or a source URL, the page becomes the scrape these endpoints
exist not to be.

The distinction from the panel is worth stating because the two are easy to
confuse: the panel shows source URLs, because the operator wrote them and a
health table without a name is unusable. This page shows source *counts*, because
a URL here would tell a reader where to fetch the same pool directly — which is
the one thing an index has.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hub.api import create_app  # noqa: E402
from hub.store import Store  # noqa: E402


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path)
    store.connect().close()
    return TestClient(create_app(store=store, sources={})), store


def test_the_status_page_is_public(client):
    """No secret, no loopback requirement. It is for reading, not for operating."""
    api, _ = client
    response = api.get("/status")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_status_data_needs_no_secret(client):
    api, _ = client
    assert api.get("/status/data").status_code == 200
    assert api.get("/status/data", headers={"x-hub-secret": ""}).status_code == 200


def test_the_status_data_carries_no_addresses(client):
    """Counts and timestamps only — no node, no source URL, no token.

    Asserted on the serialised body rather than key by key, because the failure
    this guards against is somebody adding a convenient field: a key check
    passes for keys nobody thought to add, and a scan of the text catches a URL
    or an address wherever it lands.
    """
    api, store = client
    conn = store.connect()
    # A node with a recognisable address and a source with a recognisable URL,
    # so a leak is greppable rather than theoretical.
    conn.execute(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds) VALUES ('k','vless',"
        " '203.0.113.77',443,'NL','https://secret-upstream.example/list.txt',"
        " '2026-10-16T10:00:00+00:00','2026-10-16T10:00:00+00:00',40,1)"
    )
    conn.execute(
        "INSERT INTO sources (url, enabled, rounds, empty_rounds) VALUES"
        " ('https://secret-upstream.example/list.txt', 1, 5, 0)"
    )
    conn.commit()
    conn.close()

    body = api.get("/status/data").text
    for leak in ("203.0.113.77", "secret-upstream.example", "list.txt"):
        assert leak not in body, f"the public page leaked {leak!r}"


def test_the_status_data_reports_history_not_just_now(client):
    """The page exists to show a trend, so the payload carries a series.

    A status page that reports only the current count is the landing page again.
    The interesting question — is the pool growing or dying — needs the history,
    and the funnel counts from each probing run are what answers it.
    """
    api, _ = client
    payload = api.get("/status/data").json()
    assert set(payload) >= {"now", "runs", "sources", "generations"}
    assert isinstance(payload["runs"], list)
    for row in payload["runs"]:
        assert set(row) >= {"at", "tcp", "http", "published"}
    assert isinstance(payload["sources"], dict)


def test_status_now_describes_the_published_generation(tmp_path):
    """The status page and the landing page must not quote different pool sizes.

    Both read the same store and, before this, both read the `nodes` index
    rather than the generation: 832 nodes in 43 countries over a generation of
    150 in 29. Two public pages stating two sizes for one pool is worse than
    either being slightly stale, because a reader comparing them cannot tell
    which one the subscription contains.

    Built directly against `publishes` rather than by running the pipeline: the
    property under test is which table the endpoint reads, and a pipeline run
    exercises that indirectly through a long fixture.
    """
    store = Store(tmp_path)
    conn = store.connect()
    # Index: a node that is verified and one that is not — neither belongs in
    # the "now" readings.
    conn.executemany(
        "INSERT INTO nodes (dedup_key, protocol, address, port, country, source,"
        " first_seen, last_ok, score, rounds, state)"
        " VALUES (?, 'vless', '203.0.113.1', 443, 'NL', 's', 'T', 'T', 50, 3, '{}')",
        [("k1",), ("k2",)],
    )
    conn.executemany(
        "INSERT INTO publishes"
        " (generation, sha256, tier, core, fmt, node_count, created_at)"
        " VALUES (?, ?, 'verified', ?, ?, ?, 'T')",
        [
            ("g", "sha", "sing-box", "singbox", 2),
            ("g", "sha", "cc:NL", "singbox", 2),
            ("g", "sha", "cc:US", "singbox", 1),
        ],
    )
    conn.commit()
    conn.close()
    store.flip_pointer("g", "sha")

    api = TestClient(create_app(store=store, sources={}), base_url="https://x.dev")
    now = api.get("/status/data").json()["now"]
    assert now["verified"] == 2, now
    assert now["countries"] == 2, now


def test_the_status_page_survives_an_empty_store(client):
    """A fresh install has no history, and the page must still answer.

    An empty page that explains itself is fine; a 500 on a public status page is
    the one moment the page exists for.
    """
    api, _ = client
    assert api.get("/status").status_code == 200
    payload = api.get("/status/data").json()
    assert payload["runs"] == []
    assert payload["now"]["generation"] in ("", None)
