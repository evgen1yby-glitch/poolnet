"""On-demand liveness check of one proxy, ported from the pool's edge worker.

The pool's site offers a "check any proxy" box that opens a real tunnel
through the address a visitor pasted and reports whether a full request
succeeds, how long it took, and which exit address the target saw. The
worker in `pool/workers/api/check.js` does that with `cloudflare:sockets`;
the merged hub is plain Python, so this module is the same protocol work
over `socket`.

The answer is deliberately narrow: one HTTP GET to an echo target through
the proxy. Nothing is retained — no request logs, no cache, no history.
Reserved and private addresses are refused before a socket is opened, so
the endpoint cannot be turned into a probe of the host's own network.
"""

from __future__ import annotations

import re
import socket
import time
from urllib.parse import urlsplit

#: Same target the worker uses. `httpbingo.org/get` echoes `{"origin": ...}`,
#: which is what makes the verdict checkable: a proxy that lies about
#: connectivity still has to disclose the address the target actually saw.
DEFAULT_TARGET = "http://httpbingo.org/get"

#: The worker's ceiling. A dead proxy should not hold a request for longer.
DEFAULT_TIMEOUT_MS = 8000

PROTOCOLS = ("http", "socks4", "socks5")

_ADDR = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$")


class CheckError(Exception):
    """A protocol-level failure worth reporting to the visitor."""


def parse_proxy(raw: str, proto: str) -> tuple[str, str, int] | str:
    """Parse `host:port` + protocol, or return an error string.

    Mirrors the worker's validation: dotted IPv4 only (no hostnames — a
    hostname would let the endpoint resolve arbitrary names on the host's
    behalf) and no reserved/private ranges.
    """
    match = _ADDR.match((raw or "").strip())
    if not match:
        return "expected proxy=host:port"
    port = int(match.group(2))
    if not 0 < port <= 65535:
        return "port out of range"
    protocol = (proto or "").lower()
    if protocol not in PROTOCOLS:
        return f"proto must be one of {', '.join(PROTOCOLS)}"
    a, b = (int(part) for part in match.group(1).split(".")[:2])
    reserved = (
        a == 0
        or a == 10
        or a == 127
        or (a == 100 and 64 <= b <= 127)
        or (a == 169 and b == 254)
        or (a == 172 and 16 <= b <= 31)
        or (a == 192 and b == 168)
        or a >= 224
    )
    if reserved:
        return "address is not routable"
    return protocol, match.group(1), port


class _Reader:
    """A buffer over the socket: a proxy may pipeline, so no byte is dropped."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = b""

    def _read(self, deadline: float) -> bytes:
        left = deadline - time.monotonic()
        if left <= 0:
            raise CheckError("timeout")
        self._sock.settimeout(left)
        try:
            chunk = self._sock.recv(65536)
        except TimeoutError as exc:
            raise CheckError("timeout") from exc
        if not chunk:
            raise CheckError("connection closed")
        return chunk

    def read_n(self, n: int, deadline: float) -> bytes:
        while len(self._buf) < n:
            self._buf += self._read(deadline)
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def read_until(self, marker: bytes, deadline: float) -> bytes:
        while marker not in self._buf:
            self._buf += self._read(deadline)
        cut = self._buf.index(marker) + len(marker)
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return out

    def read_rest(self, deadline: float, limit: int = 64 * 1024) -> bytes:
        out = self._buf
        self._buf = b""
        while len(out) < limit:
            try:
                out += self._read(deadline)
            except CheckError as exc:
                if str(exc) == "connection closed":
                    break
                raise
        return out[:limit]


def _open_tunnel(
    sock: socket.socket,
    reader: _Reader,
    proto: str,
    host: str,
    port: int,
    deadline: float,
) -> None:
    """OPEN a tunnel to `host:port` through the proxy."""
    if proto == "socks5":
        sock.sendall(b"\x05\x01\x00")
        greet = reader.read_n(2, deadline)
        if greet[0] != 0x05 or greet[1] != 0x00:
            raise CheckError("socks5 greeting rejected")
        request = b"\x05\x01\x00\x03" + bytes([len(host)]) + host.encode("ascii")
        request += port.to_bytes(2, "big")
        sock.sendall(request)
        head = reader.read_n(4, deadline)
        if head[1] != 0x00:
            raise CheckError(f"socks5 connect refused ({head[1]})")
        atyp = head[3]
        if atyp == 0x01:
            addr_len = 4
        elif atyp == 0x03:
            addr_len = reader.read_n(1, deadline)[0]
        elif atyp == 0x04:
            addr_len = 16
        else:
            addr_len = 0
        reader.read_n(addr_len + 2, deadline)
    elif proto == "socks4":
        request = b"\x04\x01" + port.to_bytes(2, "big") + b"\x00\x00\x00\x01\x00"
        request += host.encode("ascii") + b"\x00"
        sock.sendall(request)
        reply = reader.read_n(8, deadline)
        if reply[1] != 0x5A:
            raise CheckError(f"socks4 connect refused ({reply[1]})")
    else:
        target = f"{host}:{port}"
        sock.sendall(
            f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode("ascii")
        )
        head = reader.read_until(b"\r\n\r\n", deadline)
        match = re.match(rb"^HTTP/1\.[01] (\d{3})", head)
        if not match:
            raise CheckError("malformed CONNECT reply")
        if match.group(1) != b"200":
            raise CheckError(f"CONNECT -> {match.group(1).decode()}")


def check_proxy(
    proto: str,
    host: str,
    port: int,
    target_url: str = DEFAULT_TARGET,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict:
    """Check one proxy; always returns a verdict, never raises."""
    started = time.monotonic()
    deadline = started + timeout_ms / 1000
    target = urlsplit(target_url)
    target_host = target.hostname or ""
    target_port = target.port or 80
    sock = None
    try:
        sock = socket.create_connection(
            (host, port), timeout=max(0.001, deadline - time.monotonic())
        )
        reader = _Reader(sock)
        _open_tunnel(sock, reader, proto, target_host, target_port, deadline)
        sock.sendall(
            f"GET /get HTTP/1.1\r\nHost: {target_host}\r\n"
            f"User-Agent: evilgate\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        head = reader.read_until(b"\r\n\r\n", deadline)
        match = re.match(rb"^HTTP/1\.[01] (\d{3})", head)
        if not match:
            raise CheckError("malformed response")
        status = int(match.group(1))
        if not 200 <= status < 400:
            raise CheckError(f"HTTP {status}")
        body = reader.read_rest(deadline + 2, limit=64 * 1024)
        origin = re.search(rb'"origin"\s*:\s*"([^"]+)"', body)
        return {
            "alive": True,
            "remote_ip": origin.group(1).decode() if origin else None,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": None,
        }
    except (CheckError, OSError, ValueError) as exc:
        message = str(exc) or exc.__class__.__name__
        return {"alive": False, "remote_ip": None, "latency_ms": None, "error": message}
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
