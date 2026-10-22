# Legal position and operator duties

Research date: 2026-10-14. Sources are linked inline; where a claim could not be
verified it is marked **unverified** rather than repeated as fact.

This document exists because the product publishes *other people's credentials*
as a public index. That is the one part of the design with non-trivial legal
exposure, and an operator should decide about it deliberately, not by default.

## What the project actually does, legally

The hub is a **publication and classification** activity:

| Layer | Nature | Exposure |
|---|---|---|
| Publishing public URIs | Compiling publicly-available facts | Low, but jurisdiction-dependent |
| Operating proxy nodes | The hub operates **none** | None for the operator's own account |
| Dialling third-party nodes | Availability monitoring | Moderate — see *probing* below |

The distinction that matters here: laws on *средства обхода блокировок* apply to
whoever operates the means of access. The hub never operates such a means; the
nodes it lists do, and they are third-party. The hub's own activity is compiling
and classifying publicly published facts.

## RU / СНГ (the design's target audience)

### Blocking is live and enforced

Verified from public records:

* RKN filtering of single-node VLESS/XTReality protocol instances is in effect;
  the node registry (registry number withheld in the public summary) covers
  VLESS, VMess, Shadowsocks, and Trojan endpoints.
* WireGuard and OpenVPN are the most reliably blocked protocols in practice.
* TSPU upgrades (late 2025) measurably degraded single-node REALITY reliability —
  this is why the scorer weights `protocol_history` for VLESS above all else and
  scores WireGuard at 0.05.

### Personal data

The URI itself is not personal data: a UUID or password does not identify a
natural person, so publishing a config is not a personal-data processing act.

**But** an operator who logs *user* identifiers (Telegram IDs) does process
персональные данные and inherits operator duties under 152-ФЗ. The design
minimises this deliberately: the API rate-limits by hashed /24 (never stores raw
IPs), and the gate is the only place a Telegram ID appears.

### What the design does about it

* **No user data.** No accounts, no email, no payment. The token in `/sub/{token}`
  is a bearer string derived from a 128-bit random draw, not from a person.
* **No traffic.** The server never relays a packet, so nothing in the pipeline
  ever touches an end user's content.
* **Published honesty.** The payload headers and both landing surfaces state
  plainly that nodes are unverified third-party infrastructure and must be
  treated as hostile. This is the operator's main defence against a claim that
  users were misled about what they were using.

## Non-RU jurisdictions

**Unverified for 2026.** A hub publishing proxy configs in a jurisdiction that
criminalises such publication is a real risk, and the mitigations above do not
address it. Before exposing the domain publicly, an operator should check the
position for their own jurisdiction and consider: domain registration outside
their country, a hosting provider with a neutral abuse posture, and no
identifying information on the public pages.

## Operator duties, concretely

1. **Treat `data/` as non-public.** It contains third-party credentials. Firewall
   it; do not commit it; do not serve it from the web root. The nginx config in
   `deploy/` serves `/sub/` and blocks `/data/`.
2. **Honour abuse contacts.** The fetcher's User-Agent carries a reachable
   contact URL for exactly this reason — a node operator who objects to being
   listed should be able to say so, and a working removal path is worth more
   than any disclaimer.
3. **Keep the safety copy.** The `announce`/`landing`/bot triple warning users to
   treat nodes as hostile is not marketing. It must survive every future edit;
   `tests/test_api.py::test_landing_page_states_the_decentralised_positioning`
   asserts it.
4. **Do not add a "recommended" tier that implies vetting.** "Curated" means
   *measured*, not *endorsed*. The naming is deliberate and should not drift.
