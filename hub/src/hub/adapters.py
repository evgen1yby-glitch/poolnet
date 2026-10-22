"""Source adapters: turn non-share-URI bodies into share URIs.

Three of the sources the operator asked for are not share-URI subscriptions,
and discovering that before writing the adapters is what saved this file from
being a parser for data that cannot exist:

* **proxyfreeonly.com** answers `?limit=500&page=1` with a JSON *array of
  objects keyed `__0`..`__5`*, and the host names inside (`public-vpn-43`,
  `vpn521576029`) are the SoftEther/VPN-Gate convention. The same rows appear
  in VPN Gate's own CSV with `OpenVPN_ConfigData_Base64`. These are OpenVPN /
  SoftEther servers, not `vless://` proxies.
* **VPN Gate** (`/api/iphone/`) is CSV whose payload column is a base64
  `.ovpn` config: `dev tun`, `proto tcp`, `remote <ip> 443`, `cipher
  AES-128-CBC`, and a `<ca>` block. Again OpenVPN.
* **ipspeed.info/free-vless-reality.php** *does* serve vless+reality share
  URIs, but sits behind a Cloudflare JS challenge: curl and headless Chromium
  both get `403` / "Just a moment...". Reaching it needs a browser-grade
  fingerprint, which is an operator-supplied capability, not something to fake
  from here.

So this module does one job: **normalise a body we cannot otherwise read, and
be honest when it cannot**. An adapter that turns 2663 rows of OpenVPN into
`vless://` URIs would publish nodes that do not exist, and the pipeline would
spend its whole probe budget dialing fabrications.

The rule that keeps this safe: an adapter returns `("", reason)` and the reason
is logged, rather than returning a partial list that looks like success.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Optional, Sequence

# --------------------------------------------------------------------------- #
# result type
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Adapted:
    """A body rewritten into one-share-URI-per-line, or a refusal.

    `text` is empty exactly when `reason` is set, so a caller cannot mistake
    "adapted to nothing" for "adapted to an empty list" — the difference
    between a source outage and a source whose body shape changed.
    """

    text: str
    reason: str = ""
    #: How many URIs the adapter produced, for the run report.
    count: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _b64(text: str) -> str:
    padded = text + "=" * (-len(text) % 4)
    return base64.b64decode(padded).decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# proxyfreeonly.com  (JSON, obfuscated keys, OpenVPN family)
# --------------------------------------------------------------------------- #

#: The API's object keys, recovered by reading a real response rather than by
#: guessing. `__0` is the address, `__4` the country, `__1` what the site calls
#: a score. There is no port and no protocol column: both are fixed by the
#: SoftEther family the host names belong to.
_PFO_KEYS = ("__0", "__1", "__2", "__3", "__4", "__5")


def adapt_proxyfreeonly(body: str) -> Adapted:
    """Normalise proxyfreeonly's JSON list into nothing, with a reason.

    Deliberately produces **zero** URIs. Every row in that list is an
    OpenVPN/SoftEther endpoint; `parse_many` would reject all of them anyway,
    and converting them into a different protocol would publish nodes that
    cannot connect. Returning an explicit refusal is what makes `report.errors`
    show the real cause instead of a silent zero.
    """
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return Adapted("", "proxyfreeonly: body is not JSON")
    if isinstance(rows, dict):
        # Some deployments wrap the list: {"data": [...]}.
        for key in ("data", "servers", "result", "items"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
    if not isinstance(rows, list) or not rows:
        return Adapted("", "proxyfreeonly: empty or unexpected JSON shape")

    if not isinstance(rows[0], dict) or not any(k in rows[0] for k in _PFO_KEYS):
        return Adapted("", "proxyfreeonly: no recognised keys in first row")

    countries = {str(r.get("__4", "")) for r in rows if isinstance(r, dict)}
    return Adapted(
        "",
        f"proxyfreeonly: {len(rows)} rows are OpenVPN/SoftEther endpoints "
        f"({len(countries)} countries); not share URIs",
    )


# --------------------------------------------------------------------------- #
# VPN Gate  (CSV + base64 OpenVPN config)
# --------------------------------------------------------------------------- #

_VPNGATE_HEADER = "#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort"


def parse_vpngate_csv(body: str) -> list[dict]:
    """The one genuinely reusable part of VPN Gate: its per-server facts.

    The CSV gives a country, a measured ping and a measured throughput for
    every server, which is exactly the metadata our ranking wants — so this
    function exists to be *called by an operator tool*, and its output is
    feed for ranking, not for the node index. `adapt_vpngate` below explains
    why it cannot feed `parse_many`.
    """
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    header = next((ln for ln in lines if ln.startswith("#HostName")), "")
    if not header:
        return []
    columns = header.lstrip("#").split(",")
    rows = []
    for line in lines:
        if line.startswith("#") or line.startswith("*vpn_servers"):
            continue
        parsed = next(csv.reader([line]))
        if len(parsed) == len(columns):
            rows.append(dict(zip(columns, parsed)))
    return rows


def parse_ovpn(body: str) -> dict:
    """Pull `remote <host> <port>`, `proto`, and the `<ca>` block out of a config.

    Written for the ranking tool and for tests, not for `parse_many`: the
    parser's protocol table has no OpenVPN entry and this file does not add a
    fake one. A missing `remote` yields no host, which callers must check.
    """
    out: dict = {"host": "", "port": 0, "proto": "udp", "ca": "", "cipher": "", "auth": ""}
    lines = body.splitlines()
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key == "remote" and len(parts) >= 3:
            out["host"] = parts[1]
            try:
                out["port"] = int(parts[2])
            except ValueError:
                out["port"] = 0
        elif key == "proto" and len(parts) >= 2:
            out["proto"] = parts[1]
        elif key == "cipher" and len(parts) >= 2:
            out["cipher"] = parts[1]
        elif key == "auth" and len(parts) >= 2:
            out["auth"] = parts[1]
    ca = ""
    if "<ca>" in body and "</ca>" in body:
        ca = body.split("<ca>", 1)[1].split("</ca>", 1)[0].strip()
    out["ca"] = ca
    return out


def adapt_vpngate(body: str) -> Adapted:
    """Refuse VPN Gate bodies, with the country spread as the reason.

    The count is reported so an operator can see at a glance how much of the
    pool was considered and why none of it was ingested — that is the whole
    value of an explicit refusal over a silent empty string.
    """
    rows = parse_vpngate_csv(body)
    if not rows:
        return Adapted("", "vpngate: no CSV rows")
    countries = {r.get("CountryShort", "") for r in rows}
    return Adapted(
        "",
        f"vpngate: {len(rows)} rows are OpenVPN configs "
        f"({len(countries)} countries); not share URIs",
    )


# --------------------------------------------------------------------------- #
# ipspeed.info  (Cloudflare-gated HTML)
# --------------------------------------------------------------------------- #

#: Matches every scheme `parse_one` accepts, so a page that *does* serve URIs is
#: picked up without knowing its markup. The HTML adapter is a regex over the
## page for exactly this reason: the site's table markup is not a contract.
_URI_RE = re.compile(
    r"(?:vless|vmess|trojan|ss|hysteria2|tuic|wireguard|socks)://[^\s\"'<>]+",
    re.IGNORECASE,
)


def extract_share_uris(html: str) -> list[str]:
    """Every share URI in an arbitrary HTML page, order preserved.

    Kept separate from the adapter so the landing page's own copy can be
    checked for accidental URI leakage by the same function.
    """
    seen: set[str] = set()
    found: list[str] = []
    for match in _URI_RE.findall(html or ""):
        if match not in seen:
            seen.add(match)
            found.append(match)
    return found


def adapt_ipspeed(body: str) -> Adapted:
    """Extract share URIs from the page, or report the Cloudflare block.

    Two outcomes, both honest:

    * the page served URIs -> one URI per line, ready for `parse_many`;
    * the page served a challenge -> `reason` says so, because the difference
      between "no nodes published today" and "the gate ate our request" is the
      difference between a source that retired and a source to retry.
    """
    if not body.strip():
        return Adapted("", "ipspeed: empty body")
    if "Just a moment" in body or "cf-challenge" in body or "challenges.cloudflare" in body:
        return Adapted("", "ipspeed: Cloudflare challenge page, not node data")
    uris = extract_share_uris(body)
    if not uris:
        return Adapted("", "ipspeed: no share URIs in body")
    return Adapted("\n".join(uris), "", count=len(uris))


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

#: Body -> text transformations, keyed by the *kind* a source declares. The
#: key is not derived from the URL: a mirror of ipspeed on a different host is
#: still an ipspeed-shaped body, and a URL pattern would silently stop matching.
_ADAPTERS = {
    "proxyfreeonly": adapt_proxyfreeonly,
    "vpngate": adapt_vpngate,
    "ipspeed": adapt_ipspeed,
}


def adapt(kind: str, body: str) -> Adapted:
    """Dispatch by declared kind. An unknown kind passes the body through.

    Passing through is the right default for a plain share-URI subscription:
    most sources need no adaptation, and forcing every source to declare a kind
    would turn a missing declaration into an outage.
    """
    handler = _ADAPTERS.get((kind or "").lower())
    if handler is None:
        return Adapted(body or "", "", count=len(extract_share_uris(body or "")))
    return handler(body or "")
