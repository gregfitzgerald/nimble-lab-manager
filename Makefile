# Nimble Lab Manager -- common developer tasks.
# The app is buildless (no npm); Python deps live in a local .venv managed by run.py.
# On hosts without ensurepip, prefer `python3 run.py` which bootstraps the venv.

PY ?= .venv/bin/python

.PHONY: help run run-empty test test-fast fuzz e2e a11y concurrency lint format data demo reset

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

run:  ## Launch the server (http://127.0.0.1:8770) with the demo lab + demo logins
	NLM_SEED_DEMO=1 $(PY) -m uvicorn app.server:app --host 127.0.0.1 --port 8770

run-empty:  ## Launch as a real deployment would: empty DB, bootstrapped admin, no demo
	$(PY) -m uvicorn app.server:app --host 127.0.0.1 --port 8770

test:  ## Full test suite (unit + security + fuzz + e2e/a11y + concurrency)
	$(PY) -m pytest -q

test-fast:  ## Unit + security only (skip the slow fuzz/e2e)
	$(PY) -m pytest -q --ignore=tests/test_fuzz.py --ignore=tests/e2e

fuzz:  ## Schemathesis OpenAPI property/fuzz testing
	$(PY) -m pytest tests/test_fuzz.py -q

e2e:  ## Playwright end-to-end smoke suite
	python3 -m pytest tests/e2e/test_smoke_e2e.py -q

a11y:  ## axe-core accessibility audit
	python3 -m pytest tests/e2e/test_a11y.py -q

concurrency:  ## Concurrency stress test (proves the atomic stock guards)
	$(PY) -m pytest tests/test_concurrency.py -q

lint:  ## Lint the Python code with ruff
	python3 -m ruff check .

format:  ## Auto-format / auto-fix with ruff
	python3 -m ruff check --fix . && python3 -m ruff format .

data:  ## Regenerate a demo database (small preset)
	$(PY) generate_data.py --preset small --seed 1 --db lab.db --force

demo:  ## Build a demo DB with the real molecular-biology catalog (+2000 bulk rows)
	$(PY) generate_data.py --preset core --molbio --catalog 2000 --seed 1 --db lab.db --force
	@echo "Demo catalog loaded. Run 'make run' (or python3 run.py) and open Inventory > Catalog."

reset:  ## Rebuild the dev database from schema.sql + seed.sql
	$(PY) -c "import app.db as d; d.init_db(force=True); print('reset', d.DB_PATH)"
