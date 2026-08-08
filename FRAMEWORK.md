# Nimble Lab Manager -- Architecture & Data Model

This is the technical reference for the shipped system: how the pieces fit
together, the schema, and how to extend it safely. `README.md` is the
front-door tour (what it does, how to run it); this doc is "how it works" for
anyone reading the code or adding a feature.

---

## 1. System shape

```
  Browser (buildless SPA, web/)
  +-----------------------------------------------------------+
  |  index.html  ->  js/app.js  (router, api client, ctx, auth  |
  |                    gate, theme toggle, notification bell,   |
  |                    global search, dashboard view)           |
  |                    |                                         |
  |     19 view modules under web/js/*.js -- each exports        |
  |     `view = {id, label, minRole}` and `render(root, ctx,     |
  |     params)`, and imports nothing but the browser DOM APIs.  |
  |     app.js imports every module; modules never import each   |
  |     other, so any view can be deleted without touching the   |
  |     rest of the app.                                         |
  +--------------------------|--------------------------------+
                             |  fetch("/api/...")  JSON, same origin,
                             |  session cookie rides along
                             v
  FastAPI  (app/server.py)
    lifespan hook runs init_db() before serving; two routers:
      auth_router  -- /api/login, /api/logout, /api/me  (no session required)
      router       -- everything else, gated per-endpoint by auth.require_role
    StaticFiles mounts web/ at "/" (after the API routers, so /api/* is never
    shadowed by the static handler)
                             |
                             v
  SQLite  (lab.db, single file; schema.sql + seed.sql on first boot)
```

The frontend has no build step: `web/index.html` loads `js/app.js` as a native
ES module, which lazily imports the 18 other view modules. There is no bundler,
no transpiler, no npm install -- opening `index.html` against a running server
is the entire deploy story for the client half.

The backend is a single FastAPI app (`app/server.py`) with all routes defined
in one module, `app/api.py` (roughly 7,900 lines, organized top-to-bottom by
domain -- dashboard, locations, items/consume/restock, alerts, analytics,
tickets/templates, audit, purchase orders, compatibility, notifications,
controlled substances, cost-by-task, search, QR labels, users, catalog/
substitute groups, documents, receiving, reorder suggestions, location
contents, cycle counts, kits, equipment, funds, CSV exports). `app/auth.py`
owns password hashing, sessions, and the role gate; `app/db.py` owns the
SQLite connection and `init_db()`.

## 2. Data model

### Original SQL foundation (kept as-is)

`staff`, `protocols`, `animals`, `inventory`, `orders`, `training` -- the
six-table domain model the project started as (IACUC protocol renewals,
animal colony, reagent inventory, spend, staff training). `inventory` has
since grown many columns (see below) but keeps its original primary key and
role as the "one row per catalog item" table everything else hangs off of.

### Spatial layer -- adjacency-list locations

```
location_node
  id, parent_id -> location_node(id)     -- adjacency list, walked with a
  kind          room|bench|cabinet|fridge|freezer|shelf|rack|box|cage
  name
  capacity_rows, capacity_cols            -- set only for kind='box' (grid)
  floor_id      -> floor(id)              -- which floor-plan image/schematic
  map_x/y/w/h                             -- pixel coords (or 0..1000 abstract
                                             canvas coords when floor has no image)
```

There is no `ltree` or materialized path: the tree is a plain `parent_id`
adjacency list, and every "give me this subtree" query (floor contents,
location detail, location contents, cascading deletes) is a recursive CTE
(`WITH RECURSIVE ...`). That keeps the whole app on stock SQLite -- no
extensions, no Postgres -- while still supporting arbitrary nesting depth
(room -> freezer -> shelf -> rack -> box -> well).

### Inventory: lots, containers, usage

```
inventory        one row per catalog item (name, vendor, unit, category,
                  quantity_on_hand, reorder_threshold, reorder_max, unit_cost,
                  status active|deprecated, is_controlled, schedule,
                  hazard_class, cas_number, sds_url, disposal_instructions)
  |
  +-- item_lot          a received batch: lot_number, expiry_date, quantity,
  |     |                received_date, coa_url
  |     |
  |     +-- container    ONE physical vial/tube/bottle at (box_id, row, col);
  |                       also carries expected_box_id/row/col -- a mismatch
  |                       between actual and expected position IS the
  |                       misplacement signal (no separate flag to keep in sync)
  |
  +-- usage_event   the outflow/activity log: event_type
                     (consume|restock|move|discard|expire), quantity,
                     occurred_at, optional container_id/staff_id/ticket_id/
                     purpose. This is the spine analytics, forecasting, and
                     the Lab Tycoon interactive tutorial all read and write.
```

`quantity_on_hand` on `inventory` is a denormalized running total; the
invariant `quantity_on_hand == SUM(item_lot.quantity)` for that item is
maintained on every write path (consume, restock, kit assembly, PO receiving)
and is asserted in `test_concurrency.py` and by `generate_data.py`.

**Atomic guarded stock updates.** Consuming stock is not "read quantity, check
in Python, write quantity" -- that has a race. It is one conditional UPDATE:

```sql
UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
WHERE item_id = ? AND quantity_on_hand >= ?
```

SQLite serializes writers, so this statement is the single point that decides
success: if `rowcount == 0`, the guard failed and the caller gets HTTP 400
("insufficient quantity on hand") inside the same transaction, no partial
side effects committed. Only after that succeeds does the code walk
`item_lot` rows oldest-expiry-first (nulls last) to actually drain the lots,
then write the `usage_event`, then audit, then commit. `test_concurrency.py`
fires a burst of parallel consumes against limited stock and asserts nothing
oversells and exactly `floor(stock / qty)` requests win -- this is the
regression test for that guard.

### Auth: PBKDF2 + role hierarchy

```
app_user   username, full_name, role (CHECK IN admin/manager/member/viewer),
           password_hash, password_salt, iterations, staff_id (soft ref),
           is_active
session    token (secrets.token_urlsafe), user_id, created_at, expires_at
```

Passwords are PBKDF2-HMAC-SHA256, 210,000 iterations, a random 16-byte salt
per user, verified with `hmac.compare_digest` (constant-time). Sessions are
opaque tokens in an httponly `nlm_session` cookie, 7-day expiry. The role
hierarchy is a flat rank dict (`ROLE_RANK = {viewer: 0, member: 1, manager: 2,
admin: 3}`); `auth.require_role(min_role)` is a FastAPI dependency that admits
any role whose rank is >= the endpoint's declared minimum, so every mutating
route states its own floor at the point of definition rather than relying on
a central ACL table. `is_active` is a soft on/off switch: a deactivated user
is kept (their history stays attributable) but login is refused. Setting
`NLM_AUTH=off` short-circuits the whole system to a synthetic admin user with
no cookie required -- useful for scripting against the API or a fast local
demo.

### Append-only audit trail

```
audit_log   occurred_at, user_id (soft ref), username (copied at write time),
            action, entity_type, entity_id, detail
```

Every mutating endpoint calls a shared `_audit(conn, user, action,
entity_type, entity_id, detail)` helper inside the same transaction as the
mutation, so an audit row and its effect commit or roll back together.
`username` is denormalized (copied in at write time) so a log entry stays
readable even after the user is renamed, deactivated, or deleted -- consistent
with the rest of the schema's habit of soft references (`user_id` columns
that aren't hard foreign keys) wherever seed-order or history-preservation
matters more than referential strictness. The History view (manager+) is a
thin read over this table; the Reports view's `audit.csv` export is the same
data as a download.

### Notifications

```
notification   created_at, user_id (NULL = broadcast to managers/admins),
               kind (low_stock|expiring|approval_pending|compatibility|
               maintenance_due|other), severity (info|warn|danger), message,
               entity_type, entity_id, link_view, read_at
```

Notifications are not user-authored; they're generated from live state by
`_sync_notifications(conn)`, which is called after the writes most likely to
change what's noteworthy (e.g. after a PO status change, after an equipment
maintenance record). Regeneration dedupes on `(kind, entity_type, entity_id)`
so calling it repeatedly does not pile up duplicate rows for the same
underlying condition -- it's safe to call opportunistically rather than on a
schedule. `link_view` lets a notification deep-link straight into the SPA
view that explains it (e.g. `purchasing`, `inventory`).

### Purchasing: PO approval state machine

```
purchase_order  status: draft -> pending_approval -> approved -> submitted
                 -> ordered -> received  (or cancelled / rejected)
                 created_by, approved_by/approved_at/approver_note,
                 submitted_at, ordered_at, received_at
po_line         po_id, item_id, quantity, unit_cost, received_qty
```

Requisition (member+) creates a draft/pending PO; sign-off (manager+) approves
or rejects it with a note; receiving a line creates a new `item_lot`, bumps
`inventory.quantity_on_hand`, and books a `restock` usage_event -- so a PO
receipt and a manual restock leave an identical trail. A spend-threshold rule
can auto-generate a PO for items at/below reorder (`POST
/api/purchase-orders/auto`), and `GET /api/reorder/suggestions` surfaces
candidates without creating anything.

### Substitute groups + vendor catalog (backorder fall-through)

```
substitute_group   name, category, description
vendor_catalog      vendor, catalog_number, product_name, pack_size, unit,
                     list_price, sds_url, cas_number, hazard_class,
                     substitute_group_id -> substitute_group(id),
                     preference_rank, availability (in_stock|backorder|
                     discontinued)
```

`vendor_catalog` is an offline, seeded catalog of real vendor products.
Grouping several rows under one `substitute_group_id` with a
`preference_rank` models interchangeable products from different vendors
(e.g. the same reagent from two suppliers): when the preferred row's
`availability` is `backorder`, the app can fall through to the next-ranked
member of the group. Any catalog row can be added to `inventory` in one click
(`POST /api/catalog/{id}/add-to-inventory`).

### Kits / bill of materials

```
kit        name, description, output_item_id -> inventory(item_id), output_qty
kit_line   kit_id, item_id, quantity
```

Assembling a kit N times (`POST /api/kits/{id}/assemble`) depletes every
component through the same guarded-UPDATE path as a manual consume (so it
cannot oversell a component either), and optionally credits an output item,
rolling up component cost. This models real buffer/media prep and assay kits
as a recipe rather than a single SKU.

### Equipment: registry, booking, maintenance

```
equipment               name, category, make_model, serial_number,
                         location_id (soft ref), status (operational|
                         maintenance|out_of_service), service_interval_days,
                         last_service_date, next_service_date
equipment_reservation    equipment_id, user_id, starts_at, ends_at, purpose
equipment_maintenance    equipment_id, kind (calibration|repair|preventive|
                         inspection), performed_at, performed_by, next_due
```

`next_service_date` drives the dashboard's `equipment_due` count (service due
within 14 days) and the corresponding `maintenance_due` notification kind.
Reservations are plain time ranges with no double-booking constraint enforced
at the DB layer today (see Section 4, "known simplifications").

### Funds / grant budget burn-down

```
fund          name, sponsor, budget, start_date, end_date
fund_charge   fund_id, amount, source_type (purchase_order|ticket|manual),
              source_id, description, charged_at, charged_by
```

`remaining = budget - SUM(fund_charge.amount)`. The dashboard's
`funds_attention` count and the Funds view's burn-down bar both flag any fund
where charges exceed 90% of budget. Charges can originate from a received PO,
ticket usage, or a manual entry, each tagged by `source_type`/`source_id` so a
charge can be traced back to what generated it.

### Controlled-substance register

```
controlled_log   item_id, occurred_at, user_id, username, change (signed:
                  negative = dispensed, positive = received), balance_after,
                  reason, witness
```

A DEA-style append-only log, independent of the ordinary `usage_event` trail:
every entry stores the running balance *after* itself and a witness signature
field, matching the two-person-verification convention real controlled-
substance logs require. `inventory.is_controlled` puts an item on this
register; the dashboard's `controlled` count and the Controlled view both
read off that flag.

### Cycle counts / stocktake

```
count_session   location_id (NULL = whole lab), status (open|closed),
                 started_by/started_at, closed_at
count_line      session_id, container_id, item_id, box_name/row/col,
                 expected, counted, status (pending|found|missing|extra)
```

Opening a session snapshots the containers the map says should be under a
location; closing a session tallies found/missing/extra into a
count-accuracy KPI. `open_counts` on the dashboard is a plain count of
`count_session` rows with `status='open'`.

### Documents

```
item_document   item_id | lot_id | po_id (exactly one set), kind (sds|coa|
                 invoice|po|packing_slip|other), label, url, filename,
                 uploaded_at, uploaded_by
```

A document is either an external link (e.g. a manufacturer's SDS page) or an
uploaded file under `web/uploads/docs/`, attached to exactly one of an item, a
lot, or a purchase order.

## 3. Module layout

```
app/
  server.py    FastAPI() with a lifespan hook that calls init_db(); mounts
               auth_router and router under /api, then StaticFiles(web/) at /
  api.py       every route, grouped by domain (see Section 1); shared helpers
               live near the top: get_conn(), _rows(), _audit(), _today(),
               _compat_conflicts(conn), _sync_notifications(conn)
  notify.py    builds the alert digest (grouped text + HTML) and sends it via
               stdlib smtplib; a no-op when SMTP is unconfigured
  scheduler.py opt-in daily thread that emails that digest, claiming the day
               atomically in app_setting so concurrent workers cannot double-send
  sqlconsole.py read-only SQL console engine: mode=ro handle + SQLite authorizer
               + secret redaction + row/byte/time caps (see Section 6)
  auth.py      password hashing, session cookie, require_role() dependency,
               demo user provisioning, NLM_AUTH=off bypass
  db.py        SQLite connection factory + init_db() (builds lab.db from
               schema.sql + seed.sql on first run, idempotent on repeat runs)

web/
  index.html   the only HTML file; loads js/app.js as a module
  css/styles.css   theme tokens (:root + [data-theme="dark"]) + component styles
  js/
    app.js     router, fetch-based api client, ctx object, login gate, theme
               toggle, notification bell, global search, the Dashboard view
    <19 view modules>.js   inventory, catalog, kits, counts (stocktake),
               tickets, map, equipment, purchasing, funds, controlled, safety,
               labels, analytics, reports, usage, people, history, game, auth
```

Every view module follows the same contract: `export const view = {id, label,
minRole}` (default `minRole` is `"viewer"` when omitted) and `export async
function render(root, ctx, params)`. `app.js` builds a `Map` from `view.id` to
module (`VIEWS`), drives an `ORDER` array for nav rendering, and gates both
navigation (`canSee()`) and nav visibility by comparing the signed-in user's
role rank against the view's declared `minRole` -- so a role that can't reach
a view never even sees it in the nav, and a direct hash navigation to it
bounces back to the dashboard.

## 4. Extending the system

**Add a new view:** create `web/js/newview.js` exporting `view` (at minimum
`{id, label, minRole}`) and `render(root, ctx, params)`, import it in `app.js`,
add the module to `CHILD_MODULES`, and list its id in the relevant hub's `tabs`
array in `HUB_DEFS`. A view can gate itself behind a config flag with
`view.requiresConfig` (as the SQL console does). No build step, no registration
elsewhere.

**Add a new API endpoint:** add a route to `app/api.py` on `router` (or
`auth_router` if it must work without a session), reuse `get_conn()` /
`_rows()` / `_audit()`, and declare its role floor with
`dependencies=[Depends(auth.require_role("..."))]` if it's a mutation above
`viewer`.

**Add a new table:** add the `CREATE TABLE` to `schema.sql`, add seed rows to
`seed.sql` if it needs demo data, and consider whether `generate_data.py`
should also populate it for the synthetic-scale generator. Prefer a soft
reference (`user_id`/`*_id` column with a comment, no hard `REFERENCES`) over
a database user id, location, or ticket when the referenced row might be
edited/removed and you want the history to stay readable -- that's the
established convention here (`audit_log.user_id`, `ticket.user_id`,
`notification.user_id`, `controlled_log.user_id`, `fund_charge.charged_by`,
all soft refs) rather than one-off per table.

**Add a new CSV export:** follow the pattern in `app/api.py`'s `/api/export/*`
routes -- stdlib `csv` module into `io.StringIO`, returned as a `Response`
with `media_type="text/csv"` and a `Content-Disposition: attachment`
header, gated by role, and audited as `entity_type='export'`. Add a row to
`web/js/reports.js`'s `EXPORTS` list to surface it.

**Known simplifications** (fine for a portfolio POC, worth knowing before you
lean on them): equipment reservations enforce non-overlap in the API rather than
with a DB constraint; the location tree has no depth limit or cycle guard beyond what the
UI enforces; SQLite's single-writer model means the guarded-UPDATE pattern
handles the concurrency this app actually sees but would need a different
approach (e.g. Postgres row locks) at real multi-writer scale.

## 5. Testing

`tests/` runs against FastAPI's in-process `TestClient`, each test on its own
temporary copy of a seeded database (`app.db.DB_PATH` is repointed per test),
so the suite never touches a developer's `lab.db`. See `README.md`'s Testing
section for the file-by-file coverage breakdown and how to run it.
