"""Parser tests: every supported scheme, and every way a line can be bad.

The rule under test: `parse_one` returns exactly one of (node, error) and never
raises. A tested parser is the difference between "v2rayNG aborted the import"
and "we dropped the one bad line quietly".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.models import ParseErrorKind, Protocol, Security, Transport  # noqa: E402
from hub.parser import parse_json_config, parse_many, parse_one  # noqa: E402

UUID = "11111111-2222-3333-4444-555555555555"


# --------------------------------------------------------------------------- #
# valid inputs
# --------------------------------------------------------------------------- #


def test_vless_reality_full_roundtrip():
    uri = (
        "vless://11111111-2222-3333-4444-555555555555@nl.example.com:443"
        "?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome"
        "&pbk=TESTPUBKEY&sid=ab&spx=%2F&type=tcp&flow=xtls-rprx-vision"
        "#NL%20Reality%2001"
    )
    node, error = parse_one(uri)
    assert error is None and node is not None
    assert node.protocol is Protocol.VLESS
    assert node.address == "nl.example.com"
    assert node.port == 443
    assert node.uuid == UUID
    assert node.security is Security.REALITY
    assert node.tls.public_key == "TESTPUBKEY"
    assert node.tls.short_id == "ab"
    assert node.tls.spider_x == "/"
    assert node.flow == "xtls-rprx-vision"
    assert node.remark == "NL Reality 01"
    assert node.transport is Transport.TCP


def test_vless_websocket_path_decoded():
    uri = (
        "vless://11111111-2222-3333-4444-555555555555@de.example.com:80"
        "?security=tls&type=ws&path=%2Fedproxy&host=de.example.com#WS"
    )
    node, error = parse_one(uri)
    assert error is None
    assert node.transport is Transport.WS
    assert node.transport_settings.path == "/edproxy"
    assert node.transport_settings.host == "de.example.com"


def test_trojan_ws():
    uri = "trojan://pw@de.example.com:443?security=tls&type=ws&path=%2Ftr&host=de.example.com#T"
    node, error = parse_one(uri)
    assert error is None
    assert node.protocol is Protocol.TROJAN
    assert node.password == "pw"
    assert node.security is Security.TLS
    assert node.transport is Transport.WS


def test_trojan_percent_encoded_password():
    uri = "trojan://pw%40l%40w@de.example.com:443#T"
    node, error = parse_one(uri)
    assert error is None
    assert node.password == "pw@l@w"


def test_shadowsocks_sip002():
    import base64

    userinfo = base64.urlsafe_b64encode(b"aes-128-gcm:password").decode().rstrip("=")
    uri = f"ss://{userinfo}@fr.example.com:8388#FR-SS"
    node, error = parse_one(uri)
    assert error is None
    assert node.protocol is Protocol.SHADOWSOCKS
    assert node.method == "aes-128-gcm"
    assert node.password == "password"
    assert node.port == 8388


def test_shadowsocks_legacy_base64_whole():
    import base64

    blob = base64.urlsafe_b64encode(b"aes-256-gcm:pw@1.2.3.4:8388").decode().rstrip("=")
    uri = f"ss://{blob}#legacy"
    node, error = parse_one(uri)
    assert error is None
    assert node.address == "1.2.3.4"
    assert node.port == 8388
    assert node.password == "pw"


def test_vmess_base64_json():
    import base64
    import json

    payload = json.dumps(
        {
            "add": "us.example.com",
            "port": "443",
            "id": UUID,
            "net": "ws",
            "path": "/ws",
            "host": "us.example.com",
            "tls": "tls",
            "ps": "US WS",
        }
    )
    uri = "vmess://" + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    node, error = parse_one(uri)
    assert error is None
    assert node.protocol is Protocol.VMESS
    assert node.address == "us.example.com"
    assert node.transport is Transport.WS
    assert node.transport_settings.path == "/ws"
    assert node.remark == "US WS"


def test_hysteria2_with_obfs():
    uri = "hysteria2://pw@kz.example.com:443?sni=kz.example.com&obfs=salamander&insecure=1#KZ"
    node, error = parse_one(uri)
    assert error is None
    assert node.protocol is Protocol.HYSTERIA2
    assert node.obfs == "salamander"
    assert node.transport is Transport.QUIC


def test_hysteria2_carries_obfs_password():
    """The obfs password is not the obfs type — dropping it produced configs
    that started but could never negotiate the obfuscated handshake."""
    uri = (
        "hysteria2://pw@kz.example.com:443?obfs=salamander&obfs-password=secret%21&sni=kz.example.com"
    )
    node, error = parse_one(uri)
    assert error is None
    assert node.obfs == "salamander"
    assert node.obfs_password == "secret!"
    # The password is not part of a node's identity: the same endpoint with a
    # different obfs password is still one node.
    plain = "hysteria2://pw@kz.example.com:443?obfs=salamander&sni=kz.example.com"
    other, _ = parse_one(plain)
    assert other is not None
    assert other.dedup_key == node.dedup_key


def test_hysteria2_obfs_password_survives_json_import():
    nodes = parse_json_config(
        '[{"type":"hysteria2","server":"a.example.com","port":443,'
        '"password":"pw","obfs":{"type":"salamander","password":"secret"}}]'
    )
    assert len(nodes) == 1
    assert nodes[0].obfs == "salamander"
    assert nodes[0].obfs_password == "secret"


def test_tuic():
    uri = f"tuic://{UUID}:pw@us.example.com:443?congestion_control=bbr&alpn=h3#TUIC"
    node, error = parse_one(uri)
    assert error is None
    assert node.protocol is Protocol.TUIC
    assert node.uuid == UUID
    assert node.congestion == "bbr"


def test_ipv6_bracketed():
    """A bracketed IPv6 literal must survive authority splitting.

    Not `2001:db8::1`: that is the documentation prefix and the parser rejects
    it as non-routable (same rule the prober enforces). A routable literal here
    proves the brackets are stripped without also testing a rejected address.
    """
    uri = f"vless://{UUID}@[2606:4700:4700::1111]:443?security=tls#v6"
    node, error = parse_one(uri)
    assert error is None, error
    assert node.address == "2606:4700:4700::1111"
    assert node.port == 443


def test_documentation_prefix_ipv6_is_rejected():
    """`2001:db8::/32` is never routable, so it is not a valid node at all.

    This used to parse cleanly: the parser's block list was a separate copy
    without that prefix, while the prober's copy had it. A poisoned entry
    therefore survived parsing and only died at a later stage.
    """
    uri = f"vless://{UUID}@[2001:db8::1]:443?security=tls#v6"
    _, error = parse_one(uri)
    assert error is not None
    assert error.kind is ParseErrorKind.PRIVATE_ADDRESS


def test_parser_and_prober_reject_the_same_addresses():
    """The two guards are one list. If they drift, the shorter one wins.

    Every address below must be rejected by `parse_one` *and* by the prober's
    guard, because the parser is what admits a node to the pipeline and the
    guard is what stops the pipeline from dialling it.
    """
    from hub.prober import is_blocked_address

    for address in (
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "::1",
        "fe80::1",
        "fd00::1",
        "2001:db8::1",
        "100.100.100.200",
    ):
        assert is_blocked_address(address) is True, address
        _, error = parse_one(f"vless://{UUID}@[{address}]:443")
        assert error is not None, f"{address} parsed but is blocked"
        assert error.kind is ParseErrorKind.PRIVATE_ADDRESS, address


def test_ipv4_mapped_ipv6_private_is_blocked():
    """`::ffff:10.0.0.1` is a private address wearing a hat.

    The parser rejects it earlier — an unbracketed IPv6 host is ambiguous with
    `host:port` and is a `BAD_PORT` — so this checks the guard itself, which is
    the thing that must unwrap the mapping.
    """
    from hub.prober import is_blocked_address

    assert is_blocked_address("::ffff:10.0.0.1") is True
    assert is_blocked_address("[::ffff:10.0.0.1]") is True
    assert is_blocked_address("::ffff:1.1.1.1") is False


def test_metadata_and_documentation_hosts_are_blocked_both_ways():
    """Hostname aliases matter too: the parser rejects them by name."""
    from hub.prober import is_blocked_address

    for host in ("localhost", "metadata.google.internal"):
        assert is_blocked_address(host) is True, host
        _, error = parse_one(f"vless://{UUID}@{host}:443")
        assert error is not None, host


def test_socks_and_http():
    node, error = parse_one("socks://user:pw@1.2.3.4:1080")
    assert error is None and node.protocol is Protocol.SOCKS and node.username == "user"
    node, error = parse_one("http://1.2.3.4:8080")
    assert error is None and node.protocol is Protocol.HTTP_PROXY


def test_bare_base64_body_is_unwrapped():
    import base64

    good = f"vless://{UUID}@a.example.com:443?security=reality#a"
    good2 = "trojan://pw@b.example.com:443#b"
    body = base64.urlsafe_b64encode(f"{good}\n{good2}\n".encode()).decode()
    nodes, errors = parse_many(body)
    assert len(nodes) == 2 and not errors


# --------------------------------------------------------------------------- #
# invalid inputs
# --------------------------------------------------------------------------- #


def test_empty_is_error():
    _, error = parse_one("")
    assert error is not None and error.kind is ParseErrorKind.EMPTY


def test_unknown_scheme_is_error_not_skip():
    _, error = parse_one("myscheme://whatever")
    assert error is not None and error.kind is ParseErrorKind.UNKNOWN_SCHEME


def test_private_address_is_rejected_ssrf():
    _, error = parse_one(f"vless://{UUID}@10.0.0.1:443")
    assert error is not None and error.kind is ParseErrorKind.PRIVATE_ADDRESS


def test_metadata_endpoint_rejected():
    _, error = parse_one(f"vless://{UUID}@169.254.169.254:80")
    assert error is not None and error.kind is ParseErrorKind.PRIVATE_ADDRESS


def test_bad_uuid():
    _, error = parse_one("vless://not-a-uuid@a.example.com:443")
    assert error is not None and error.kind is ParseErrorKind.BAD_UUID


def test_bad_port():
    _, error = parse_one(f"vless://{UUID}@a.example.com:99999")
    assert error is not None and error.kind is ParseErrorKind.BAD_PORT


def test_missing_password():
    _, error = parse_one("trojan://@a.example.com:443")
    assert error is not None and error.kind is ParseErrorKind.MISSING_PASSWORD


def test_grpc_without_service_name_is_error():
    uri = f"vless://{UUID}@a.example.com:443?type=grpc#g"
    _, error = parse_one(uri)
    assert error is not None  # gRPC with no serviceName fails sing-box 1.8+


def test_vmess_bad_base64():
    _, error = parse_one("vmess://!!!notbase64!!!")
    assert error is not None and error.kind is ParseErrorKind.BAD_BASE64


def test_duplicate_query_keys_first_wins_like_v2rayN():
    """v2rayN's own `Utils.ParseQueryString` does `if (result[key] is null)
    result.Add(key, val)` — the first occurrence wins and later ones are
    discarded. That is the behaviour that must be matched here, because a node
    duplicated this way must configure identically in both.

    The URI deliberately puts the *unsafe* value first (`ws`, `/first`), so a
    last-wins regression would import a node the reference client configures
    differently — the failure mode this test exists to catch.
    """
    uri = (
        f"vless://{UUID}@a.example.com:443"
        "?type=ws&type=tcp&path=%2Ffirst&path=%2Fsecond#dup"
    )
    node, error = parse_one(uri)
    assert error is None
    assert node.transport is Transport.WS
    assert node.transport_settings.path == "/first"


def test_parse_many_reports_every_bad_line():
    body = "\n".join(
        [
            f"vless://{UUID}@a.example.com:443#ok",
            "",
            "# a comment",
            "garbage",
            "trojan://@b.example.com:443",
        ]
    )
    nodes, errors = parse_many(body)
    assert len(nodes) == 1
    assert len(errors) == 2
    assert {e.kind for e in errors} == {
        ParseErrorKind.UNKNOWN_SCHEME,
        ParseErrorKind.MISSING_PASSWORD,
    }


def test_parse_one_never_raises_on_weird_input():
    for value in [":", "://", "vless://", "ss://", "vmess://{}", "http://:80"]:
        _, error = parse_one(value)
        assert error is not None, value


def test_dedup_key_ignores_remark():
    a = f"vless://{UUID}@a.example.com:443?security=reality#one"
    b = f"vless://{UUID}@a.example.com:443?security=reality#two"
    node_a, _ = parse_one(a)
    node_b, _ = parse_one(b)
    assert node_a.dedup_key == node_b.dedup_key
    assert str(node_a).count(str(node_b.address)) == 1
    assert UUID not in str(node_a)  # credentials never in the display form
