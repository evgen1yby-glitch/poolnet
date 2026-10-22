"""Renderer tests, including the traps that break naive generators."""

from __future__ import annotations

import base64
import json
import re
import tempfile
import sys
import uuid as uuid_lib

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hub.models import Format, Protocol, Security, Transport, TransportSettings, TLS  # noqa: E402
from hub.parser import parse_one  # noqa: E402
from hub.renderer import (  # noqa: E402
    RenderParams,
    mint_tag,
    render_base64,
    render_clash,
    render_singbox,
    render_validated,
)

UUID = "11111111-2222-3333-4444-555555555555"


def _node(**over):
    from hub.models import Node

    base = dict(
        protocol=Protocol.VLESS,
        address="nl.example.com",
        port=443,
        uuid=UUID,
        transport=Transport.TCP,
        transport_settings=TransportSettings(kind=Transport.TCP),
        security=Security.REALITY,
        tls=TLS(sni="www.microsoft.com", fingerprint="chrome",
               public_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", short_id="ab"),
        flow="xtls-rprx-vision",
        remark="NL 01",
        country="NL",
        source="fixture",
    )
    base.update(over)
    return Node(**base)


def _params(**over):
    base = dict(fmt=Format.SINGBOX, client_core="sing-box", title="hub", cache_id="abc123")
    base.update(over)
    return RenderParams(**base)


# --------------------------------------------------------------------------- #
# tags
# --------------------------------------------------------------------------- #


def test_tags_are_minted_and_unique():
    used: set[str] = set()
    a = mint_tag(1, _node(address="a.example.com"), used=used)
    b = mint_tag(1, _node(address="b.example.com"), used=used)
    assert a != b
    # A deliberate collision is extended, not silently overwritten: sing-box
    # FATALs on duplicate tags.
    c = mint_tag(1, _node(address="a.example.com"), used=used)
    assert c not in (a, b)
    # The name is the country, numbered — not a serial. A user picks from this
    # string, so `n001-vless-nl` told them the node's index in this build and
    # nothing they could act on.
    assert c == "🇳🇱 Нидерланды 3", c


def test_tag_is_deterministic_for_same_pool():
    used: set[str] = set()
    assert mint_tag(3, _node(), used=used) == mint_tag(3, _node(), used=set())


# --------------------------------------------------------------------------- #
# base64
# --------------------------------------------------------------------------- #


def test_base64_roundtrip_and_uri_validity():
    nodes = [_node(), _node(address="de.example.com", country="DE", remark="DE 01")]
    payload = render_base64(nodes, _params(fmt=Format.BASE64))
    import base64

    lines = base64.b64decode(payload).decode().splitlines()
    assert len(lines) == 2
    for line in lines:
        back, error = parse_one(line)
        assert error is None, (line, error)
        assert back.address != ""


def test_base64_emits_no_headers():
    payload = render_base64([_node()], _params(fmt=Format.BASE64))
    assert "profile-title" not in payload
    assert "subscription-userinfo" not in payload


# --------------------------------------------------------------------------- #
# sing-box
# --------------------------------------------------------------------------- #


def test_singbox_config_is_valid_json_and_shaped_right():
    nodes = [_node(), _node(address="de.example.com", country="DE")]
    text = render_singbox(nodes, _params())
    config = json.loads(text)  # raises if malformed

    order = [o.get("type") for o in config["outbounds"]]
    # The last three are the group, the selector, and the direct exit the
    # route rules point at. `urltest` must come before `selector` (the
    # selector's `outbounds` list references it), and `direct` must exist at
    # all — the route rules send DNS and private traffic to it.
    assert order[-3:] == ["urltest", "selector", "direct"]
    assert config["route"]["final"] == "proxy"
    assert config["dns"]["servers"][1]["server"] == "198.18.0.2"
    assert config["experimental"]["cache_file"]["cache_id"] == "abc123"


def test_singbox_interval_is_go_duration_not_seconds():
    text = render_singbox([_node()], _params())
    urltest = [o for o in json.loads(text)["outbounds"] if o["type"] == "urltest"][0]
    # "10m" is correct; 300 fails validation in sing-box.
    assert urltest["interval"] == "10m"
    assert isinstance(urltest["interval"], str)
    assert urltest["tolerance"] == 150
    assert urltest["interrupt_exist_connections"] is False


def test_singbox_drops_xhttp_for_singbox_core():
    nodes = [
        _node(),
        _node(
            address="x.example.com",
            transport=Transport.XHTTP,
            transport_settings=TransportSettings(kind=Transport.XHTTP, path="/x"),
        ),
    ]
    text = render_singbox(nodes, _params(client_core="sing-box"))
    tags = [o["tag"] for o in json.loads(text)["outbounds"]]
    assert not any("x.example" in t for t in tags)
    assert len([o for o in json.loads(text)["outbounds"] if o["type"] == "vless"]) == 1


def test_singbox_keeps_xhttp_for_xray_core():
    nodes = [
        _node(
            address="x.example.com",
            transport=Transport.XHTTP,
            transport_settings=TransportSettings(kind=Transport.XHTTP, path="/x"),
        )
    ]
    text = render_singbox(nodes, _params(client_core="xray"))
    assert len([o for o in json.loads(text)["outbounds"] if o["type"] == "vless"]) == 1


def test_singbox_reality_section_present():
    text = render_singbox([_node()], _params())
    outbound = [o for o in json.loads(text)["outbounds"] if o["type"] == "vless"][0]
    # The fixture's key is a real 32-byte base64url value, not a placeholder:
    # Xray refuses a short one outright ("invalid password"), so a stub here
    # would let a payload through that no Xray core can start.
    assert outbound["tls"]["reality"]["public_key"].startswith("AAECAwQFBgcI")
    assert outbound["tls"]["utls"]["fingerprint"] == "chrome"
    assert "allowInsecure" not in outbound["tls"]


def test_cache_id_changes_when_pool_changes():
    a = render_singbox([_node()], _params(cache_id="aaa"))
    b = render_singbox([_node(), _node(address="b.example.com")], _params(cache_id="bbb"))
    assert json.loads(a)["experimental"]["cache_file"]["cache_id"] == "aaa"
    assert json.loads(b)["experimental"]["cache_file"]["cache_id"] == "bbb"


# --------------------------------------------------------------------------- #
# clash
# --------------------------------------------------------------------------- #


def test_clash_interval_is_integer_seconds():
    text = render_clash([_node()], _params(fmt=Format.CLASH))
    assert re.search(r"^\s+interval: 600$", text, re.MULTILINE)  # int, not "10m"
    assert "interval: 10m" not in text
    assert re.search(r"^\s+tolerance: 150$", text, re.MULTILINE)


def test_clash_proxy_names_are_unique():
    nodes = [_node(), _node(address="a.example.com"), _node(address="b.example.com")]
    text = render_clash(nodes, _params(fmt=Format.CLASH))
    names = re.findall(r'name: "(n\d+-[^"]+)"', text)
    assert len(names) == len(set(names))


def test_clash_proxy_list_matches_group_membership():
    nodes = [_node(), _node(address="a.example.com")]
    text = render_clash(nodes, _params(fmt=Format.CLASH))
    proxies = set(re.findall(r'^\s+- \{name: "(n\d+[^"]+)"', text, re.MULTILINE))
    group = set(
        re.findall(r"^\s+- (n\d+[^\s]+)$", text, re.MULTILINE)
    )
    assert proxies <= group


# --------------------------------------------------------------------------- #
# chunking
# --------------------------------------------------------------------------- #


def test_payload_is_chunked_to_max_nodes():
    nodes = [_node(address=f"{i}.example.com") for i in range(500)]
    payload, included = render_validated(
        nodes, _params(max_nodes=200, fmt=Format.BASE64, client_core="sing-box")
    )
    assert len(included) == 200
    import base64

    assert len(base64.b64decode(payload).decode().splitlines()) == 200


# --------------------------------------------------------------------------- #
# validation hook
# --------------------------------------------------------------------------- #


def test_validation_failure_returns_none_payload():
    """A payload that never validates must raise, not silently publish.

    The first `render_validated(nodes, validate=always_fail)` is the point:
    with one node and a validator that always fails there is nothing to
    fall back to, so the only honest outcome is an exception the caller can
    turn into "keep the previous generation".
    """
    nodes = [_node()]
    with pytest.raises(ValueError):
        render_validated(nodes, _params(), validate=lambda text, fmt: False)


def test_validation_pass_returns_payload():
    calls = []

    def ok(text, fmt):
        calls.append(fmt)
        return True

    nodes = [_node()]
    payload, included = render_validated(nodes, _params(), validate=ok)
    assert payload is not None
    assert len(included) == 1
    assert calls == [Format.SINGBOX]


def test_render_validated_drops_tail_not_head():
    """When validation keeps failing, the tail is dropped — never the head.

    `render_validated` re-renders with a shrinking pool until the validator
    passes, so the question it answers is *which* node gets cut. BASE64 keeps
    the payload one-URI-per-node so the count is unambiguous, and the nodes are
    passed in strength order, so the head must survive every attempt.
    """
    import base64

    good = [_node(address=f"{i}.example.com") for i in range(20)]
    attempts: list[int] = []

    def flaky(text, fmt):
        attempts.append(len(base64.b64decode(text).decode().splitlines()))
        # Fail until only a few nodes remain: the tail is what gets cut.
        return attempts[-1] <= 3

    payload, included = render_validated(
        good, _params(fmt=Format.BASE64, max_nodes=20), validate=flaky
    )
    assert included
    assert len(included) <= 3
    # Each attempt cuts the tail by ~10%, so the pool only ever shrinks and the
    # first node — the strongest — is still emitted when validation finally
    # passes. 20 -> 18 -> 16 -> ... is descending, never ascending.
    assert attempts == sorted(attempts, reverse=True)
    assert "0.example.com" in base64.b64decode(payload).decode()


# --------------------------------------------------------------------------- #
# country groups
# --------------------------------------------------------------------------- #


def _outbounds_of(text):
    return json.loads(text)["outbounds"]


def test_each_country_gets_its_own_urltest_group():
    """Four Dutch nodes must land in one group, not four separate entries.

    This is the whole "one country, one destination, automatic switch" feature:
    a client shows `g-nl` with the four members behind it, so a dead node is
    replaced by a live one without the user touching anything. A flat selector
    over individual nodes would leave the user picking nodes by hand.
    """
    nodes = [
        _node(address=f"nl{i}.example.com", remark=f"NL {i}") for i in range(4)
    ]
    # add two German nodes so there is more than one country in play
    nodes += [_node(address=f"de{i}.example.com", remark=f"DE {i}", country="DE")
              for i in range(2)]

    text = render_singbox(nodes, _params())
    groups = [o for o in _outbounds_of(text) if o["type"] == "urltest"]
    by_tag = {g["tag"]: g["outbounds"] for g in groups}

    assert set(by_tag) == {"🇳🇱 Нидерланды", "🇩🇪 Германия"}, by_tag
    # Size, not order: the deterministic order is asserted separately because it
    # is what keeps `cache_id` stable across rotations.
    assert len(by_tag["🇳🇱 Нидерланды"]) == 4
    assert len(by_tag["🇩🇪 Германия"]) == 2


def test_group_selection_is_flat_not_nested():
    """sing-box #1807 crashes on a selector whose members are urltest groups.

    The selector therefore lists the *group tags* and the node tags together,
    which is a flat reference the client resolves without a second level of
    indirection. Read structurally rather than by count of nesting, because
    "how deep is too deep" is exactly the question that bug turns on.
    """
    nodes = [_node(address=f"nl{i}.example.com", remark=f"NL {i}") for i in range(3)]
    nodes += [_node(address=f"de{i}.example.com", remark=f"DE {i}", country="DE")
              for i in range(3)]
    text = render_singbox(nodes, _params())
    outbounds = _outbounds_of(text)
    selector = next(o for o in outbounds if o["type"] == "selector")
    urltests = {o["tag"] for o in outbounds if o["type"] == "urltest"}
    # `direct` is a real outbound too, and the selector is allowed to name it.
    leaf_tags = {o["tag"] for o in outbounds
                 if o.get("type") in ("vless", "trojan", "ss", "direct")}

    # Every reference in the selector resolves at the same level: a group tag or
    # a node tag, never a tag of a group that itself contains groups.
    for ref in selector["outbounds"]:
        assert ref in urltests or ref in leaf_tags, ref
    assert {"🇳🇱 Нидерланды", "🇩🇪 Германия"} <= set(selector["outbounds"])
    # The shape #1807 crashes on: a group whose members are groups.
    for group in (o for o in outbounds if o["type"] == "urltest"):
        assert not (set(group["outbounds"]) & urltests), group["tag"]


def test_nodes_without_a_measured_country_become_the_auto_group():
    """An unmeasured country is not a country, and must not invent one.

    The landing page shows "unknown" rather than guessing from the hostname;
    the payload has to agree with the page or a user clicks a country and gets
    nodes that exit somewhere else.
    """
    nodes = [_node(address="mystery.example.com", remark="?", country="")]
    text = render_singbox(nodes, _params())
    groups = [o for o in _outbounds_of(text) if o["type"] == "urltest"]
    assert [g["tag"] for g in groups] == ["auto"]
    assert len(groups[0]["outbounds"]) == 1


def test_country_shard_emits_only_that_country():
    """A shard is the payload a "Netherlands" link on the page points at."""
    nodes = [
        _node(address="nl1.example.com", remark="NL 1"),
        _node(address="de1.example.com", remark="DE 1", country="DE"),
        _node(address="nl2.example.com", remark="NL 2"),
    ]
    text = render_singbox(nodes, _params(country="nl"))
    outbounds = _outbounds_of(text)
    node_tags = {o["tag"] for o in outbounds if o.get("type") in ("vless", "trojan", "ss")}
    # Every node in the payload carries the Dutch tag suffix minted by the
    # renderer, so counting tags is the same as counting nodes.
    assert len(node_tags) == 2
    assert all("Нидерланды" in t for t in node_tags), node_tags
    # One group, and it is Dutch.
    assert [g["tag"] for g in outbounds if g["type"] == "urltest"] == ["🇳🇱 Нидерланды"]


def test_shard_for_a_country_with_no_nodes_is_empty_but_valid():
    """An empty shard must not produce a dangling reference.

    A payload that references a group with no members is a FATAL in sing-box and
    a broken import in mihomo, which is worse than an honest empty result.
    """
    nodes = [_node(address="de1.example.com", remark="DE 1", country="DE")]
    text = render_singbox(nodes, _params(country="nl"))
    config = json.loads(text)
    assert config["outbounds"], "an empty payload still needs a proxy shape"
    for group in (o for o in config["outbounds"] if o["type"] == "urltest"):
        assert group["outbounds"], f"{group['tag']} has no members"


def test_a_mixed_pool_filters_by_country_in_every_dialect():
    """The filter inside the renderer, not the one in `country_shards`.

    `country_shards` hands `render` a pool that is already one country, so a
    shard built from a shard cannot tell whether the renderer filters at all.
    The filter matters for a caller that passes a *mixed* pool with `country`
    set — which is what the landing page's per-country link used to be, and
    what any future caller will naturally write. Tested per dialect because the
    three dialects implement the filter three times, and a mutation to one of
    them is invisible to a test that only renders one.
    """
    nodes = [
        _node(uuid=str(uuid_lib.UUID(int=1)), remark="NL 1",
              address="nl1.example.com", country="NL"),
        _node(uuid=str(uuid_lib.UUID(int=2)), remark="DE 1",
              address="de1.example.com", country="DE"),
        _node(uuid=str(uuid_lib.UUID(int=3)), remark="NL 2",
              address="nl2.example.com", country="NL"),
    ]

    # base64: decode, then compare hosts. Not substrings — the flag emoji in
    # the remark percent-encodes to bytes that contain the other country code.
    b64 = render_base64(nodes, _params(fmt=Format.BASE64, country="nl"))
    hosts = {u.split("@", 1)[1].split(":", 1)[0]
             for u in base64.b64decode(b64).decode().split()}
    assert hosts == {"nl1.example.com", "nl2.example.com"}, hosts

    # clash: the proxy names are minted from the country, so a leaked DE node
    # shows up as a `-de` name.
    clash = render_clash(nodes, _params(fmt=Format.CLASH, client_core="mihomo", country="nl"))
    assert "Германия" not in clash, clash
    assert clash.count("Нидерланды") >= 2, clash

    # sing-box: already covered above, asserted here too so the three dialects
    # fail together if the shared contract ever regresses.
    sb = render_singbox(nodes, _params(country="nl"))
    assert "de1" not in sb, sb


def test_country_group_order_is_stable():
    """Same input, same bytes: `cache_id` depends on it.

    Ordering by descending size then alphabetically means a pool that gains one
    Dutch node does not reshuffle the German group's position, so clients do not
    see a changed payload — and the user does not see their selection move.
    """
    def build():
        nodes = [
            _node(address=f"de{i}.example.com", remark=f"DE {i}", country="DE")
            for i in range(3)
        ]
        nodes += [
            _node(address=f"nl{i}.example.com", remark=f"NL {i}") for i in range(2)
        ]
        return render_singbox(nodes, _params())

    first = build()
    groups = [o["tag"] for o in _outbounds_of(first) if o["type"] == "urltest"]
    assert groups == ["🇩🇪 Германия", "🇳🇱 Нидерланды"], groups  # 3 DE nodes then 2 NL nodes
    assert build() == first


# --------------------------------------------------------------------------- #
# per-country shards
# --------------------------------------------------------------------------- #


def test_a_country_shard_contains_only_that_country():
    """The whole point of the shard: `country/nl` must not contain DE nodes.

    Asserted by *decoding* the payload and counting the share URIs, not by
    searching the raw bytes for the other country's code: base64 of an NL URI
    contains the substring "de" by coincidence, and a test that searches raw
    base64 fails on a correct payload — which is how a test ends up enforcing a
    property nobody meant.
    """
    from hub.renderer import country_shards

    # Every node needs its own uuid *and* remark: `_filtered` dedups on the
    # share URI, and a fixture pool of identical credentials collapses to one
    # node regardless of address. A test built on such a pool asserts a count
    # that is true for the wrong reason, and passes with the country filter
    # deleted.
    def pool(cc, host, n):
        return [
            _node(
                uuid=str(uuid_lib.UUID(int=i)),
                remark=f"{cc} node {i}",
                address=f"{host}{i}.example.com",
                country=cc,
            )
            for i in range(n)
        ]

    nodes = pool("NL", "nl", 3) + pool("DE", "de", 3)
    nl = next(s for s in country_shards(nodes) if s.cc == "NL")
    # Decode, then compare *hosts*, not substrings: the remark carries the
    # country's flag emoji, and its percent-encoding contains the other
    # country's code by coincidence (`nl` -> `%F0%9F%87%B3...`, whose bytes
    # include "de"). A substring test on the URI is therefore unsound in both
    # directions — it fails on a correct payload and can pass on a wrong one.
    uris = base64.b64decode(nl.payload).decode().split()
    hosts = {u.split("@", 1)[1].split(":", 1)[0] for u in uris}
    assert hosts == {"nl0.example.com", "nl1.example.com", "nl2.example.com"}, hosts
    assert nl.included == 3, nl.included


def test_a_country_with_one_node_still_gets_a_shard():
    """One node is enough to be a country a user can be given a link for.

    The threshold was 2, reasoning that a one-node file is "a redirect with
    extra steps". That optimises for file count and misses the point of the
    endpoint: a user tests *that country*, and a 404 because the country is
    small is not a saving — it is the feature being unavailable. The pool is
    long-tailed, so most countries have one or two nodes.
    """
    from hub.renderer import country_shards

    nodes = [_node(country="NL") for _ in range(4)] + [_node(country="DE")]
    codes = {s.cc for s in country_shards(nodes)}
    assert "DE" in codes, codes
    assert "NL" in codes, codes


def test_shards_are_capped_and_the_cap_is_the_biggest_countries():
    """Capped by node count, not by country code, and the cap is visible.

    Sorting by *count* is what makes the cap safe to raise: the countries that
    get a file are the ones users actually ask for. Sorting by code instead
    would silently drop the big ones whenever the alphabet went the other way.
    """
    from hub.renderer import MAX_COUNTRY_SHARDS, country_shards

    # `MAX_COUNTRY_SHARDS + 5` distinct countries, each with exactly the minimum
    # number of nodes, so the cap is the only thing deciding who is in. Codes
    # are spelled out rather than generated, because a generator that collides
    # tests a smaller pool than it claims to and the assertion passes anyway.
    singles = [f"C{i:02d}" for i in range(MAX_COUNTRY_SHARDS + 5)]
    assert len(set(singles)) == MAX_COUNTRY_SHARDS + 5, "fixture codes must be distinct"

    nodes = [_node(address=f"big{i}.example.com", country="US") for i in range(9)]
    nodes += [_node(address=f"{cc.lower()}{i}.example.com", country=cc)
              for cc in singles for i in range(2)]

    shards = country_shards(nodes)
    codes = {s.cc for s in shards}
    assert len(codes) <= MAX_COUNTRY_SHARDS, sorted(codes)
    assert "US" in codes, "the biggest country lost its shard"
    assert codes == {"US"} | set(singles[: MAX_COUNTRY_SHARDS - 1]), sorted(codes)


def test_a_node_with_no_measured_country_rides_in_the_full_payload():
    """`country=""` is not a country, and must not become a shard for "".

    `country_shards` skips empties rather than writing `verified-.singbox`: a
    file named for the empty string is both useless to a client and a lookup
    that `_CC` in the API would have to special-case.
    """
    from hub.renderer import country_shards

    nodes = [_node(country="NL") for _ in range(3)] + [_node(country="") for _ in range(3)]
    codes = {s.cc for s in country_shards(nodes)}
    assert "" not in codes, codes
    assert codes == {"NL"}, codes


def test_shard_order_is_stable_for_the_same_pool():
    """A shard list that reorders makes the generation id a lottery.

    The generation name is content-derived over payload names, so if the
    *order* of shards depends on dict or set iteration, the same pool hashes to
    two different generation ids on two runs — the content-addressed rollback
    quietly not working, with nothing else failing to point at it.

    Note what is *not* asserted: that the payload bytes are identical when the
    node order changes. Tags are index-derived (`n001-…`), so reversing the pool
    legitimately produces different tags. Ordering the shard *list* is what is
    stable, and that is the part the generation digest is computed over.
    """
    from hub.renderer import country_shards

    def pool(order):
        nodes = [_node(address=f"nl{i}.example.com", country="NL") for i in range(3)]
        nodes += [_node(address=f"de{i}.example.com", country="DE") for i in range(3)]
        nodes += [_node(address=f"fr{i}.example.com", country="FR") for i in range(2)]
        return nodes if order else list(reversed(nodes))

    first = [(s.cc, s.fmt) for s in country_shards(pool(True))]
    second = [(s.cc, s.fmt) for s in country_shards(pool(False))]
    assert first == second, (first, second)
    assert first, "no shards at all"


def test_xray_shards_are_base64_only():
    """A core that cannot read a dialect must not get a shard in it.

    `verified-NL.singbox` served to an Xray client is a 200 with garbage in it,
    which is worse than a 404: the client looks like it succeeded.
    """
    from hub.renderer import Format, country_shards

    nodes = [_node(country="NL") for _ in range(3)]
    xray = {s.fmt for s in country_shards(nodes, core="xray")}
    assert xray == {Format.BASE64}, xray
    clash = {s.fmt for s in country_shards(nodes, core="mihomo")}
    assert clash == {Format.CLASH}, clash


def test_clash_payload_survives_hostile_field_values():
    """A node field must not be able to forge YAML structure.

    The Clash emitter built each proxy by string concatenation, so a value
    containing a double quote, a brace and a newline closed the flow mapping
    and injected new keys — `password: "x", udp: false}\n    extra: {a: 1}`
    is not a password, it is a second YAML node. `yaml.safe_load` then parses
    the forged structure happily, and the published payload no longer means
    what the renderer thinks it wrote.

    These values come from upstream subscription sources, i.e. from text the
    project does not control.
    """
    import yaml

    hostile = 'pw", udp: false}\n  injected: {a: 1}\n  x: "'
    nodes = [
        _node(protocol=Protocol.SHADOWSOCKS, method="aes-256-gcm", password=hostile, remark="ss"),
        _node(protocol=Protocol.TROJAN, password=hostile, remark="tj"),
        _node(remark=hostile, tls=TLS(sni=hostile, fingerprint="chrome", public_key="K", short_id="ab")),
    ]
    payload = render_clash(nodes, _params(fmt=Format.CLASH))
    doc = yaml.safe_load(payload)

    proxies = doc["proxies"]
    assert len(proxies) == len(nodes)
    # The forged key must not have become structure anywhere in the document.
    for proxy in proxies:
        assert "injected" not in proxy, proxy
    # And the round trip must preserve the password verbatim.
    ss = next(p for p in proxies if p["type"] == "ss")
    assert ss["password"] == hostile


def test_remarks_are_human_names_not_source_repo_names():
    """What the user sees must be a country, not the GitHub repo it came from.

    The remark was `node.remark`, which the parser fills from the upstream
    share URI's fragment. For this pool that fragment is the *source's* own
    label — every node from `Epodonios/vless` is called "EPODONIOS" — so a
    subscription listed 25 identical names, and VMess nodes (whose XML-ish
    format carries no fragment) had no name at all. A flat list of the same
    word is not a usable client UI.
    """
    import base64 as b64

    nodes = [
        _node(country="NL", remark="EPODONIOS"),
        _node(country="DE", remark="EPODONIOS"),
        _node(country="FI", remark=""),
    ]
    raw = render_base64(nodes, _params(fmt=Format.BASE64))
    lines = b64.b64decode(raw).decode("utf-8").splitlines()
    assert len(lines) == 3

    import urllib.parse as up

    fragments = [up.unquote(up.urlparse(line).fragment) for line in lines]
    # No node may be labelled with the upstream source's name.
    for fragment in fragments:
        assert "EPODONIOS" not in fragment.upper(), fragments
    # And every node has a name, including the one whose remark was empty.
    for fragment in fragments:
        assert fragment.strip(), fragments


def test_remark_names_are_unique_within_a_payload():
    """Two nodes with the same country must still be distinguishable.

    `mint_tag` already de-collides *tags* for sing-box and mihomo, where a
    duplicate is a hard error. The remark is the same problem in the base64
    dialect, where nothing de-collides it: a client shows a list, and two
    identical rows cannot be told apart or reliably selected.
    """
    import base64 as b64
    import urllib.parse as up

    nodes = [_node(country="NL", remark="EPODONIOS") for _ in range(5)]
    raw = render_base64(nodes, _params(fmt=Format.BASE64))
    lines = b64.b64decode(raw).decode("utf-8").splitlines()
    fragments = [up.unquote(up.urlparse(line).fragment) for line in lines]
    assert len(set(fragments)) == len(fragments), fragments


def test_tag_is_a_human_label_not_a_serial():
    """The sing-box/mihomo tag is the node name a user picks from.

    `n001-vless-fi` is a serial number: it tells a user the index of the node
    in this build and nothing they can act on. The country and a way to tell
    two nodes of the same country apart is what the list needs.
    """
    import json

    nodes = [_node(country="NL"), _node(country="DE"), _node(country="NL")]
    payload = render_singbox(nodes, _params(fmt=Format.SINGBOX))
    config = json.loads(payload)
    tags = [o["tag"] for o in config["outbounds"] if o.get("type") in ("vless", "vmess", "trojan", "shadowsocks", "hysteria2", "tuic")]
    assert len(tags) == 3
    assert len(set(tags)) == 3, tags
    for tag in tags:
        assert not tag.startswith("n0"), tag
        assert "-vless-" not in tag, tag


def test_the_top_level_selector_lists_countries_only():
    """The user must see one entry per country, not that plus every node.

    The design is "one link, showing a list of countries": picking a country
    connects to its best reachable node and re-picks when that node dies. The
    `g-{CC}` urltest groups already do that. But the top-level `proxy` selector
    also listed every individual node (`group_tags + tags`), so a client showed
    "🇫🇮 Финляндия" *and* "🇫🇮 Финляндия 2/3/4" — the country selector plus the
    four members it already rotates between. A list of 25 nodes for 9 countries
    is not a country picker, and the duplicates are unusable: a user who taps
    one node gets that node only, with no failover, which is the exact failure
    the grouping exists to prevent.
    """
    import json

    nodes = [_node(country="FI") for _ in range(4)] + [_node(country="DE") for _ in range(2)]
    config = json.loads(render_singbox(nodes, _params(fmt=Format.SINGBOX)))

    proxy = next(o for o in config["outbounds"] if o.get("tag") == "proxy")
    members = proxy["outbounds"]

    # Exactly: one group per country, plus `direct`. No bare node tags.
    group_tags = [o["tag"] for o in config["outbounds"] if o.get("type") == "urltest"]
    node_tags = [
        o["tag"] for o in config["outbounds"]
        if o.get("type") in ("vless", "vmess", "trojan", "shadowsocks", "hysteria2", "tuic")
    ]
    assert set(group_tags) == {"🇫🇮 Финляндия", "🇩🇪 Германия"}, group_tags
    assert not (set(members) & set(node_tags)), (
        "individual nodes leaked into the country picker: "
        f"{sorted(set(members) & set(node_tags))}"
    )
    assert sorted(members) == sorted(group_tags + ["direct"]), members


def test_every_node_is_still_reachable_through_its_country_group():
    """Dropping nodes from the selector must not drop them from the payload.

    The fix is to stop *listing* nodes at the top level, not to stop emitting
    them: each one is still an outbound and still a member of its country's
    urltest group, which is what makes failover work.
    """
    import json

    nodes = [_node(country="FI") for _ in range(3)]
    config = json.loads(render_singbox(nodes, _params(fmt=Format.SINGBOX)))
    group = next(o for o in config["outbounds"] if o.get("tag") == "🇫🇮 Финляндия")
    assert len(group["outbounds"]) == 3, group["outbounds"]


def test_the_clash_country_picker_lists_countries_only():
    """The mihomo `proxy` select must offer countries, not countries plus nodes.

    Same defect as the sing-box selector, in the other dialect: `proxy` listed
    the country groups *and* every individual node, so a Clash user saw
    "🇫🇮 Финляндия" next to "🇫🇮 Финляндия 2/3/4". Picking a node bypasses the
    url-test group, so it never fails over.
    """
    import yaml

    nodes = [_node(country="FI") for _ in range(4)] + [_node(country="DE")]
    doc = yaml.safe_load(render_clash(nodes, _params(fmt=Format.CLASH)))

    groups = {g["name"]: g for g in doc["proxy-groups"]}
    node_names = {p["name"] for p in doc["proxies"]}

    selector = groups["proxy"]
    leaked = [m for m in selector["proxies"] if m in node_names]
    assert not leaked, f"individual nodes leaked into the picker: {leaked}"

    # Every country is offered, and every node is still reachable through its
    # country's url-test group.
    assert "🇫🇮 Финляндия" in selector["proxies"], selector["proxies"]
    assert groups["🇫🇮 Финляндия"]["type"] == "url-test"
    assert len(groups["🇫🇮 Финляндия"]["proxies"]) == 4, groups["🇫🇮 Финляндия"]["proxies"]
    # DIRECT/REJECT stay: they are mihomo built-ins a user expects.
    assert "REJECT" in selector["proxies"], selector["proxies"]


def test_one_node_per_country_removes_the_duplicates():
    """The Happ shape: one entry per country, so the list is a country picker.

    Happ does not support proxy groups — its own documentation describes a
    subscription body as a URI list or a JSON array and never mentions groups,
    load balancing or automatic selection. So the `urltest` grouping this
    project emits is invisible there, and a flat list shows every node: four
    "🇫🇮 Финляндия" entries in a row.

    With one node per country the list *is* the country picker, and the node
    kept is the best-scoring one because the input is already sorted by score.
    What is lost is client-side failover, which is a property of the client,
    not something this endpoint can add.
    """
    from hub.renderer import RenderParams, render_base64
    import base64 as b64
    import urllib.parse as up

    nodes = (
        [_node(country="FI", remark="") for _ in range(4)]
        + [_node(country="DE", remark="") for _ in range(2)]
        + [_node(country="BR", remark="")]
    )
    params = RenderParams(
        fmt=Format.BASE64, client_core="xray", title="hub", one_per_country=True
    )
    lines = b64.b64decode(render_base64(nodes, params)).decode("utf-8").splitlines()
    assert len(lines) == 3, lines  # FI, DE, BR — not 7

    names = [up.unquote(up.urlparse(line).fragment) for line in lines]
    assert names == ["🇧🇷 Бразилия", "🇩🇪 Германия", "🇫🇮 Финляндия"], names


def test_one_per_country_can_be_turned_off():
    """The full list stays available: it is the format with real failover.

    Dropping nodes for every consumer would trade the sing-box/mihomo
    failover for a cosmetic property, so this is opt-in per request.
    """
    from hub.renderer import RenderParams, render_base64
    import base64 as b64

    nodes = [_node(country="FI", remark="") for _ in range(4)]
    params = RenderParams(fmt=Format.BASE64, client_core="xray", title="hub")
    lines = b64.b64decode(render_base64(nodes, params)).decode("utf-8").splitlines()
    assert len(lines) == 4, lines


def test_rotation_slices_a_different_node_each_round():
    """`rotating` picks one node per country, advancing on each round.

    This is the answer to "Happ has no auto-rotation". Happ cannot group, so it
    cannot re-point a dead node itself — but it *does* refetch the subscription
    (`profile-update-interval`, which this hub already sends). Rotating the
    chosen node per fetch means a client that refreshes every few hours is on a
    different exit each time, and a node that died is simply never chosen again
    once the next probe drops it from the pool.

    The rotation must be a rotation, not a re-sort: with the same input and
    round 0 the output must equal the non-rotating result (so the first import
    is the best node), and successive rounds must advance.
    """
    from hub.renderer import RenderParams, render_base64
    import base64 as b64
    import urllib.parse as up

    nodes = (
        [_node(country="FI", address=f"fi{i}.example.com") for i in range(3)]
        + [_node(country="DE", address=f"de{i}.example.com") for i in range(2)]
    )
    seen_first = []
    for rnd in range(3):
        params = RenderParams(
            fmt=Format.BASE64, client_core="xray", title="hub",
            one_per_country=True, rotation=rnd,
        )
        lines = b64.b64decode(render_base64(nodes, params)).decode("utf-8").splitlines()
        assert len(lines) == 2, lines  # one FI + one DE
        hosts = [up.urlparse(line).hostname for line in lines]
        seen_first.append(tuple(hosts))
    # Three rounds must not all pick the same node.
    assert len(set(seen_first)) > 1, seen_first


def test_rotation_wraps_around_and_keeps_every_node_reachable():
    """Rotation is modulo the group size, so no node is starved or out of range.

    A naive `nodes[rotation]` raises IndexError once the counter passes the
    group size, and a `min(rotation, len-1)` would pin the last node forever.
    Both are tested here because both are one-line mistakes.
    """
    from hub.renderer import RenderParams, render_base64
    import base64 as b64
    import urllib.parse as up

    nodes = [_node(country="FI", address=f"fi{i}.example.com") for i in range(3)]
    picked = set()
    for rnd in range(9):
        params = RenderParams(
            fmt=Format.BASE64, client_core="xray", title="hub",
            one_per_country=True, rotation=rnd,
        )
        lines = b64.b64decode(render_base64(nodes, params)).decode("utf-8").splitlines()
        assert len(lines) == 1, lines
        picked.add(up.urlparse(lines[0]).hostname)
    assert picked == {"fi0.example.com", "fi1.example.com", "fi2.example.com"}, picked


def test_each_xray_entry_has_its_own_balancer_and_observatory():
    """Every array element must be independently self-sufficient.

    The array is a list of *countries*, so each element carries its own
    balancer and its own observatory over its own nodes. An element missing the
    observatory has no health signal, and `leastPing` then degenerates to
    "whichever node is first" — the failover disappears while the config still
    starts, which is the failure mode with no error message.
    """
    import json

    from hub.renderer import RenderParams, render_xray

    nodes = (
        [_node(country="FI", address=f"fi{i}.example.com") for i in range(3)]
        + [_node(country="DE", address=f"de{i}.example.com") for i in range(2)]
    )
    body = json.loads(render_xray(nodes, RenderParams(fmt=Format.SINGBOX, client_core="xray")))
    assert len(body) == 2, body

    for entry in body:
        balancers = entry["routing"]["balancers"]
        assert len(balancers) == 1, balancers
        tag = balancers[0]["tag"]
        assert balancers[0]["strategy"]["type"] == "leastPing", balancers[0]
        assert balancers[0]["selector"] == [f"{tag}-"], balancers[0]

        # The observatory watches exactly the nodes that balancer selects.
        obs = entry["observatory"]
        assert obs["subjectSelector"] == [f"{tag}-"], obs
        assert obs["probeUrl"].startswith("http"), obs
        assert obs["probeInterval"], obs

        # A routing rule must actually send traffic to this balancer, or the
        # group is declared and never used.
        used = {r.get("balancerTag") for r in entry["routing"]["rules"]}
        assert tag in used, entry["routing"]["rules"]

        # Every node in this entry belongs to this country.
        node_tags = [
            o["tag"] for o in entry["outbounds"]
            if o["tag"] not in ("direct", "block")
        ]
        assert node_tags, entry["outbounds"]
        for t in node_tags:
            assert t.startswith(tag + "-"), (tag, t)
        assert set(obs["subjectSelector"]) == {f"{tag}-"}


def test_every_xray_array_element_passes_the_real_core_check():
    """Each element is validated by the actual Xray binary, one at a time.

    The array is Happ's *envelope*, not an Xray construct: the core itself
    refuses it outright — `json: cannot unmarshal array into Go value of type
    conf.Config` — because Happ unwraps the array and hands each element to the
    core separately. So the check is per element, which is also the check that
    matters: one malformed country in the array is one country that cannot
    connect, and the failure would surface on the user's device with no clue
    from the hub.

    Skipped when no Xray binary is available, which is the normal case on a
    host that has never needed one.
    """
    import json
    import os
    import shutil
    import subprocess

    from hub.renderer import RenderParams, render_xray

    binary = os.environ.get("XRAY_BIN") or shutil.which("xray")
    if not binary:
        import pytest

        pytest.skip("no xray binary; set XRAY_BIN to run this")

    nodes = (
        [_node(country="FI", address=f"fi{i}.example.com") for i in range(2)]
        + [_node(country="DE", address="de.example.com")]
    )
    body = json.loads(render_xray(nodes, RenderParams(fmt=Format.SINGBOX, client_core="xray")))
    assert body, "the array must not be empty"

    for entry in body:
        remarks = entry.pop("remarks", "?")
        entry.pop("meta", None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(entry, fh)
            path = fh.name
        try:
            result = subprocess.run(
                [binary, "run", "-test", "-c", path],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            os.unlink(path)
        assert result.returncode == 0, f"{remarks}: {result.stdout}{result.stderr}"


def test_every_country_the_pool_can_measure_has_a_flag_and_a_name():
    """A measured country must render as a flag and a word, not as a bare code.

    `BY` appeared in a client's list as "🌐 BY 1": a flag-less, nameless entry,
    because the country had never been in the pool before and neither table
    covered it. The node was fine; the label was unreadable, and no test caught
    it because the tables are only consulted for codes that happen to appear.

    Pinned against the codes this pool has actually measured, so the next new
    country fails a test instead of shipping a blank.
    """
    from hub.countries import country_name
    from hub.renderer import _country_flag

    # Every code seen in a published generation so far, plus the ones the
    # sources are known to carry.
    seen = [
        "AE", "AM", "BR", "BY", "CA", "DE", "EE", "FI", "FR", "GB", "HK", "HU",
        "ID", "IN", "IT", "JP", "KR", "KZ", "LT", "LV", "MD", "NL", "PL", "RO",
        "RS", "SE", "SG", "TH", "TR", "TW", "US", "VN", "ZA", "CH", "ES", "AT",
    ]
    missing_flags = [c for c in seen if _country_flag(c) == "🌐"]
    missing_names = [c for c in seen if country_name(c) == c]
    assert not missing_flags, f"no flag for: {missing_flags}"
    assert not missing_names, f"no name for: {missing_names}"


def test_legacy_shadowsocks_ciphers_are_dropped_for_xray():
    """A cipher Xray 26 removed must not reach the payload.

    Xray 26.x supports only the AEAD ciphers; `aes-128-cfb` and friends were
    removed, and a single node using one makes the core refuse the **whole
    config**. That is how a 150-node payload became a 4-node one: seven country
    groups contained one legacy-cipher node each and were discarded entire.

    The drop is per node, so the rest of that country survives.
    """
    from hub.models import Protocol
    from hub.renderer import RenderParams, render_xray
    import json

    nodes = [
        _node(protocol=Protocol.SHADOWSOCKS, method="aes-128-gcm",
              password="pw", security=Security.NONE, tls=TLS(), country="NL"),
        _node(protocol=Protocol.SHADOWSOCKS, method="aes-128-cfb",
              password="shadowsocks", security=Security.NONE, tls=TLS(), country="NL"),
        _node(protocol=Protocol.SHADOWSOCKS, method="rc4-md5",
              password="x", security=Security.NONE, tls=TLS(), country="NL"),
    ]
    # Each node must report honestly whether xray can speak it.
    assert nodes[0].supports_core("xray") is True
    assert nodes[1].supports_core("xray") is False
    assert nodes[2].supports_core("xray") is False

    body = json.loads(render_xray(nodes, RenderParams(fmt=Format.SINGBOX, client_core="xray")))
    assert len(body) == 1, body
    tags = [o["tag"] for o in body[0]["outbounds"] if o["tag"] not in ("direct", "block")]
    assert tags == ["NL-1"], tags


def test_plaintext_vless_to_a_public_ip_is_dropped_for_xray():
    """Xray refuses it, so it must never be rendered.

    The core's own rule, from its error: "vless without TLS or other encryption
    is prohibited unless the server address is a private IP or domain". A node
    that violates it does not fail alone — the core refuses the **whole
    config**, so one such node takes down its entire country group in the
    client, which is what a real Happ import hit (`NL-3`).

    A *domain* is the case that must survive: the rule exempts it, so a
    hostname with no TLS is legitimate and dropping it would lose working
    nodes.
    """
    from hub.models import Security
    from hub.renderer import RenderParams, render_xray
    import json

    nodes = [
        # Public IP, no TLS: Xray rejects this outright.
        _node(address="138.124.90.177", security=Security.NONE, tls=TLS(), country="NL"),
        # A domain, no TLS: explicitly allowed by the same rule.
        _node(address="example.com", security=Security.NONE, tls=TLS(), country="NL"),
        # Public IP with REALITY: the normal case, and fine.
        _node(address="1.2.3.4", country="NL"),
    ]
    assert nodes[0].supports_core("xray") is False, "plaintext vless to a public IP"
    assert nodes[1].supports_core("xray") is True, "a domain is exempt"
    assert nodes[2].supports_core("xray") is True

    # Asserted by *address*, not by tag: tags are positional, so the surviving
    # domain node takes `NL-1` and a tag-based check would pass while the
    # rejected node shipped.
    body = json.loads(render_xray(nodes, RenderParams(fmt=Format.SINGBOX, client_core="xray")))
    addresses = [
        o["settings"]["vnext"][0]["address"]
        for e in body
        for o in e["outbounds"]
        if o["tag"] not in ("direct", "block")
    ]
    assert "138.124.90.177" not in addresses, addresses
    assert "example.com" in addresses, addresses


def test_plaintext_is_still_fine_for_cores_that_accept_it():
    """The restriction is Xray's, and must not spread to the other dialects.

    sing-box and mihomo accept a plaintext endpoint, so dropping these nodes for
    them would discard working configs — the same over-correction in the other
    direction.
    """
    node = _node(address="138.124.90.177", security=Security.NONE, tls=TLS())
    assert node.supports_core("sing-box") is True
    assert node.supports_core("mihomo") is True
