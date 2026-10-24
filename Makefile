# PoolNet — repo-wide development entry points.
.PHONY: test lint site check help

# Hub pytest, then pool unit tests.
test:
	cd hub && python3 -m pytest -p no:cacheprovider
	cd pool && npm test

# Hub ruff, then pool typecheck and lint. `RUFF` is overridable so a
# developer whose PATH has a newer ruff (new default rules) can point it at
# the pinned 0.6.9 venv: `make lint RUFF=.venv/bin/ruff`.
RUFF ?= ruff

lint:
	cd hub && $(RUFF) check src tests
	cd pool && npm run typecheck && npm run lint

# Public site linkcheck (web/site).
site:
	python3 scripts/site_links.py

# Everything CI gates on.
check: lint test site

# List available targets.
help:
	@echo "targets:"
	@echo "  test   hub pytest + pool npm test"
	@echo "  lint   hub ruff + pool typecheck/lint"
	@echo "  site   web/site linkcheck"
	@echo "  check  lint + test + site"
	@echo "  help   this list"
