# Using the pool

Everything is plain files over HTTP. Pick the language you already use;
no SDK, no keys, no account.

## curl

```bash
# every working proxy, best quality first
curl -s https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/all.txt | head -20

# one protocol only
curl -s https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/socks5.txt

# one country
curl -s https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/country/US.txt

# full metadata (grade, latency, uptime, exit IP, network)
curl -s https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/proxies.json | jq '.proxies[0]'

# pool statistics
curl -s https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/stats.json | jq '.total'
```

Test one proxy through a real endpoint:

```bash
curl -s --max-time 12 -x socks5h://1.2.3.4:1080 https://api.ipify.org
```

The files also exist verbatim in the repository under `data/`, so a plain
`git clone` is enough when you want the exact snapshots with history.

## Python

```python
import json, urllib.request

pool = json.load(urllib.request.urlopen(
    "https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/proxies.json"
))["proxies"]

elite = [p for p in pool if p["anonymity"] == "elite"]
print(f"{len(elite)} elite proxies, median latency {pool[0]['latency_ms']} ms")
```

A working rotator that re-tests candidates and caches the survivors lives in
[`examples/rotate.py`](../examples/rotate.py); shell and Node variants sit next to it
([`first_10.sh`](../examples/first_10.sh), [`rotate.mjs`](../examples/rotate.mjs)):

```bash
python3 examples/rotate.py          # prints and caches the elite set
python3 examples/rotate.py https://api.ipify.org 20
```

## Node

```js
const pool = await fetch('https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data/proxies.json').then((r) => r.json());

const fast = pool.proxies.filter((p) => p.latency_ms < 800 && !p.tls_mitm);
console.log(
  fast
    .slice(0, 10)
    .map((p) => `${p.protocol}://${p.host}:${p.port}`)
    .join('\n'),
);
```

## A note on expectations

A public proxy is a stranger's machine. Free pools behave like one:

- **Measure, then rely.** Entries die within minutes; re-check right before
  use, and treat `anonymity: "transparent"` as leaking your address.
- **No credentials, no payments, no personal data** through any entry.
- **`tls_mitm: true`** means the proxy terminates TLS itself — fine for a
  throwaway lookup, useless for anything real.
- Throughput is a lottery: the median latency in the pool is in the seconds,
  not milliseconds.

If you need reliability, this pool is a benchmark to compare against, not a
replacement for a paid provider.
