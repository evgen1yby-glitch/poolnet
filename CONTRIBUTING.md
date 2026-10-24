# Contributing

## One rule

A change to behaviour needs a test that fails without it. Pin the property you
claim, not merely the implementation line.

## Before a pull request

```sh
python3 -m venv .venv
.venv/bin/pip install -e "./hub[dev]"
cd pool && npm ci && cd ..
make check RUFF=.venv/bin/ruff
```

The site smoke test is separate and runs in CI:

```sh
python3 scripts/site_smoke.py
```

## Context

- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Deployment and operations](docs/DEPLOY.md)
- [Audit and remaining plan](docs/AUDIT-2026-10-24.md)
- [Licensing](LICENSE) — `hub/` AGPL-3.0, `pool/` MIT, fonts OFL-1.1

Be precise about claims: numbers on the site must come from the current
publication, and generated lists belong in the `lists` branch, not `main`.
