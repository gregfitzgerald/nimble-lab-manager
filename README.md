# Nimble Lab Manager

**A map-first inventory and operations platform for a working wet lab -- built to
showcase full-stack engineering and data modelling, and it runs fully offline.**

Nimble Lab Manager answers the question that eats the most time at the bench:
*where is the thing, and is it still good?* Spreadsheets tell you a reagent
exists and roughly how many you have -- but not which shelf of which freezer,
which box, which well -- so people re-buy things they own, thaw expired lots, and
lose an afternoon hunting for a tube misfiled two racks over. This app treats
physical location as a first-class part of the record: it draws the lab as a
clickable schematic down to the individual freezer-box grid, flags what is
expiring or already expired, detects containers sitting in the wrong well, and
forecasts what you are about to run out of. It has since grown past the map into
a fairly complete lab-operations suite -- inventory and lot/expiry tracking,
spatial maps, purchasing with PI approvals, grant-budget burn-down, equipment
booking and maintenance, a controlled-substance register, safety/compatibility
checking, analytics, and an interactive tutorial. It is a portfolio proof-of-concept
built by a former lab manager on a domain I ran for five years, not a toy dataset.

Buildless by design: no npm, no bundler, no CDN, no front-end framework. Clone
and run one command, and the app itself works with the network unplugged. (The
one exception is the interactive `/docs` API explorer, which is FastAPI's stock
Swagger UI and loads its assets from a CDN.)

### Walkthrough

A guided tour of the app: dashboard, inventory and lot detail, the map drilling
into a freezer's contents, purchasing approvals, grant burn-down, safety
conflicts, analytics, kits, the interactive tutorial, and the live alerts feed.

![Nimble Lab Manager walkthrough](docs/walkthrough.gif)

## Screenshots

**Dashboard** -- command center: stock, expiry, spatial and safety exceptions,
approvals, equipment service, counts, and budgets at a glance, plus a live
"attention needed" feed generated from current state.

![Dashboard](docs/screenshots/dashboard.png)

**Inventory** -- reagents and consumables with lot-level expiry, min-max reorder
math, hazard and controlled-substance flags, and per-item status (ok / low /
expiring / expired).

![Inventory](docs/screenshots/inventory.png)

**Map** -- the headline feature. A hand-drawn SVG floor plan drills room -> unit
-> shelf -> box, where a freezer box renders as a real grid of wells coloured by
state (occupied, expiring, expired, misplaced, empty). The contents table below
shows every lot in the box, including containers flagged as misplaced.

![Map: freezer-box grid drill-down](docs/screenshots/map.png)

**Purchasing** -- a purchase order in the approval workflow (`draft ->
pending_approval -> approved -> ordered -> received`). Receiving a line creates a
new lot and restocks inventory automatically.

![Purchasing: PO awaiting PI sign-off](docs/screenshots/purchasing.png)

**Funds** -- grant/budget burn-down. Charges from received POs, ticket usage, and
manual entries draw each fund down; the bar turns red as a fund nears its budget.

![Funds burn-down](docs/screenshots/funds.png)

**Safety** -- a storage-compatibility checker that flags incompatible hazard
classes sharing a location (oxidizers next to flammables, acids next to bases)
with a severity for each, plus the hazard-incompatibility reference behind it.

![Safety: storage-compatibility conflicts](docs/screenshots/safety.png)

**Analytics** -- hand-rolled inline-SVG charts (no chart library): monthly spend
with a cumulative line, daily consumption, forecast-to-stockout ranking, and
cost-per-task rollups.

![Analytics](docs/screenshots/analytics.png)

**Interactive tutorial (Lab Tycoon)** -- a hands-on, tick-loop supply-chain sim
where autonomous researcher NPCs generate demand and consume reagents. It is the
teaching entry point for new users: it drives the *same* REST API as the rest of
the app, so every simulated consume and reorder is a real write to the same
database the dashboard reads, and it rehearses the exact planning the tool is
built to encourage.

![Lab Tycoon interactive tutorial](docs/screenshots/game.png)

## Quick start

One command creates a local virtual environment, installs dependencies on first
run, builds `lab.db` from `schema.sql` + `seed.sql`, and starts the server:

```bash
python3 run.py
```

On Windows, `start-nimble.bat` does the same from inside WSL and opens your
browser once the server answers. Then open <http://127.0.0.1:8770>.

Interactive API docs (the FastAPI/OpenAPI explorer) are served at
<http://127.0.0.1:8770/docs>. Use the in-app "Reset demo data" button (or
`POST /api/reset`) to rebuild the database from seed at any time; Ctrl+C stops
the server.

### Logging in

`python3 run.py` starts in **demo mode** and ships four demo accounts, one per
role in the `viewer < member < manager < admin` hierarchy:

| Username  | Password  | Role    |
|-----------|-----------|---------|
| `admin`   | `admin`   | admin   |
| `manager` | `manager` | manager |
| `member`  | `member`  | member  |
| `viewer`  | `viewer`  | viewer  |

The one-click buttons on the login screen fill these in. They exist **only in
demo mode** -- see [Running a real lab (empty start)](#running-a-real-lab-empty-start)
for how a deployed instance starts empty and secure instead, with no well-known
credentials.

Roles gate both the UI (nav items you can't reach are hidden -- People is
admin-only) and the API (every mutating endpoint declares its minimum role
server-side, so the gate can't be bypassed from the browser).

To skip login entirely -- scripting against the API, or a quick local demo -- set
`NLM_AUTH=off` before starting the server:

```bash
NLM_AUTH=off python3 run.py
```

Every request is then treated as an admin session with no cookie required. The
demo data is dated so "today" surfaces the interesting cases: expired and
expiring lots, low-stock reorders, misplaced containers, pending purchase orders,
equipment due for service, and months of consumption history for the analytics.

### Running a real lab (empty start)

Demo mode is opt-in (the `NLM_SEED_DEMO` flag, which `run.py` sets for you). Any
other launch -- Docker, Fly, or a plain `uvicorn` (or `make run-empty`) --
starts with an **empty database and no demo accounts**. On first boot the app
creates a single admin:

- Set `NLM_ADMIN_USER` / `NLM_ADMIN_PASSWORD` beforehand to choose the login, or
- leave them unset and read the one-time generated password from the startup
  logs, then change it in **Admin > People**.

From there you build your own lab: add users, draw your rooms and freezers on the
map, and bulk-import your existing stock (**Home > Reports > Import inventory**). Because
there is no demo data to wipe, the destructive "Reset demo data" action is
disabled outside demo mode. Cookies are marked `Secure` automatically over HTTPS
(and `fly.toml` sets `NLM_SECURE_COOKIES=1`).

### Alerts and email digests

Open alerts -- expiring reagents, low stock, equipment service and calibration
due, license expiry, POs awaiting approval, storage-compatibility conflicts --
surface in the in-app notifications bell and, in **Settings > Email alert
digest**, as a grouped preview you can view any time (and send on demand).

To have them reach people who are *not* in the app, turn on the daily email
digest: set `NLM_SCHEDULER=1`, list recipients in `NLM_DIGEST_TO` (comma
separated), and configure SMTP:

```bash
NLM_SMTP_HOST=smtp.example.com NLM_SMTP_PORT=587 \
NLM_SMTP_USER=alerts@example.com NLM_SMTP_PASSWORD=... \
NLM_DIGEST_TO="pi@example.com,labmgr@example.com" \
NLM_SCHEDULER=1 NLM_DIGEST_HOUR=7 \
  <your launch command>
```

The digest is sent once per day at `NLM_DIGEST_HOUR` (local, default 7). Email is
entirely optional: with SMTP unset the in-app preview still works, and an admin
can trigger a test send from the digest panel. (On hosts that stop the machine
when idle -- e.g. Fly.io `auto_stop_machines` -- keep one machine running so the
scheduler can fire.)

## Feature tour

The SPA organises 26 views into 8 hub pages (Home, Inventory, Preparations,
Procurement, Facilities, Usage, Admin, Help), each hub a landing page with tabs,
behind a role-aware left-hand nav -- plus a live notification bell, global search
and a command palette (Ctrl-K) in the top bar. An admin can rename, reorder or
hide hubs in Settings.

- **Dashboard** -- command-center counts and a deduplicated "attention needed"
  feed built from live state.
- **Inventory** -- item list and detail: multi-lot expiry, min-max reorder,
  hazard class and CAS number, controlled flag, linked SDS/CoA, printable QR
  label, and consume/restock actions that write `usage_event` rows. When the
  shelf and the record disagree, **Set actual quantity** reconciles to the
  counted number in one audited step -- recorded as an adjustment, not as
  consumption, so a recount never distorts usage analytics or forecasts.
  Discontinued items can be deprecated (a reversible soft archive that keeps
  all their history) rather than deleted.
- **Catalog** -- an offline vendor catalog (real catalog numbers, pack sizes,
  prices) with cross-vendor price comparison, one-click add-to-inventory, and
  substitute groups so a backordered vendor falls through to the next-ranked
  alternative.
- **Kits** -- bill-of-materials recipes; assembling a kit depletes every
  component under the same guarded stock path as a manual consume.
- **Preparations** -- in-house recipes (buffers, media, mixes) turned into dated
  batches; making a batch draws its ingredients down through the same guarded
  stock path, and batches carry their own expiry into the alert feed.
- **Glassware** -- a check-out register for shared glassware and dishware: who
  holds each piece, when it is due back, and a board of what is currently out,
  with overdue returns raising an alert.
- **IT** -- computers and instruments-with-a-licence: hardware assets (serial,
  warranty, assignee) and software licences whose expiry feeds the same alerts.
- **Maintenance** -- recurring chores (cleaning rotas, calibration, service) on a
  schedule, completing one advancing its next-due date; stale chores can be
  deprecated without losing their history.
- **Tickets** -- "work session" records (who used what, and why), optionally
  pre-filled from a reusable task template, feeding the same `usage_event` log.
- **Map** -- clickable SVG floor plan (optionally over an uploaded blueprint)
  drilling to a real box-grid of wells coloured by state.
- **Equipment** -- registry with a reservation calendar and a
  maintenance/calibration log that drives the "service due" count.
- **Purchasing** -- requisition-through-receiving PO workflow with PI sign-off;
  receiving creates lots and restocks; low-stock items surface reorder
  suggestions.
- **Funds** -- grant/budget burn-down with charge history and over-budget flags.
- **Controlled** -- a DEA-style append-only, signed running-balance register per
  controlled item, independent of the ordinary consume/restock trail.
- **Safety** -- storage-compatibility conflict detection across hazard classes.
- **Labels** -- printable QR labels rendered server-side as SVG (via `segno`).
- **Analytics** -- inline-SVG spend, consumption, forecast, and cost-per-task
  charts.
- **Usage** -- per-member usage history with an admin-only vs. everyone
  visibility setting.
- **People** (admin-only) -- create/deactivate users, assign roles, reset
  passwords.
- **History** (manager+) -- the append-only audit trail.
- **SQL console** (optional, off by default) -- the backend is a single SQLite
  file, so an admin who prefers SQL can query it directly for questions no
  built-in report anticipates. Enable it in **Settings > SQL console**; until
  then the tab does not exist and the endpoints refuse. It is defended in four
  independent layers: the feature gate plus admin-only routes, a connection
  opened `mode=ro`, a SQLite **authorizer** that vetoes anything but a plain read
  (no writes, DDL, `ATTACH`, `PRAGMA`, or `load_extension` -- enforced at parse
  level, so it cannot be talked around the way a regex can), and refusal to read
  password hashes or session tokens even for an admin. One statement at a time,
  results capped at 1000 rows, a 5-second deadline so a cartesian join cannot pin
  the CPU, and every query -- including refused ones -- written to the audit log.
- **Reports** -- summary counts, role-gated CSV exports, and CSV import with a
  dry-run preview and per-row errors. Imported rows match existing items by
  catalog number, then item id, then name, so re-importing an edited vendor
  sheet updates the right product instead of silently duplicating it or merging
  two reagents that share a name.
- **Stocktake** -- cycle counts that end in an actionable state: closing a
  session flags containers the count could not find (so they stop reading as
  present everywhere else) and lists the affected items for reconciliation.
  Quantities are never adjusted automatically, because a container is not
  necessarily one stock unit. **Scan with camera** walks the shelf counting tube
  after tube from a phone.
- **Scanning** -- printed QR labels resolve to their item, and any code (QR deep
  link, item id, or vendor catalog number) can be scanned with the device camera
  from Stocktake or the command palette's "Scan a label". Uses the browser's
  built-in barcode reader, so it stays dependency-free; where that is
  unavailable (notably iOS Safari) it says so and falls back to typing the code,
  and the phone's own camera app still opens the label's deep link.
- **Tutorial** ("Lab Tycoon") -- an interactive, hands-on tutorial: the
  supply-chain sim that teaches the app by writing through the real API.

## Architecture and data model

```
  Browser (buildless SPA, web/)
  +-----------------------------------------------------------+
  |  index.html  ->  js/app.js  (router, api client, ctx)     |
  |  20 vanilla-JS ES-module views, no build step, no CDN     |
  +--------------------------|--------------------------------+
                             |  fetch (JSON over HTTP, same origin)
                             v
  FastAPI  (app/server.py -> app/api.py; auth_router + router under /api)
                             |
                             v
  SQLite   (lab.db, built from schema.sql + seed.sql on first boot)
```

The interesting engineering is in the data layer -- see **[FRAMEWORK.md](FRAMEWORK.md)**
for the full model. Highlights:

- **Spatial hierarchy as an adjacency list.** Locations reference `parent_id`
  and are walked with a **recursive CTE**, so arbitrary-depth room -> freezer ->
  shelf -> rack -> box nesting runs on plain SQLite with no Postgres or `ltree`
  extension. Containers live in wells (row/col) inside boxes; items own multiple
  lots with independent expiry.
- **Race-safe stock updates.** Consuming stock is a single guarded UPDATE --
  `SET quantity_on_hand = quantity_on_hand - ? WHERE item_id = ? AND
  quantity_on_hand >= ?` -- so under concurrent load SQLite serializes the
  writers, each re-checks committed state, and overselling is impossible; a loser
  gets a clean 400 instead of a negative balance. A dedicated concurrency test
  (below) proves this against real parallel HTTP traffic.
- **Auth and roles.** Cookie sessions with **PBKDF2-HMAC-SHA256** password
  hashing (per-user salt, 210k iterations, stdlib-only) and the four-level role
  hierarchy enforced server-side on every mutating endpoint.
- **Audit trail.** Every create/update/consume/restock/settings change appends a
  row to an immutable `audit_log`, surfaced in the History view.

The project began as a pure-SQL exercise, and that layer still stands alone: six
domain tables plus five operational queries in `queries/` (IACUC renewals,
reorder points, colony census, monthly spend with a window function, training
expiry) run with nothing but the `sqlite3` CLI. The web app's analytics reuse
that exact logic, so the SPA and the raw SQL always tell the same story.

`generate_data.py` fabricates a larger, self-consistent lab "world" into a fresh
SQLite DB (stdlib-only, seeded and date-anchored for full reproducibility) so the
map, forecasts, and alerts all light up and the schema is shown to scale beyond
the hand-written seed.

### Demo catalog (real molecular-biology products)

For demos, the repo ships a curated catalog of **~100 real molecular-biology
products** in [`molbio_catalog.py`](molbio_catalog.py) -- polymerases (Taq, Q5,
Phusion), restriction enzymes (EcoRI-HF, BamHI-HF, ...), ligases, prep kits
(QIAprep, RNeasy, Monarch, Qubit, TRIzol), competent cells, DNA ladders, common
buffers and chemicals with **real CAS numbers** (SDS, DTT, TEMED, phenol:chloroform,
ethidium bromide, ...), media, antibiotics, antibodies, and plasticware. Catalog
numbers use each vendor's real product codes where known.

Build a demo database that loads it (plus a few thousand realistic bulk rows so
search, filtering, and pagination have something to chew on):

```bash
make demo                                                   # via the Makefile, or:
python3 generate_data.py --force --molbio                   # the ~100 curated products
python3 generate_data.py --force --molbio --catalog 5000    # + realistic bulk for scale
```

Then start the app and open **Inventory > Catalog** to browse it (and "Add to
inventory" from it). The bulk rows reuse the real chemical identities, so the same
reagent shows up from several vendors at different pack sizes and prices -- like a
real cross-vendor catalog. `make reset` restores the standard feature-demo seed.

The bundled catalog uses real catalog numbers with **representative** prices. To
load **genuinely-sourced** prices, [`import_catalog.py`](import_catalog.py)
imports a vendor price CSV into the catalog:

```bash
python3 import_catalog.py prices.csv --vendor "Fisher Scientific"   # or:
python3 import_catalog.py prices.csv --dry-run                      # preview, write nothing
```

Where to get a real, legal price CSV: **GSA Advantage** (<https://www.gsaadvantage.gov>)
publishes each vendor's Authorized Federal Supply Schedule electronic catalog as
a download -- Fisher's channel is contract `GS07F161BA` -- which are public,
federally-negotiated prices. A **Fisher/Thermo PunchOut (cXML)** account exposes
live contract prices you can export. The importer aliases common header spellings
(`MFR PART NUMBER`, `ITEM DESCRIPTION`, `GSA PRICE`, ...); use `--map
'HEADER=field'` for anything it doesn't recognise. Rows match on
(vendor, catalog_number), so re-importing an updated sheet refreshes prices
instead of duplicating.

## Testing and quality

**438 automated tests** back the app, run with `pytest` against FastAPI's
in-process `TestClient` -- each test gets its own temporary SQLite database, so
running the suite never touches your development `lab.db`:

```bash
pip install -r requirements.txt -r requirements-dev.txt   # or into .venv
python -m pytest -q
```

The suite is deliberately broad:

- **Unit + role/security tests** -- item/lot/expiry math, first-expiry-first lot
  drain, the on-hand floor at zero, the full `viewer < member < manager < admin`
  gate, `NLM_AUTH=off` open mode, and the security surface (`test_security.py`).
- **OpenAPI property/fuzz testing (Schemathesis)** -- for every operation in the
  app's own OpenAPI schema, Schemathesis synthesises boundary values, wrong
  types, missing fields, and oversized inputs and asserts the server never
  returns a 5xx. This **found and drove fixes for two real 5xx bug classes**: an
  unbounded-integer path/query parameter that overflowed SQLite's 8-byte range
  (now answered as 400), and a CSV exporter that crashed on NUL bytes in stored
  free-text (now scrubbed). Both are locked in as regression guards.
- **Accessibility audits (axe-core)** -- Playwright renders the key views and
  runs axe-core, asserting **zero critical or serious** WCAG violations.
- **Playwright end-to-end** -- a browser-driven smoke test of the real SPA
  against a live in-process server.
- **Concurrency stress test** (`test_concurrency.py`) -- fires a burst of
  parallel consumes at limited stock and asserts exactly `floor(stock / qty)`
  winners, no oversell, no negative balance, and no 5xx -- a real integration
  proof of the guarded-UPDATE race safety described above.

Security hardening is tested, not just claimed: **CSRF** double-submit cookie
tokens on mutating requests, a **Content-Security-Policy** plus
`X-Frame-Options: DENY`, and a sliding-window **login rate limit** (429 after
repeated failures).

## Tech stack

- **Backend:** Python 3, FastAPI + uvicorn, SQLite (single `lab.db` file).
  QR generation uses `segno` (pure-Python), so even labels stay offline.
- **Frontend:** vanilla-JavaScript ES modules -- no build step, no framework.
  Floor plan, box grids, and analytics charts are all hand-rolled inline SVG.
  FastAPI serves the static `web/` directory directly: one process, one port.
- **Auth:** cookie sessions, PBKDF2-hashed passwords, four-level roles, with an
  `NLM_AUTH=off` escape hatch for open local access.
- **No build step, no CDN, no external runtime dependencies at the browser** --
  the whole thing works fully offline.

## Configuration reference

Every environment variable the app reads. All are optional; the defaults are what
`python3 run.py` gives you.

| Variable | Default | Purpose |
|---|---|---|
| `NLM_AUTH` | `on` | `off` disables login entirely (every request acts as admin). Local/scripting only. |
| `NLM_SEED_DEMO` | off | `1` loads the demo lab and the four demo logins. `run.py` sets it; deployments leave it off and start empty. |
| `NLM_ADMIN_USER` | `admin` | Username for the admin bootstrapped on an empty database. |
| `NLM_ADMIN_PASSWORD` | generated | Password for that admin. If unset, a random one is generated and logged once at startup. |
| `NLM_SECURE_COOKIES` | off | Force the `Secure` cookie flag. Set automatically for HTTPS requests; `fly.toml` pins it on. |
| `NLM_ALLOW_RESET` | off | Permit `POST /api/reset` (which wipes every table) outside demo mode. Leave off on a real lab. |
| `NLM_TZ` | server local | IANA zone (e.g. `America/New_York`) for the digest send hour. In a container the server clock is UTC, so set this to get your actual morning. |
| `NLM_SCHEDULER` | off | `1` starts the daily alert-digest thread. |
| `NLM_DIGEST_HOUR` | `7` | Hour (0-23, in `NLM_TZ`) to send the digest. |
| `NLM_DIGEST_TO` | -- | Comma-separated digest recipients. |
| `NLM_SMTP_HOST` | -- | SMTP server. Unset means email is disabled (the in-app digest preview still works). |
| `NLM_SMTP_PORT` | `587` | SMTP port. |
| `NLM_SMTP_USER` / `NLM_SMTP_PASSWORD` | -- | SMTP credentials, if the server needs them. |
| `NLM_SMTP_FROM` | `NLM_SMTP_USER` | `From:` address on the digest. |
| `NLM_SMTP_TLS` | on | `0` disables STARTTLS. |

## Deploy

A `Dockerfile` + `docker-compose.yml` (`docker compose up --build`, then
<http://localhost:8770>) and a ready-to-edit `fly.toml` ship in the repo root.
Both start **empty and secure** -- the schema builds on first boot and a single
admin is bootstrapped (see [Running a real lab](#running-a-real-lab-empty-start));
set `NLM_SEED_DEMO=1` if you instead want the throwaway demo lab. A mounted
volume (`nlm-data` / `nlm_data`, at `/data`) keeps `lab.db` across rebuilds. A
single SQLite file means a single machine -- the right shape for this workload.

### Durability (backup + migrations)

A single `lab.db` on one volume is the whole business state, so two pieces guard
it:

- **Streaming backup (Litestream, opt-in).** Set `LITESTREAM_REPLICA_URL` (e.g.
  `s3://your-bucket/nlm`) plus object-store credentials and the container
  continuously streams the database to object storage; on a fresh volume the
  entrypoint restores it automatically. Unset, the app runs exactly as before.
  See `litestream.yml` and `docker-entrypoint.sh`. On Fly, also set
  `min_machines_running = 1` (a stopped machine replicates nothing).
- **Versioned migrations.** `schema.sql` builds a fresh database complete; an
  existing one is upgraded by an ordered, `PRAGMA user_version`-gated migration
  runner (`app/db.py`, `_MIGRATIONS`) applied on startup. To change the schema on
  a live deployment, edit `schema.sql` *and* append a `(version, sql)` step --
  never renumber a released step.

## Contributing and license

See `CONTRIBUTING.md` for setup and conventions, and the `Makefile` for common
tasks (`make help`). Licensed under the MIT License -- see `LICENSE`.
