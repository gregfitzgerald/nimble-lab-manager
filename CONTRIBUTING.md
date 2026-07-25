# Contributing

Nimble Lab Manager is a portfolio project, but it is set up to be worked on like
a real codebase. This is the short version; see `FRAMEWORK.md` for the
architecture and data model.

## Setup

No build step, no npm, no CDN. You need Python 3.10+.

```
python3 run.py          # bootstraps a local .venv, installs deps, starts the server
# then open http://127.0.0.1:8770  (or use start-nimble.bat on Windows)
```

Auth is on by default (demo logins `admin/admin`, `manager/manager`,
`member/member`, `viewer/viewer`). Set `NLM_AUTH=off` to run the open demo that
auto-logs-in as an admin.

## Common tasks

Use the `Makefile`:

```
make help          # list tasks
make run           # start the server
make test          # full suite (unit + security + fuzz + e2e/a11y + concurrency)
make test-fast     # unit + security only (skips the slow fuzz/e2e)
make lint          # ruff
make format        # ruff --fix + ruff format
make reset         # rebuild the dev DB from schema.sql + seed.sql
```

## Conventions

- Backend: FastAPI + SQLite, every query parameterised, mutations audited. Keep
  stock changes on the atomic guarded-`UPDATE` pattern (see `consume_item`) so
  concurrency can never oversell -- there is a test that enforces this.
- Frontend: buildless vanilla-JS ES modules in `web/js/`. Each view exports
  `view = {id, label, minRole}` and `render(root, ctx, params)`; no imports
  between view modules. Spartan Web 1.0 styling -- reuse the CSS tokens/classes,
  and use colour only to signal problems. Escape server text with
  `textContent`/`el(...)`, never `innerHTML`.
- Tests: add unit tests for new endpoints (role-gating + behaviour). Run
  `make lint` and `make test-fast` before opening a PR; CI runs the full matrix
  including OpenAPI fuzzing (Schemathesis) and accessibility (axe-core).

## Adding a feature

1. Schema in `schema.sql` (+ seed data in `seed.sql` and `generate_data.py`).
2. Endpoints in `app/api.py` (role-gate + `_audit`).
3. A view module in `web/js/`, registered in `web/js/app.js`.
4. Tests. Keep `ruff check .` clean and the suite green.
