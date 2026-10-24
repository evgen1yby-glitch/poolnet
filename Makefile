# PoolNet — repo-wide development entry points.
.PHONY: test lint site check help

# CI pins ruff 0.6.9 (hub/pyproject.toml `[project.optional-dependencies].dev`).
# Never let a newer system ruff silently apply new rules to the frozen baseline.
RUFF_VERSION := 0.6.9
RUFF ?= python3 -m ruff

# Hub pytest, then pool unit tests. The pool pattern is explicit because
# `/bin/sh` does not expand `**`; `test/*.test.ts` is flat and safe.
test:
	cd hub && python3 -m pytest -p no:cacheprovider
	cd pool && node --import tsx --test test/*.test.ts

# Hub ruff (exact version), then pool typecheck and lint. Install the pinned
# tool with `pip install -e "./hub[dev]"`, or point RUFF at a venv:
#   make lint RUFF=.venv/bin/ruff
lint:
	@version="$$($(RUFF) --version 2>/dev/null | awk '{print $$2}')"; \
	if [ "$$version" != "$(RUFF_VERSION)" ]; then \
		echo "ruff $(RUFF_VERSION) required, found '$$version'."; \
		echo "Install the CI toolchain: python3 -m venv .venv && .venv/bin/pip install -e './hub[dev]'"; \
		echo "Then run: make lint RUFF=.venv/bin/ruff"; \
		exit 1; \
	fi
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
	@echo "  test   hub pytest + pool node:test"
	@echo "  lint   hub ruff $(RUFF_VERSION) + pool typecheck/lint"
	@echo "  site   web/site linkcheck"
	@echo "  check  lint + test + site"
	@echo "  help   this list"
	@echo ""
	@echo "RUFF override: make lint RUFF=.venv/bin/ruff (must be $(RUFF_VERSION))"
