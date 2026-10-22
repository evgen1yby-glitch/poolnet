# Security policy

## What this software is, and what that means for you

The hub is a **control plane**. It fetches publicly published proxy
configurations, verifies them, and republishes the survivors as client
subscriptions. It never relays user traffic: the server consumes a node exactly
as an end user's device would, only to find out whether that node works.

Three consequences shape everything below, and they are not boilerplate:

**The node list is not a secret.** It is assembled from public sources and
republished. If you find a way to read it, you have found a way to read
something that was already on the internet. Report it as a bug, not as a
vulnerability.

**The subscription token is a secret, and it is the only one.** It gates *who
can poll*, not *what is in the list*. A leaked token means someone else's
requests count against your rate limit; it does not expose your traffic,
because the hub never carries any.

**The nodes are hostile.** Every endpoint in a published list belongs to an
unknown third party, and the list is not a recommendation. This is stated on
the landing page, in the bot's message and in the served headers, because a user
who does not understand it is the one who loses.

## Reporting a vulnerability

Open a [private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository. Do not open a public issue for anything in the categories
below.

Please include what you did, what you expected, and what happened. A proof of
concept against a local instance is worth more than a description.

**Never test against someone else's deployment.** The hub is meant to be
self-hosted, and a running instance belongs to whoever runs it. If you find an
exposed instance in the wild, report it to its operator rather than probing it.

## In scope

| Area | Why it matters |
| --- | --- |
| **SSRF in the prober** | The prober dials addresses taken from public text. A node entry pointing at `169.254.169.254` or an RFC1918 address must never be dialled. The guard is in `models.is_blocked_ip` and is re-applied before every connection. |
| **Path traversal on the subscription endpoint** | `/sub/{token}/{tier}` and `/sub/{token}/country/{cc}` build a filesystem path. A code that reaches the lookup unvalidated is a traversal against the generation directory, not a country. |
| **Token disclosure** | The token appears in the URL path. It must not reach nginx access logs, the application log, an error page, or a response header. |
| **Resource exhaustion** | The rate limiter's bucket map is attacker-controlled by key. Unbounded growth is a memory exhaustion. |
| **Rendering injection** | Node fields arrive from untrusted text. A password or SNI that closes a YAML flow mapping forges structure in a published payload, and the client parses the forgery happily. |
| **Denial of service against the probe** | A source that returns 10 000 malformed lines in a round must not take the pipeline down or starve the other sources. |

## Out of scope

- **Reading the published node list.** It is public by design.
- **A node behaving maliciously.** That is the threat model, not a bug; the
  hub verifies reachability, not good faith. The published warning says so.
- **The hub relaying traffic.** It has no code path that does so, and one
  appearing would be a critical finding rather than a feature request.
- **Rate-limit bypass by rotating IPs.** Detecting distributed clients is not a
  goal; the limits exist to bound load, and a distributed client is bounded too.
- **Anything requiring an already-compromised host**, such as reading the
  database file directly.

## What the software already does

Listed so a report does not have to rediscover it, and so a *failure* of any of
these is a valid finding:

- **SSRF guard** applied to every node address, with IPv4-mapped IPv6
  unwrapped, non-routable ranges blocked, and the same block list shared by the
  parser and the prober — one list, two importers, so the two cannot disagree.
  It runs once per node before the probe and again when the prober builds its
  candidate list. **It does not resolve hostnames** — see "Known gaps".
- **Probing is opt-in and isolated.** Node dialling happens only under
  `--allow-network`, and in practice inside a dedicated network namespace with
  its own veth uplink. The default run fetches and publishes but never opens a
  probe socket.
- **Bearer tokens are stored as SHA-256 digests**, never as plaintext, and are
  compared with `hmac.compare_digest`.
- **`X-Forwarded-For` is trusted only from a loopback peer**, and the shipped
  nginx vhost overwrites it with `$remote_addr` rather than appending.
- **Publication is validated per format** before a generation becomes current:
  base64 payloads are decode-and-reparse checked, sing-box JSON goes through
  `sing-box check`, Clash YAML is parsed and shape-checked. A payload Xray
  refuses is dropped node by node, because one bad node otherwise discards its
  entire country group.
- **Generations are content-addressed and atomic**: built in a temporary
  directory, verified against a per-payload manifest, then made current by an
  `os.replace` on a pointer file, under a cross-process lock.
- **Subprocess calls take a timeout** and never run with a shell.

## Known gaps

Recorded here on purpose. A gap that is documented is a gap a reader can decide
about; a gap that is only in the code is one they will assume away.

**The SSRF guard does not resolve hostnames.** A node whose `address` is a
hostname rather than an IP literal passes `models.is_blocked_address`, and
nothing re-checks the resolved address before the TCP dial. A name pointing at
`127.0.0.1` or `169.254.169.254` therefore reaches `_raw_connect` and
`_tls_handshake`.

Two things bound it in the shipped deployment, and neither is a fix:

- node dialling only happens under `--allow-network` (`hub-probe.service`), and
  that unit runs inside the `hubns` namespace, so a loopback address resolves
  against *that* namespace's loopback rather than the host's. The host's own
  services — the MariaDB on `127.0.0.1:3306`, the hub API on `127.0.0.1:8090` —
  are not reachable from there.
- a deployment that probes on the host network without that namespace has the
  gap in full.

Closing it means resolving at dial time and pinning the vetted address. That is
a transport-layer change, not a guard change, and it is not done.

## Supported versions

There are no released versions yet. Fixes land on `main`; if you are running a
fork, rebase rather than expecting a backport.
