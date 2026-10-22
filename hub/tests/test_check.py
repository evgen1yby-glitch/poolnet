"""`/api/check` — the check page's backend, and the probe it wraps.

Ported from the pool's edge worker: interval parsing, the reserved-range
refusal, SOCKS5/CONNECT handshakes and the echo-target verdict. The socket
work is tested against a local fake proxy rather than the network, so the
suite does not depend on an external target being up.
"""

from __future__ import annotations

import socket
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from hub.checkproxy import check_proxy, parse_proxy  # noqa: E402


class _Proxy(socketserver.BaseRequestHandler):
    """A one-shot HTTP or SOCKS5 proxy that always reaches the echo target."""

    def handle(self) -> None:
        conn = self.request
        first = conn.recv(1)
        if first == b"\x05":
            conn.recv(3)
            conn.sendall(b"\x05\x00")
            head = conn.recv(4)
            if head[3] == 0x01:
                conn.recv(4 + 2)
            else:
                length = conn.recv(1)[0]
                conn.recv(length + 2)
            conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        else:
            buf = first
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += conn.recv(4096)
        body = b'{"origin": "203.0.113.9"}'
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )


@pytest.fixture()
def fake_proxy():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Proxy)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("raw", "proto", "expected"),
    [
        ("1.2.3.4:8080", "http", ("http", "1.2.3.4", 8080)),
        ("8.8.8.8:1080", "socks5", ("socks5", "8.8.8.8", 1080)),
        ("1.1.1.1:1080", "SOCKS4", ("socks4", "1.1.1.1", 1080)),
    ],
)
def test_parse_accepts_routable(raw, proto, expected):
    assert parse_proxy(raw, proto) == expected


@pytest.mark.parametrize(
    ("raw", "proto"),
    [
        ("", "http"),
        ("example.com:80", "http"),
        ("1.2.3.4", "http"),
        ("1.2.3.4:0", "http"),
        ("1.2.3.4:70000", "http"),
        ("1.2.3.4:80", "ftp"),
        ("127.0.0.1:80", "http"),
        ("10.1.2.3:80", "http"),
        ("192.168.1.1:80", "http"),
        ("169.254.1.1:80", "http"),
        ("172.16.5.5:80", "http"),
        ("100.64.0.1:80", "http"),
        ("0.0.0.0:80", "http"),
        ("224.0.0.1:80", "http"),
    ],
)
def test_parse_refuses_traversal_and_reserved(raw, proto):
    assert isinstance(parse_proxy(raw, proto), str)


def test_http_connect_reaches_echo_target(fake_proxy):
    out = check_proxy("http", "127.0.0.1", fake_proxy, timeout_ms=2000)
    assert out["alive"] is True, out
    assert out["remote_ip"] == "203.0.113.9"
    assert isinstance(out["latency_ms"], int)
    assert out["error"] is None


def test_socks5_handshake_reaches_echo_target(fake_proxy):
    out = check_proxy("socks5", "127.0.0.1", fake_proxy, timeout_ms=2000)
    assert out["alive"] is True, out
    assert out["remote_ip"] == "203.0.113.9"


def test_closed_port_is_a_verdict_not_an_exception():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    out = check_proxy("http", "127.0.0.1", port, timeout_ms=500)
    assert out["alive"] is False
    assert out["error"]


def test_route_validates_and_never_caches(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hub import api as api_module
    from hub import gateway as gateway_module
    from hub.store import Store

    seen: list[tuple[str, str, int]] = []

    def fake_check(proto, host, port, *args, **kwargs):
        seen.append((proto, host, port))
        return {"alive": True, "remote_ip": "203.0.113.9", "latency_ms": 42, "error": None}

    monkeypatch.setattr(gateway_module, "check_proxy", fake_check)
    client = TestClient(api_module.create_app(store=Store(Path("/tmp/opencode/checkroute"))))

    r = client.get("/api/check", params={"proxy": "8.8.8.8:1080", "proto": "socks5"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json() == {
        "proxy": "socks5://8.8.8.8:1080",
        "alive": True,
        "remote_ip": "203.0.113.9",
        "latency_ms": 42,
        "error": None,
    }
    assert seen == [("socks5", "8.8.8.8", 1080)]

    bad = client.get("/api/check", params={"proxy": "127.0.0.1:80", "proto": "http"})
    assert bad.status_code == 400
    assert bad.headers["cache-control"] == "no-store"
    assert "routable" in bad.json()["error"]
