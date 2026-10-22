# Contributing

Thanks for helping the pool stay fresh. Two kinds of contributions matter
most: **new sources** and **parser fixes**.

## Add a source

Open a PR that appends to `sources.yaml`:

```yaml
- id: my-source-socks5
  url: https://example.com/list.txt
  format: plain # plain | json
  protocol: socks5 # only used when a line has no scheme
```

Requirements:

- The list is published by someone else (GitHub raw file, scraper API,
  proxy directory). Do not propose scanners or anything that mass-probes the
  network — this project only consumes already-published lists.
- It yields **≥ 50 parsable entries**. The discover workflow enforces the
  same threshold when it files candidates.
- Supported shapes: plain text lines (`ip:port`, `http://ip:port`,
  `socks5://user:pass@ip:port`) or a geonode-style JSON API
  (`{"data": [{"ip": ..., "port": ..., "protocols": [...]}]}`).
- Prefer sources that update at least hourly and carry no tracking pixels,
  paywalls or JS-rendered pages (we fetch with a plain HTTP GET).

A PR that disables a dead source (`enabled: false`) is as welcome as one that
adds a source; both are verified by the next pipeline run.

## Development

```bash
npm ci
npm run typecheck   # tsc --noEmit
npm test            # node:test, includes local SOCKS5/echo mocks
npx tsx src/index.ts cycle   # end-to-end run against live sources
```

When you touch parsing or checking, add a regression test first: the
historic bug that dropped every `scheme://` line (zeroing whole sources) is
guarded by `test/parse.test.ts`.

## Commit style

Conventional commits (`feat:`, `fix:`, `data:` for pipeline runs, `chore:`).
Keep commits focused; `data/` changes are generated, not hand-edited.

## License

Contributions are accepted under the [MIT License](LICENSE).
