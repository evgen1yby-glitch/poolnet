# VPN Hub Operations Runbook

This runbook describes the repository's intended deployment and the verified boundaries of the current IP-only installation. **Do not infer that a command has been run merely because it appears here.** Before any production change, compare the live system with this document and the source-controlled deployment files.

## 1. Service and network boundaries

The hub is a subscription control plane. It fetches public source lists, verifies third-party endpoints, and publishes static subscription payloads. It is not a VPN server and must not relay user traffic.

Production layout:

```text
Happ / client device
   | HTTPS :8444 (public; subscription and health endpoints)
   v
nginx dedicated hub vhost
   | HTTP to 127.0.0.1:8090 only
   v
hub API (read-only subscription service)

hub-worker: fetches public sources, no node probing
hub-probe: explicitly enabled node verification inside the existing hubns namespace
```

The host default route must never be changed for this service. Do not run a VPN client, change host routes, or route ordinary server traffic through indexed nodes. The probe namespace has a separate veth/NAT egress and makes limited direct outbound checks to third-party nodes; it is not an end-user tunnel. Keep the existing `hubns` configuration unchanged unless a separately reviewed network design requires otherwise. The server also hosts unrelated applications and a Marzban VPN project: preserve their ports, listeners, nginx vhosts, firewall rules, and routes.

The intended public listener is HTTPS `:8444`; the API port `:8090` must bind only to loopback and must not be allowed by UFW. Nginx on this shared host must not claim `:443` or alter unrelated vhosts. Review the active `/etc/nginx/conf.d/hub.conf` and systemd unit before applying anything from `deploy/`; repository templates do not automatically update the live system.

## 2. Secrets and repository hygiene

Keep runtime secrets outside Git, normally in `/etc/hub/hub.env` with restrictive permissions. Never commit `.hub-token`, bot/API secrets, private keys, certificates, runtime databases, subscription payloads containing credentials, or logs. The repository `.gitignore` excludes known local state; always review `git status --ignored`, staged files, and the staged diff before committing. Do not print tokens or complete subscription URIs in terminal output, issue trackers, documentation, or access logs.

Recommended secret setup (operator-managed):

```sh
sudo install -o root -g astrobot -m 0640 /dev/null /etc/hub/hub.env
sudoedit /etc/hub/hub.env
```

Store `HUB_TOKEN` and any bot credentials there only if needed. The Telegram bot is intentionally out of scope for the current IP-only test deployment; do not start or enable it as part of subscription testing.

## 3. Local development and safe verification

Use Python 3.11 or newer. Install dependencies in an isolated virtual environment and run only the hermetic tests by default:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python run_tests.py
# or: python -m pytest tests/ -q
ruff check src tests
```

The project's unit tests are designed not to open external sockets. Do not infer from them that a third-party node or Happ import works. Node probing is network activity and is not part of the normal test suite. Production probing may only be performed through the already-isolated `hub-probe.service`/`hubns` path and only with bounded settings. Never run `hub run --allow-network` directly on the host.

Before changing a live unit, firewall rule, or nginx file, record a read-only baseline of the hub listener, UFW rule set, active unit, current generation, TLS SAN/expiry, and health of neighboring applications. Validate the exact systemd unit and nginx configuration before reload. Roll back only the hub-specific file/rule that changed; do not reset UFW or reload with an unvalidated global config. If a safe rollback cannot be guaranteed, stop before deployment.

## 4. IP-only TLS and HTTPS publication

### State: issued and active

The hub origin `https://<HUB_HOST>:8444` serves a publicly trusted
Let's Encrypt certificate. It was issued on 2026-10-16 from the `shortlived`
profile into the dedicated lineage `hub-ip-<HUB_HOST-DASHED>` under the default
`/etc/letsencrypt` config directory, and the vhost was pointed at it after
`nginx -t` passed. The SAN is a `critical` `IP Address:` extension for the host.
extension; the chain is `YE2` → `Root YE` → `ISRG Root X2` and validates
against the ordinary system trust store, so `curl` succeeds without `-k`.

Renewal needs no new units. The pre-existing `certbot-le.timer` runs
`certbot renew` at 03:00 and 15:00 with the `certbot-le-nginx-reload` deploy
hook, which runs `nginx -t` and reloads nginx **only** on success. The timer
renews the default config directory, so this lineage is collected with the
domain lineages it already covers. Certbot 5.7 lives in `/opt/certbot-le`,
kept separate from the distro's certbot 2.9 — the 2.9 build predates
`--ip-address` and is left serving the domain lineages untouched.

Two consequences worth holding onto. First, IP certificates are short-lived by
policy (about 160 h / 7 days), so **the certificate expires in days, not
months** — a monitoring gap of a week is an outage, and renewal frequency is
not tunable. Second, the deploy hook reloads nginx for *every* vhost, so a
successful renewal touches the shared server; the `nginx -t` gate is what keeps
a bad state from reaching the other sites.

### Reissuing

```sh
# Staging dry-run first; it exercises the identical path without issuing.
sudo /opt/certbot-le/bin/certbot certonly --dry-run \
  --webroot -w /var/www/certbot --ip-address <HUB_HOST> \
  --preferred-profile shortlived --cert-name hub-ip-<HUB_HOST-DASHED> \
  --non-interactive --agree-tos --register-unsafely-without-email

# Issue for real, then confirm SAN and chain before trusting it.
sudo /opt/certbot-le/bin/certbot certonly \
  --webroot -w /var/www/certbot --ip-address <HUB_HOST> \
  --preferred-profile shortlived --cert-name hub-ip-<HUB_HOST-DASHED> \
  --non-interactive --agree-tos --register-unsafely-without-email
sudo openssl x509 -in /etc/letsencrypt/live/hub-ip-<HUB_HOST-DASHED>/cert.pem \
  -noout -subject -issuer -dates -ext subjectAltName

# Only after the SAN shows the exact IP and the chain validates:
sudo nginx -t && sudo systemctl reload nginx
openssl s_client -connect <HUB_HOST>:8444 -verify_ip <HUB_HOST> </dev/null
curl --fail --silent --show-error https://<HUB_HOST>:8444/healthz
```

Notes that change the outcome: use the default config directory so the existing
timer picks the lineage up — a separate `--config-dir` produces a certificate
that is valid but that nothing renews. Do not reuse an address-named lineage
such as one named after the address, which is really a domain certificate and
shares no identity with this one. After issuance, confirm the file paths in
`deploy/nginx-hub-8444.conf` match this lineage rather than assuming them.

Official references: [Let’s Encrypt IP and six-day certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability), [Certbot IP certificate instructions](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).

## 5. Firewall and service checks

Inspect these facts read-only:

```sh
sudo systemctl status hub-api.service hub-api-external.service nginx.service
sudo ss -ltnp
sudo ufw status numbered
sudo nginx -t
```

Verified state on this host (2026-10-16):

- `hub-api.service` listens only on `127.0.0.1:8090`; `hub-api-external.service`
  is stopped and disabled, and `deploy/run-external.sh` refuses to run.
- Public clients reach `:8444` over a trusted certificate (see section 4).
- Direct public access to `:8090` is closed: the two `8090/tcp` allow rules
  (IPv4 and IPv6) were deleted, and the port no longer answers from outside.
- `:8444` is allowed in UFW for IPv4 and IPv6. It was **not**, and that was the
  cause of a real outage: every check performed from the server itself passes
  without the rule, because traffic to the host's own address does not traverse
  the INPUT chain. The port answered locally and timed out for every external
  client. Verify reachability from outside the host, never only from it.
- `/metrics` returns 404 through the vhost (`location = /metrics { deny all }`).
- `/sub/...` is not logged: the location sets `access_log off`, and the vhost
  keeps a `hub_safe` format plus a URI map that redacts token-bearing paths
  anywhere else.
- Marzban on `:8443` and the neighbouring vhosts on `:443` were re-checked
  after the nginx reload and continued to answer 200.

Removing a UFW rule renumbers the ones after it. Confirm the current numbers
with `ufw status numbered` and delete only the exact 8090 entries; never remove
the `8443` rule or touch unrelated ports.

### Operator panel

`/admin` shows the pool, per-source health, the generation history, the
verification funnel and the issued token digests. It is for the operator, not
for visitors, and it is protected by two independent layers:

**nginx denies it at the edge.** The shipped vhost has
`location ^~ /admin { allow 127.0.0.1; deny all; }`. This is the layer that
matters and the reason it exists: through a vhost nginx *is* the socket peer, so
the application's loopback check passes for every visitor and would leave only
the shared secret protecting the panel.

**The application checks loopback and the secret.** `x-hub-secret` must equal
`HUB_BOT_SECRET` from `/etc/hub/hub.env`, and a request whose peer is not
loopback is refused even with the right secret. An unset secret closes the panel
rather than opening it — comparing two empty strings would otherwise succeed.

Reach it over an SSH tunnel, which arrives from loopback at both layers:

```sh
ssh -L 8090:127.0.0.1:8090 you@host
# then, on your machine:
#   curl -H "x-hub-secret: $(ssh you@host sudo sed -n 's/^HUB_BOT_SECRET=//p' /etc/hub/hub.env)" \
#        http://127.0.0.1:8090/admin/data
```

The panel deliberately shows **no traffic data**, because there is none to show:
the hub never carries it. It also shows only the first 12 characters of each
token digest — enough to tell two tokens apart when revoking one, not enough to
be useful to anyone reading the response.

## 6. Feed, health, and country shards

The publisher generates full subscription payloads and country-specific shards from measured exit countries. A country link exists only if the current generation contains a shard. Small country groups may be omitted by the renderer's minimum-count/cap policy; country counts in general statistics are not proof that a shard exists.

Check health and the current manifest before sharing a subscription. `/healthz` reports `stale` once the generation is older than `HUB_STALE_AFTER_HOURS` (default 7 h), which is one `hub-probe.timer` cycle (6 h) plus slack: under that rule `stale` means a scheduled probe round did not happen. Do not tighten it below the probe cadence — a threshold shorter than the cycle makes a healthy box permanently red, and a monitor that is always red is ignored. If the probe cadence changes, change `HUB_STALE_AFTER_HOURS` in `/etc/hub/hub.env` with it (and `tests/test_api.py::test_stale_threshold_is_longer_than_the_probe_cycle` will fail until the default matches the timer). Fetching sources does not refresh the verified generation; verification occurs on the separate probe schedule. Report the observed generation timestamp and health state rather than promising real-time availability.

The source list may contain formats that cannot become share URIs. In particular, OpenVPN/SoftEther provider data is not interchangeable with VLESS/VMess/Trojan/Shadowsocks URI feeds, and Cloudflare challenges may block automated retrieval. Do not fabricate proxy URIs or claim those upstreams contribute to a Happ feed unless their adapters produce supported, validated entries.

## 7. Happ test procedure (client-side only)

The intended candidate format is `format=base64`, which yields newline-delimited share URIs. This can be fetched and unit-tested locally, but actual Happ compatibility is not yet established by an HTTP 200 or by project tests. The protocol/client research document says Happ may interpret JSON through Xray-core; verify the exact Happ version and selected payload format on a dedicated client before declaring compatibility.

The preconditions below were all confirmed on 2026-10-16 before a link was
handed out; re-check the time-sensitive ones (1, 4) before reusing a link later.

1. The IP certificate is trusted and matches `<HUB_HOST>` — verified with
   `openssl s_client -verify_ip` against the system trust store.
2. External HTTPS reachability on `:8444` is confirmed — a plain `curl` returned 200.
3. The API is loopback-bound and public `:8090` access is closed — confirmed.
4. `/healthz` reports `ok` and the current generation contains the country shard.
   The generation is only as fresh as the last 6-hourly probe round.
5. Token paths are not logged — `/sub/` sets `access_log off`, and the one
   historical log that predated that was scrubbed.

Subscription URL pattern (insert the live operator token locally; do not commit or paste it into logs):

```text
https://<HUB_HOST>:8444/sub/<HUB_TOKEN>?format=base64
```

### What the endpoint returns, and why each part is there

`GET` and `HEAD` both answer on every subscription route. `HEAD` was previously
**405** (FastAPI does not register HEAD for `@app.get`), which made a probe of a
working link look like a broken one; it is now handled by rewriting the method
at the ASGI layer, so every route — default, tier, and country — is covered at
once and the body is dropped per RFC 9110.

| Header | Value | Why it matters |
| --- | --- | --- |
| `profile-title` | `hub <tier> (<core>)`, ≤25 chars | Shown as the profile name. Happ truncates at 25 characters, so a longer value is cut mid-word. |
| `subscription-userinfo` | `upload=0; download=0; total=0; expire=7258118400` | Hiddify drops the whole block unless **both** `total` and `expire` are present. `expire` is a real timestamp: `0` reads as 1970, i.e. already expired. |
| `profile-update-interval` | `6` | Integer hours; matches the probe cadence. |
| `profile-web-page-url` | the hub origin | Rendered as a tile by Hiddify, mihomo, Shadowrocket, Happ. |
| `support-url` | `<origin>/help` | A tappable tile, so `/help` is a **real route** — it previously 404'd while still being advertised. |
| `announce` | warning text | Happ renders up to 200 characters. |
| `content-disposition` | `attachment; filename="<tier>-<core>.<ext>"` | `.json` / `.txt` / `.yaml`, the extensions clients expect. |

Country codes with no shard return 404 with a body listing the codes that do
exist, so a client can stop retrying instead of treating it as a broken link.

### Happ: `?unique=1`, and why it exists

Happ cannot group. Its own developer documentation describes a subscription
body as a URI list or a JSON array and never mentions proxy groups, load
balancing, or automatic selection; it also passes a JSON config to the Xray
core 1:1, which is the Xray schema, not the sing-box one this project emits.
So the `urltest` grouping every other payload carries is invisible there, and a
flat list shows each node: four "🇫🇮 Финляндия" rows for four Finnish nodes.

`?unique=1` serves `{tier}-unique.base64` — one node per country, the
highest-scoring one, because the node list is already ranked. The result is a
list that *is* a country picker. Use it for Happ and for any client that
cannot group:

```text
https://<HUB_HOST>:8444/sub/<TOKEN>?format=base64&unique=1
```

A bare `?unique` counts as on. The flag is accepted on the base64 dialect
only: the JSON and YAML payloads keep their groups deliberately, because a
client that understands them fails over *within* a country — strictly better
than a single pinned node — and removing that to make the lists look alike
would trade a real capability for an appearance.

**What is lost, stated plainly:** with one node per country there is no
automatic re-selection. If that node dies the user must pick another country,
or re-import. That is a property of the client, not something this endpoint
can supply — the server cannot re-point a connection it is not carrying.

Country URL pattern:

```text
https://<HUB_HOST>:8444/sub/<HUB_TOKEN>/country/FR?format=base64
```

Replace `FR` only with a country code present in the current generation. In the
generation published 2026-10-16T10:24:59Z (`gen-d8455bbecc6e`) the shards are
`FI, FR, US, DE, PL, TR`; a 404 for any other code is expected, and the 404 body
lists what does exist. That set is not a promise about a later generation — the
country mix follows whatever the 6-hourly probe finds, and the renderer omits
groups below its minimum count. A country with the lowest counts (2–4 nodes in
that generation) is the most likely to disappear first.

Test each country by importing the matching URL in Happ on the user's
phone/computer, then checking the client's displayed exit IP/country. A real
connection test must occur on that client device. Do not initiate the VPN on the
server, change the server's default route, or use server traffic as a VPN
tunnel. The hub only serves the subscription; it does not carry the client's
traffic.

## 8. Troubleshooting and rollback

- **TLS trust error:** check `openssl s_client` output, IP SAN, chain, expiry, renewal logs, and active nginx certificate paths. Do not use `curl -k` as the success criterion.
- **Connection refused/time-out on 8444:** inspect listener, UFW, upstream, and external network reachability. Do not expose port 8090 as a workaround.
- **404 for a country:** inspect the active generation manifest and filenames; the shard may not exist or have been omitted by the minimum-count policy.
- **Stale feed:** inspect worker/probe timer history and namespace health. Do not launch an unisolated probe.
- **Nginx change fails validation:** do not reload. Restore the saved hub-specific config and rerun `nginx -t` before any reload.
- **API change fails:** restore the hub-specific service file, reload systemd, and verify the previous process and neighbor services. Keep 8090 closed publicly; do not roll back by restoring the insecure public API listener.

## 9. Known limitations

- Public free proxy endpoints are untrusted third parties. Never send personal credentials through them.
- Happ compatibility and actual country egress must be confirmed by client-side import/connection testing.
- Bot tokens are outside the current deployment scope; the existing bot path must not be treated as a secure per-user issuance workflow.
- No client-side VPN test has been performed by this runbook. No promise of per-country connectivity should be made until verified from the client's network.
