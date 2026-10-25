<p align="center"><img src="web/site/assets/logo-96.png" width="96" alt="PoolNet"></p>

<h1 align="center">PoolNet</h1>

<p align="center"><a href="README.md">Русский</a> · English</p>

<p align="center"><strong>Open VPN and proxy lists verified with real connections.</strong><br>
Updated every 15 minutes · free 7-day key · no account required</p>

<p align="center">
  <a href="https://poolnet.online"><img src="https://img.shields.io/badge/site-poolnet.online-7c5cff" alt="site"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/tree/lists"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/badges/alive.json" alt="proxies"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/tree/lists"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/badges/verified.json" alt="VPN nodes"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/actions"><img src="https://github.com/evgen1yby-glitch/poolnet/actions/workflows/lists.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0%20%2B%20MIT-blue" alt="license"></a>
</p>

<p align="center"><a href="https://poolnet.online"><img src="docs/screenshots/home.webp" width="92%" alt="PoolNet home page"></a></p>

## What is this?

PoolNet is a public catalog of two pools sharing one verification engine:

- **Proxies** — HTTP, SOCKS4 and SOCKS5. Reachability, exit IP, latency and
  uptime are measured with a full request through the proxy, not a ping.
- **VPN** — VLESS, Shadowsocks, VMess and Trojan. A node must pass TCP → TLS →
  a raised client configuration → an end-to-end HTTP request to be published.
- **Free key** — a personal 7-day subscription without Telegram or payment.

Traffic goes **directly from the client to the node**. PoolNet is not the
operator, does not relay traffic and does not guarantee third-party
infrastructure. Treat every published node as untrusted.

## Automatic lists

The [`lists`](https://github.com/evgen1yby-glitch/poolnet/tree/lists) branch is
refreshed automatically every 15 minutes from the live verified snapshot.
Add a URL to your client as a subscription.

| Data | URL |
| --- | --- |
| All proxies | [pool/all.txt](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/all.txt) |
| HTTP / SOCKS5 / SOCKS4 | [HTTP](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/http.txt) · [SOCKS5](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/socks5.txt) · [SOCKS4](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/socks4.txt) |
| JSON with exit IP, ASN, country, uptime | [proxies.json](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/proxies.json) |
| VPN for Happ / Hiddify / sing-box | [verified-sing-box.base64](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-sing-box.base64) |
| VPN for Xray / v2rayNG | [verified-xray.base64](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-xray.base64) |
| Clash / mihomo | [verified-sing-box.clash](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-sing-box.clash) |

The branch is a snapshot, not a personal key: it has no subscription term.
For a personal 7-day key use [poolnet.online/free](https://poolnet.online/free).

## Screenshots

| Proxy pool | VPN |
| --- | --- |
| <img src="docs/screenshots/proxy.webp" alt="Proxy pool" width="100%"> | <img src="docs/screenshots/vpn.webp" alt="VPN" width="100%"> |
| <img src="docs/screenshots/free.webp" alt="Free key" width="100%"> | <img src="docs/screenshots/mobile-proxy.webp" alt="Mobile" width="58%"> |

## Quick start

```sh
curl -s https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/all.txt | head
curl -s https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/proxies.json | jq '.proxies[0]'
```

Run your own instance:

```sh
pip install -e "./hub[dev]"
cd pool && npm ci && cd ..
HUB_SITE=web/site POOLNET_POOL_DIR=pool/data python3 -m hub serve --port 8090
```

## How verification works

**VPN:** source → protocol parser → TCP → TLS → raised configuration →
end-to-end HTTP. A failure at any stage means the node is not published.
**Proxy:** CONNECT tunnel → forwarding nonce → exit IP and headers →
anonymity/latency. Publication rejects records without a proven exit IP and
records whose exit IP is the checker itself.

More: [methodology](https://poolnet.online/verify) and
[architecture](docs/ARCHITECTURE.md).

## Repository

| Path | Purpose | License |
| --- | --- | --- |
| `web/site/` | bilingual site: pools, verification, free key, status | AGPL-3.0 |
| `hub/` | VPN pool: collection, 6-stage checks, subscriptions, bot, APIs | AGPL-3.0 |
| `pool/` | proxy pool: sources, checks, benchmark, JSON/TXT publication | MIT |
| `docs/` | architecture, deployment, audit, third-party notices | — |

## Contributing

Before a PR: `make check RUFF=.venv/bin/ruff` and
`python3 scripts/site_smoke.py`. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).

If this project is useful, a star helps other people find it and signals that
the open data is worth maintaining.

## License

`hub/` and the site are **AGPL-3.0-or-later**; `pool/` is **MIT**; fonts are
**OFL-1.1**. See [LICENSE](LICENSE), [NOTICE](NOTICE) and
[docs/THIRD-PARTY.md](docs/THIRD-PARTY.md).
