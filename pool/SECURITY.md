# Security policy & abuse reports

## Reporting abuse

To request removal of an address, or to report content the pipeline touched
that concerns you, email **abuse@your-domain.example** with the affected
`proto://host:port` entries and a short description. Requests are handled
manually; the goal is to act within a few business days.

Because the pool is regenerated from sources on every cycle, take-down is
implemented by disabling the offending entries, either through a per-source
`enabled: false` flag in `sources.yaml` or by adding the entries to the
deny list referenced from `docs/operations.md`.

## Reporting vulnerabilities in the pipeline

Security issues in the tooling (not the proxies themselves) are welcome at
the same address. Please don't open public issues for anything that could
affect unattended CI runners.

## Design notes relevant to safety

- **Validation traffic only ever leaves GitHub-hosted runners.** No
  operator-owned server or address is used to connect to the proxies, and
  nothing about the checking process touches personal infrastructure.
- **No port scanning.** The pipeline only fetches URLs that are already
  published as lists; candidate volumes stay in the range of normal HTTP
  client behaviour, and every source is fetched at most once per cycle with
  a contact-bearing User-Agent.
- **Untrusted responses.** Proxy responses are parsed for a status line and
  a bounded body; nothing is executed, and nothing is forwarded. The TLS
  MITM detection exists because a meaningful share of open proxies
  terminate TLS themselves — that fact is published in `data/proxies.json`
  (`tls_mitm`) so consumers can avoid them.
