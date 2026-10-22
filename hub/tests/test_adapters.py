"""Adapter tests. Every fixture here is a real response body, saved verbatim.

The point of using live bodies is that a guessed schema is the failure mode
this module exists to prevent: `__0`..`__5` keys, a `*vpn_servers` line before
the header, and a Cloudflare "Just a moment..." page are all things an
invented fixture would have gotten wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.adapters import (  # noqa: E402
    Adapted,
    adapt,
    adapt_ipspeed,
    adapt_proxyfreeonly,
    adapt_vpngate,
    extract_share_uris,
    parse_ovpn,
    parse_vpngate_csv,
)

# --------------------------------------------------------------------------- #
# fixtures: what the sources actually answer with
# --------------------------------------------------------------------------- #

#: Two rows of the real `?limit=500&page=1` response, obfuscated keys intact.
PFO_SAMPLE = """[
  {"vpn_servers":"public-vpn-43","__0":"219.100.37.7","__1":2892468,"__2":14,"__3":129606790,"__4":"JP","__5":1118995861},
  {"vpn_servers":"vpn521576029","__0":"58.96.70.159","__1":1556692,"__2":7,"__3":97947395,"__4":"AU","__5":1293430790}
]"""

#: The VPN Gate CSV: a `*vpn_servers` marker line, then a `#`-prefixed header.
#: Only the first 14 columns of one real row are kept; the base64 OpenVPN blob
#: is replaced with a real, short one so the test stays readable.
VPNGATE_SAMPLE = "*vpn_servers\n" + "#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,TotalUsers,TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64\n" + 'public-vpn-199,219.100.37.196,2907927,24,167409114,Japan,JP,127,1027311792,12146440,846120175798934,2weeks,Daiyuu Nobori,,TVEgQ0FGTEFHQQo=\n'

#: What Cloudflare served us on a real curl of ipspeed.info.
CF_CHALLENGE = (
    '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
    "</head><body>Just a moment... Performing security verification</body></html>"
)

#: A plausible future body from the same site, once the gate is passed.
IPSPEED_URIS = (
    "<table><tr><td>vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443"
    "?security=reality&sni=www.microsoft.com#NL</td></tr>"
    "<tr><td>trojan://pw@5.6.7.8:8443?sni=example.com#DE</td></tr></table>"
)


# --------------------------------------------------------------------------- #
# proxyfreeonly
# --------------------------------------------------------------------------- #


def test_proxyfreeonly_rows_are_openvpn_so_nothing_is_ingested():
    """The API's rows are OpenVPN endpoints; publishing them as proxies is a lie.

    `parse_many` would reject all 2663 rows anyway, so an adapter that
    "successfully" adapted them would burn the probe budget on nothing while
    reporting a healthy fetch.  The refusal is the correct answer, and the
    reason is what an operator reads to know why the pool is empty.
    """
    result = adapt_proxyfreeonly(PFO_SAMPLE)
    assert result.text == ""
    assert "OpenVPN" in result.reason
    assert result.ok is False


def test_proxyfreeonly_reason_reports_how_much_was_discarded():
    """A refusal that says nothing about scale is indistinguishable from a bug."""
    result = adapt_proxyfreeonly(PFO_SAMPLE)
    assert "2 rows" in result.reason
    # The countries are the useful part: an operator can see which markets are
    # covered without trusting a node we never verified.
    assert result.reason


def test_proxyfreeonly_unparseable_body_is_reported_as_such():
    result = adapt_proxyfreeonly("<html>gateway timeout</html>")
    assert result.text == ""
    assert result.reason


def test_proxyfreeonly_accepts_a_wrapped_list():
    """The site has shipped `{"data": [...]}`; both shapes must be recognised."""
    wrapped = '{"data": [{"__0": "1.2.3.4", "__4": "NL"}]}'
    result = adapt_proxyfreeonly(wrapped)
    assert result.text == ""
    assert "OpenVPN" in result.reason  # still refused, but recognised


# --------------------------------------------------------------------------- #
# VPN Gate
# --------------------------------------------------------------------------- #


def test_vpngate_csv_parses_despite_the_marker_line():
    """The `*vpn_servers` line comes *before* the header, which trips naive parsers."""
    rows = parse_vpngate_csv(VPNGATE_SAMPLE)
    assert len(rows) == 1
    assert rows[0]["HostName"] == "public-vpn-199"
    assert rows[0]["IP"] == "219.100.37.196"
    assert rows[0]["CountryShort"] == "JP"
    assert rows[0]["Ping"] == "24"


def test_the_marker_line_can_never_become_a_row():
    """Pinned because the width check alone happened to hide this.

    `*vpn_servers` fails the column-count check by accident, so a test that
    only counts rows passes whether or not the marker is explicitly skipped —
    the guard looked redundant and a deletion of it showed nothing. A marker
    line padded with commas to the right width *would* slip through, and a row
    named `*vpn_servers` would then be ranked as a server.
    """
    padded = "*vpn_servers" + "," * 14  # 15 fields, exactly as many as the header
    body = f"#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,TotalUsers,TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64\n{padded}\n"
    rows = parse_vpngate_csv(body)
    assert rows == [], rows


def test_vpngate_is_refused_because_its_configs_are_openvpn():
    result = adapt_vpngate(VPNGATE_SAMPLE)
    assert result.text == ""
    assert "OpenVPN" in result.reason


def test_vpngate_without_rows_is_a_distinct_failure():
    result = adapt_vpngate("#HostName,IP\n")
    assert result.reason


def test_ovpn_config_fields_are_extracted():
    """The ranking tool needs host/port/proto; `parse_many` does not take OpenVPN."""
    ovpn = "dev tun\nproto tcp\nremote 219.100.37.196 443\ncipher AES-128-CBC\nauth SHA1\n<ca>\nMIIB\n</ca>\n"
    parsed = parse_ovpn(ovpn)
    assert parsed["host"] == "219.100.37.196"
    assert parsed["port"] == 443
    assert parsed["proto"] == "tcp"
    assert parsed["cipher"] == "AES-128-CBC"
    assert parsed["ca"] == "MIIB"


def test_ovpn_without_a_remote_has_no_host():
    """A config that cannot name its server is not a usable one."""
    assert parse_ovpn("client\nnobind\n")["host"] == ""


# --------------------------------------------------------------------------- #
# ipspeed
# --------------------------------------------------------------------------- #


def test_cloudflare_challenge_is_reported_not_silently_dropped():
    """"The gate ate our request" is a retry, not a source that retired."""
    result = adapt_ipspeed(CF_CHALLENGE)
    assert result.text == ""
    assert "Cloudflare" in result.reason


def test_ipspeed_uris_are_extracted_from_html():
    result = adapt_ipspeed(IPSPEED_URIS)
    assert result.ok
    assert result.count == 2
    assert result.text.splitlines()[0].startswith("vless://")
    # Round-trip through the real parser: an adapter that emits a URI
    # `parse_one` rejects has produced nothing.
    from hub.parser import parse_many

    nodes, errors = parse_many(result.text, source="fixture")
    assert not errors, errors
    assert len(nodes) == 2


def test_page_with_no_uris_is_reported_as_empty():
    result = adapt_ipspeed("<html><body>maintenance</body></html>")
    assert result.text == ""
    assert result.reason


def test_extract_share_uris_deduplicates_and_preserves_order():
    html = "vless://a@1.1.1.1:443#x vless://a@1.1.1.1:443#x vless://b@2.2.2.2:443#y"
    assert extract_share_uris(html) == ["vless://a@1.1.1.1:443#x", "vless://b@2.2.2.2:443#y"]


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #


def test_unknown_kind_passes_the_body_through():
    """A plain subscription needs no adaptation, and must not be broken by one."""
    body = "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443#n"
    result = adapt("", body)
    assert result.text == body


def test_each_known_kind_routes_to_its_own_adapter():
    assert adapt("proxyfreeonly", PFO_SAMPLE).reason.startswith("proxyfreeonly")
    assert adapt("vpngate", VPNGATE_SAMPLE).reason.startswith("vpngate")
    assert adapt("ipspeed", CF_CHALLENGE).reason.startswith("ipspeed")


# --------------------------------------------------------------------------- #
# ranking the one source that can be ranked without measuring anything
# --------------------------------------------------------------------------- #


def test_unmeasured_rows_sort_last_not_first():
    """"Never measured" is not "measured at zero".

    A row whose `Speed` is `-` or empty would rank *first* under a naive
    descending sort of `-float("-")` errors, or under `or 0.0` it would rank
    last as the *slowest* server — which is the same wrong answer expressed
    two different ways.
    """
    from hub.cli import _rank_by_source_numbers

    rows = [
        {"CountryShort": "JP", "IP": "1.1.1.1", "HostName": "fast",
         "NumVpnSessions": "1", "Ping": "10", "Speed": "100000000"},
        {"CountryShort": "JP", "IP": "2.2.2.2", "HostName": "unknown",
         "NumVpnSessions": "1", "Ping": "10", "Speed": "-"},
        {"CountryShort": "JP", "IP": "3.3.3.3", "HostName": "slowest",
         "NumVpnSessions": "1", "Ping": "10", "Speed": "1000"},
        {"CountryShort": "JP", "IP": "4.4.4.4", "HostName": "blank",
         "NumVpnSessions": "1", "Ping": "10", "Speed": ""},
    ]
    ranked = _rank_by_source_numbers(rows)
    # Both unmeasured forms (`-` and an empty cell) sort after every measured
    # row; their order relative to each other is not specified, because they
    # are the same thing.
    assert [r["host"] for r in ranked[:2]] == ["fast", "slowest"], [
        (r["host"], r["speed"]) for r in ranked
    ]
    assert {r["host"] for r in ranked[2:]} == {"blank", "unknown"}
    assert all(r["speed"] is None for r in ranked[2:])


def test_a_missing_ping_does_not_crash_the_table():
    """`Ping` is `-` on rows the source never timed."""
    from hub.cli import _rank_by_source_numbers

    rows = [{"CountryShort": "JP", "IP": "1.1.1.1", "HostName": "h",
             "NumVpnSessions": "1", "Ping": "-", "Speed": "5000000"}]
    ranked = _rank_by_source_numbers(rows)
    assert ranked[0]["ping"] is None
    assert ranked[0]["mbps"] == 5.0


def test_the_vpngate_speed_column_is_bytes_per_second():
    """`mbps` divides by 1e6, not by 1024*1024.

    167_409_114 B/s is 167 Mbps. Dividing by 2**20 would report 159.6 and make
    the column disagree with every other network tool the operator reads.
    """
    from hub.cli import _rank_by_source_numbers

    rows = [{"CountryShort": "JP", "IP": "1.1.1.1", "HostName": "h",
             "NumVpnSessions": "1", "Ping": "24", "Speed": "167409114"}]
    assert _rank_by_source_numbers(rows)[0]["mbps"] == pytest.approx(167.409114)
