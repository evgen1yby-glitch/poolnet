# Research addendum: protocols, clients, headers (2026-10-14)

Appended to `2026-10-14-subscription-hub-research.md` after the final research agent
completed. These facts directly constrain the parser and renderer implementations.

---

## 12. Protocol landscape for a RU/СНГ-targeted pool

| Protocol | Status | Censorship resistance (RU) | Share of free pool |
|---|---|---|---|
| **VLESS + REALITY (+`xtls-rprx-vision`)** | Stable, **de-facto gold standard** | Best available. Masquerades as a real TLS handshake; resistant to active probing | **~75.5%** |
| VLESS + XHTTP | Experimental | Better than WS (full CDN compat), but client and server must be the same Xray version | small, growing |
| **Trojan** | Stable but **compromised** | ~90% detected since the Aug 2025 GFW upgrade used active probing | ~9.4% |
| **Hysteria2** | Stable | QUIC/UDP bypasses TCP filters; `obfs=salamander`; vulnerable to UDP/CGNAT throttling | ~2.0% |
| **Shadowsocks-2022** | Stable | Predictable AEAD structure; **~95% detected in RU** | ~5.4% |
| **WireGuard / WARP** | Stable (WG) | **~100% blocked in RU** — statistical analysis → throttling mid-2024 → full blocking | ~0.3% |
| VMess + WS | **Deprecated in Xray 26.x** | ~80% detected (Sep 2025), packet timing + size distribution inside TLS | ~7.0% |
| ShadowTLS v3 | **Dead** | Broken by Aparecium: 4-byte HMAC tainting detectable via ServerFinished length | negligible |

Verified RU blocking timeline: OpenVPN/WG ~100% (2024) → SS ~95% (Sep 2024) → Trojan ~90%
(Aug 2025) → VMess ~80% (Sep 2025) → **TSPU began actively interfering with VLESS+TLS
handshakes late 2025** → plain VLESS stopped working late 2025 → VLESS+TCP+Reality degraded
May 2026 → from ~5 Jun 2026 **v2rayN VLESS+Reality fails from RU region unless the core is
switched to sing-box**.

**Two critical design consequences:**

1. **REALITY is not permanent either.** Aparecium demonstrated a NewSessionTicket vector
   partially applicable to REALITY, and post-handshake detection is an open discussion in
   Xray-core. → **Design for config rotation, not "set it and forget it".**
2. **`client-core` is a first-class render parameter.** Upstream sing-box **does not support
   XHTTP** (maintainer declined, SagerNet/sing-box#3550); Xray-core does. A config that
   lists XHTTP nodes as "sing-box compatible" is dead-on-arrival for SFA/Hiddify on the
   upstream core. → The renderer must know which core the client will use and drop nodes
   the core cannot speak.

### `client-core` compatibility matrix (MVP scope)

| Protocol | Xray-core | sing-box upstream | mihomo |
|---|---|---|---|
| VLESS + REALITY + Vision | yes | yes | yes |
| VLESS + XHTTP | yes | **no** | yes |
| Trojan | yes (deprecated-ish) | yes | yes |
| Hysteria2 | **no** | yes | yes |
| Shadowsocks-2022 | yes | yes | yes |
| VMess | yes | yes | yes |
| TUIC | no | yes | yes |

---

## 13. Client matrix (who displays what)

| Client | Platforms | Accepts | Subscription headers | Deep link |
|---|---|---|---|---|
| **sing-box official** 1.14.3 | Android/iOS/macOS/tvOS | sing-box JSON only | `profile-title` via `#fragment` only; **no `subscription-userinfo`** | `sing-box://import-remote-profile?url=<URLENC>#<NAMEENC>` |
| **Hiddify** v4.1.1 | all desktop + mobile | JSON, Clash YAML, base64, single URIs | **full set**, incl. inline `#`-headers in first 10 lines | `hiddify://import/<url-or-uri>#<name>` |
| **v2rayNG** 2.3.11 | Android | base64 + single URIs | **NONE** (all three header tickets closed as "no such plan") | `v2rayng://install-sub?url=<URLENC>#<NAME>` |
| **v2rayN** 7.25.6 | Windows/Linux/macOS | base64, sing-box JSON, Clash partial | full set | `v2rayn://install-sub?url=<URLENC>` |
| **NekoBox** 1.4.2 (semi-abandoned, core pinned 1.12) | Android arm64 | **outbounds only** — routing ignored | `content-disposition` only | `nekobox://install-sub?url=<URLENC>` |
| **Karing** v1.2.26 | all | all three major formats | `subscription-userinfo` + `isp-name`/`isp-url`/`isp-faq`; sends `x-hwid` | `karing://install-config?url=&name=&isp-name=&isp-url=&isp-faq=&outbound-dns=` |
| **FlClash** v0.9.0 | Android/Win/mac/Linux (**no iOS**) | **Clash/mihomo YAML only** | `subscription-userinfo`, `content-disposition` | `clash://install-config?url=<URLENC>` |
| **Clash Meta / mihomo** 1.19.32 | all | Clash YAML (native) | full set | `cmfa://install-config?url=<URLENC>` |
| **Shadowrocket** | iOS/macOS | base64, Clash partial | full set | `sub://<BASE64(url)>#<URLENC_REMARK>` |
| **Streisand** | iOS/macOS | all three | undocumented | `streisand://import/<URLENC>` |
| **Happ** v26.9.9 | **widest incl. Android/Linux** | VLESS(Reality)/VMess/Trojan/SS/Socks/Hy2; **JSON passed to Xray-core 1:1** | **richest set** | `happ://add` |

---

## 14. Header spec (de-facto standard: XTLS/Xray-core discussion #4877)

| Header | Value | Displayed by | Notes |
|---|---|---|---|
| `profile-title` | plain or `base64:<b64-of-utf8>`; literal `NULL` = client's choice | Hiddify, v2rayN, mihomo, Shadowrocket, Happ | **not v2rayNG**. Happ limits to 25 chars |
| `content-disposition` | `attachment; filename="x"`; UTF-8: `attachment;filename=UTF-8''%D1%82...` | all except v2rayNG | extension `.txt/.yaml/.yml/.json` is stripped |
| `profile-update-interval` | **integer hours** (e.g. `1`) | Hiddify, v2rayN, mihomo, Shadowrocket, Happ | **not v2rayNG** |
| `subscription-userinfo` | `upload=<b>; download=<b>; total=<b>; expire=<unix_ts>` | Hiddify, v2rayN, mihomo, Karing, FlClash, Shadowrocket, Happ | **not v2rayNG**. `expire=0` is a **real timestamp** (1970), not "unlimited" |
| `profile-web-page-url` | URL | Hiddify, v2rayN, mihomo, Shadowrocket, Happ | not FlClash/Karing |
| `support-url` | URL | Hiddify, v2rayN, mihomo, Shadowrocket, Happ | |
| `announce` | text (Happ: **max 200 chars**) | Happ, v2rayTun | `announce` ≠ `announce-url` |
| `isp-name`/`isp-url`/`isp-faq` | urlencode-required | Karing | values **must** be `urlencode()`d |
| `moved-permanently-to` | URL | Hiddify | rewrite subscription URL — **domain-block resistance** |

**Inline body headers** (when HTTP headers are impossible — e.g. GitHub Pages or a static
nginx path): Hiddify parses the **first 10 lines** prefixed `#` (text/YAML) or `//` (JSON).
Happ and INCY do similar. HTTP headers always take precedence.

```
#profile-title: base64:SSDinaTvuusz...
#profile-update-interval: 1
#subscription-userinfo: upload=0; download=0; total=0; expire=0
#profile-web-page-url: https://...
```

### Traps that break naive generators

| Trap | Detail |
|---|---|
| **`interval` type differs** | sing-box `"interval": "10m"` (Go duration) vs mihomo `interval: 300` (int seconds). Emitting `3m` into Clash YAML is silently ignored; emitting `300` into sing-box JSON fails validation. |
| **Duplicate tags are fatal** | sing-box: `FATAL start service: outbound tag proxy duplicated`. mihomo: duplicate `proxies[].name` illegal, and its auto `-01` suffixing itself collided (#2931). **Server must mint globally unique tags.** |
| **`allowInsecure` removed** | In Xray 26.x it is a **hard failure** since 2026-06-01. Replacement: `pinnedPeerCertSha256` / `verifyPeerCertByName`. |
| **Hiddify drops the whole `subscription-userinfo` block** if the panel does not return **both** `total` and `expire` — and then also skips `support-url` / `profile-web-page-url` tiles (#2242). Always send both; use a large number for "unlimited". |
| **Hiddify needs HTTP headers** | v2rayNG shows none of them, so headers are a UX bonus for Hiddify/Karing/mihomo — **never a control mechanism**. |
| **Karing caches a static tag snapshot inside urltest groups** (#2008, still open) → after a subscription rotation the group must be deleted and rebuilt. → **server-side ordering only**. |
| **Clash Verge Rev hides all headers unless the request `User-Agent` contains `clash`** | → the renderer must be able to serve both dialects; add a `global-ua`-friendly path. |
| **sing-box 1.14.0 broke v2rayN** (`require match_response`, `independent_cache` removed) — clients bring their own core, so **we cannot pin the core version**. Test configs against 1.13.x and 1.14.x. |
| **`type: relay` does not exist in mihomo** — only `select`/`url-test`/`fallback`/`load-balance`; chaining uses `dialer-proxy`. |
| **mihomo url-test does not follow `use:`** — health-check only covers the `proxies` list, not nodes pulled from proxy-providers. |
| **v2rayN base64 decode throws on HTML responses** (captive portal/4xx) → empty or partial node list. |
| **v2rayN duplicate query keys** resolve first-wins, OrdinalIgnoreCase; the URI parser splits on the **first** `=` only. |
| **v2rayN strict "no skip bad line"** — one malformed URI aborts the whole import (#5670, #5299). → validate every URI before emit. |
| **1k+ line subscriptions freeze v2rayNG import** (#2165); Karing import UI freezes likewise → **chunk to ≤200 nodes**. |
| **`experimental.cache_file.cache_id` must change when the node set changes**, else FakeIP/DNS cache points at dead IPs (FlClash #734, stale nodes after update). |

---

## 15. Recommended client config skeleton (sing-box)

Key decisions with rationale:

- **`urltest.interval: "10m"`, not the default `3m`.** With 50 nodes and `idle_timeout: 30m`,
  3-minute intervals mean ~17 full cycles/hour per node — this is exactly what makes clients
  sluggish on large lists.
- **`tolerance: 150`, not 50.** At 50 ms, micro-jitter flips the outbound and breaks
  long-lived connections (Google/ChatGPT re-logins, video-call drops).
- **`interrupt_exist_connections: false`**, explicit.
- **`download_detour: "direct"` on every `rule_set`** — otherwise rule-set loading goes
  through the proxy and can deadlock at startup.
- **`dns_address: 198.18.0.2`** — the benchmark-reserved range, not routable.
- **Anti-leak:** DoH server via `detour: "auto"`, local resolver direct.
- **Route rule order:** `sniff` → `hijack-dns` → DNS-out → private direct → `geoip-ru`/`geosite-ru`
  direct → `resolve` → proxy. Inverting (proxy before sniff) breaks domain detection.
- `stack` is deprecated in 1.15 (removal in 1.17) — omit for new configs.
- `independent_cache` is deprecated; DNS persistence now via `store_dns`.

Full skeleton in session notes; to be emitted by `render` with:
`interval: "10m"`, `tolerance: 150`, `idle_timeout: "30m"`, chunked to ≤200 nodes per payload.

---

## 16. Verdict: what a naive implementer gets wrong (consolidated top-10)

1. Upstream sing-box does **not** support XHTTP → an `sing-box`-format payload containing
   XHTTP nodes is dead for official clients. → renderer needs a `client_core` parameter.
2. v2rayNG displays **zero** subscription headers → headers are UX, never control.
3. `v2rayng://install-sub?url=` registers the group but never fetches it (closed "not
   planned"); `&name=` doesn't work, the name comes from the `#NAME` fragment, and the URL
   must be percent-encoded.
4. Shadowrocket `sub://` payload is base64 of the URL and **must not** be percent-encoded
   (3x-ui double-encoded it and had to revert: commit 990bca1, issue #4441).
5. Hiddify discards the entire `subscription-userinfo` block unless **both** `total` and
   `expire` are present — and then also drops `support-url`/`profile-web-page-url`.
6. Karing's static urltest tag snapshot (#2008) → client-side groups are useless under
   rotation; **server-side ordering only**.
7. sing-box 1.14.0 breaks v2rayN and we can't pin the client's core → test against 1.13 and 1.14.
8. Duplicate outbound tags are a hard `FATAL` in sing-box and illegal in mihomo → mint tags
   server-side.
9. In RU everything but VLESS+Reality is effectively dead — and REALITY itself is under
   active research (NST vector, post-handshake detection) → **design for config rotation**.
10. Clash Verge Rev withholds all headers unless UA contains `clash` → serve both dialects.
