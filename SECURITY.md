# Security policy

PoolNet is a catalog and verification service, not a VPN operator: published
nodes are third-party infrastructure, traffic goes directly from the client to
the node, and no guarantee is possible.

## Reporting

Do not open a public issue for a vulnerability that exposes tokens, the admin
panel, SSRF, or user data. Send a private report through GitHub's **Security →
Report a vulnerability** form for this repository. Include the affected URL or
commit, reproduction steps, and impact. Please allow reasonable time for a fix
before disclosure.

## Scope

- `https://poolnet.online` — API, free-key issuance, admin boundary, `/pool/*`,
  `/vpn/*` snapshots;
- `hub/` — SSRF checks, subscription tokens, publication, bot endpoints;
- `pool/` — proxy verification and publication.

Out of scope: the safety or honesty of third-party proxy/VPN nodes themselves;
the project publishes them as untrusted and warns users not to send sensitive
traffic through them.

## Operational expectations

Secrets live only in `/etc/poolnet/*.env` (mode 640, root:poolnet). Never paste
private keys, tokens, or `.env` contents into an issue, a workflow, or a commit.
See [docs/DEPLOY.md](docs/DEPLOY.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
