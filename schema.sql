-- Lab Operations Database -- schema
-- A relational model of the real operational problems a lab manager solves:
-- animal colony under IACUC, protocol renewals, reagent inventory, spend, and staff training.
-- Portable SQLite (also runs on Postgres with minor date-function changes noted in the README).

PRAGMA foreign_keys = ON;

CREATE TABLE staff (
    staff_id    INTEGER PRIMARY KEY,
    full_name   TEXT    NOT NULL,
    role        TEXT    NOT NULL,          -- PI, Lab Manager, Postdoc, Technician, Undergraduate
    email       TEXT    UNIQUE,
    hire_date   DATE    NOT NULL
);

CREATE TABLE protocols (
    protocol_id     INTEGER PRIMARY KEY,
    title           TEXT    NOT NULL,
    pi_staff_id     INTEGER NOT NULL REFERENCES staff(staff_id),
    approved_date   DATE    NOT NULL,
    renewal_due     DATE    NOT NULL,      -- IACUC protocols require annual renewal
    status          TEXT    NOT NULL DEFAULT 'active'  -- active, expired, suspended
);

CREATE TABLE animals (
    animal_id       INTEGER PRIMARY KEY,
    strain          TEXT    NOT NULL,
    sex             TEXT    NOT NULL CHECK (sex IN ('M','F')),
    date_of_birth   DATE    NOT NULL,
    protocol_id     INTEGER NOT NULL REFERENCES protocols(protocol_id),
    cage            TEXT,
    status          TEXT    NOT NULL DEFAULT 'alive'   -- alive, euthanized, transferred
);

CREATE TABLE inventory (
    item_id             INTEGER PRIMARY KEY,
    item_name           TEXT    NOT NULL,
    vendor              TEXT,
    unit                TEXT,               -- e.g. vial, box, L
    quantity_on_hand    INTEGER NOT NULL,
    reorder_threshold   INTEGER NOT NULL,   -- reorder when on_hand <= threshold
    unit_cost           REAL    NOT NULL,
    -- Product classification. Allowed values (enforced softly at the app layer,
    -- NOT via a CHECK constraint, so new categories can be added without a
    -- schema migration): reagent, supply, chemical, antibody, enzyme, media,
    -- animal, equipment, other.
    category            TEXT    NOT NULL DEFAULT 'other',
    sds_url             TEXT,               -- product-level Safety Data Sheet link (NULL when N/A)
    -- Disposal guidance copied from the product SDS (typically section 13);
    -- free text, NULL for plain supplies with no hazardous-waste handling.
    disposal_instructions TEXT,
    -- Lifecycle state. 'deprecated' is a soft-delete: the row (and all its
    -- history -- lots, usage_event, orders) is preserved, just hidden from
    -- active pick-lists. Enforced softly at the app layer (no CHECK), allowed
    -- values: active, deprecated.
    status              TEXT    NOT NULL DEFAULT 'active',
    -- Controlled-substance tracking. is_controlled=1 puts the item on the
    -- controlled register (running-balance log with witness). schedule is the
    -- DEA schedule string (I-V), free text, NULL when not controlled.
    is_controlled       INTEGER NOT NULL DEFAULT 0,
    controlled_schedule TEXT,
    -- Reorder automation. reorder_threshold (above) is the min / reorder point;
    -- reorder_max is the "top up to" level an auto-generated PO fills to.
    reorder_max         INTEGER NULL,
    -- Chemical-safety metadata (GHS). hazard_class is a comma-separated list of
    -- GHS classes/pictogram keys (e.g. 'flammable,toxic'); cas_number is the
    -- Chemical Abstracts registry number. Both NULL for non-chemicals.
    hazard_class        TEXT,
    cas_number          TEXT,
    -- Which vendor_catalog product this stock was sourced from (soft ref, no FK).
    catalog_id          INTEGER NULL,
    -- Per-container package size as a human string (e.g. "500 mL", "500 g",
    -- "6 x 1 L"). Distinct from `unit` (the count noun) -- an item can be 6
    -- bottles OF 500 mL each. Copied from vendor_catalog.pack_size on add.
    pack_size           TEXT,
    -- Storage requirements. storage_temp is the required temperature
    -- (RT | 4C | -20C | -80C | LN2 | other), matched against a compartment's
    -- temp_rating for placement checks; light_sensitive flags store-in-dark.
    storage_temp        TEXT    NULL,
    light_sensitive     INTEGER NOT NULL DEFAULT 0,
    -- Optional user-uploaded product photo, served from web/uploads/products/.
    photo_filename      TEXT    NULL
);

CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    item_id     INTEGER NOT NULL REFERENCES inventory(item_id),
    quantity    INTEGER NOT NULL,
    order_date  DATE    NOT NULL,
    unit_cost   REAL    NOT NULL,           -- cost at time of order (may differ from current)
    ordered_by  INTEGER NOT NULL REFERENCES staff(staff_id)
);

CREATE TABLE training (
    training_id     INTEGER PRIMARY KEY,
    staff_id        INTEGER NOT NULL REFERENCES staff(staff_id),
    course          TEXT    NOT NULL,       -- e.g. IACUC Core, Bloodborne Pathogens, Surgery
    completed_date  DATE    NOT NULL,
    expires_date    DATE    NOT NULL
);

CREATE INDEX idx_animals_protocol ON animals(protocol_id);
CREATE INDEX idx_orders_item       ON orders(item_id);
CREATE INDEX idx_training_staff    ON training(staff_id);

-- =====================================================================
-- SPATIAL + LOT/CONTAINER + ACTIVITY MODEL (Nimble Lab Manager extension)
-- Location hierarchy via adjacency list (parent_id) + recursive CTE.
-- All map coords live in a 0..1000 canvas space for the SVG floor plan.
-- =====================================================================

-- A floor / room the map is drawn on. image_filename NULL => abstract schematic
-- rendered in a 0..1000 canvas space. When image_filename is set it names a real
-- uploaded floor-plan image stored under web/uploads/floors/<file>, and
-- image_width/image_height record that image's natural pixel size.
CREATE TABLE floor (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    image_filename  TEXT    NULL,       -- file under web/uploads/floors/; NULL = abstract schematic
    image_width     INTEGER NULL,       -- natural pixel width of that image
    image_height    INTEGER NULL        -- natural pixel height of that image
);

CREATE TABLE location_node (
    id             INTEGER PRIMARY KEY,
    parent_id      INTEGER NULL REFERENCES location_node(id),
    kind           TEXT    NOT NULL,   -- room | bench | cabinet | fridge | freezer | shelf | rack | box | cage
    name           TEXT    NOT NULL,
    capacity_rows  INTEGER NULL,       -- only for kind=box (grid)
    capacity_cols  INTEGER NULL,       -- only for kind=box (grid)
    floor_id       INTEGER NULL,       -- soft reference to floor.id (no hard FK, to keep seed order flexible)
    -- map_x/map_y/map_w/map_h are pixel coordinates in the floor image's natural
    -- space when that floor has image_filename set, or an abstract 0..1000 canvas
    -- space when image_filename is NULL (schematic).
    map_x          REAL    NULL,
    map_y          REAL    NULL,
    map_w          REAL    NULL,
    map_h          REAL    NULL,
    -- Storage suitability (feature: placement warnings). allowed_hazards is a
    -- comma-separated list of hazard keywords this compartment is rated to hold
    -- (empty/NULL = unrestricted); temp_rating is the compartment's temperature
    -- (RT | 4C | -20C | -80C | LN2 | other), matched against item.storage_temp.
    allowed_hazards TEXT   NULL,
    temp_rating     TEXT   NULL
);

CREATE TABLE item_lot (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES inventory(item_id),
    lot_number     TEXT,
    expiry_date    DATE    NULL,
    quantity       INTEGER NOT NULL,
    received_date  DATE,
    coa_url        TEXT                -- lot-specific Certificate of Analysis link (NULL when N/A)
);

CREATE TABLE container (   -- a physical vial/tube/bottle occupying ONE grid position in a box
    id               INTEGER PRIMARY KEY,
    item_lot_id      INTEGER NOT NULL REFERENCES item_lot(id),
    box_id           INTEGER NOT NULL REFERENCES location_node(id),   -- ACTUAL box
    row              INTEGER NOT NULL,                                -- ACTUAL position
    col              INTEGER NOT NULL,
    expected_box_id  INTEGER NULL REFERENCES location_node(id),
    expected_row     INTEGER NULL,                                    -- where it SHOULD be
    expected_col     INTEGER NULL,
    status           TEXT    NOT NULL DEFAULT 'in_use'   -- in_use | empty | discarded
);

CREATE TABLE usage_event (   -- OUTFLOW / activity log (drives analytics AND the game)
    id            INTEGER PRIMARY KEY,
    item_id       INTEGER NULL REFERENCES inventory(item_id),
    container_id  INTEGER NULL REFERENCES container(id),
    staff_id      INTEGER NULL REFERENCES staff(staff_id),
    event_type    TEXT    NOT NULL,   -- consume | restock | move | discard | expire
    quantity      INTEGER NULL,
    occurred_at   TIMESTAMP NOT NULL,
    note          TEXT    NULL,
    ticket_id     INTEGER NULL,       -- soft ref to ticket(id): consume events booked against a ticket
    purpose       TEXT    NULL        -- why the item was used (mirrors the ticket purpose)
);

CREATE INDEX idx_usage_item        ON usage_event(item_id);
CREATE INDEX idx_usage_occurred    ON usage_event(occurred_at);
CREATE INDEX idx_container_box      ON container(box_id);
CREATE INDEX idx_item_lot_item      ON item_lot(item_id);
CREATE INDEX idx_location_parent    ON location_node(parent_id);
CREATE INDEX idx_location_floor     ON location_node(floor_id);

-- =====================================================================
-- AUTH (application logins; separate from the staff roster)
-- Passwords are PBKDF2-HMAC-SHA256 (salt + hash + iteration count) computed
-- in app/auth.py. Demo users are seeded from Python in db.init_db() -- never
-- as hardcoded hashes in seed.sql.
-- =====================================================================

CREATE TABLE app_user (
    id             INTEGER PRIMARY KEY,
    username       TEXT    NOT NULL UNIQUE,
    full_name      TEXT    NOT NULL,
    role           TEXT    NOT NULL CHECK (role IN ('admin','manager','member','viewer')),
    password_hash  TEXT    NOT NULL,
    password_salt  TEXT    NOT NULL,
    iterations     INTEGER NOT NULL,
    staff_id       INTEGER NULL REFERENCES staff(staff_id),
    created_at     TIMESTAMP NOT NULL,
    -- Soft on/off switch: a deactivated user is kept for history but cannot log
    -- in (login checks this). Admins toggle it from the People view.
    is_active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE session (
    token       TEXT PRIMARY KEY,               -- secrets.token_urlsafe
    user_id     INTEGER NOT NULL REFERENCES app_user(id),
    created_at  TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP NOT NULL
);

CREATE INDEX idx_session_user ON session(user_id);

-- =====================================================================
-- ACTIVITY / TICKETING / TEMPLATES / SETTINGS (Nimble Lab Manager v2)
-- Tickets record who used which items and why; task_templates pre-fill a
-- ticket for a recurring bench procedure; audit_log is an append-only trail
-- powering the History view; app_setting holds runtime config.
-- =====================================================================

-- Append-only activity trail. Denormalized on purpose (username copied in) so
-- an entry stays readable even after the referenced user/entity changes or is
-- removed. user_id is a soft reference to app_user(id) (nullable, no hard FK).
CREATE TABLE audit_log (
    id           INTEGER PRIMARY KEY,
    occurred_at  TIMESTAMP NOT NULL,
    user_id      INTEGER   NULL,        -- soft ref to app_user(id)
    username     TEXT      NULL,        -- copied at write time for readability
    action       TEXT      NOT NULL,    -- login, item.create, item.update, item.deprecate,
                                        -- consume, restock, container.move, ticket.create,
                                        -- task.update, settings.update, ...
    entity_type  TEXT      NULL,        -- e.g. inventory, container, ticket, app_setting
    entity_id    INTEGER   NULL,
    detail       TEXT      NULL         -- short human string or JSON blob
);

-- A ticket = one person's work session that consumed items for a purpose.
-- user_id is a SOFT reference to app_user(id) (no hard FK) so seed.sql can load
-- before ensure_demo_users() populates app_user -- mirrors location_node.floor_id.
CREATE TABLE ticket (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,       -- soft ref to app_user(id)
    ticket_date DATE    NOT NULL,
    task        TEXT    NULL,           -- procedure name, often a task_template.name
    purpose     TEXT    NULL,           -- why the work was done
    note        TEXT    NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE TABLE ticket_line (
    id          INTEGER PRIMARY KEY,
    ticket_id   INTEGER NOT NULL REFERENCES ticket(id),
    item_id     INTEGER NOT NULL REFERENCES inventory(item_id),
    quantity    INTEGER NOT NULL,
    -- Unit the member logged usage in (defaults to the item's tracked unit).
    -- Recording convenience: stock is still deducted in the item's base unit.
    unit        TEXT    NULL
);

-- A reusable recipe: the items (and default quantities) a recurring procedure
-- pulls, so a ticket can be pre-filled from a template.
CREATE TABLE task_template (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NULL
);

CREATE TABLE task_template_line (
    id               INTEGER PRIMARY KEY,
    template_id      INTEGER NOT NULL REFERENCES task_template(id),
    item_id          INTEGER NOT NULL REFERENCES inventory(item_id),
    default_quantity INTEGER NOT NULL
);

-- Simple key/value runtime config (e.g. usage_visibility = admin_only).
CREATE TABLE app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX idx_audit_occurred        ON audit_log(occurred_at);
CREATE INDEX idx_audit_username        ON audit_log(username);
CREATE INDEX idx_ticket_user           ON ticket(user_id);
CREATE INDEX idx_ticket_date           ON ticket(ticket_date);
CREATE INDEX idx_ticket_line_ticket    ON ticket_line(ticket_id);
CREATE INDEX idx_ttl_template          ON task_template_line(template_id);

-- =====================================================================
-- PURCHASING (purchase-order workflow) + CONTROLLED-SUBSTANCE REGISTER
-- =====================================================================

-- A purchase order moves through draft -> submitted -> ordered -> received
-- (or cancelled). Receiving a line restocks inventory (creates an item_lot,
-- bumps quantity_on_hand, books a 'restock' usage_event). created_by is a soft
-- reference to app_user(id) (no hard FK), consistent with ticket.user_id.
-- A purchase order now moves through an approval workflow:
--   draft -> pending_approval -> approved -> submitted -> ordered -> received
--   (or cancelled / rejected at the appropriate points).
-- approved_by/approved_at record the PI or certifying officer's sign-off;
-- submitted_at marks it sent to the vendor. Receiving a line restocks inventory.
CREATE TABLE purchase_order (
    id           INTEGER PRIMARY KEY,
    vendor       TEXT    NULL,
    status       TEXT    NOT NULL DEFAULT 'draft',
    created_by   INTEGER NULL,                        -- requester; soft ref app_user(id)
    created_at   TIMESTAMP NOT NULL,
    approved_by  INTEGER NULL,                        -- PI / certifying officer; soft ref app_user(id)
    approved_at  TIMESTAMP NULL,
    approver_note TEXT   NULL,
    submitted_at TIMESTAMP NULL,
    ordered_at   TIMESTAMP NULL,
    received_at  TIMESTAMP NULL,
    expected_arrival DATE  NULL,        -- when an ordered PO is expected to arrive
    fund_id      INTEGER   NULL,        -- soft ref fund(id): which grant pays for it
    note         TEXT    NULL
);

CREATE TABLE po_line (
    id           INTEGER PRIMARY KEY,
    po_id        INTEGER NOT NULL REFERENCES purchase_order(id),
    item_id      INTEGER NOT NULL REFERENCES inventory(item_id),
    quantity     INTEGER NOT NULL,
    unit_cost    REAL    NOT NULL DEFAULT 0,
    received_qty INTEGER NOT NULL DEFAULT 0
);

-- DEA-style controlled-substance register: an append-only signed-change log
-- with the running balance after each entry and a witness signature. user_id
-- is a soft reference to app_user(id).
CREATE TABLE controlled_log (
    id            INTEGER PRIMARY KEY,
    item_id       INTEGER NOT NULL REFERENCES inventory(item_id),
    occurred_at   TIMESTAMP NOT NULL,
    user_id       INTEGER NULL,        -- soft ref app_user(id)
    username      TEXT    NULL,        -- copied at write time for readability
    change        INTEGER NOT NULL,    -- signed: negative = dispensed, positive = received
    balance_after INTEGER NOT NULL,    -- running balance after this entry
    reason        TEXT    NULL,        -- procedure / purpose
    witness       TEXT    NULL         -- second-person signature (regulatory requirement)
);

CREATE INDEX idx_po_line_po            ON po_line(po_id);
CREATE INDEX idx_po_line_item          ON po_line(item_id);
CREATE INDEX idx_purchase_order_status ON purchase_order(status);
CREATE INDEX idx_controlled_log_item   ON controlled_log(item_id);
CREATE INDEX idx_controlled_log_time   ON controlled_log(occurred_at);

-- =====================================================================
-- VENDOR CATALOG + SUBSTITUTE GROUPS + DOCUMENT ATTACHMENTS
-- =====================================================================

-- A group of interchangeable products (e.g. "Paraformaldehyde, powder") sourced
-- from different vendors. When the preferred product is on backorder, ordering
-- falls through to the next available member by preference_rank.
CREATE TABLE substitute_group (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    category    TEXT    NULL,
    description TEXT    NULL
);

-- Bundled offline catalog of real vendor products (real catalog numbers, pack
-- sizes, list prices). Rows can be added to inventory in one click, priced for
-- purchase orders, and grouped as substitutes for backorder fall-through.
-- substitute_group_id / preference_rank drive the "default to next vendor" logic;
-- availability is the current supply state.
CREATE TABLE vendor_catalog (
    id                 INTEGER PRIMARY KEY,
    vendor             TEXT    NOT NULL,
    catalog_number     TEXT    NOT NULL,
    product_name       TEXT    NOT NULL,
    category           TEXT    NOT NULL DEFAULT 'other',
    pack_size          TEXT    NULL,          -- e.g. "500 g", "6 x 1 L"
    unit               TEXT    NULL,
    list_price         REAL    NULL,
    sds_url            TEXT    NULL,          -- manufacturer public SDS page
    product_url        TEXT    NULL,          -- product page
    cas_number         TEXT    NULL,
    hazard_class       TEXT    NULL,          -- GHS classes (comma-separated)
    substitute_group_id INTEGER NULL,         -- soft ref substitute_group(id)
    preference_rank    INTEGER NULL,          -- 1 = preferred within the group
    availability       TEXT    NOT NULL DEFAULT 'in_stock'  -- in_stock|backorder|discontinued
);

-- Documents attached to an item, a specific lot, or a purchase order:
-- SDS, Certificate of Analysis, invoice, PO copy, packing slip, other. Either a
-- URL (external link, e.g. a manufacturer SDS) or an uploaded file under
-- web/uploads/docs/<filename>. Exactly one of item_id / lot_id / po_id is set.
CREATE TABLE item_document (
    id           INTEGER PRIMARY KEY,
    item_id      INTEGER NULL REFERENCES inventory(item_id),
    lot_id       INTEGER NULL REFERENCES item_lot(id),
    po_id        INTEGER NULL REFERENCES purchase_order(id),
    kind         TEXT    NOT NULL,            -- sds|coa|invoice|po|packing_slip|other
    label        TEXT    NULL,
    url          TEXT    NULL,                -- external link
    filename     TEXT    NULL,               -- uploaded file under web/uploads/docs/
    uploaded_at  TIMESTAMP NOT NULL,
    uploaded_by  INTEGER NULL                 -- soft ref app_user(id)
);

CREATE INDEX idx_vendor_catalog_group  ON vendor_catalog(substitute_group_id);
CREATE INDEX idx_vendor_catalog_vendor ON vendor_catalog(vendor);
CREATE INDEX idx_item_document_item    ON item_document(item_id);
CREATE INDEX idx_item_document_lot     ON item_document(lot_id);
CREATE INDEX idx_item_document_po      ON item_document(po_id);

-- =====================================================================
-- IN-APP NOTIFICATIONS
-- Generated from live state (low stock, expiring lots, POs awaiting approval,
-- storage-compatibility conflicts). user_id NULL = visible to all managers/admins
-- (an operational alert); a set user_id targets one person. read_at marks it read.
-- Regeneration dedupes on (kind, entity_type, entity_id) so refreshing does not
-- pile up duplicates.
-- =====================================================================
CREATE TABLE notification (
    id           INTEGER PRIMARY KEY,
    created_at   TIMESTAMP NOT NULL,
    user_id      INTEGER NULL,        -- soft ref app_user(id); NULL = broadcast
    kind         TEXT    NOT NULL,    -- low_stock|expiring|approval_pending|compatibility|maintenance_due|other
    severity     TEXT    NOT NULL DEFAULT 'info',   -- info|warn|danger
    message      TEXT    NOT NULL,
    entity_type  TEXT    NULL,
    entity_id    INTEGER NULL,
    link_view    TEXT    NULL,        -- SPA view id to open (e.g. 'inventory','purchasing')
    read_at      TIMESTAMP NULL
);

CREATE INDEX idx_notification_unread ON notification(read_at);
CREATE INDEX idx_notification_dedupe ON notification(kind, entity_type, entity_id);

-- =====================================================================
-- CYCLE COUNT / STOCKTAKE RECONCILIATION
-- A count session snapshots the containers expected under a location (from the
-- spatial map), then staff mark each found/missing or scan codes; extras that
-- weren't expected get added. Closing computes a count-accuracy KPI.
-- =====================================================================
CREATE TABLE count_session (
    id           INTEGER PRIMARY KEY,
    location_id  INTEGER NULL,        -- soft ref location_node(id); NULL = whole lab
    name         TEXT    NULL,
    status       TEXT    NOT NULL DEFAULT 'open',   -- open|closed
    started_by   INTEGER NULL,        -- soft ref app_user(id)
    started_at   TIMESTAMP NOT NULL,
    closed_at    TIMESTAMP NULL,
    note         TEXT    NULL
);

CREATE TABLE count_line (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES count_session(id),
    container_id INTEGER NULL REFERENCES container(id),
    item_id      INTEGER NULL REFERENCES inventory(item_id),
    box_name     TEXT    NULL,
    row          INTEGER NULL,
    col          INTEGER NULL,
    expected     INTEGER NOT NULL DEFAULT 1,
    counted      INTEGER NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|found|missing|extra
    counted_at   TIMESTAMP NULL,
    counted_by   INTEGER NULL
);

CREATE INDEX idx_count_line_session ON count_line(session_id);
CREATE INDEX idx_count_session_status ON count_session(status);

-- =====================================================================
-- KITS / BILL OF MATERIALS (reagent recipes)
-- A kit is a recipe of component consumables. Assembling it N times depletes
-- each component (guarded) and optionally produces an output item, rolling up
-- component cost. Mirrors real buffer/media prep and assay kits.
-- =====================================================================
CREATE TABLE kit (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL UNIQUE,
    description    TEXT    NULL,
    output_item_id INTEGER NULL REFERENCES inventory(item_id),  -- produced item (optional)
    output_qty     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE kit_line (
    id        INTEGER PRIMARY KEY,
    kit_id    INTEGER NOT NULL REFERENCES kit(id),
    item_id   INTEGER NOT NULL REFERENCES inventory(item_id),
    quantity  INTEGER NOT NULL
);

CREATE INDEX idx_kit_line_kit ON kit_line(kit_id);

-- =====================================================================
-- EQUIPMENT REGISTRY + BOOKING + MAINTENANCE / CALIBRATION
-- =====================================================================
CREATE TABLE equipment (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT    NOT NULL,
    category              TEXT    NULL,     -- centrifuge, microscope, PCR, freezer, cabinet, ...
    make_model            TEXT    NULL,
    serial_number         TEXT    NULL,
    location_id           INTEGER NULL,     -- soft ref location_node(id)
    status                TEXT    NOT NULL DEFAULT 'operational',  -- operational|maintenance|out_of_service
    purchase_date         DATE    NULL,
    service_interval_days INTEGER NULL,     -- calibration/PM cadence
    last_service_date     DATE    NULL,
    next_service_date     DATE    NULL,     -- when the next service is due
    cleanup_url           TEXT    NULL,     -- link to cleaning/decontamination procedure (SOP)
    note                  TEXT    NULL
);

CREATE TABLE equipment_reservation (
    id           INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    user_id      INTEGER NULL,             -- soft ref app_user(id)
    starts_at    TIMESTAMP NOT NULL,
    ends_at      TIMESTAMP NOT NULL,
    purpose      TEXT    NULL,
    created_at   TIMESTAMP NOT NULL
);

CREATE TABLE equipment_maintenance (
    id           INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    kind         TEXT    NULL,             -- calibration|repair|preventive|inspection
    performed_at DATE    NULL,
    performed_by TEXT    NULL,
    note         TEXT    NULL,
    next_due     DATE    NULL
);

CREATE INDEX idx_equipment_status      ON equipment(status);
CREATE INDEX idx_equip_resv_equipment  ON equipment_reservation(equipment_id);
CREATE INDEX idx_equip_resv_time       ON equipment_reservation(starts_at, ends_at);
CREATE INDEX idx_equip_maint_equipment ON equipment_maintenance(equipment_id);

-- =====================================================================
-- COMPUTERS / IT: hardware asset register + software licenses.
-- it_asset tracks machines/printers/network gear (like equipment, but with
-- warranty + who it's assigned to); software_license tracks software/subscriptions
-- with product codes, seat counts, renewal cost, associated server cost, and an
-- expiry date surfaced in notifications.
-- =====================================================================
CREATE TABLE it_asset (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    kind          TEXT    NULL,     -- desktop|laptop|server|printer|network|peripheral|other
    make_model    TEXT    NULL,
    serial_number TEXT    NULL,
    location_id   INTEGER NULL,     -- soft ref location_node(id)
    assigned_to   INTEGER NULL,     -- soft ref app_user(id)
    purchase_date DATE    NULL,
    warranty_end  DATE    NULL,
    status        TEXT    NOT NULL DEFAULT 'in_service',  -- in_service|repair|retired
    note          TEXT    NULL
);

CREATE TABLE software_license (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL,
    vendor            TEXT    NULL,
    product_code      TEXT    NULL,   -- license key / product / order code
    seats             INTEGER NULL,   -- seats/installs allowed
    assigned_asset_id INTEGER NULL,   -- soft ref it_asset(id) (optional)
    expiry_date       DATE    NULL,   -- license/subscription expiry (drives alerts)
    annual_cost       REAL    NULL,   -- renewal / subscription cost
    server_cost       REAL    NULL,   -- associated server / hosting cost
    note              TEXT    NULL
);

CREATE INDEX idx_it_asset_status    ON it_asset(status);
CREATE INDEX idx_software_expiry     ON software_license(expiry_date);

-- =====================================================================
-- GLASSWARE / DISHWARE CHECK-OUT: shared labware that members borrow and
-- return, so everyone can see who currently holds each piece. glassware_item is
-- the physical object; glassware_checkout is a loan (returned_at NULL = still out).
-- =====================================================================
CREATE TABLE glassware_item (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,     -- e.g. "1 L Erlenmeyer flask #3"
    kind        TEXT    NULL,         -- flask|beaker|bottle|dish|cylinder|graduated|other
    identifier  TEXT    NULL,         -- asset tag / etched label
    location_id INTEGER NULL,         -- home location (soft ref location_node)
    status      TEXT    NOT NULL DEFAULT 'available',  -- available|checked_out|broken|retired
    note        TEXT    NULL
);

CREATE TABLE glassware_checkout (
    id             INTEGER PRIMARY KEY,
    glassware_id   INTEGER NOT NULL REFERENCES glassware_item(id),
    user_id        INTEGER NULL,        -- who holds it (soft ref app_user)
    checked_out_at TIMESTAMP NOT NULL,
    due_at         TIMESTAMP NULL,
    returned_at    TIMESTAMP NULL,      -- NULL = still checked out
    purpose        TEXT    NULL,
    note           TEXT    NULL
);

CREATE INDEX idx_glass_checkout_item ON glassware_checkout(glassware_id);
CREATE INDEX idx_glass_checkout_open ON glassware_checkout(returned_at);

-- =====================================================================
-- GRANT / FUND COST ALLOCATION + BUDGET BURN-DOWN
-- Funds hold a budget; charges (from received POs, ticket usage, or manual
-- entries) draw it down. Remaining = budget - SUM(charges).
-- =====================================================================
CREATE TABLE fund (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,          -- e.g. R01-NS123456
    sponsor     TEXT    NULL,              -- NIH, NSF, internal, ...
    budget      REAL    NOT NULL DEFAULT 0,
    start_date  DATE    NULL,
    end_date    DATE    NULL,
    note        TEXT    NULL
);

CREATE TABLE fund_charge (
    id           INTEGER PRIMARY KEY,
    fund_id      INTEGER NOT NULL REFERENCES fund(id),
    amount       REAL    NOT NULL,
    source_type  TEXT    NULL,             -- purchase_order|ticket|manual
    source_id    INTEGER NULL,
    description  TEXT    NULL,
    charged_at   TIMESTAMP NOT NULL,
    charged_by   INTEGER NULL              -- soft ref app_user(id)
);

CREATE INDEX idx_fund_charge_fund ON fund_charge(fund_id);

-- =====================================================================
-- PREPARATIONS (in-house mixes like aCSF, PBS, PFA) -- recipe + dated batches
-- A preparation is a recipe of component reagents. "Making a batch" consumes the
-- components from inventory and records a tracked batch with its OWN prep date and
-- expiry, so home-made reagents are tracked and alerted on just like purchased ones.
-- =====================================================================
CREATE TABLE preparation (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,   -- e.g. "aCSF", "4% PFA", "PBS 1x"
    description     TEXT    NULL,
    category        TEXT    NULL,              -- buffer|fixative|media|other
    shelf_life_days INTEGER NULL,              -- default days-to-expiry for a new batch
    sop_url         TEXT    NULL,              -- link to the lab-approved SOP for making it
    note            TEXT    NULL
);

CREATE TABLE preparation_line (
    id             INTEGER PRIMARY KEY,
    preparation_id INTEGER NOT NULL REFERENCES preparation(id),
    item_id        INTEGER NOT NULL REFERENCES inventory(item_id),
    quantity       INTEGER NOT NULL
);

CREATE TABLE preparation_batch (
    id             INTEGER PRIMARY KEY,
    preparation_id INTEGER NOT NULL REFERENCES preparation(id),
    lot_label      TEXT    NULL,               -- e.g. "PBS-2607A"
    made_by        INTEGER NULL,               -- soft ref app_user(id)
    made_at        TIMESTAMP NOT NULL,
    expiry_date    DATE    NULL,
    amount         TEXT    NULL,               -- e.g. "1 L", "500 mL"
    status         TEXT    NOT NULL DEFAULT 'in_use',  -- in_use|used|discarded
    note           TEXT    NULL
);

CREATE INDEX idx_prep_line_prep    ON preparation_line(preparation_id);
CREATE INDEX idx_prep_batch_prep   ON preparation_batch(preparation_id);
CREATE INDEX idx_prep_batch_expiry ON preparation_batch(expiry_date);

-- =====================================================================
-- LAB MAINTENANCE -- recurring chores (cleaning, autoclaving, DI-water fills)
-- Each chore has a location and a recurrence; completing it logs who/when and
-- advances the next-due date. Chores coming due drive maintenance notifications.
-- =====================================================================
CREATE TABLE chore (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    category     TEXT    NULL,        -- cleaning|autoclave|water|calibration|stocking|other
    location_id  INTEGER NULL,        -- soft ref location_node(id): where it's done
    interval_days INTEGER NULL,       -- recurrence cadence (NULL = one-off / as-needed)
    last_done    DATE    NULL,
    next_due     DATE    NULL,
    instructions TEXT    NULL,        -- how to do it (or a link to the SOP)
    note         TEXT    NULL,
    status       TEXT    NOT NULL DEFAULT 'active'  -- active | deprecated (retired, keeps history)
);

CREATE TABLE chore_log (
    id        INTEGER PRIMARY KEY,
    chore_id  INTEGER NOT NULL REFERENCES chore(id),
    done_by   INTEGER NULL,           -- soft ref app_user(id)
    done_at   TIMESTAMP NOT NULL,
    note      TEXT    NULL
);

CREATE INDEX idx_chore_next_due  ON chore(next_due);
CREATE INDEX idx_chore_log_chore ON chore_log(chore_id);
