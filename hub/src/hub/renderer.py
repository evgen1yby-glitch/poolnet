"""Payload generation. Pure functions; the only I/O is the optional
`sing-box check` hook, injected as a callable.

Three renderers, three dialects, one model:

* `render_base64` — newline-joined share links, base64-wrapped. Consumers:
  v2rayNG, v2rayN, Shadowrocket, NekoBox.
* `render_singbox` — full sing-box JSON config with `route`/`dns`/`urltest`.
* `render_clash` — mihomo YAML with `proxy-groups` and a `url-test` group.

Every emitted URI is produced by the emitter in this module, never copied from
the source, because:

* sing-box FATALs on duplicate outbound tags, and mihomo rejects duplicate
  `proxies[].name` — so **tags are minted server-side**, globally unique per
  payload;
* v2rayNG freezes on imports above ~1000 lines (#2165) — so payloads are
  **chunked to <=200 nodes**;
* upstream sing-box does not implement XHTTP (SagerNet/sing-box#3550) — so the
  renderer takes a `client_core` and drops nodes the core cannot speak;
* `interval` is a Go duration in sing-box (`"10m"`) but an integer number of
  seconds in mihomo (`300`) — the two renderers emit different types;
* Karing caches a static tag snapshot inside urltest groups (#2008) — so
  **ordering is decided server-side** and never left to the client.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence
from .countries import country_name
from .models import Format, MAX_NODES_PER_PAYLOAD, Node, Protocol, Transport

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

#: 10 minutes, not the sing-box default of 3m. With 50 nodes and
#: `idle_timeout: 30m`, a 3-minute interval means ~17 full cycles per hour per
#: node, which is exactly what makes clients sluggish on large lists.
URLTEST_INTERVAL = "10m"
URLTEST_INTERVAL_SECONDS = 600

#: 150 ms, not the default 50 ms. At 50 ms, micro-jitter flips the outbound and
#: breaks long-lived connections (re-login loops, video-call drops).
URLTEST_TOLERANCE = 150

URLTEST_IDLE_TIMEOUT = "30m"

#: Deliberately not interrupting: a switch mid-connection is more damaging than
#: a slightly stale choice.
URLTEST_INTERRUPT = False

URLTEST_URL = "http://www.gstatic.com/generate_204"

#: 198.18.0.2 is the benchmark-reserved range and is not routable. Using it
#: means a misconfigured resolver fails fast instead of leaking.
DNS_ADDRESS = "198.18.0.2"


@dataclass(frozen=True)
class RenderParams:
    """Everything the renderer needs that is not the node list itself."""

    fmt: Format
    client_core: str  # "xray" | "sing-box" | "mihomo"
    title: str = "hub"
    update_interval_hours: int = 6
    cache_id: str = ""  # hash of the node set; must change when nodes change
    max_nodes: int = MAX_NODES_PER_PAYLOAD
    zero_tier: bool = False  # reserved: never emit more than one tier's worth
    #: When set, this payload is one country's shard: only nodes whose exit
    #: country matches are emitted, and the groups are named after the country
    #: rather than "auto". An empty string means the unfiltered payload.
    #:
    #: A separate shard per country is what gives a client "Netherlands" as a
    #: single destination with all of its nodes underneath, instead of one flat
    #: list where the country is only a naming convention. It is *not* nested
    #: groups: a `selector` whose members are `urltest` groups is what sing-box
    #: issue #1807 crashes on, so the grouping is flattened by construction.
    country: str = ""
    #: Keep only the best node per country, dropping the rest.
    #:
    #: For clients that cannot group. Happ's own documentation describes a
    #: subscription body as a URI list or a JSON array and never mentions proxy
    #: groups, load balancing or automatic selection — so the `urltest` grouping
    #: this renderer emits for sing-box and mihomo is invisible there, and a
    #: flat list shows every node: four "🇫🇮 Финляндия" entries in a row.
    #:
    #: With one node per country the list *is* a country picker. The node kept
    #: is the best-scoring one, because the input arrives sorted by score.
    #: What is lost is client-side failover — a property of the client, not
    #: something this endpoint can add, so it is opt-in per request rather than
    #: the default.
    one_per_country: bool = False
    #: Which node to pick from each country when `one_per_country` is set.
    #:
    #: A plain counter, advanced by the caller on every fetch, so the *same*
    #: request URL returns a different exit over time. That is how rotation is
    #: delivered to a client that cannot group: Happ has no proxy groups and
    #: cannot re-point a dead node, but it does refetch the subscription on
    #: `profile-update-interval` — so a rotating payload means a client that
    #: refreshes periodically lands on a different node each time, and a node
    #: that died is simply not chosen again once the next probe drops it.
    #:
    #: 0 picks the best node, so the very first import is the strongest one.
    rotation: int = 0


# ---------------------------------------------------------------------------
# Tag minting
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Share-URI emitter
# ---------------------------------------------------------------------------


#: Country code -> flag emoji. Only where a *measured* country exists: the
#: base64 dialect has no grouping, so the remark is the only place a country
#: can appear at all, and inventing one from a hostname would put the wrong
#: flag on a node.
_FLAG = {
    "NL": "🇳🇱", "DE": "🇩🇪", "FI": "🇫🇮", "US": "🇺🇸", "GB": "🇬🇧", "UK": "🇬🇧",
    "FR": "🇫🇷", "SE": "🇸🇪", "PL": "🇵🇱", "CZ": "🇨🇿", "AT": "🇦🇹", "CH": "🇨🇭",
    "LT": "🇱🇹", "LV": "🇱🇻", "EE": "🇪🇪", "MD": "🇲🇩", "RO": "🇷🇴", "BG": "🇧🇬",
    "IT": "🇮🇹", "ES": "🇪🇸", "PT": "🇵🇹", "IE": "🇮🇪", "DK": "🇩🇰", "NO": "🇳🇴",
    "BE": "🇧🇪", "CA": "🇨🇦", "TR": "🇹🇷", "KZ": "🇰🇿", "GE": "🇬🇪", "AM": "🇦🇲",
    "RS": "🇷🇸", "SK": "🇸🇰", "SI": "🇸🇮", "HR": "🇭🇷", "HU": "🇭🇺", "GR": "🇬🇷",
    "UA": "🇺🇦", "JP": "🇯🇵", "SG": "🇸🇬", "HK": "🇭🇰", "KR": "🇰🇷", "AU": "🇦🇺",
    "IN": "🇮🇳", "BR": "🇧🇷", "AR": "🇦🇷", "MX": "🇲🇽", "ZA": "🇿🇦", "AE": "🇦🇪",
    "IL": "🇮🇱", "IS": "🇮🇸", "LU": "🇱🇺", "MT": "🇲🇹", "CY": "🇨🇾", "AL": "🇦🇱",
    "TH": "🇹🇭", "TW": "🇹🇼", "ID": "🇮🇩", "BY": "🇧🇾",
    "BA": "🇧🇦", "MK": "🇲🇰", "ME": "🇲🇪", "AZ": "🇦🇿", "UZ": "🇺🇿", "VN": "🇻🇳", "MY": "🇲🇾", "PH": "🇵🇭", "NZ": "🇳🇿",
}


def _country_flag(country: str) -> str:
    return _FLAG.get((country or "").upper(), "🌐")


def node_label(node: Node, *, index: int = 0, used: dict[str, int] | None = None) -> str:
    """The name a user sees for a node: `🇳🇱 Нидерланды 2`.

    Not `node.remark`. The remark is whatever the upstream share URI carried in
    its fragment, which for this pool is the *source's* own label: every node
    scraped from `Epodonios/vless` arrives called "EPODONIOS", so the list read
    as 25 identical entries, and the VMess lines (whose format has no fragment)
    arrived with no name at all. That is a list nobody can choose from.

    The country is the only thing about a node a user can act on — it is what
    "test the VPN by country" means — so it leads, with the flag for scanning
    and a number only when the same country appears more than once, which is
    the case that needs disambiguating.

    `used` accumulates per-country counts across one payload, so the numbering
    is per payload and stable for a given node list.
    """
    country = (node.country or "").upper()
    flag = _country_flag(country)
    name = country_name(country) if country else "Unknown"
    if used is None:
        return f"{flag} {name}".strip()
    used[country] = used.get(country, 0) + 1
    count = used[country]
    # Numbered from the second occurrence only, and this is the base64 dialect's
    # rule alone. There are no groups here — the list is flat — so a lone
    # "🇧🇷 Бразилия 1" would imply siblings that do not exist. sing-box and
    # mihomo do not use this branch for tags: `mint_tag` counts separately and
    # numbers from 1 there, because a node tag must differ from its country's
    # group tag to avoid a duplicate, which is a FATAL in sing-box.
    return f"{flag} {name}" if count == 1 else f"{flag} {name} {count}"


def mint_tag(index: int, node: Node, *, used: set[str] | None = None) -> str:
    """The outbound tag: the node's name, always with a numeric suffix.

    The suffix is what keeps a node's tag disjoint from its country's *group*
    tag. A group is named `🇫🇮 Финляндия` and is the entry the user picks; a
    node is `🇫🇮 Финляндия 1`, `…2`, `…3`. Without the suffix the first node of
    a country would carry exactly the group's tag, and a duplicate tag is a
    `FATAL` in sing-box and an illegal config in mihomo — the payload would not
    start at all.

    Numbering from 1 rather than only on repeat also makes the count visible:
    a user reading `🇫🇮 Финляндия 3` in a diagnostics view can tell it is the
    third node of that country rather than a node of an unnamed one.

    The `used` set is still consulted, because two nodes can share a country
    *and* an ordinal only if the set was seeded externally — and correctness
    has to win over cosmetics in that case too.
    """
    # `node_label` without a counter gives the bare country name, which is also
    # the *group* tag. The ordinal is what separates the two namespaces, so it
    # is counted from `used` rather than from a label-local counter: the set is
    # the payload's whole tag namespace and is already threaded through every
    # call site. `used=None` means the caller wants the bare label (a group
    # name), not a node tag.
    base = node_label(node)
    if used is None:
        return base

    suffix = 1
    tag = f"{base} {suffix}"
    while tag in used:
        suffix += 1
        tag = f"{base} {suffix}"
    used.add(tag)
    return tag


def _uri(node: Node, label: str) -> str:
    """Emit a share URI for a node. We generate it; we never echo the source."""
    proto = node.protocol.value
    fragment = _encode_remark(label)

    if proto == Protocol.VLESS.value:
        query = {
            "encryption": "none",
            "security": node.security.value,
            "type": node.transport.value,
            "flow": node.flow,
        }
        _apply_tls(query, node)
        _apply_transport(query, node)
        return f"vless://{node.uuid}@{_authority(node)}?{_query(query)}#{fragment}"

    if proto == Protocol.TROJAN.value:
        query = {
            "security": node.security.value,
            "type": node.transport.value,
        }
        _apply_tls(query, node)
        _apply_transport(query, node)
        return f"trojan://{_uri_escape(node.password)}@{_authority(node)}?{_query(query)}#{fragment}"

    if proto == Protocol.SHADOWSOCKS.value:
        userinfo = base64.urlsafe_b64encode(
            f"{node.method}:{node.password}".encode()
        ).decode().rstrip("=")
        return f"ss://{userinfo}@{_authority(node)}#{fragment}"

    if proto == Protocol.HYSTERIA2.value:
        query = {"obfs": node.obfs} if node.obfs else {}
        if node.tls.sni:
            query["sni"] = node.tls.sni
        if node.tls.allow_insecure:
            query["insecure"] = "1"
        return f"hysteria2://{_uri_escape(node.password)}@{_authority(node)}?{_query(query)}#{fragment}"

    if proto == Protocol.TUIC.value:
        query = {
            "congestion_control": node.congestion or "bbr",
            "sni": node.tls.sni or node.address,
            "alpn": ",".join(node.tls.alpn) or "h3",
        }
        return f"tuic://{node.uuid}:{_uri_escape(node.password)}@{_authority(node)}?{_query(query)}#{fragment}"

    if proto == Protocol.VMESS.value:
        payload = {
            "v": "2",
            # `ps` is the VMess name field — the one a client shows. It used to
            # carry `node.remark`, which arrived empty for VMess because the
            # format has no fragment to hold a label, so every VMess line in the
            # list was nameless. It carries the same country label as the other
            # dialects now.
            "ps": label,
            "add": node.address,
            "port": str(node.port),
            "id": node.uuid,
            "aid": "0",
            "scy": node.method or "auto",
            "net": node.transport.value,
            "type": node.transport_settings.header_type,
            "host": node.transport_settings.host or node.tls.sni,
            "path": node.transport_settings.path or "/",
            "tls": node.security.value,
            "sni": node.tls.sni,
            "alpn": ",".join(node.tls.alpn),
        }
        blob = base64.urlsafe_b64encode(
            _json_dumps(payload).encode()
        ).decode().rstrip("=")
        return f"vmess://{blob}"

    # socks/http: emit as-is. These are intentionally browser-friendly, so the
    # password is percent-escaped rather than left raw in the URI.
    userinfo = ""
    if node.username:
        userinfo = _uri_escape(node.username)
        if node.password:
            userinfo += ":" + _uri_escape(node.password)
        userinfo += "@"
    scheme = "https" if node.security is not None and node.security.value == "tls" else proto
    return f"{scheme}://{userinfo}{_authority(node)}#{fragment}"


def _authority(node: Node) -> str:
    if ":" in node.address and not node.address.startswith("["):
        return f"[{node.address}]:{node.port}"
    return f"{node.address}:{node.port}"


def _encode_remark(remark: str) -> str:
    """Remarks go into a URI fragment, so they must be percent-encoded."""
    out = []
    for ch in remark:
        if ch.isalnum() or ch in "-._~":
            out.append(ch)
        else:
            out.extend("%%%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)


def _uri_escape(value: str) -> str:
    return _encode_remark(value)


def _query(params: dict) -> str:
    """Serialise a query, dropping empties and preserving insertion order."""
    parts = []
    for key, value in params.items():
        if value == "" or value is None:
            continue
        if isinstance(value, bool):
            parts.append(f"{key}={'1' if value else '0'}")
        else:
            parts.append(f"{key}={_uri_escape(str(value))}")
    return "&".join(parts)


def _apply_tls(query: dict, node: Node) -> None:
    if node.security.value != "none":
        if node.tls.sni:
            query["sni"] = node.tls.sni
        if node.tls.fingerprint:
            query["fp"] = node.tls.fingerprint
        if node.tls.alpn:
            query["alpn"] = ",".join(node.tls.alpn)
        if node.tls.allow_insecure:
            # Emitted for fidelity; clients may reject it (Xray 26.x removed it).
            query["allowInsecure"] = "1"
        if node.security.value == "reality":
            if node.tls.public_key:
                query["pbk"] = node.tls.public_key
            if node.tls.short_id:
                query["sid"] = node.tls.short_id
            if node.tls.spider_x:
                query["spx"] = node.tls.spider_x


def _apply_transport(query: dict, node: Node) -> None:
    ts = node.transport_settings
    if ts.host:
        query["host"] = ts.host
    if ts.path:
        query["path"] = ts.path
    if ts.kind is Transport.GRPC and ts.service_name:
        query["serviceName"] = ts.service_name


def _json_dumps(payload: dict) -> str:
    """Deterministic JSON: sorted keys, no spaces (matches vmess convention)."""
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# base64 renderer
# ---------------------------------------------------------------------------


def render_base64(nodes: Sequence[Node], params: RenderParams) -> str:
    """Newline-joined share links, base64-wrapped.

    No headers of any kind — v2rayNG displays none, so a header here would be
    silently ignored. The only thing this format guarantees is that every line
    is a valid, self-describing URI.

    There is no grouping mechanism in this dialect, which is why it is the one
    format that cannot offer country selection: v2rayNG and friends show a flat
    list ordered by the remark. So the closest honest equivalent is to *sort* by
    country, so a pool reads as blocks — all Dutch nodes together, then German —
    and the remark carries the flag emoji that makes the block identifiable.
    """
    kept = _filtered(nodes, params)
    if params.country:
        kept = [n for n in kept if n.country.upper() == params.country.upper()]
    if params.one_per_country:
        # Group by country, then take one node per country. The input arrives
        # ordered by score, so index 0 is the best node and the ordering inside
        # each group is "best first" — which is what makes `rotation=0` the
        # strongest pick and each later round the next-best.
        groups: dict[str, list[Node]] = {}
        for node in kept:
            # A node with no measured country is its own entry, keyed by its
            # dedup key: "" is not a country, and collapsing all of them into
            # one bucket would hide nodes rather than de-duplicate a country.
            key = (node.country or "").upper() or f"\0{node.dedup_key}"
            groups.setdefault(key, []).append(node)
        picked: list[Node] = []
        for key, group in groups.items():
            # Modulo, not a clamp or a bare index: `rotation` grows without
            # bound as fetches accumulate, a bare index raises IndexError past
            # the group size, and a clamp would pin the last node forever —
            # both are one-line mistakes and both are tested.
            picked.append(group[params.rotation % len(group)])
        kept = picked
    ordered = sorted(
        kept[: params.max_nodes],
        key=lambda n: ((n.country or "ZZ").upper(), _encode_remark(n.remark)),
    )
    # Labels are minted in emit order, so the per-country counters increment
    # down the list a user actually reads. They are not derived from the sort
    # key, which would number nodes by an order the client does not show.
    used: dict[str, int] = {}
    return base64.b64encode(
        "\n".join(_uri(n, node_label(n, used=used)) for n in ordered).encode("utf-8")
    ).decode("ascii")


# ---------------------------------------------------------------------------
# sing-box renderer
# ---------------------------------------------------------------------------


def render_singbox(nodes: Sequence[Node], params: RenderParams) -> str:
    """A complete sing-box 1.12/1.14-compatible config.

    Structure (order matters — see research §15): log -> dns -> inbounds ->
    outbounds -> route. The `urltest` outbound comes **after** the nodes so that
    a FATAL on a bad tag surfaces before the group references it.
    """
    import json

    kept = _filtered(nodes, params)
    if params.country:
        kept = [n for n in kept if n.country.upper() == params.country.upper()]
    limited = kept[: params.max_nodes]

    outbounds: list[dict] = []
    used_tags: set[str] = set()
    tags: list[str] = []
    for index, node in enumerate(limited, start=1):
        outbound = _singbox_outbound(node, index, used_tags)
        outbounds.append(outbound)
        tags.append(outbound["tag"])

    # Group by *measured* exit country. Nodes with no measurement are grouped
    # under "auto"; a country shard has exactly one group by construction, and
    # the unfiltered payload groups by country when every node has one.
    #
    # The tags are passed in rather than re-derived: `_singbox_outbound` is what
    # de-collides them against `used_tags`, and minting a second time here would
    # produce a different tag for the same node — a FATAL in sing-box, where a
    # group referencing an unknown outbound refuses to start.
    # One `urltest` per country: this is the whole point of the payload, so a
    # single-country pool still gets one rather than degenerating into a bare
    # selector. A selector alone would leave the user with a list of individual
    # nodes and no automatic failover — exactly the "one died, it never switched"
    # failure the grouping exists to prevent.
    groups = _country_groups(list(zip(limited, tags)))
    group_tags: list[str] = []
    for label, label_tags in groups.items():
        name = _group_tag(label)
        outbounds.append({
            "type": "urltest",
            "tag": name,
            "outbounds": label_tags,
            "url": URLTEST_URL,
            "interval": URLTEST_INTERVAL,
            "tolerance": URLTEST_TOLERANCE,
            "idle_timeout": URLTEST_IDLE_TIMEOUT,
            "interrupt_exist_connections": URLTEST_INTERRUPT,
        })
        group_tags.append(name)

    # An empty pool still needs a working proxy shape rather than a dangling
    # selector, or the client rejects the whole config. A group with no members
    # is a FATAL in sing-box, so this only fires when there is something to put
    # in it — an empty payload emits the selector over no outbounds instead.
    if tags and not group_tags:
        outbounds.append({
            "type": "urltest",
            "tag": "auto",
            "outbounds": tags,
            "url": URLTEST_URL,
            "interval": URLTEST_INTERVAL,
            "tolerance": URLTEST_TOLERANCE,
            "idle_timeout": URLTEST_IDLE_TIMEOUT,
            "interrupt_exist_connections": URLTEST_INTERRUPT,
        })
        group_tags = ["auto"]

    # A flat selector over the group tags — the country picker.
    #
    # Deliberately *not* nested: a selector whose members are urltest groups is
    # the shape sing-box #1807 crashes on, and this payload is rendered for
    # exactly the clients that would hit it. "Flat" here describes the nesting
    # depth, not the membership: the members are the `g-{CC}` groups.
    #
    # The individual node tags were previously appended here as well
    # (`group_tags + tags`), which put every node in the picker next to the
    # country that already rotates between them. A client then showed
    # "🇫🇮 Финляндия" and "🇫🇮 Финляндия 2", "3", "4" as siblings, and picking a
    # node chose that one node with no failover — the failure the whole grouping
    # exists to prevent. The nodes are not removed from the payload: each is
    # still an outbound and still a member of its country's urltest group, so
    # failover within a country works exactly as designed.
    #
    # `direct` stays a separate outbound (the route rules send DNS and private
    # traffic to it) and is listed here so the user can pick it from the UI too.
    outbounds.append({"type": "selector", "tag": "proxy",
                      "outbounds": group_tags + ["direct"]})
    outbounds.append({"type": "direct", "tag": "direct"})

    config = {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"type": "local", "tag": "local"},
                {"type": "udp", "server": DNS_ADDRESS, "tag": "dns-remote"},
                {"type": "tls", "server": DNS_ADDRESS, "tag": "dns-remote-doh"},
            ],
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            }
        ],
        "outbounds": outbounds,
        "route": {
            "rules": [
                {"action": "sniff"},
                {"action": "hijack-dns", "inbound": "mixed-in"},
                {"action": "route", "outbound": "direct", "port": 53},
                {"ip_is_private": True, "action": "route", "outbound": "direct"},
                {"action": "route", "outbound": "dns-remote", "rule_set": ["geosite-ru"]},
                {"action": "resolve"},
                {"action": "route", "outbound": "proxy"},
            ],
            "rule_set": [
                {
                    "tag": "geosite-ru",
                    "type": "remote",
                    "format": "binary",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-ru.srs",
                    "download_detour": "direct",
                }
            ],
            "final": "proxy",
        },
    }

    if params.cache_id:
        config["experimental"] = {
            "cache_file": {"enabled": True, "cache_id": params.cache_id}
        }

    return json.dumps(config, indent=2, ensure_ascii=False)


def _country_groups(pairs: Sequence[tuple[Node, str]]) -> dict[str, list[str]]:
    """Group `(node, its already-minted tag)` by measured exit country.

    The key is the tag the caller minted, not a fresh one, because that is what
    an outbound group lists. Order is by descending group size then
    alphabetically, so the most useful country comes first and the payload is
    byte-stable across runs: `cache_id` hashes the node set for exactly that
    reason, and an unstable order would churn the id on every rotation without
    any node actually changing.

    Nodes with no country are keyed `""`, which becomes the `auto` group.
    """
    buckets: dict[str, list[str]] = {}
    for node, tag in pairs:
        buckets.setdefault((node.country or "").upper(), []).append(tag)
    return dict(
        sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )


def _group_tag(label: str) -> str:
    """A stable, client-visible group name for one country.

    This is the string the user picks from the client's list, so it is the
    country's own name — `🇫🇮 Финляндия` — not `g-fi`. The `g-` form was a
    namespace guard, and the namespace is guarded differently now: a group is
    named after its country and every node carries a numeric suffix, so the two
    can never collide. That matters because a duplicate tag is a FATAL in
    sing-box and an illegal config in mihomo.

    `auto` is passed through unchanged; it is the flat fallback group.
    """
    if not label or label == "auto":
        return "auto"
    country = label.upper()
    flag = _country_flag(country)
    return f"{flag} {country_name(country)}".strip()


def _clash_country_groups(
    nodes: Sequence[Node], names: Sequence[str]
) -> dict[str, list[str]]:
    """Country -> that country's proxy names, in the renderer's stable order.

    Shares `_country_groups`' ordering so a sing-box payload and a mihomo payload
    from the same pool list countries in the same sequence: the user picks
    "Netherlands" in one client and expects to find it in the same place in the
    other.
    """
    pairs = list(zip(nodes, names))
    grouped = _country_groups(pairs)
    return {label: members for label, members in grouped.items()}


def _clash_group_names(nodes: Sequence[Node], names: Sequence[str]) -> list[str]:
    """The group names a `select` lists: the country groups, plus a flat `auto`.

    `auto` is kept because clients and users both expect it in a mihomo config —
    it is the one group that always exists elsewhere, and dropping it in favour
    of country groups alone breaks the muscle memory of every Clash user.
    """
    labels = list(_clash_country_groups(nodes, names))
    return [_group_tag(label) for label in labels] + ["auto"]


def _singbox_outbound(node: Node, index: int, used: set[str]) -> dict:
    """One node as a sing-box outbound. Tag is always minted here."""
    tag = mint_tag(index, node, used=used)
    base: dict = {"tag": tag, "server": node.address, "server_port": node.port}

    tls = None
    if node.security.value != "none":
        tls = {"enabled": True}
        if node.tls.sni:
            tls["server_name"] = node.tls.sni
        if node.tls.fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": node.tls.fingerprint}
        if node.tls.alpn:
            tls["alpn"] = [a for a in node.tls.alpn if a]
        if node.security.value == "reality":
            tls["reality"] = {
                "enabled": True,
                "public_key": node.tls.public_key,
                "short_id": node.tls.short_id,
            }
        # allowInsecure is dropped for Xray 26.x hard-failure parity.

    transport = None
    ts = node.transport_settings
    if ts.kind is not Transport.TCP:
        transport = {"type": ts.kind.value}
        if ts.kind in (Transport.WS, Transport.HTTP2, Transport.HTTPUPGRADE, Transport.XHTTP):
            transport["path"] = ts.path or "/"
            if ts.host:
                transport["headers"] = {"Host": ts.host}
        elif ts.kind is Transport.GRPC:
            transport["service_name"] = ts.service_name or ""

    if node.protocol is Protocol.VLESS:
        base.update({"type": "vless", "uuid": node.uuid})
        if node.flow:
            base["flow"] = node.flow
    elif node.protocol is Protocol.VMESS:
        base.update({"type": "vmess", "uuid": node.uuid, "security": node.method or "auto"})
    elif node.protocol is Protocol.TROJAN:
        base.update({"type": "trojan", "password": node.password})
    elif node.protocol is Protocol.SHADOWSOCKS:
        base.update({"type": "shadowsocks", "method": node.method, "password": node.password})
    elif node.protocol is Protocol.HYSTERIA2:
        base.update({"type": "hysteria2", "password": node.password})
        if node.obfs:
            # `obfs` in a share link is a *type* selectable value ("salamander"
            # / "salamander-udp"); the keying material is a separate `obfs-password`
            # the share link does not always carry. Reusing the type as the password
            # produces a config that starts but cannot negotiate.
            base["obfs"] = {"type": node.obfs}
            if node.obfs_password:
                base["obfs"]["password"] = node.obfs_password
    elif node.protocol is Protocol.TUIC:
        base.update({"type": "tuic", "uuid": node.uuid, "password": node.password})
        if node.congestion:
            base["congestion_control"] = node.congestion
    elif node.protocol is Protocol.WIREGUARD:
        base.update(
            {"type": "wireguard", "private_key": node.password, "peer_public_key": node.flow}
        )
    else:
        raise ValueError(f"cannot render {node.protocol.value} for sing-box")

    if tls:
        base["tls"] = tls
    if transport:
        base["transport"] = transport
    return base


# ---------------------------------------------------------------------------
# Clash (mihomo) renderer
# ---------------------------------------------------------------------------


#: How often a client's Xray core re-probes every node of every country.
#: 30s is the reference value for `observatory`: fast enough that a node dying
#: mid-session is noticed before a TCP connection times out, slow enough that
#: probing every node of every country does not itself become the traffic.
XRAY_PROBE_INTERVAL = "30s"

#: The URL an observatory probes. `generate_204` is the same endpoint the
#: sing-box urltest uses, for the same reason: a 204 with no body measures
#: reachability without pulling bytes, and it is not a domain a hostile node
#: operator can easily intercept.
XRAY_PROBE_URL = URLTEST_URL


def _xray_outbound(node: Node, tag: str) -> dict:
    """One node as an Xray-core outbound. The tag is passed in, never minted."""
    if node.protocol is Protocol.VLESS:
        user = {"id": node.uuid, "encryption": "none"}
        if node.flow:
            user["flow"] = node.flow
        out = {
            "tag": tag,
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": node.address,
                    "port": node.port,
                    "users": [user],
                }]
            },
        }
    elif node.protocol is Protocol.VMESS:
        out = {
            "tag": tag,
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": node.address,
                    "port": node.port,
                    "users": [{
                        "id": node.uuid,
                        "alterId": 0,
                        "security": node.method or "auto",
                    }],
                }]
            },
        }
    elif node.protocol is Protocol.TROJAN:
        out = {
            "tag": tag,
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": node.address,
                    "port": node.port,
                    "password": node.password,
                }]
            },
        }
    elif node.protocol is Protocol.SHADOWSOCKS:
        out = {
            "tag": tag,
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": node.address,
                    "port": node.port,
                    "method": node.method,
                    "password": node.password,
                }]
            },
        }
    else:
        # Hysteria2/TUIC are sing-box/mihomo protocols; Xray does not speak
        # them. `_filtered` drops them for this core, so reaching here is a bug
        # in the caller rather than a node to skip quietly.
        raise ValueError(f"xray cannot render {node.protocol.value}")

    stream = _xray_stream(node)
    if stream:
        out["streamSettings"] = stream
    return out


def _xray_stream(node: Node) -> dict:
    """Xray `streamSettings` for a node, or `{}` for a bare TCP node."""
    stream: dict = {}
    network = node.transport.value
    if network != "tcp":
        stream["network"] = network
    if network == "ws":
        stream["wsSettings"] = {
            "path": node.transport_settings.path or "/",
            "headers": {"Host": node.transport_settings.host or node.tls.sni or node.address},
        }
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": node.transport_settings.path or ""}

    if node.security.value == "tls":
        stream["security"] = "tls"
        sni = node.tls.sni or node.address
        tls: dict = {"serverName": sni}
        if node.tls.alpn:
            tls["alpn"] = [a for a in node.tls.alpn if a]
        if node.tls.fingerprint:
            tls["fingerprint"] = node.tls.fingerprint
        stream["tlsSettings"] = tls
    elif node.security.value == "reality":
        stream["security"] = "reality"
        # No `allowInsecure` anywhere: Xray 26.x made it a hard failure, and a
        # payload that cannot start is worse than one that refuses a bad cert.
        stream["realitySettings"] = {
            "serverName": node.tls.sni or node.address,
            "fingerprint": node.tls.fingerprint or "chrome",
            "publicKey": node.tls.public_key,
            "shortId": node.tls.short_id or "",
        }
    return stream


def _xray_config(outbounds: list[dict], groups: dict[str, list[str]]) -> dict:
    """One complete Xray config: outbounds plus a balancer per country.

    Split out because the subscription body is an *array* of these and each
    entry must carry its own balancer and observatory — an entry without them
    is a node list again, which is the thing the array exists to replace.
    """
    balancers = [
        {"tag": cc, "selector": [f"{cc}-"], "strategy": {"type": "leastPing"}}
        for cc in sorted(groups)
    ]
    config: dict = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "socks", "port": 10808, "listen": "127.0.0.1",
             "protocol": "socks", "settings": {"udp": True}},
            {"tag": "http", "port": 10809, "listen": "127.0.0.1", "protocol": "http"},
        ],
        "outbounds": outbounds,
    }
    if balancers:
        config["observatory"] = {
            "subjectSelector": sorted({f"{cc}-" for cc in groups}),
            "probeUrl": XRAY_PROBE_URL,
            "probeInterval": XRAY_PROBE_INTERVAL,
            "enableConcurrency": True,
        }
        config["routing"] = {
            "domainStrategy": "AsIs",
            "balancers": balancers,
            "rules": [
                {"type": "field", "network": "tcp,udp", "balancerTag": b["tag"]}
                for b in balancers
            ] + [{"type": "field", "network": "tcp,udp", "outboundTag": "direct"}],
        }
    return config


def render_xray(nodes: Sequence[Node], params: RenderParams) -> str:
    """A JSON **array** of Xray configs — one element per country.

    The envelope is a JSON array, not an object, because that is what Happ
    documents for an advanced subscription: "JSON Arrays: Advanced data sets
    including pre-configured keys, routing rules, and Reality parameters". The
    first version of this renderer emitted a single object, built on a different
    doc line ("this JSON configuration is passed exactly as is") that describes
    *importing a config by hand*, not the shape of a subscription body. The
    distinction matters because the wrong envelope is not a smaller feature — it
    is a body the client was never documented to parse.

    One element per country, each a self-contained config with:

      * `remarks` — the name the client shows. Happ's per-server metadata field
        (`meta.serverDescription`) is about a single node, and the element name
        is what makes the array a list of *countries*;
      * its own outbounds, one per node of that country;
      * its own `observatory` and one `leastPing` balancer.

    So each entry fails over on its own: the client's Xray core probes that
    country's nodes, keeps traffic on the lowest-latency living one, and moves
    to the next when one dies — without the hub, which is not in the data path,
    and without the user noticing. Per-country rather than one global balancer,
    because a global one would silently move a user who chose Finland to Brazil.

    The hub does not run Xray, so this is a static string like the other
    dialects; the client's core is the authority on whether it starts.
    """
    kept = _filtered(nodes, params)
    if params.country:
        kept = [n for n in kept if n.country.upper() == params.country.upper()]
    kept = kept[: params.max_nodes]

    # Group first, so a tag's prefix can be derived from the group it belongs to
    # and a selector can never disagree with the outbound list.
    buckets: dict[str, list[Node]] = {}
    for node in kept:
        buckets.setdefault((node.country or "XX").upper(), []).append(node)

    entries: list[dict] = []
    for cc in sorted(buckets):
        outbounds: list[dict] = [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
        tags: list[str] = []
        for index, node in enumerate(buckets[cc], start=1):
            # `{CC}-{n}`: readable in the client's log, unique by construction,
            # and prefix-matchable so the balancer's selector stays a short
            # prefix rather than an enumeration that can drift.
            tag = f"{cc}-{index}"
            outbounds.append(_xray_outbound(node, tag))
            tags.append(tag)
        config = _xray_config(outbounds, {cc: tags})
        # `XX` is what Cloudflare returns when it cannot determine the exit
        # country, and it is kept as its own group rather than guessed at from
        # the hostname — a node called `unitedstates1.example.com` may exit
        # anywhere, and a wrong flag is worse than an honest "unknown". But the
        # literal `XX` in a client's list reads as a broken entry, so the group
        # is named in words.
        label = "Страна не определена" if cc == "XX" else country_name(cc)
        remarks = f"{_country_flag(cc)} {label} {len(tags)}".strip()
        # `remarks` is the element's display name; `meta` is the documented
        # per-entry metadata slot the app reads for the subtitle.
        config["remarks"] = remarks
        config["meta"] = {
            "serverDescription": (
                f"{len(tags)} nodes, exit country not measured"
                if cc == "XX"
                else f"{len(tags)} nodes in {country_name(cc)}"
            )
        }
        entries.append(config)
    return json.dumps(entries, ensure_ascii=False, indent=2)


def render_clash(nodes: Sequence[Node], params: RenderParams) -> str:
    """mihomo YAML with `url-test` groups.

    Integer `interval` in **seconds** — emitting `10m` here is silently ignored,
    and emitting `300` into the sing-box JSON fails validation.

    One `url-test` per country plus a flat `select` over them, so the client
    shows "Netherlands" as a destination and switches to a live member on its
    own. Clash's `select` cannot contain a group as a member, which is why the
    structure is a selector over groups rather than the flat node list it
    started as — the nodes are reachable directly too, for a user who wants to
    pin one.
    """
    kept = _filtered(nodes, params)
    if params.country:
        kept = [n for n in kept if n.country.upper() == params.country.upper()]
    limited = kept[: params.max_nodes]

    seen: set[str] = set()
    proxies: list[str] = []
    names: list[str] = []
    for index, node in enumerate(limited, start=1):
        entry, name = _clash_proxy(node, index, seen)
        proxies.append(entry)
        names.append(name)

    group_interval = URLTEST_INTERVAL_SECONDS  # int, not "10m"
    lines: list[str] = []
    lines.append(f"# {params.title}")
    lines.append("mixed-port: 7890")
    lines.append("allow-lan: false")
    lines.append("mode: rule")
    lines.append("log-level: warning")
    lines.append("ipv6: false")
    lines.append("external-controller: 127.0.0.1:9090")
    lines.append("")
    lines.append("dns:")
    lines.append("  enable: true")
    lines.append(f"  listen: 0.0.0.0:{DNS_PORT}")
    lines.append("  enhanced-mode: fake-ip")
    lines.append("  fake-ip-range: 198.18.0.1/16")
    lines.append("  nameserver:")
    lines.append(f"    - {DNS_ADDRESS}")
    lines.append("")
    lines.append("proxies:")
    lines.extend(f"  - {p}" for p in proxies)
    lines.append("")
    lines.append("proxy-groups:")
    for label, label_names in _clash_country_groups(limited, names).items():
        lines.append(f"  - name: {_group_tag(label)}")
        lines.append("    type: url-test")
        lines.append("    url: " + URLTEST_URL)
        lines.append(f"    interval: {group_interval}")
        lines.append(f"    tolerance: {URLTEST_TOLERANCE}")
        lines.append("    lazy: false")
        lines.append("    proxies:")
        lines.extend(f"      - {n}" for n in label_names)
    # The `auto` group is what a Clash user reaches for by default, so it stays
    # even though the country groups now carry the real choice. It url-tests
    # everything, which makes it the "just give me the fastest one" option.
    if names:
        lines.append("  - name: auto")
        lines.append("    type: url-test")
        lines.append("    url: " + URLTEST_URL)
        lines.append(f"    interval: {group_interval}")
        lines.append(f"    tolerance: {URLTEST_TOLERANCE}")
        lines.append("    lazy: false")
        lines.append("    proxies:")
        lines.extend(f"      - {n}" for n in names)
    # The picker offers countries (`g-{CC}` url-test groups) and the flat
    # `auto`, not the nodes those groups already rotate between. Listing the
    # nodes here too put "🇫🇮 Финляндия" beside "🇫🇮 Финляндия 2/3/4" and made
    # picking a country indistinguishable from picking one of its members,
    # which skips the url-test failover.
    lines.append("  - name: proxy")
    lines.append("    type: select")
    lines.append("    proxies:")
    lines.extend(f"      - {g}" for g in _clash_group_names(limited, names))
    lines.append("      - DIRECT")
    lines.append("      - REJECT")
    lines.append("")
    lines.append("rules:")
    lines.append("  - GEOSITE,category-ads-all,REJECT")
    lines.append("  - GEOSITE,private,DIRECT")
    lines.append("  - GEOIP,private,DIRECT")
    lines.append("  - GEOSITE,geolocation-!cn,proxy")
    lines.append("  - MATCH,proxy")
    lines.append("")
    return "\n".join(lines)


DNS_PORT = 53


def _yaml_scalar(value):
    """Render one scalar for a flow mapping, safely.

    Every free-text field in a proxy entry arrives from an upstream source, so
    it is untrusted. Building the entry by interpolation let a password
    containing `"` and `}` close the mapping and inject sibling keys, and a
    newline inside a value broke the document into a second node — the parser
    accepted the forged structure, so the published payload silently stopped
    meaning what this module wrote.

    `json.dumps` is used rather than a hand-written escaper because JSON
    scalars are a strict subset of YAML flow scalars: the quoting and escaping
    rules are already the ones the parser will read back. A YAML emitter would
    be the alternative, but the entries are emitted as flow mappings by design
    (compact, one line per node) and `json.dumps` produces exactly that.
    """
    return json.dumps(value, ensure_ascii=False)


def _clash_proxy(node: Node, index: int, seen: set[str]) -> tuple[str, str]:
    """YAML proxy entry plus the (de-collided) name it must be referenced by.

    Every value is passed through `_yaml_scalar`; nothing is interpolated raw.
    """
    name = mint_tag(index, node, used=seen)
    q = _yaml_scalar
    fields: list[str] = [f"name: {q(name)}", f"server: {q(node.address)}", f"port: {int(node.port)}"]

    if node.protocol is Protocol.VLESS:
        fields += ["type: vless", f"uuid: {q(node.uuid)}", "udp: true",
                   f"tls: {str(node.security.value != 'none').lower()}"]
        if node.security.value != "none":
            servername = node.tls.sni or node.address
            fields.append(f"servername: {q(servername)}")
            if node.tls.fingerprint:
                fields.append(f"client-fingerprint: {q(node.tls.fingerprint)}")
            if node.flow:
                fields.append(f"flow: {q(node.flow)}")
            if node.security.value == "reality":
                fields.append(
                    "reality-opts: {public-key: %s, short-id: %s}"
                    % (q(node.tls.public_key), q(node.tls.short_id))
                )
            if node.transport is not Transport.TCP:
                fields.append(f"network: {q(node.transport.value)}")
            if node.transport is Transport.WS:
                fields.append(
                    "ws-opts: {path: %s, headers: {Host: %s}}"
                    % (q(node.transport_settings.path or "/"),
                       q(node.transport_settings.host or servername))
                )

    elif node.protocol is Protocol.TROJAN:
        fields += ["type: trojan", f"password: {q(node.password)}", "udp: true", "tls: true",
                   f"servername: {q(node.tls.sni or node.address)}"]

    elif node.protocol is Protocol.SHADOWSOCKS:
        fields += ["type: ss", f"cipher: {q(node.method)}", f"password: {q(node.password)}", "udp: true"]

    elif node.protocol is Protocol.HYSTERIA2:
        fields += ["type: hysteria2", f"password: {q(node.password)}",
                   f"sni: {q(node.tls.sni or node.address)}", "udp: true"]
        if node.obfs:
            fields.append(f"obfs: {q(node.obfs)}")

    elif node.protocol is Protocol.TUIC:
        fields += ["type: tuic", f"uuid: {q(node.uuid)}", f"password: {q(node.password)}",
                   "udp: true", 'alpn: ["h3"]']

    elif node.protocol is Protocol.VMESS:
        fields += ["type: vmess", f"uuid: {q(node.uuid)}", "alterId: 0",
                   f"cipher: {q(node.method or 'auto')}", "udp: true",
                   f"tls: {'true' if node.security.value != 'none' else 'false'}"]
        if node.transport is not Transport.TCP:
            fields.append(f"network: {q(node.transport.value)}")
        if node.transport in (Transport.WS, Transport.HTTPUPGRADE):
            fields.append(
                "ws-opts: {path: %s, headers: {Host: %s}}"
                % (q(node.transport_settings.path or "/"),
                   q(node.transport_settings.host or node.tls.sni or node.address))
            )

    else:
        raise ValueError(f"cannot render {node.protocol.value} for clash")

    return "{" + ", ".join(fields) + "}", name


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def _filtered(nodes: Iterable[Node], params: RenderParams) -> list[Node]:
    """Drop nodes the target core cannot speak, preserving order.

    An XHTTP node dropped for `client_core=sing-box` is a *correct* drop, not a
    data loss: upstream sing-box would reject the whole config anyway.
    """
    kept = [n for n in nodes if n.supports_core(params.client_core)]
    if params.max_nodes and len(kept) > params.max_nodes:
        return kept[: params.max_nodes]
    return kept


def render(
    nodes: Sequence[Node],
    params: RenderParams,
    *,
    validate: Callable[[str, Format], bool] | None = None,
) -> tuple[bytes | None, list[Node]]:
    """Render one payload. Returns (payload, included_nodes).

    `None` is returned when the rendered config fails validation — the caller
    discards the payload and keeps the previous generation (**fail-open**, never
    fail-closed). A single bad node is not reason enough to abort the run, so
    validation failures here are reported for the whole payload and the caller
    decides; `render_validated` below automates that decision.
    """
    if params.fmt is Format.BASE64:
        body = render_base64(nodes, params)
        payload = body.encode("ascii")
    elif params.fmt is Format.SINGBOX:
        # `client_core` selects the *schema*, not just which nodes survive.
        # Xray and sing-box both take JSON but they are different dialects with
        # different field names, and dispatching on `fmt` alone sent every
        # `client_core="xray"` payload through `render_singbox` — so
        # `render_xray` was unreachable from `render_validated` and the Xray
        # payload was never published, silently, because a payload that is
        # rendered by the wrong function validates fine as the wrong dialect.
        if params.client_core == "xray":
            payload = render_xray(nodes, params).encode("utf-8")
        else:
            payload = render_singbox(nodes, params).encode("utf-8")
    elif params.fmt is Format.CLASH:
        payload = render_clash(nodes, params).encode("utf-8")
    else:  # pragma: no cover - exhaustive
        raise ValueError(params.fmt)

    if validate is not None and not validate(payload.decode("utf-8", "replace"), params.fmt):
        return None, []

    included = _filtered(nodes, params)[: params.max_nodes]
    return payload, included


def render_validated(
    nodes: Sequence[Node],
    params: RenderParams,
    *,
    validate: Callable[[str, Format], bool] | None = None,
) -> tuple[bytes, list[Node]]:
    """Render, and if the payload fails validation, drop the offending nodes.

    Binary-searches the smallest suffix removal that makes the payload valid,
    which is safe because nodes are ordered by score: dropping the tail drops
    the weakest nodes, never the strongest.
    """
    if validate is None:
        payload, included = render(nodes, params)
        assert payload is not None
        return payload, included

    working = list(nodes)
    while working:
        payload, included = render(working, params, validate=validate)
        if payload is not None:
            return payload, included
        if len(working) <= 1:
            break
        # Remove the last 10% and retry, then keep halving: cheap and monotone.
        cut = max(1, len(working) // 10)
        working = working[: len(working) - cut]
    raise ValueError("no valid payload could be produced from the given nodes")


# ---------------------------------------------------------------------------
# Per-country shards
# ---------------------------------------------------------------------------

#: Countries whose shards are worth a file each. Capped because the shard
#: matrix is tiers x countries x cores x formats, and a long tail of one- and
#: two-node countries would spend most of the publish budget on payloads nobody
#: ever requests. A country below this either rides inside the full payload or
#: gets its own file once it earns one.
#:
#: Not a correctness limit: `render(..., country=cc)` works for any country at
#: any time, so raising this is a policy change, not a code change.
MAX_COUNTRY_SHARDS = 32

#: Every measured country gets a shard, including a one-node country.
#:
#: The previous value was 2, on the reasoning that "one node in its own file is
#: a redirect with extra steps". That reasoning optimises for file count and
#: ignores what the endpoint is for: a user is given a country link to test
#: *that country*, and a 404 because the country happens to be small is not a
#: saving, it is the feature being unavailable. The pool is small and its
#: country mix is long-tailed, so most countries have one or two nodes.
#:
#: A 404 body already names the countries that do exist, so the failure mode is
#: legible rather than silent — which is why raising this again would be a
#: deliberate product decision, not a tuning knob.
MIN_COUNTRY_SHARD_NODES = 1


@dataclass(frozen=True)
class CountryShard:
    """One country's payload, in one format."""

    cc: str
    fmt: Format
    payload: bytes
    included: int


def _shard_formats(core: str) -> tuple[Format, ...]:
    """The formats one core can actually carry.

    Same pair of exclusions `pipeline._publish` applies, repeated here rather
    than passed in: a shard written in a dialect its core cannot read is a 200
    with an unparseable body, which is worse than a 404 because the client
    appears to succeed.
    """
    if core == "xray":
        return (Format.BASE64,)
    if core == "mihomo":
        return (Format.CLASH,)
    return (Format.BASE64, Format.SINGBOX)


def country_shards(
    nodes: Sequence[Node],
    *,
    tier: str = "verified",
    core: str = "sing-box",
    limit: int = MAX_COUNTRY_SHARDS,
    minimum: int = MIN_COUNTRY_SHARD_NODES,
    validate: Callable[[str, Format], bool] | None = None,
) -> list[CountryShard]:
    """Render one payload per country, for the biggest countries first.

    This is what makes `/sub/{token}/country/{cc}` possible: the API serves
    bytes from a generation directory and holds no `Node` objects, so a country
    that is not on disk before the request arrives cannot be rendered during
    it. Writing the shards at publish time is the only way the endpoint can
    stay as cheap as the whole-tier one.

    Ordering is by node count descending, then by country code, and it is
    deterministic because the tie-break is: an unstable order would make the
    same pool hash to a different generation id on different runs, which
    silently defeats the content-addressed rollback.
    """
    buckets: dict[str, list[Node]] = {}
    for node in nodes:
        cc = (node.country or "").upper()
        if not cc:
            continue  # no measured country: it belongs to the full payload
        buckets.setdefault(cc, []).append(node)

    ranked = sorted(
        (cc for cc, group in buckets.items() if len(group) >= minimum),
        key=lambda cc: (-len(buckets[cc]), cc),
    )[:limit]

    shards: list[CountryShard] = []
    for cc in ranked:
        group = buckets[cc]
        for fmt in _shard_formats(core):
            # `country=` makes the renderer emit only this country's nodes and
            # name the groups after it, so a client shows "Netherlands" as one
            # destination instead of a flat list where the country is a naming
            # convention in a remark.
            payload, included = render_validated(
                group,
                RenderParams(
                    fmt=fmt,
                    client_core=core,
                    title=f"hub-{tier}-{cc.lower()}",
                    country=cc,
                    cache_id=hashlib.sha256(
                        "".join(n.dedup_key for n in group).encode()
                    ).hexdigest()[:16],
                ),
                validate=validate,
            )
            if not payload:
                continue
            shards.append(CountryShard(cc, fmt, payload, len(included)))
    return shards
