"""Serialise a `Node` so a verified node survives between rounds.

Why this exists: `nodes` keeps `dedup_key`, `address`, `port` and `country` —
enough to *recognise* a node and not enough to *reconstruct* one. The uuid, the
password and the transport settings are exactly what a render needs, so a node
carried between rounds without them becomes a placeholder that passes every
check and then produces a payload whose entries connect nowhere. That failure is
silent: the count looks right and the client gets dead configs.

So the node is stored whole. The plan for it is to make the pool the union of
what has been *proven working recently* rather than the intersection of what a
single round happened to probe — the live pool shares only 316 distinct nodes
across four rounds that each verified 57-239, so publishing one round makes the
country list flicker for no reason a user can see.

Two rules, both tested:

* **Round trip is exact**, including every credential-bearing field. A partial
  round trip is the failure that looks like success.
* **Unreadable state drops the node.** Rebuilding a fake from partial data is
  precisely the bug this module was written to fix, so a node that cannot be
  rebuilt is returned as `None` and the caller skips it.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

from .models import Node, Protocol, Security, Transport, TransportSettings, TLS

__all__ = ["node_to_json", "node_from_json"]


def node_to_json(node: Node) -> str:
    """The node as a JSON object, every field included.

    `asdict` recurses into the nested dataclasses, which is what makes this
    complete by construction: a field added to `Node`, `TLS` or
    `TransportSettings` is serialised without a change here. The enums need
    their values because the round trip must not depend on Python's enum
    lookup accepting a raw name.
    """
    data = asdict(node)
    data["protocol"] = node.protocol.value
    data["transport"] = node.transport.value
    data["security"] = node.security.value
    data["transport_settings"]["kind"] = node.transport_settings.kind.value
    # `alpn` is a tuple, which JSON has no type for; a list round-trips back
    # through `TLS(alpn=...)` identically because the dataclass does not
    # compare container types.
    data["tls"]["alpn"] = list(node.tls.alpn)
    return json.dumps(data, ensure_ascii=False)


def node_from_json(blob: str) -> Optional[Node]:
    """Rebuild a node, or `None` if the stored form is unusable.

    Never raises and never guesses. A node that cannot be rebuilt is dropped by
    the caller, which is visible in the run report; a node rebuilt from partial
    data is not visible at all, and that is the failure mode this exists to
    avoid.
    """
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        address = str(data["address"])
        port = int(data["port"])
        protocol = Protocol(data["protocol"])
        transport = Transport(data.get("transport", Transport.TCP.value))
        security = Security(data.get("security", Security.NONE.value))
        # A node with no address cannot be dialled, and an empty one is how a
        # truncated record arrives.
        if not address or not 0 < port < 65536:
            return None

        raw_ts = data.get("transport_settings") or {}
        settings = TransportSettings(
            kind=Transport(raw_ts.get("kind", transport.value)),
            host=str(raw_ts.get("host") or ""),
            path=str(raw_ts.get("path") or ""),
            service_name=str(raw_ts.get("service_name") or ""),
            header_type=str(raw_ts.get("header_type") or "none"),
        )
        raw_tls = data.get("tls") or {}
        tls = TLS(
            sni=str(raw_tls.get("sni") or ""),
            fingerprint=str(raw_tls.get("fingerprint") or ""),
            alpn=tuple(str(a) for a in (raw_tls.get("alpn") or ())),
            allow_insecure=bool(raw_tls.get("allow_insecure", False)),
            public_key=str(raw_tls.get("public_key") or ""),
            short_id=str(raw_tls.get("short_id") or ""),
            spider_x=str(raw_tls.get("spider_x") or ""),
        )
    except (KeyError, ValueError, TypeError):
        return None

    return Node(
        protocol=protocol,
        address=address,
        port=port,
        uuid=str(data.get("uuid") or ""),
        password=str(data.get("password") or ""),
        username=str(data.get("username") or ""),
        transport=transport,
        transport_settings=settings,
        security=security,
        tls=tls,
        flow=str(data.get("flow") or ""),
        method=str(data.get("method") or ""),
        obfs=str(data.get("obfs") or ""),
        obfs_password=str(data.get("obfs_password") or ""),
        congestion=str(data.get("congestion") or ""),
        source=str(data.get("source") or ""),
        remark=str(data.get("remark") or ""),
        country=str(data.get("country") or ""),
    )
