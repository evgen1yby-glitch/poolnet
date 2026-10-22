#!/usr/bin/env bash
# Recreate `hubns` — the probe's sandbox — if it is missing.
#
# `hubns` is a bind mount on /run/netns/hubns, i.e. tmpfs. It does not survive a
# reboot. Nothing on this box recreates it automatically, so after a restart the
# timer fires into:
#
#     sudo[..]: Cannot open network namespace "hubns": No such file or directory
#
# which is an honest error but an opaque one: it says a file is missing and says
# nothing about a namespace, an uplink, or what the prober was supposed to do.
# This script is the documented fix, run once at boot via hub-ns.service.
#
# Idempotent by construction: if the namespace exists, it does nothing. That is
# the property that lets it be wired to boot, or run by hand after an upgrade,
# without destroying a sandbox that is currently in use.
#
# What it does NOT do, deliberately: it never modifies a route on the host, never
# repeats an iptables rule that is already present, and never touches eth0. It
# adds two interfaces on a link-local address range and one MASQUERADE rule
# scoped to that range, which is why it is safe to point at a box running other
# work.
#
#   hub-probe.service  probes from inside the namespace this creates
#   hub-ns.service     runs this at boot, before network-online.target
#
# Usage:  ./deploy/hubns-ensure.sh            # create if absent, report state
#         ./deploy/hubns-ensure.sh --verify   # create if absent, then prove it
#         ./deploy/hubns-ensure.sh --name X --subnet 10.99.1
#
# The `--name`/`--subnet` pair exists so the creation path can be exercised on a
# real kernel without touching the live sandbox — see tests for how. Namespacing
# by argument rather than by hardcoded constant is what makes the create path
# testable at all: the default is the production sandbox, and any other name is
# disposable.
set -euo pipefail

NS_NAME="hubns"
SUBNET="10.99.0"
VERIFY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify) VERIFY=1; shift ;;
        --name) NS_NAME="$2"; shift 2 ;;
        --subnet) SUBNET="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

HOST_IP="${SUBNET}.1"
NS_IP="${SUBNET}.2"
# Production keeps the historical names, because the live NAT rule already on
# this box names `veth-hub-br` explicitly (`! -o veth-hub-br -j MASQUERADE`) and
# the prober's own header documents them. Every other name derives from the
# namespace, so a test sandbox cannot be handed a pair that already belongs to
# production — which is the difference between exercising the create path and
# silently attaching the live host to a throwaway namespace.
if [[ "$NS_NAME" == "hubns" ]]; then
    HOST_IF="veth-hub"
    HOST_BR="veth-hub-br"
else
    HOST_IF="veth-${NS_NAME}"
    HOST_BR="veth-${NS_NAME}-br"
fi

exists() {
    ip netns list 2>/dev/null | awk '{print $1}' | grep -qx "$NS_NAME"
}

if exists; then
    echo "$NS_NAME: already present ($(ip netns list | grep -F "$NS_NAME"))"
    exit 0
fi

# Refuse to create for a name whose resources are already in use. A half-created
# sandbox is worse than a missing one: `ip link add veth-hub` fails if veth-hub
# exists, but the *reason* it exists could be a previous run of this script that
# died between `ip link add` and `ip link set ... netns`, and silently reusing
# that pair would attach the live host to a namespace that may not be this one.
for iface in "$HOST_IF" "$HOST_BR"; do
    if ip link show "$iface" >/dev/null 2>&1; then
        echo "refusing: interface $iface already exists and is not owned by $NS_NAME" >&2
        exit 1
    fi
done

echo "$NS_NAME: missing, creating it"

# 1. the namespace itself
ip netns add "$NS_NAME"

# 2. a veth pair: one end stays here ("the router"), the other goes inside
ip link add "$HOST_IF" type veth peer name "$HOST_BR"
ip link set "$HOST_IF" netns "$NS_NAME"

# 3. host side: address, up. This is a point-to-point link with a link-local
#    address — nothing routable outside this box depends on it.
ip address add "${HOST_IP}/24" dev "$HOST_BR"
ip link set "$HOST_BR" up

# 4. namespace side: address, loopback, and a default route *out through the veth*
ip -n "$NS_NAME" address add "${NS_IP}/24" dev "$HOST_IF"
ip -n "$NS_NAME" link set "$HOST_IF" up
ip -n "$NS_NAME" link set lo up
ip -n "$NS_NAME" route add default via "$HOST_IP"

# 5. The part that is easy to miss and is the reason this script is not three
#    lines: `FORWARD` has a policy of DROP on this host (ufw's default), and the
#    NAT rule below does nothing without a rule permitting the traffic through
#    the filter table first. NAT translates the source address; it does not
#    decide whether the packet may be forwarded at all.
#
#    So each subnet needs its own pair, and the pair is what the working `hubns`
#    has:
#
#        ACCEPT  in  veth-hub-br  10.99.0.0/24 -> 0.0.0.0/0                       (out)
#        ACCEPT  out veth-hub-br  0.0.0.0/0 -> 10.99.0.0/24  state RELATED,ESTABLISHED (back)
#
#    Without the first, nothing leaves. Without the second, the TCP handshake
#    completes inside the namespace and the SYN-ACK never returns, so a probe
#    dials a node and reports it dead. One NAT rule plus these two is what makes
#    a namespace that can actually reach the third-party nodes it is meant to
#    test — verified by resolving a name from inside the namespace below, which
#    is a check that cannot pass on a host-only route.
iptables -C FORWARD -i "$HOST_BR" -s "${SUBNET}.0/24" ! -o "$HOST_BR" -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$HOST_BR" -s "${SUBNET}.0/24" ! -o "$HOST_BR" -j ACCEPT
iptables -C FORWARD -o "$HOST_BR" -d "${SUBNET}.0/24" -m conntrack \
        --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -o "$HOST_BR" -d "${SUBNET}.0/24" -m conntrack \
        --ctstate RELATED,ESTABLISHED -j ACCEPT

# 6. The NAT rule itself, which is the half everyone remembers.
iptables -t nat -C POSTROUTING -s "${SUBNET}.0/24" ! -o "$HOST_BR" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "${SUBNET}.0/24" ! -o "$HOST_BR" -j MASQUERADE

echo "$NS_NAME: created (${NS_IP}/24 via ${HOST_IP}) on $HOST_IF/$HOST_BR"

if [[ "$VERIFY" == "1" ]]; then
    # A namespace that exists is not a namespace that works. This proves the two
    # things a probe needs and would otherwise discover missing ten minutes into
    # a run: a default route, and DNS.
    #
    # The DNS check runs *inside* the namespace, which is the whole point and the
    # reason it is not a bare `python3`. Resolving from the host would succeed
    # every time — the host has working DNS — and would therefore be evidence
    # about the host, not about this namespace. `ip netns exec` is what makes the
    # check mean what its output claims.
    ip -n "$NS_NAME" route show default
    ip netns exec "$NS_NAME" python3 -c \
        "import socket; print('dns:', socket.gethostbyname('raw.githubusercontent.com'))"
    echo "$NS_NAME: verified"
fi
