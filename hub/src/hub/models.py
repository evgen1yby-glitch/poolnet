"""Intermediate representation and typed errors for everything the pipeline touches.

Design rule: a value that is *known to be wrong* is a typed error, never a silent
drop and never a partially-filled record. Callers decide what to do with it.
"""

from __future__ import annotations

import enum
import hashlib
import ipaddress
from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ParseErrorKind(str, enum.Enum):
    """Every way a share URI can be rejected by the parser."""

    EMPTY = "empty"
    UNKNOWN_SCHEME = "unknown_scheme"
    NO_NETLOC = "no_netloc"
    BAD_BASE64 = "bad_base64"
    BAD_JSON = "bad_json"
    MISSING_UUID = "missing_uuid"
    BAD_UUID = "bad_uuid"
    MISSING_PASSWORD = "missing_password"
    BAD_PORT = "bad_port"
    MISSING_ADDRESS = "missing_address"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    PRIVATE_ADDRESS = "private_address"


@dataclass(frozen=True)
class ParseError:
    """A URI the parser refused. `line` is the 1-based original line number."""

    kind: ParseErrorKind
    line: int
    raw: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - presentation only
        return f"line {self.line}: {self.kind.value}: {self.detail or self.raw[:60]}"


# --------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------


#: Addresses we must never dial, in one place.

#: The parser and the prober each need this list, and having them keep separate
#: copies is how a poisoned entry gets through one of them: the prober blocked
#: `2001:db8::/32` while the parser did not, so a documentation-prefix address
#: parsed cleanly and then died at a later stage. One list, two importers.
BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "2001:db8::/32",  # documentation prefix, never routable
    )
)

#: Cloud metadata endpoints that a poisoned node entry tries to reach.
METADATA_HOSTS = (
    "169.254.169.254",
    "metadata.google.internal",
    "100.100.100.200",
)


def is_blocked_ip(literal: str) -> bool:
    """True if `literal` is an IP inside `BLOCKED_NETWORKS`.

    Raises `ValueError` for anything that is not an IP — callers that accept
    hostnames use `is_blocked_address` instead, which resolves this.
    """
    ip = ipaddress.ip_address(literal.strip().strip("[]"))
    if ip.version == 6 and ip.ipv4_mapped:
        # ::ffff:10.0.0.1 is a private address wearing a hat.
        ip = ip.ipv4_mapped
    return any(ip in net for net in BLOCKED_NETWORKS)


def is_blocked_address(address: str) -> bool:
    """True if `address` must never be dialled. Hostnames pass through.

    **A hostname that resolves to a blocked address is not caught here, and
    nothing downstream catches it either.** This is the whole guard, not the
    cheap first line of one: the pipeline calls it once per node before the
    probe (`pipeline.run_once`), and the prober calls it again when it builds
    its candidate list — but neither resolves a hostname, so a name pointing at
    `127.0.0.1` or `169.254.169.254` passes both checks and reaches the dial.

    That is a real gap and it is recorded rather than papered over, because an
    earlier version of this docstring claimed a re-check at connection time
    that does not exist, which is worse than the gap: it tells a reader the
    case is handled and stops them looking. Closing it means resolving at dial
    time and pinning the vetted address, which is a change to the transport
    layer rather than to this function.

    The practical exposure is bounded by where the prober runs: node dialling
    is opt-in, and in the shipped deployment it happens inside a dedicated
    network namespace whose egress is a veth uplink, so a name resolving to the
    host's own loopback does not reach the host's services. A deployment that
    probes on the host network without that namespace would have the gap in
    full. See `SECURITY.md`, "Known gaps".
    """
    candidate = (address or "").strip().strip("[]").lower()
    if not candidate or candidate in ("localhost", *METADATA_HOSTS):
        return True
    try:
        return is_blocked_ip(candidate)
    except ValueError:
        return False


class Protocol(str, enum.Enum):
    VLESS = "vless"
    VMESS = "vmess"
    TROJAN = "trojan"
    SHADOWSOCKS = "ss"
    SHADOWSOCKSR = "ssr"
    HYSTERIA2 = "hysteria2"
    TUIC = "tuic"
    WIREGUARD = "wireguard"
    SOCKS = "socks"
    HTTP_PROXY = "http"


# Protocols a client-core can actually speak. `XRAY_ONLY` means "xray-core and
# descendants"; `SB_ONLY` means "upstream sing-box / mihomo" (Hysteria2, TUIC);
# `BOTH` means every mainstream client. This is what makes the renderer's
# `client_core` parameter data-driven rather than hard-coded.
#: Shadowsocks ciphers Xray-core 26.x still accepts.
#:
#: Xray removed the non-AEAD ciphers, and a node using one does not fail alone:
#: the core refuses the **entire config**, so one `aes-128-cfb` node discarded
#: its whole country. That is not hypothetical — it took a 150-node payload down
#: to 4 nodes in one round, because seven country groups each contained a legacy
#: cipher and were dropped entire.
#:
#: The list is short because the AEAD set *is* short. `none` is accepted (it is
#: a plaintext cipher used by a few public nodes), and `2022-blake3-*` is
#: accepted but needs a base64 key rather than a password, so it is listed
#: rather than filtered — the parser keeps what the source declared, and the
#: core is the authority on whether it starts.
XRAY_SHADOWSOCKS_CIPHERS: frozenset[str] = frozenset({
    "aes-128-gcm",
    "aes-256-gcm",
    "chacha20-poly1305",
    "chacha20-ietf-poly1305",
    "none",
})

#: Ciphers whose name starts with this are the 2022 edition, accepted by Xray
#: with a key rather than a password.
_SS2022_PREFIX = "2022-blake3-"

#: Protocols Xray will not accept over plaintext to a public address.
#:
#: Shadowsocks is excluded deliberately: it *is* its own encryption, which is
#: why the rule names "TLS or other encryption" and leaves it alone.
_XRAY_NEEDS_ENCRYPTION: frozenset[Protocol] = frozenset({
    Protocol.VLESS,
    Protocol.VMESS,
    Protocol.TROJAN,
})

PROTOCOL_CORES: dict[Protocol, frozenset[str]] = {
    Protocol.VLESS: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.VMESS: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.TROJAN: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.SHADOWSOCKS: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.HYSTERIA2: frozenset({"sing-box", "mihomo"}),
    Protocol.TUIC: frozenset({"sing-box", "mihomo"}),
    Protocol.WIREGUARD: frozenset({"sing-box", "mihomo"}),
    Protocol.SOCKS: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.HTTP_PROXY: frozenset({"xray", "sing-box", "mihomo"}),
    Protocol.SHADOWSOCKSR: frozenset(),
}


class Transport(str, enum.Enum):
    TCP = "tcp"
    WS = "ws"
    GRPC = "grpc"
    HTTP2 = "h2"
    QUIC = "quic"
    XHTTP = "xhttp"
    HTTPUPGRADE = "httpupgrade"


class Security(str, enum.Enum):
    NONE = "none"
    TLS = "tls"
    REALITY = "reality"


# --------------------------------------------------------------------------
# Transports and TLS settings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TLS:
    """TLS/REALITY parameters exactly as they appear in the share link."""

    sni: str = ""
    fingerprint: str = ""  # uTLS fingerprint, e.g. "chrome"
    alpn: tuple[str, ...] = ()
    allow_insecure: bool = False
    # REALITY
    public_key: str = ""
    short_id: str = ""
    spider_x: str = ""


@dataclass(frozen=True)
class TransportSettings:
    """Per-transport tuning. `kind` decides which fields are meaningful."""

    kind: Transport = Transport.TCP
    host: str = ""
    path: str = ""
    service_name: str = ""  # grpc
    # header handling
    header_type: str = "none"

    def validate(self, proto: Protocol) -> None:
        """Structural sanity: a transport that cannot carry a stream.

        Raises `ValueError` — callers translate it into a typed `ParseError`.
        """
        if self.kind in (Transport.WS, Transport.HTTP2, Transport.HTTPUPGRADE, Transport.XHTTP):
            if proto in (Protocol.SHADOWSOCKS, Protocol.WIREGUARD):
                raise ValueError(
                    f"{proto.value} cannot ride {self.kind.value}"
                )
        if self.kind is Transport.GRPC and not self.service_name:
            # An empty gRPC service name is legal in share links but is
            # rejected by sing-box 1.8+.
            raise ValueError("grpc requires serviceName")
        if self.kind in (Transport.WS, Transport.HTTP2, Transport.HTTPUPGRADE, Transport.XHTTP):
            if not self.path:
                raise ValueError(f"{self.kind.value} requires path")
        if self.kind is Transport.WS and not self.host:
            # WS links commonly omit Host; sing-box then derives it from SNI.
            pass


# --------------------------------------------------------------------------
# Node
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    """One proxy endpoint, normalised from a share URI or a JSON config."""

    protocol: Protocol
    address: str
    port: int
    # credentials (only the ones the protocol needs)
    uuid: str = ""
    password: str = ""
    username: str = ""
    # transport
    transport: Transport = Transport.TCP
    transport_settings: TransportSettings = field(default_factory=TransportSettings)
    security: Security = Security.NONE
    tls: TLS = field(default_factory=TLS)
    # protocol-specific extras that a render needs
    flow: str = ""  # VLESS flow, e.g. xtls-rprx-vision
    method: str = ""  # SS cipher
    obfs: str = ""  # hysteria2 obfs=salamander
    obfs_password: str = ""  # hysteria2 obfs-password; not part of the dedup key
    congestion: str = ""
    # provenance
    source: str = ""
    remark: str = ""
    # measured, filled in by the prober
    country: str = ""

    # ---- identity -------------------------------------------------------

    @property
    def dedup_key(self) -> str:
        """Stable identity of the *endpoint*, ignoring remarks and provenance.

        A node that appears in two sources under two different names must be
        treated as one node. Credential-bearing fields must be excluded from
        the display form of this value — see `__str__`.

        The key is a SHA-256 over ``proto|host|port|creds`` so it is safe to log
        and safe to use as a filename component.
        """
        parts = [
            self.protocol.value,
            self.address.lower(),
            str(self.port),
            self.uuid,
            self.password,
            self.obfs,
            self.method,
        ]
        blob = "|".join(parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def short_key(self) -> str:
        """First 12 hex chars of `dedup_key` — enough for human-readable tags."""
        return self.dedup_key[:12]

    def __str__(self) -> str:
        """Never include credentials. Safe for logs, tags, and file names."""
        return f"{self.protocol.value}://{self.address}:{self.port}"

    # ---- core compatibility --------------------------------------------

    def supports_core(self, core: str) -> bool:
        """Can a client using `core` (xray / sing-box / mihomo) speak this node?

        Upstream sing-box does not implement XHTTP (SagerNet/sing-box#3550), so
        an XHTTP node is dropped rather than shipped as a dead outbound.
        """
        if self.transport is Transport.XHTTP and core != "xray":
            return False
        if core not in PROTOCOL_CORES.get(self.protocol, frozenset()):
            return False
        # A Shadowsocks node is only speakable if its cipher is. Reported here
        # rather than dropped silently in the renderer, so the same rule governs
        # the probe, the tiers and every dialect: a client that cannot start a
        # config must never be handed one.
        if self.protocol is Protocol.SHADOWSOCKS and core == "xray":
            method = (self.method or "").lower()
            return method.startswith(_SS2022_PREFIX) or method in XRAY_SHADOWSOCKS_CIPHERS
        if core == "xray" and self.protocol in _XRAY_NEEDS_ENCRYPTION:
            # Xray's rule, from its own error message: "vless without TLS or
            # other encryption is prohibited unless the server address is a
            # private IP or domain". A node that breaks it does not fail alone —
            # the core refuses the whole config, so one such node takes down its
            # entire country group in the client. A real Happ import reported
            # exactly this for `NL-3`.
            #
            # A domain is exempt, and that is not a technicality to ignore:
            # plenty of public nodes are plain VLESS behind a hostname, and
            # dropping them would discard working configs.
            if self.security is Security.NONE and not self._is_domain():
                return False
        return True

    def _is_domain(self) -> bool:
        """True when `address` is a hostname rather than a bare IP literal.

        Used for Xray's encryption exemption: the rule is phrased in terms of
        the address being "a private IP or domain", and a hostname is the case
        that actually occurs in this pool. A private IP would also be exempt,
        but the SSRF guard drops those long before here.
        """
        candidate = (self.address or "").strip().strip("[]")
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return bool(candidate)
        return False


# --------------------------------------------------------------------------
# Probe results
# --------------------------------------------------------------------------


class Stage(str, enum.Enum):
    """The five verification stages, in order."""

    TCP = "tcp"  # 1. TCP connect
    TLS = "tls"  # 2. TLS handshake with the real SNI
    CONFIG = "config"  # 3. sing-box check
    HTTP = "http"  # 4. HTTP over the proxy, 2 rounds
    REPUTATION = "reputation"  # 5. published nodes only


@dataclass
class ProbeResult:
    """Everything the prober measured about one node in one run."""

    dedup_key: str
    stage_reached: Stage
    ok: bool = False
    # stage timings (seconds)
    tcp_ms: Optional[float] = None
    tls_ms: Optional[float] = None
    http_ms: Optional[float] = None
    http_ms_round2: Optional[float] = None
    jitter_ms: Optional[float] = None
    # speed test (top-N only)
    speed_bps: Optional[float] = None
    # what the canary learned
    exit_ip: str = ""
    exit_country: str = ""
    exit_asn: str = ""
    exit_colo: str = ""
    # security checks
    injected: bool = False
    cert_substituted: bool = False
    dns_tampered: bool = False
    transparent_proxy: bool = False
    risk_score: Optional[int] = None
    # provenance of the failure
    error: str = ""
    rounds_passed: int = 0

    @property
    def latency_ms(self) -> float:
        """Best available latency signal, http first then tls then tcp."""
        for value in (self.http_ms, self.tls_ms, self.tcp_ms):
            if value is not None:
                return value
        return float("inf")


# --------------------------------------------------------------------------
# Score
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Score:
    """0-100 with the per-factor breakdown so a score is auditable."""

    total: int
    latency: float
    availability: float
    jitter: float
    source_history: float
    protocol_history: float
    throughput: float
    fingerprint_resistance: float
    geo_integrity: float
    rubric_version: str


# --------------------------------------------------------------------------
# Payloads
# --------------------------------------------------------------------------


class Format(str, enum.Enum):
    BASE64 = "base64"  # v2rayNG, v2rayN, Shadowrocket, NekoBox
    SINGBOX = "singbox"  # sing-box, Hiddify, v2rayN, Happ
    CLASH = "clash"  # mihomo, FlClash, Karing, Clash Verge Rev


class Tier(str, enum.Enum):
    CURATED = "curated"
    VERIFIED = "verified"


#: Maximum nodes per payload. Above ~1000 v2rayNG freezes on import (#2165)
#: and Karing's import UI does the same; 200 is the practiced ceiling.
MAX_NODES_PER_PAYLOAD = 200

#: Number of previous generations retained for instant rollback.
RETAINED_GENERATIONS = 3
