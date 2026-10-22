"""Share-URI parsing. Pure functions, no network, no subprocess.

Supported inputs
----------------
``vless://`` ``vmess://`` ``trojan://`` ``ss://`` ``hysteria2://`` ``tuic://``
``wireguard://`` ``socks://`` ``http://`` and plain JSON (sing-box outbound).

Design decisions that come from verified client behaviour:

* **Unknown scheme is an error, never a skip.** v2rayN aborts a whole import on
  one malformed line (#5670, #5299), so we must know about every line we emit.
* **First-`=` split only, first-wins duplicates.** v2rayN's URI parser splits
  on the first ``=`` and resolves duplicate query keys first-wins. Matching that
  exactly means a node that imports cleanly in v2rayN imports cleanly here.
* **Two Shadowsocks encodings** are accepted, because both exist in the wild:
  ``ss://<b64 of method:password>@host:port`` and
  ``ss://<b64 of method:password@host:port>`` (SIP002 vs legacy).
* **Fragment remarks are percent-decoded**, not raw — a remark containing ``#``
  must survive the round trip.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
import urllib.parse
from dataclasses import replace
from typing import Optional

from .models import (
    Node,
    ParseError,
    ParseErrorKind,
    Protocol,
    is_blocked_address,
    Security,
    Transport,
    TransportSettings,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: The urlsafe base64 alphabet. Padding is stripped by some publishers and
#: re-added by the decoder, so it is optional here.
urlsafe_alphabet_re = re.compile(r"^[A-Za-z0-9\-_]*=*$")


class _Rejected(Exception):
    """Internal control flow: carry a typed ParseError to parse_many."""

    def __init__(self, kind: ParseErrorKind, detail: str = "") -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(detail or kind.value)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _b64decode_strict(value: str, *, line: int) -> bytes:
    """Base64 decode that rejects the garbage that HTML error pages yield.

    v2rayN throws on a non-base64 body (captive portal, 4xx) — we match that
    strictness instead of producing a garbage Node.

    `validate` only exists on `b64decode`; `urlsafe_b64decode` forwards its
    keyword arguments to `binascii.a2b_base64`, which does not accept one, so
    passing it raises `TypeError` — and `parse_one` catches that as
    "unhandled TypeError", turning every `ss://` and `vmess://` link into a
    bogus `unknown_scheme` error. Strictness comes instead from validating the
    alphabet explicitly below, which is also what makes a padded-but-corrupt
    blob fail rather than decode to junk.
    """
    cleaned = value.strip()
    if urlsafe_alphabet_re.fullmatch(cleaned) is None:
        raise _Rejected(ParseErrorKind.BAD_BASE64, f"not urlsafe base64: {cleaned[:40]!r}")
    padding = (-len(cleaned)) % 4
    cleaned += "=" * padding
    try:
        return base64.urlsafe_b64decode(cleaned.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise _Rejected(ParseErrorKind.BAD_BASE64, str(exc)) from exc


def _first_wins(query: str, key: str) -> Optional[str]:
    """Mimic v2rayN: split on the first '=', duplicate keys resolve first-wins."""
    best: Optional[str] = None
    for chunk in query.split("&"):
        if not chunk:
            continue
        name, _, value = chunk.partition("=")
        if name.lower() == key.lower():
            if best is None:
                best = value
    if best is None:
        return None
    return urllib.parse.unquote(best)


def _has(query: str, key: str) -> bool:
    return any(
        chunk.partition("=")[0].lower() == key.lower() for chunk in query.split("&") if chunk
    )


def _unbracket_ipv4_literal(raw: str) -> str:
    """`vless://u@[10.0.0.1]:443` -> `vless://u@10.0.0.1:443`.

    Only the authority is touched, and only when the bracket genuinely wraps a
    dotted-quad IPv4. A bracketed IPv6 literal is legal and must survive, and a
    bracketed *hostname* is a typo this does not want to silently repair — so
    the rewrite is deliberately narrow and anything it does not recognise is
    returned untouched (and then reported by `urlsplit` or the guard).
    """
    start = raw.find("://")
    if start == -1:
        return raw
    bracket = raw.find("[", start + 3)
    if bracket == -1:
        return raw
    end = raw.find("]", bracket)
    if end == -1:
        return raw
    inner = raw[bracket + 1 : end]
    try:
        is_ipv4 = ipaddress.ip_address(inner).version == 4
    except ValueError:
        return raw  # a hostname or garbage; not ours to repair
    if not is_ipv4:
        return raw
    return raw[:bracket] + inner + raw[end + 1 :]


def _check_address(address: str) -> str:
    """Reject private/loopback/link-local literals; allow hostnames through.

    The block list lives in `models.is_blocked_address` so the parser and the
    prober cannot drift: they each reject a different subset and a poisoned
    entry slips through whichever is shorter.
    """
    address = address.strip().strip("[]")
    if not address:
        raise _Rejected(ParseErrorKind.MISSING_ADDRESS)
    if is_blocked_address(address):
        raise _Rejected(ParseErrorKind.PRIVATE_ADDRESS, address)
    return address


def _check_port(raw: str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise _Rejected(ParseErrorKind.BAD_PORT, str(raw)) from None
    if not 1 <= port <= 65535:
        raise _Rejected(ParseErrorKind.BAD_PORT, str(port))
    return port


def _check_uuid(value: str) -> str:
    if not value:
        raise _Rejected(ParseErrorKind.MISSING_UUID)
    if not _UUID_RE.match(value):
        raise _Rejected(ParseErrorKind.BAD_UUID, value)
    return value.lower()


_TRANSPORTS = {
    "tcp": Transport.TCP,
    "ws": Transport.WS,
    "websocket": Transport.WS,
    "grpc": Transport.GRPC,
    "h2": Transport.HTTP2,
    "http": Transport.HTTP2,
    "quic": Transport.QUIC,
    "xhttp": Transport.XHTTP,
    "httpupgrade": Transport.HTTPUPGRADE,
}

_SECURITIES = {
    "tls": Security.TLS,
    "reality": Security.REALITY,
    "none": Security.NONE,
    "": Security.NONE,
}


def _transport(query: str) -> Transport:
    raw = _first_wins(query, "type") or "tcp"
    try:
        return _TRANSPORTS[raw.lower()]
    except KeyError:
        raise _Rejected(ParseErrorKind.MISSING_REQUIRED_FIELD, f"type={raw}") from None


def _transport_settings(query: str, kind: Transport) -> TransportSettings:
    host = _first_wins(query, "host") or ""
    path = _first_wins(query, "path") or _first_wins(query, "serviceName") or ""
    header_type = _first_wins(query, "headerType") or "none"
    if header_type.lower() == "http":
        header_type = "http"
    return TransportSettings(
        kind=kind,
        host=host,
        path=path,
        service_name=_first_wins(query, "serviceName") or "",
        header_type=header_type,
    )


def _tls_from_query(query: str, security: Security) -> dict:
    sni = _first_wins(query, "sni") or ""
    fp = _first_wins(query, "fp") or ""
    alpn = _first_wins(query, "alpn") or ""
    alpn_tuple = tuple(a for a in (p.strip() for p in alpn.split(",")) if a)
    insecure = (_first_wins(query, "allowInsecure") or "0") in ("1", "true")
    from .models import TLS

    return TLS(
        sni=sni,
        fingerprint=fp,
        alpn=alpn_tuple,
        allow_insecure=insecure,
        public_key=_first_wins(query, "pbk") or "",
        short_id=_first_wins(query, "sid") or "",
        spider_x=_first_wins(query, "spx") or "",
    )


# --------------------------------------------------------------------------
# per-scheme parsers
# --------------------------------------------------------------------------


def _parse_vless(parts: urllib.parse.SplitResult, line: int) -> Node:
    userinfo, _, hostport = parts.netloc.rpartition("@")
    uuid = _check_uuid(urllib.parse.unquote(userinfo))
    if not hostport:
        raise _Rejected(ParseErrorKind.NO_NETLOC)
    address, _, port_raw = _rpartition_hostport(hostport)
    address = _check_address(address)
    port = _check_port(port_raw)
    query = parts.query
    transport = _transport(query)
    security = _SECURITIES.get((_first_wins(query, "security") or "none").lower(), Security.NONE)
    flow = _first_wins(query, "flow") or ""
    # REALITY with no flow is still valid; plain TLS with a flow is not.
    if flow and "xtls" not in flow.lower():
        flow = flow  # keep, the renderer normalises
    ts = _transport_settings(query, transport)
    ts.validate(Protocol.VLESS)
    tls = _tls_from_query(query, security)
    remark = urllib.parse.unquote(parts.fragment or "")
    return Node(
        protocol=Protocol.VLESS,
        address=address,
        port=port,
        uuid=uuid,
        transport=transport,
        transport_settings=ts,
        security=security,
        tls=tls,
        flow=flow,
        remark=remark,
    )


def _parse_trojan(parts: urllib.parse.SplitResult, line: int) -> Node:
    userinfo, _, hostport = parts.netloc.rpartition("@")
    password = urllib.parse.unquote(userinfo)
    if not password:
        raise _Rejected(ParseErrorKind.MISSING_PASSWORD)
    address, _, port_raw = _rpartition_hostport(hostport)
    address = _check_address(address)
    port = _check_port(port_raw)
    query = parts.query
    transport = _transport(query)
    security = _SECURITIES.get((_first_wins(query, "security") or "tls").lower(), Security.TLS)
    ts = _transport_settings(query, transport)
    ts.validate(Protocol.TROJAN)
    tls = _tls_from_query(query, security)
    return Node(
        protocol=Protocol.TROJAN,
        address=address,
        port=port,
        password=password,
        transport=transport,
        transport_settings=ts,
        security=security,
        tls=tls,
        remark=urllib.parse.unquote(parts.fragment or ""),
    )


def _parse_ss(parts: urllib.parse.SplitResult, line: int) -> Node:
    """Both SS encodings: SIP002 and the legacy all-base64 form.

    ``ss://<b64(method:password)>@host:port#remark``  (SIP002)
    ``ss://<b64(method:password@host:port)>#remark``  (legacy)
    ``ss://<b64(method:password)>@[v6]:port``         (SIP002, IPv6)
    """
    raw_netloc = parts.netloc
    remark = urllib.parse.unquote(parts.fragment or "")

    # Try SIP002 first: there is an '@' in the netloc.
    if "@" in raw_netloc:
        userinfo, _, hostport = raw_netloc.rpartition("@")
        decoded = _b64decode_strict(userinfo, line=line).decode("utf-8", errors="replace").strip()
        if ":" not in decoded:
            # Some links ship the credentials base64'd but already "method:password"
            raise _Rejected(ParseErrorKind.MISSING_PASSWORD, decoded[:40])
        method, _, password = decoded.partition(":")
        hostport = hostport.strip()
    else:
        # Legacy: everything is inside the base64 blob.
        blob = _b64decode_strict(raw_netloc, line=line).decode("utf-8", errors="replace").strip()
        if "@" not in blob:
            raise _Rejected(ParseErrorKind.MISSING_ADDRESS, blob[:60])
        userinfo, _, hostport = blob.rpartition("@")
        if ":" not in userinfo:
            raise _Rejected(ParseErrorKind.MISSING_PASSWORD, userinfo[:40])
        method, _, password = userinfo.partition(":")

    if not password:
        raise _Rejected(ParseErrorKind.MISSING_PASSWORD, method)
    address, _, port_raw = _rpartition_hostport(hostport)
    address = _check_address(address)
    port = _check_port(port_raw)
    # SS plugin argument, if present, lives in the query.
    plugin = _first_wins(parts.query, "plugin") or ""
    return Node(
        protocol=Protocol.SHADOWSOCKS,
        address=address,
        port=port,
        password=password,
        method=method.strip(),
        transport_settings=TransportSettings(kind=Transport.TCP),
        remark=remark,
        flow=plugin,
    )


def _parse_vmess(parts: urllib.parse.SplitResult, line: int) -> Node:
    """vmess is base64-of-JSON. The JSON is the only source of fields."""
    blob = _b64decode_strict(parts.netloc, line=line).decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        # Some clients URL-encode the base64 payload.
        try:
            blob = urllib.parse.unquote(blob)
            data = json.loads(blob)
        except json.JSONDecodeError:
            raise _Rejected(ParseErrorKind.BAD_JSON, str(exc)) from exc
    if not isinstance(data, dict):
        raise _Rejected(ParseErrorKind.BAD_JSON, "not an object")

    address = _check_address(str(data.get("add", "")).strip())
    port = _check_port(str(data.get("port", "")).strip())
    uuid = _check_uuid(str(data.get("id", "")).strip())

    net_raw = str(data.get("net", "tcp") or "tcp").lower()
    transport = _TRANSPORTS.get(net_raw, Transport.TCP)
    ts = TransportSettings(
        kind=transport,
        host=str(data.get("host", "") or "").strip(),
        path=str(data.get("path", "") or "/").strip() or "/",
        header_type=str(data.get("type", "none") or "none"),
    )
    ts.validate(Protocol.VMESS)

    tls_raw = str(data.get("tls", "") or "").lower()
    security = Security.TLS if tls_raw in ("tls", "xtls", "reality") else Security.NONE
    if tls_raw == "reality":
        security = Security.REALITY

    from .models import TLS

    alpn = str(data.get("alpn", "") or "")
    tls = TLS(
        sni=str(data.get("sni", "") or data.get("host", "") or "").strip(),
        alpn=tuple(a for a in (p.strip() for p in alpn.split(",")) if a),
        public_key=str(data.get("pbk", "") or "").strip(),
        short_id=str(data.get("sid", "") or "").strip(),
    )
    remark = str(data.get("ps", "") or "")
    return Node(
        protocol=Protocol.VMESS,
        address=address,
        port=port,
        uuid=uuid,
        transport=transport,
        transport_settings=ts,
        security=security,
        tls=tls,
        flow=str(data.get("flow", "") or ""),
        method=str(data.get("scy", "auto") or "auto"),
        remark=remark,
    )


def _parse_hysteria2(parts: urllib.parse.SplitResult, line: int) -> Node:
    password, _, hostport = parts.netloc.rpartition("@") if "@" in parts.netloc else ("", "", parts.netloc)
    if not password:
        password = urllib.parse.unquote(parts.netloc)
        hostport = ""
        raise _Rejected(ParseErrorKind.MISSING_ADDRESS)
    password = urllib.parse.unquote(password)
    query = parts.query
    # hysteria2 (and hy2) embed the password in the userinfo and carry obfs in
    # the query; the port may be a range in some links.
    address, _, port_raw = _rpartition_hostport(hostport)
    address = _check_address(address)
    port = _check_port(port_raw.split(",")[0])
    obfs = _first_wins(query, "obfs") or ""
    obfs_password = _first_wins(query, "obfs-password") or ""
    congestion = _first_wins(query, "congestion_control") or ""
    from .models import TLS

    tls = TLS(sni=_first_wins(query, "sni") or address, allow_insecure=(_first_wins(query, "insecure") == "1"))
    return Node(
        protocol=Protocol.HYSTERIA2,
        address=address,
        port=port,
        password=password,
        transport=Transport.QUIC,
        transport_settings=TransportSettings(kind=Transport.QUIC),
        security=Security.TLS,
        tls=tls,
        obfs=obfs,
        obfs_password=obfs_password,
        congestion=congestion,
        remark=urllib.parse.unquote(parts.fragment or ""),
    )


def _parse_tuic(parts: urllib.parse.SplitResult, line: int) -> Node:
    userinfo, _, hostport = parts.netloc.rpartition("@")
    uuid = _check_uuid(urllib.parse.unquote(userinfo.rpartition(":")[0] or userinfo))
    password = urllib.parse.unquote(userinfo.rpartition(":")[2] or userinfo)
    address, _, port_raw = _rpartition_hostport(hostport)
    address = _check_address(address)
    port = _check_port(port_raw)
    query = parts.query
    congestion = _first_wins(query, "congestion_control") or "bbr"
    from .models import TLS

    return Node(
        protocol=Protocol.TUIC,
        address=address,
        port=port,
        uuid=uuid,
        password=password,
        transport=Transport.QUIC,
        transport_settings=TransportSettings(kind=Transport.QUIC),
        security=Security.TLS,
        tls=TLS(
            sni=_first_wins(query, "sni") or address,
            alpn=tuple(a for a in (_first_wins(query, "alpn") or "h3").split(",") if a),
        ),
        congestion=congestion,
        remark=urllib.parse.unquote(parts.fragment or ""),
    )


def _parse_wireguard(parts: urllib.parse.SplitResult, line: int) -> Node:
    query = urllib.parse.parse_qs(parts.query)
    address = _check_address(parts.hostname or "")
    port = _check_port(str(parts.port or "51820"))
    # The whole config travels in the query for conf-mode WG.
    public_key = query.get("publicKey", [""])[0]
    if not public_key:
        raise _Rejected(ParseErrorKind.MISSING_REQUIRED_FIELD, "publicKey")
    secret = query.get("secretKey", [""])[0]
    return Node(
        protocol=Protocol.WIREGUARD,
        address=address,
        port=port,
        password=secret,
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        remark=urllib.parse.unquote(parts.fragment or ""),
        flow=public_key,  # reuse the spare string field for the peer key
    )


def _parse_socks_or_http(parts: urllib.parse.SplitResult, line: int) -> Node:
    proto = (
        Protocol.SOCKS if parts.scheme.lower().startswith("socks") else Protocol.HTTP_PROXY
    )
    security = Security.NONE
    # Optional userinfo.
    userinfo = ""
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, netloc = netloc.rpartition("@")
    address, _, port_raw = _rpartition_hostport(netloc)
    address = _check_address(address)
    port = _check_port(port_raw or "1080")
    username, password = "", ""
    if userinfo:
        username, _, password = urllib.parse.unquote(userinfo).partition(":")
    if parts.scheme.lower() in ("https", "socks5s", "socks4s"):
        security = Security.TLS
    return Node(
        protocol=proto,
        address=address,
        port=port,
        username=username,
        password=password,
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=security,
        remark=urllib.parse.unquote(parts.fragment or ""),
    )


def _rpartition_hostport(value: str) -> tuple[str, str, str]:
    """Split ``host:port`` handling bracketed IPv6 literals.

    ``[2001:db8::1]:443`` -> ``("2001:db8::1", ":", "443")``
    ``1.2.3.4:443``       -> ``("1.2.3.4", ":", "443")``
    ``2001:db8::1``        -> raised as NO_NETLOC (no port).
    """
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            raise _Rejected(ParseErrorKind.NO_NETLOC, value)
        address = value[1:end]
        rest = value[end + 1 :]
        if not rest.startswith(":"):
            raise _Rejected(ParseErrorKind.BAD_PORT, value)
        return address, ":", rest[1:]
    if value.count(":") > 1:
        raise _Rejected(ParseErrorKind.BAD_PORT, f"unbracketed IPv6 {value}")
    address, sep, port = value.rpartition(":")
    if not sep:
        raise _Rejected(ParseErrorKind.BAD_PORT, value)
    return address, sep, port


# --------------------------------------------------------------------------
# JSON (sing-box outbound) support
# --------------------------------------------------------------------------


def parse_json_config(text: str) -> list[Node]:
    """Parse a sing-box-style JSON body into Nodes.

    Accepts a bare outbound, a list of outbounds, or a full config with an
    ``outbounds`` key. Anything else is a typed error via the caller.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Rejected(ParseErrorKind.BAD_JSON, str(exc)) from exc

    outbounds: list[dict] = []
    if isinstance(data, dict):
        if "outbounds" in data and isinstance(data["outbounds"], list):
            outbounds = [o for o in data["outbounds"] if isinstance(o, dict)]
        elif "type" in data:
            outbounds = [data]
    elif isinstance(data, list):
        outbounds = [o for o in data if isinstance(o, dict) and "type" in o]

    mapping = {
        "vless": Protocol.VLESS,
        "vmess": Protocol.VMESS,
        "trojan": Protocol.TROJAN,
        "shadowsocks": Protocol.SHADOWSOCKS,
        "hysteria2": Protocol.HYSTERIA2,
        "tuic": Protocol.TUIC,
        "wireguard": Protocol.WIREGUARD,
        "socks": Protocol.SOCKS,
        "http": Protocol.HTTP_PROXY,
    }
    result: list[Node] = []
    for obj in outbounds:
        proto = mapping.get(str(obj.get("type", "")).lower())
        if proto is None:
            continue  # selector/urltest/direct groups, not nodes
        address = _check_address(str(obj.get("server", "")).strip())
        # sing-box/mihomo both key the port as `port`; `server_port` is the Xray
        # and v2rayN spelling. Reading only one of them rejected every config
        # from the other toolchain as a BAD_PORT of "0".
        port_raw = str(obj.get("port") or obj.get("server_port") or "").strip() or "0"
        port = _check_port(port_raw)
        tls_obj = obj.get("tls") or {}
        security = Security.NONE
        if tls_obj.get("enabled"):
            security = (
                Security.REALITY if tls_obj.get("reality") else Security.TLS
            )
        from .models import TLS

        tls = TLS(
            sni=str(tls_obj.get("server_name", "") or "").strip(),
            fingerprint=str(tls_obj.get("utls", {}).get("fingerprint", "") or ""),
            public_key=str(tls_obj.get("reality", {}).get("public_key", "") or ""),
            short_id=str(tls_obj.get("reality", {}).get("short_id", "") or ""),
        )
        if isinstance(obj.get("transport"), dict):
            t_kind = _TRANSPORTS.get(str(obj["transport"].get("type", "tcp")).lower(), Transport.TCP)
        else:
            t_kind = Transport.TCP
        result.append(
            Node(
                protocol=proto,
                address=address,
                port=port,
                uuid=str(obj.get("uuid", "") or ""),
                password=str(obj.get("password", "") or ""),
                username=str(obj.get("username", "") or ""),
                method=str(obj.get("method", "") or ""),
                flow=str(obj.get("flow", "") or ""),
                obfs=_obfs_type(obj),
                obfs_password=_obfs_password(obj),
                transport=t_kind,
                transport_settings=TransportSettings(kind=t_kind),
                security=security,
                tls=tls,
                remark=str(obj.get("tag", "") or ""),
            )
        )
    return result


def _obfs_type(obj: dict) -> str:
    """Hysteria2 obfs type. Accepts both `{"obfs": {"type": ...}}` and a bare
    `{"obfs": "salamander"}`, which is what some JSON sources emit."""
    value = obj.get("obfs", "")
    if isinstance(value, dict):
        return str(value.get("type", "") or "")
    return str(value or "")


def _obfs_password(obj: dict) -> str:
    """Hysteria2 obfs password. Silently dropping it produced configs that
    started but could not negotiate, so it is carried through explicitly."""
    value = obj.get("obfs", "")
    if isinstance(value, dict):
        return str(value.get("password", "") or "")
    return str(obj.get("obfs-password", "") or "")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

_SCHEME_TABLE = {
    "vless": _parse_vless,
    "trojan": _parse_trojan,
    "ss": _parse_ss,
    "vmess": _parse_vmess,
    "hysteria2": _parse_hysteria2,
    "hy2": _parse_hysteria2,
    "tuic": _parse_tuic,
    "wireguard": _parse_wireguard,
    "wg": _parse_wireguard,
    "socks": _parse_socks_or_http,
    "socks5": _parse_socks_or_http,
    "socks4": _parse_socks_or_http,
    "http": _parse_socks_or_http,
    "https": _parse_socks_or_http,
}


def parse(uri: str, *, line: int = 0, source: str = "") -> Node:
    """Parse one share URI into a Node.

    Raises `_Rejected` (internal). Use `parse_one` for the public contract.
    """
    raw = (uri or "").strip()
    if not raw:
        raise _Rejected(ParseErrorKind.EMPTY)

    # A JSON blob is a legitimate "URI" in subscription lists.
    if raw.startswith("{") or raw.startswith("["):
        nodes = parse_json_config(raw)
        if not nodes:
            raise _Rejected(ParseErrorKind.MISSING_REQUIRED_FIELD, "no outbounds")
        return nodes[0]

    if "://" not in raw:
        # Very common: a bare "host:port" line in a scraped list.
        raise _Rejected(ParseErrorKind.UNKNOWN_SCHEME, raw[:40])

    # `urlsplit` refuses `[<IPv4 literal>]:port` outright — Python has validated
    # bracketed hosts since 3.6 and an IPv4 address is not allowed there. A
    # subscription list full of `[10.0.0.1]:443` lines would then crash this
    # function with ValueError instead of returning a typed SSRF rejection, and
    # the address would never reach the guard at all. Rewriting the bracketed
    # IPv4 form into its plain equivalent first keeps that decision in the
    # parser, where it belongs.
    raw = _unbracket_ipv4_literal(raw)

    parts = urllib.parse.urlsplit(raw)
    scheme = parts.scheme.lower()
    handler = _SCHEME_TABLE.get(scheme)
    if handler is None:
        raise _Rejected(ParseErrorKind.UNKNOWN_SCHEME, scheme)
    node = handler(parts, line)
    if source:
        node = replace(node, source=source, country=node.country)
    return node


def parse_one(uri: str, *, line: int = 0, source: str = "") -> tuple[Optional[Node], Optional[ParseError]]:
    """Public contract: exactly one of (node, error) is set.

    Never raises, never silently drops. `parse_many` is built on this.
    """
    try:
        return parse(uri, line=line, source=source), None
    except _Rejected as exc:
        return None, ParseError(
            kind=exc.kind, line=line or 0, raw=(uri or "").strip(), detail=exc.detail
        )
    except Exception as exc:  # noqa: BLE001 - a parser must never crash the run
        return None, ParseError(
            kind=ParseErrorKind.UNKNOWN_SCHEME,
            line=line or 0,
            raw=(uri or "").strip(),
            detail=f"unhandled {type(exc).__name__}: {exc}",
        )


def parse_many(
    body: str, *, source: str = "", start_line: int = 1
) -> tuple[list[Node], list[ParseError]]:
    """Parse a subscription body (or a raw newline list).

    Returns every node it could and a typed error for every line it could not.
    Base64-wrapped bodies are unwrapped automatically — v2rayN does the same.
    """
    text = body or ""
    lines = text.splitlines()
    # An all-base64 body is a single line with no scheme.
    if len(lines) <= 1 and lines and "://" not in lines[0] and lines[0].strip():
        try:
            decoded = base64.urlsafe_b64decode(
                lines[0].strip() + "=" * ((-len(lines[0].strip())) % 4)
            ).decode("utf-8", errors="replace")
            if "://" in decoded:
                lines = decoded.splitlines()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass

    nodes: list[Node] = []
    errors: list[ParseError] = []
    for index, line_text in enumerate(lines, start=start_line):
        stripped = line_text.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        node, error = parse_one(stripped, line=index, source=source)
        if node is not None:
            nodes.append(node)
        elif error is not None:
            errors.append(error)
    return nodes, errors
