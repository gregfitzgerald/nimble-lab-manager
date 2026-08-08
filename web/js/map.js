// map.js -- Spatial map: schematic floor plan (SVG) + freezer box grids.
// Headline feature. Hand-rolled SVG, no libraries. Uses only ctx + design tokens.

export const view = { id: "map", label: "Map", fullBleed: true };

// -------------------------------------------------------------------------
// One-time scoped styles. Reference ONLY design-system tokens so the map
// stays visually consistent with the shell in light and dark themes.
// -------------------------------------------------------------------------
const STYLE_ID = "map-scoped-styles";
function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
  /* Full-bleed: the wrap fills the whole right panel (#view-root is a full-height
     flex column via .full-bleed) and the stage grows to eat all leftover space.
     The shell chain is min-height (not a definite height), so we bound the wrap to
     the viewport minus the 42px sticky topbar; that gives flex:1 something to cap
     against and keeps the plan on-screen instead of growing the page. */
  .map-wrap { display:flex; flex-direction:column; gap:12px; flex:1 1 auto;
    min-height:0; height:calc(100vh - 42px); max-height:calc(100vh - 42px);
    padding:14px 12px; box-sizing:border-box; }
  .map-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .map-crumbs { display:flex; align-items:center; gap:6px; flex-wrap:wrap;
    font-size:14px; color:var(--text-muted); }
  .map-crumb { cursor:pointer; color:var(--text-muted); background:none; border:none;
    padding:2px 4px; font:inherit; border-radius:6px; }
  .map-crumb:hover { color:var(--text); background:var(--accent-soft); }
  .map-crumb.current { color:var(--text); cursor:default; font-weight:600; }
  .map-crumb.current:hover { background:none; }
  .map-crumb-sep { color:var(--border); }
  .map-spacer { flex:1 1 auto; }
  .map-floorsel { padding:6px 10px; border:1px solid var(--border); border-radius:8px;
    background:var(--bg-elev); color:var(--text); font:inherit; font-size:13px;
    cursor:pointer; }
  .map-tools { display:inline-flex; align-items:center; gap:8px; flex-wrap:wrap; }

  .map-stage { position:relative; background:var(--bg-elev); border:1px solid var(--border);
    border-radius:var(--radius); overflow:hidden; box-shadow:var(--shadow);
    flex:1 1 auto; min-height:280px; display:flex; flex-direction:column; }
  .map-svg { display:block; width:100%; flex:1 1 auto; min-height:0; touch-action:none;
    cursor:default; background:var(--bg);
    user-select:none; -webkit-user-select:none; -moz-user-select:none; }
  .map-svg text { user-select:none; -webkit-user-select:none; }

  /* Floor Plan body: left tree sidebar + stage filling the rest. */
  .map-body { display:flex; gap:12px; flex:1 1 auto; min-height:0; }
  .map-tree { flex:0 0 240px; width:240px; overflow:auto; min-height:0;
    background:var(--bg-elev); border:1px solid var(--border);
    border-radius:var(--radius); box-shadow:var(--shadow); padding:6px 0;
    font-size:13px; }
  .map-tree-empty { padding:12px 14px; color:var(--text-muted); font-size:12px; }
  .map-tnode { display:flex; align-items:center; gap:4px; padding:4px 8px;
    cursor:pointer; color:var(--text); white-space:nowrap; border:none;
    background:none; width:100%; text-align:left; font:inherit; font-size:13px; }
  .map-tnode:hover { background:var(--accent-soft); }
  .map-tnode.selected { background:var(--accent-soft); font-weight:600; }
  .map-tcaret { display:inline-flex; width:14px; justify-content:center;
    color:var(--text-muted); flex:0 0 14px; }
  .map-tcaret.leaf { visibility:hidden; }
  .map-tname { overflow:hidden; text-overflow:ellipsis; }
  .map-thint { color:var(--text-muted); font-size:11px; margin-left:auto;
    padding-left:8px; }
  @media (max-width:768px) { .map-body { flex-direction:column; }
    .map-tree { flex:0 0 auto; width:auto; max-height:180px; } }

  /* Deep-link "locate" highlight: a distinct accent outline that survives zoom. */
  .map-unit.map-locate > rect, .map-room.map-locate > rect {
    stroke:var(--accent); stroke-width:3; }
  .well-locate { outline:3px solid var(--accent); outline-offset:-1px;
    box-shadow:0 0 0 2px var(--bg); }
  /* Sub-container "contains" affordance + plain suitability tag (neutral). */
  .map-unit .u-sub-badge { fill:var(--text-muted); font-weight:600; pointer-events:none; }
  .map-unit .u-suit-tag { fill:var(--text-muted); font-weight:500; pointer-events:none; }
  /* Placement warning outline reuses the conflict/danger styling. */
  .map-unit.has-placement > rect { stroke:var(--danger); stroke-width:3; }

  /* Floor plan units. Strokes are non-scaling so they stay legible whether the
     coordinate space is the abstract 0..1000 canvas or a large image in pixels. */
  .map-room > rect, .map-unit > rect, .map-resize-handle, .map-grid-lines line,
  .map-alert-dot, .map-conflict-badge circle, .map-conflict-badge text {
    vector-effect:non-scaling-stroke; }
  .map-svg.has-image image { pointer-events:none; user-select:none; }
  .map-svg.has-image .map-room > rect { fill:transparent; }
  .map-svg.has-image .map-unit > rect { fill-opacity:.85; }
  .map-room > rect { fill:var(--bg-elev); stroke:var(--border); stroke-width:2; }
  .map-room > text { fill:var(--text-muted); font-weight:600; letter-spacing:.02em; }
  .map-unit { cursor:pointer; }
  .map-unit > rect { fill:var(--bg-elev); stroke:var(--border); stroke-width:2;
    transition:fill .12s, stroke .12s; }
  .map-unit:hover > rect { fill:var(--accent-soft); stroke:var(--accent); }
  .map-unit > text { fill:var(--text); font-weight:600; pointer-events:none; }
  .map-unit > text.sub { fill:var(--text-muted); font-weight:500; }
  .map-unit.kind-freezer > rect, .map-unit.kind-fridge > rect { fill:var(--accent-soft); }
  .map-unit.has-expiring > rect { stroke:var(--warn); stroke-width:3; }
  .map-unit.has-misplaced > rect { stroke:var(--danger); stroke-width:3; }
  .map-unit.has-misplaced.has-expiring > rect { stroke:var(--danger); }
  /* Incompatible-hazard conflict: the ONE genuine problem the map colors. */
  .map-unit.has-conflict > rect { stroke:var(--danger); stroke-width:3; }
  .map-alert-dot { pointer-events:none; }
  .map-conflict-badge { pointer-events:none; }

  /* Node (drill) tiles */
  .map-tiles { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
    gap:12px; padding:16px; }
  .map-tile { text-align:left; cursor:pointer; background:var(--bg-elev);
    border:1px solid var(--border); border-radius:var(--radius); padding:14px;
    display:flex; flex-direction:column; gap:6px; transition:border-color .12s, transform .08s;
    color:var(--text); font:inherit; }
  .map-tile:hover { border-color:var(--accent); transform:translateY(-1px); }
  .map-tile .t-name { font-weight:600; }
  .map-tile .t-kind { font-size:12px; color:var(--text-muted); text-transform:uppercase;
    letter-spacing:.05em; }
  .map-tile.has-misplaced { border-color:var(--danger); }

  /* Grid view */
  .map-grid-scroll { overflow:auto; padding:16px; flex:1 1 auto; min-height:0; }
  .map-grid { display:grid; gap:4px; width:max-content; margin:0 auto; }
  .map-grid .gh { font-size:11px; color:var(--text-muted); display:flex;
    align-items:center; justify-content:center; }
  .well { width:34px; height:34px; border-radius:7px; border:1px solid var(--border);
    background:var(--empty); cursor:default; transition:transform .06s, box-shadow .06s;
    position:relative; }
  .well-occupied { background:var(--occupied); cursor:pointer; }
  .well-expiring { background:var(--warn); cursor:pointer; }
  .well-expired  { background:var(--danger); cursor:pointer; }
  .well-empty    { background:var(--empty); }
  .well-misplaced { outline:3px solid var(--danger); outline-offset:-1px;
    box-shadow:0 0 0 2px var(--bg); }
  .well.clickable:hover { transform:scale(1.12); box-shadow:var(--shadow); z-index:2; }

  .map-legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px;
    color:var(--text-muted); padding:0 16px 14px; }
  .map-legend span { display:inline-flex; align-items:center; gap:6px; }
  .map-legend i { width:14px; height:14px; border-radius:4px; display:inline-block; }

  /* Misplaced focus mode */
  .focus-mis .map-unit:not(.has-misplaced) { opacity:.30; }
  .focus-mis .map-tile:not(.has-misplaced) { opacity:.35; }
  .focus-mis .well:not(.well-misplaced) { opacity:.35; }

  .map-tip { position:fixed; z-index:50; pointer-events:none; max-width:240px;
    background:var(--bg-elev); color:var(--text); border:1px solid var(--border);
    border-radius:8px; box-shadow:var(--shadow); padding:8px 10px; font-size:12px;
    line-height:1.45; opacity:0; transition:opacity .08s; }
  .map-tip.show { opacity:1; }
  .map-tip .tt { font-weight:600; margin-bottom:2px; }
  .map-tip .tr { color:var(--text-muted); }
  .map-empty { padding:40px; text-align:center; color:var(--text-muted); }

  /* Layout edit mode (manager+) */
  .map-stage.editing { outline:2px dashed var(--accent); outline-offset:-2px; }
  .map-editbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:8px 12px; border:1px solid var(--accent); border-radius:var(--radius);
    background:var(--accent-soft); font-size:13px; color:var(--text); }
  .map-editbar .eb-hint { color:var(--text-muted); }
  .map-editbar .eb-sel { font-weight:600; }
  .map-grid-lines line { stroke:var(--border); stroke-width:1; opacity:.35;
    pointer-events:none; }
  .map-unit.editable, .map-room.editable { cursor:move; }
  .map-unit.editable:hover > rect { fill:var(--bg-elev); }
  .map-unit.selected > rect, .map-room.selected > rect {
    stroke:var(--accent); stroke-width:3; stroke-dasharray:6 4; }
  .map-resize-handle { fill:var(--accent); stroke:var(--bg-elev); stroke-width:2;
    cursor:nwse-resize; }
  .map-addform { display:flex; align-items:flex-end; gap:10px; flex-wrap:wrap;
    padding:10px 12px; border:1px solid var(--border); border-radius:var(--radius);
    background:var(--bg-elev); box-shadow:var(--shadow); }
  .map-addform label { display:flex; flex-direction:column; gap:4px; font-size:11px;
    color:var(--text-muted); text-transform:uppercase; letter-spacing:.05em; }
  .map-addform input, .map-addform select { padding:6px 8px; border:1px solid var(--border);
    border-radius:8px; background:var(--bg); color:var(--text); font:inherit; font-size:13px; }
  .map-addform input[type=number] { width:64px; }
  .map-addform .haz-grid { display:grid; grid-template-columns:repeat(2,auto);
    gap:2px 10px; text-transform:none; letter-spacing:0; }
  .map-addform .haz-grid label { flex-direction:row; align-items:center; gap:5px;
    text-transform:none; letter-spacing:0; font-size:12px; color:var(--text); }
  .map-addform .haz-grid input { padding:0; }

  /* Contents panel (below the map): everything stored at/under a node. */
  .map-contents { border:1px solid var(--border); border-radius:var(--radius);
    background:var(--bg-elev); box-shadow:var(--shadow); overflow:hidden; }
  .map-contents-head { padding:10px 14px; border-bottom:1px solid var(--border);
    display:flex; flex-direction:column; gap:4px; }
  .map-contents-title { font-weight:600; color:var(--text); }
  .map-path { font-size:12px; color:var(--text-muted); }
  .map-path .sep { color:var(--border); padding:0 4px; }
  .map-contents-body { max-height:340px; overflow:auto; }
  .map-ctab { width:100%; border-collapse:collapse; font-size:13px; }
  .map-ctab th, .map-ctab td { text-align:left; padding:7px 12px;
    border-bottom:1px solid var(--border); white-space:nowrap; }
  .map-ctab th { color:var(--text-muted); font-weight:600; font-size:11px;
    text-transform:uppercase; letter-spacing:.05em; position:sticky; top:0;
    background:var(--bg-elev); }
  .map-ctab tbody tr { cursor:pointer; }
  .map-ctab tbody tr:hover { background:var(--accent-soft); }
  .map-ctab .c-item { color:var(--text); font-weight:600; }
  .map-ctab .c-muted { color:var(--text-muted); }
  .map-ctab .c-bad { color:var(--danger); }
  .map-ctab .c-warn { color:var(--warn); }

  /* Safety propagation in the contents panel. Danger BORDER on the conflict
     block is the only color here; the plain hazard note stays neutral. */
  .map-cwarn { border:1px solid var(--danger); border-radius:var(--radius);
    margin:10px 14px 4px; padding:8px 10px; }
  .map-cwarn-title { font-weight:600; font-size:11px; text-transform:uppercase;
    letter-spacing:.05em; color:var(--text); margin-bottom:6px; }
  .map-cwarn-line { font-size:13px; margin-bottom:6px; }
  .map-cwarn-line:last-child { margin-bottom:0; }
  .map-cwarn.placement { border-color:var(--warn); }
  .map-cwarn .cw-head { color:var(--text); font-weight:600; }
  .map-cwarn .cw-items { color:var(--text-muted); font-size:12px; margin-top:2px; }
  .map-haznote { margin:10px 14px 4px; padding:6px 10px; border:1px solid var(--border);
    border-radius:var(--radius); font-size:13px; color:var(--text-muted); }

  /* Right-click context menu (spartan bordered box, plain rows). */
  .map-ctxmenu { position:fixed; z-index:60; min-width:160px; padding:4px;
    background:var(--bg-elev); border:1px solid var(--border);
    border-radius:8px; box-shadow:var(--shadow); font-size:13px; }
  .map-ctxmenu .cm-head { padding:6px 10px; color:var(--text-muted); font-size:11px;
    text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid var(--border);
    margin-bottom:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width:220px; }
  .map-ctxmenu button { display:block; width:100%; text-align:left; padding:7px 10px;
    background:none; border:none; color:var(--text); font:inherit; font-size:13px;
    cursor:pointer; border-radius:6px; }
  .map-ctxmenu button:hover { background:var(--accent-soft); color:var(--text); }
  .map-ctxmenu button.cm-danger { color:var(--danger); }
  .map-ctxmenu button.cm-danger:hover { background:var(--danger); color:var(--bg-elev); }
  `;
  document.head.appendChild(s);
}

// -------------------------------------------------------------------------
// Small helpers
// -------------------------------------------------------------------------
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(name, attrs) {
  const el = document.createElementNS(SVGNS, name);
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}
// Truncate an SVG label with an ellipsis so it never overflows its rect. SVG
// text has no CSS clipping, so we estimate character width from the font size.
function fitLabel(text, maxWidth, fontSize) {
  const s = String(text == null ? "" : text);
  const charW = fontSize * 0.58;
  const maxChars = Math.floor(maxWidth / charW);
  if (maxChars >= s.length) return s;
  if (maxChars <= 1) return s.slice(0, 1);
  return s.slice(0, maxChars - 1) + "…";
}
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function daysUntil(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + (dateStr.length <= 10 ? "T00:00:00" : ""));
  if (isNaN(d)) return null;
  const now = new Date();
  const a = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const b = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((a - b) / 86400000);
}
// Location kinds accepted by the backend (mirrors schema.sql). Ordered roughly
// large -> small so the add/edit picker reads as a containment hierarchy.
const KINDS = [
  "building", "zone", "room", "bench", "cabinet", "fridge", "freezer",
  "shelf", "rack", "drawer", "tower", "incubator", "tank", "box", "cage",
];
// Temperature ratings + hazard keywords a compartment can advertise (mirrors
// the location schema). Used by the manager edit form and the on-plan tags.
const TEMP_RATINGS = ["", "RT", "4C", "-20C", "-80C", "LN2", "other"];
const HAZARD_KINDS = ["flammable", "oxidizer", "corrosive", "toxic",
  "irritant", "acid", "base", "water-reactive"];
// Edit-mode snap grid, in schematic (0..1000) user units. Image floors scale
// this by their space factor so snapping density stays visually consistent.
const SNAP = 20;
function snapTo(v, step) { return Math.round(v / step) * step; }
// ctx.api has no delete/multipart verbs; mirror its request semantics here.
// Never set Content-Type for FormData bodies: the browser must add the
// multipart boundary itself.
async function apiFetch(path, opts) {
  const res = await fetch(path, Object.assign({ credentials: "same-origin" }, opts));
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch (_) { data = text; } }
  if (!res.ok) {
    const detail = (data && data.detail) ||
      (typeof data === "string" && data) || res.statusText;
    throw new Error(detail || ("HTTP " + res.status));
  }
  return data;
}
function apiDelete(path) { return apiFetch(path, { method: "DELETE" }); }
// Load an image file locally to read its natural pixel dimensions.
function readImageSize(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      URL.revokeObjectURL(url);
      if (w > 0 && h > 0) resolve({ w, h });
      else reject(new Error("could not read image dimensions"));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("file is not a readable image"));
    };
    img.src = url;
  });
}
// walk a nested location tree, calling fn(node, ancestors[])
function walkTree(nodes, fn, anc = []) {
  for (const n of nodes || []) {
    fn(n, anc);
    if (n.children && n.children.length) walkTree(n.children, fn, anc.concat(n));
  }
}

// -------------------------------------------------------------------------
// render
// -------------------------------------------------------------------------
export async function render(root, ctx, params) {
  ensureStyles();
  const { api } = ctx;

  // module-scoped state
  const state = {
    floors: [],
    floor: null,
    tree: [], // full location tree (for edit-mode parent picker)
    misplacedRaw: [],
    expiringRaw: [],
    misplacedBoxIds: new Set(), // location_node ids of boxes with misplaced containers
    misplacedBoxNames: new Set(),
    unitAlerts: new Map(), // floor-unit id -> {mis:bool, exp:bool}
    conflictLocIds: new Set(), // location ids with incompatible-hazard conflicts
    placementLocIds: new Set(), // location ids with placement/suitability warnings
    treeExpanded: new Set(), // sidebar tree: ids of expanded nodes
    childCount: new Map(), // location id -> direct child count (from tree)
    locateUnitId: null, // deep-link: on-plan unit to outline until next nav
    locateWell: null, // deep-link: {boxId,row,col} well to outline in a grid
    editUnitId: null, // manager form: id being edited (null = creating)
    focusMis: false,
    editMode: false, // manager+ layout editing (floor plan only)
    selectedUnitId: null,
    view: { x: 0, y: 0, w: 1000, h: 1000 }, // svg viewBox for pan/zoom
    fullView: { x: 0, y: 0, w: 1000, h: 1000 },
    // Coordinate space of the current floor ("user units"):
    // image floors use image pixels, schematic floors use the 0..1000 canvas.
    // k scales schematic-tuned constants (fonts, handles, snap) into the space.
    space: { W: 1000, H: 1000, k: 1, snap: SNAP, image: false },
    viewFloorId: null, // floor the current pan/zoom view belongs to
    seedRect: null, // clicked map coords seeded from the context menu "Add ..."
    crumbs: [{ id: null, name: "Floor plan" }], // navigation stack
  };

  // Derive the drawing space for a floor. When image_url is set, map coords
  // are PIXELS in the image's natural (image_width x image_height) space;
  // otherwise they live in the abstract 0..1000 schematic canvas.
  function floorSpace(f) {
    if (f && f.image_url) {
      const W = Number(f.image_width) || 1000;
      const H = Number(f.image_height) || 1000;
      const k = Math.max(W, H) / 1000;
      return { W, H, k, snap: Math.max(1, Math.round(SNAP * k)), image: true };
    }
    const W = (f && f.width) || 1000;
    const H = (f && f.height) || 1000;
    return { W, H, k: 1, snap: SNAP, image: false };
  }
  function rootCrumbName() {
    if (state.floors.length > 1 && state.floor && state.floor.name) {
      return state.floor.name;
    }
    return "Floor plan";
  }
  const canEdit = !!(ctx.user &&
    (ctx.user.role === "manager" || ctx.user.role === "admin"));

  // shared tooltip element
  const tip = el("div", "map-tip");
  document.body.appendChild(tip);
  // shared right-click context menu element (built on demand, body-anchored)
  const ctxMenu = el("div", "map-ctxmenu");
  const onDocDown = (ev) => {
    if (ctxMenu.parentNode && !ctxMenu.contains(ev.target)) closeCtxMenu();
  };
  const onDocKey = (ev) => { if (ev.key === "Escape") closeCtxMenu(); };
  document.addEventListener("pointerdown", onDocDown, true);
  document.addEventListener("keydown", onDocKey);
  const cleanup = () => {
    tip.remove();
    closeCtxMenu();
    document.removeEventListener("pointerdown", onDocDown, true);
    document.removeEventListener("keydown", onDocKey);
  };
  // remove tooltip if the view is torn down (root emptied by router)
  const mo = new MutationObserver(() => {
    if (!root.isConnected || !wrap.isConnected) { cleanup(); mo.disconnect(); }
  });

  const wrap = el("div", "map-wrap");
  root.appendChild(wrap);
  // Observe the router's container, not this view's own node: the router tears
  // views down with `container.innerHTML = ""`, which mutates the PARENT. Watching
  // `root` meant the callback never fired, so the body-level tooltip node and the
  // two document listeners below leaked on every visit to the map.
  mo.observe(root.parentNode || document.body, { childList: true });

  // --- top bar: breadcrumb + floor selector + controls ---
  const bar = el("div", "map-bar");
  const crumbs = el("nav", "map-crumbs");
  const floorSel = document.createElement("select");
  floorSel.className = "map-floorsel";
  floorSel.setAttribute("aria-label", "Floor");
  floorSel.style.display = "none";
  floorSel.addEventListener("change", () => {
    const f = state.floors.find((x) => String(x.floor_id) === floorSel.value);
    if (!f || f === state.floor) return;
    state.floor = f;
    state.selectedUnitId = null;
    state.crumbs = [{ id: null, name: rootCrumbName() }];
    computeAlertOverlays(state.tree, state.misplacedRaw, state.expiringRaw);
    renderCrumbs();
    drawFloor();
  });
  const spacer = el("div", "map-spacer");
  const misBtn = el("button", "btn btn-ghost", "Highlight misplaced");
  misBtn.type = "button";
  const backBtn = el("button", "btn btn-ghost", "Back");
  backBtn.type = "button";
  const zoomInBtn = el("button", "btn btn-ghost", "Zoom in");
  zoomInBtn.type = "button";
  zoomInBtn.setAttribute("aria-label", "Zoom in");
  const zoomOutBtn = el("button", "btn btn-ghost", "Zoom out");
  zoomOutBtn.type = "button";
  zoomOutBtn.setAttribute("aria-label", "Zoom out");
  const resetViewBtn = el("button", "btn btn-ghost", "Reset view");
  resetViewBtn.type = "button";
  let editBtn = null;
  // Manager/admin-only layout tools: floor plan image upload/remove and
  // portable layout import/export. Never built for viewer/member roles.
  let toolsGrp = null, removeImgBtn = null;
  if (canEdit) {
    editBtn = el("button", "btn btn-ghost", "Edit layout");
    editBtn.type = "button";
    editBtn.addEventListener("click", () => setEditMode(!state.editMode));

    toolsGrp = el("span", "map-tools");
    const uploadBtn = el("button", "btn btn-ghost btn-sm", "Upload floor plan");
    uploadBtn.type = "button";
    removeImgBtn = el("button", "btn btn-ghost btn-sm", "Remove image");
    removeImgBtn.type = "button";
    removeImgBtn.style.display = "none";
    const exportBtn = el("button", "btn btn-ghost btn-sm", "Export layout");
    exportBtn.type = "button";
    const importBtn = el("button", "btn btn-ghost btn-sm", "Import layout");
    importBtn.type = "button";
    const uploadInput = document.createElement("input");
    uploadInput.type = "file";
    uploadInput.accept = "image/*";
    uploadInput.style.display = "none";
    const importInput = document.createElement("input");
    importInput.type = "file";
    importInput.accept = ".json,application/json";
    importInput.style.display = "none";
    uploadBtn.addEventListener("click", () => uploadInput.click());
    importBtn.addEventListener("click", () => importInput.click());
    uploadInput.addEventListener("change", () => {
      const f = uploadInput.files && uploadInput.files[0];
      uploadInput.value = "";
      if (f) uploadPlan(f);
    });
    importInput.addEventListener("change", () => {
      const f = importInput.files && importInput.files[0];
      importInput.value = "";
      if (f) importLayout(f);
    });
    removeImgBtn.addEventListener("click", removeImage);
    exportBtn.addEventListener("click", exportLayout);
    toolsGrp.append(uploadBtn, removeImgBtn, exportBtn, importBtn,
      uploadInput, importInput);
  }
  bar.append(crumbs, floorSel, spacer);
  if (toolsGrp) bar.appendChild(toolsGrp);
  if (editBtn) bar.appendChild(editBtn);
  bar.append(zoomInBtn, zoomOutBtn, resetViewBtn, backBtn, misBtn);
  wrap.appendChild(bar);

  // Edit-mode banner + add-unit form (manager+ only; hidden in view mode).
  const editBar = el("div", "map-editbar");
  editBar.style.display = "none";
  const addForm = el("div", "map-addform");
  addForm.style.display = "none";
  if (canEdit) {
    wrap.appendChild(editBar);
    wrap.appendChild(addForm);
  }

  // Body: left tree sidebar + the stage filling the rest.
  const mapBody = el("div", "map-body");
  const treePanel = el("nav", "map-tree");
  treePanel.setAttribute("aria-label", "Location tree");
  const stage = el("div", "map-stage");
  mapBody.append(treePanel, stage);
  wrap.appendChild(mapBody);

  // Contents panel: a bordered table of everything stored at/under the node the
  // user has drilled into. Hidden on the floor-plan root; filled by loadContents.
  const contentsPanel = el("div", "map-contents");
  contentsPanel.style.display = "none";
  wrap.appendChild(contentsPanel);
  // Guards against a slow contents fetch landing after the user navigated on.
  let contentsToken = 0;

  misBtn.addEventListener("click", () => {
    state.focusMis = !state.focusMis;
    stage.classList.toggle("focus-mis", state.focusMis);
    misBtn.classList.toggle("btn-primary", state.focusMis);
    misBtn.classList.toggle("btn-ghost", !state.focusMis);
  });
  backBtn.addEventListener("click", () => {
    if (state.crumbs.length > 1) {
      clearLocate();
      state.crumbs.pop();
      const dest = state.crumbs[state.crumbs.length - 1];
      openCrumb(dest, state.crumbs.length - 1);
      renderTree();
    }
  });

  function renderCrumbs() {
    crumbs.innerHTML = "";
    state.crumbs.forEach((c, i) => {
      if (i > 0) crumbs.appendChild(el("span", "map-crumb-sep", "/"));
      const last = i === state.crumbs.length - 1;
      const b = el("button", "map-crumb" + (last ? " current" : ""), c.name);
      b.type = "button";
      if (!last) b.addEventListener("click", () => {
        clearLocate();
        state.crumbs = state.crumbs.slice(0, i + 1);
        openCrumb(c, i);
        renderTree();
      });
      crumbs.appendChild(b);
    });
    backBtn.disabled = state.crumbs.length <= 1;
    const atRoot = state.crumbs.length === 1;
    resetViewBtn.style.display = atRoot ? "" : "none";
    zoomInBtn.style.display = atRoot ? "" : "none";
    zoomOutBtn.style.display = atRoot ? "" : "none";
    // Layout editing / floor tools only apply to the floor-plan root.
    if (editBtn) editBtn.style.display = atRoot ? "" : "none";
    if (toolsGrp) toolsGrp.style.display = atRoot ? "" : "none";
    floorSel.style.display = atRoot && state.floors.length > 1 ? "" : "none";
  }

  function openCrumb(c, idx) {
    if (idx === 0 || c.id == null) drawFloor();
    else openNode(c.id, false);
  }

  // --------------------------------------------------------------
  // Left sidebar location tree (rooms > cabinets/racks > boxes)
  // --------------------------------------------------------------
  function renderTree() {
    treePanel.innerHTML = "";
    if (!state.tree || !state.tree.length) {
      treePanel.appendChild(el("div", "map-tree-empty", "No locations yet."));
      return;
    }
    const build = (nodes, depth) => {
      for (const n of nodes || []) {
        const kids = n.children || [];
        const hasKids = kids.length > 0;
        const expanded = state.treeExpanded.has(n.id);
        const row = el("button", "map-tnode");
        row.type = "button";
        row.style.paddingLeft = (8 + depth * 14) + "px";
        if (state.locateUnitId === n.id || state.selectedUnitId === n.id) {
          row.classList.add("selected");
        }
        const caret = el("span", "map-tcaret" + (hasKids ? "" : " leaf"),
          hasKids ? (expanded ? "▾" : "▸") : "•");
        if (hasKids) caret.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (expanded) state.treeExpanded.delete(n.id);
          else state.treeExpanded.add(n.id);
          renderTree();
        });
        row.appendChild(caret);
        row.appendChild(el("span", "map-tname", n.name));
        row.appendChild(el("span", "map-thint",
          hasKids ? (n.kind + " · " + kids.length) : n.kind));
        row.addEventListener("click", () => onTreeSelect(n));
        treePanel.appendChild(row);
        if (hasKids && expanded) build(kids, depth + 1);
      }
    };
    build(state.tree, 0);
  }

  // Nearest ancestor (or the node itself) that is drawn on the floor plan.
  function onPlanAncestorId(id) {
    let target = null, anc = [];
    walkTree(state.tree, (n, a) => { if (n.id === id) { target = n; anc = a; } });
    const chain = target ? anc.concat(target) : [];
    for (let i = chain.length - 1; i >= 0; i--) {
      if (chain[i].map_x != null) return chain[i].id;
    }
    return null;
  }
  function treeNode(id) {
    let found = null;
    walkTree(state.tree, (n) => { if (n.id === id) found = n; });
    return found;
  }
  function floorOfUnit(id) {
    for (const f of state.floors) {
      if ((f.units || []).some((u) => u.id === id)) return f;
    }
    return null;
  }
  function expandTreeTo(id) {
    walkTree(state.tree, (n, a) => {
      if (n.id === id) { for (const x of a) state.treeExpanded.add(x.id); state.treeExpanded.add(n.id); }
    });
  }
  function clearLocate() { state.locateUnitId = null; state.locateWell = null; }

  // Set the viewBox to a unit's bounding box (plus margin) so it fills the view.
  function frameToUnit(u) {
    if (!u || u.map_x == null) return;
    const m = Math.max(u.map_w, u.map_h) * 0.18 + 8;
    state.view = { x: u.map_x - m, y: u.map_y - m,
      w: u.map_w + 2 * m, h: u.map_h + 2 * m };
    const svg = stage.querySelector(".map-svg");
    if (svg) applyView(svg);
  }

  // Focus a ROOM: show the floor plan and frame the viewBox to that room.
  function focusRoom(u) {
    const f = floorOfUnit(u.id);
    if (f && f !== state.floor) state.floor = f;
    drawFloor();
    frameToUnit(u);
    state.crumbs = [state.crumbs[0], { id: u.id, name: u.name }];
    renderCrumbs();
  }

  // Sidebar click: highlight on the plan and drill (rooms frame, boxes open grid).
  function onTreeSelect(n) {
    state.locateWell = null;
    state.locateUnitId = onPlanAncestorId(n.id) || n.id;
    if (n.kind === "room") {
      focusRoom(n);
    } else {
      state.crumbs = [state.crumbs[0], { id: n.id, name: n.name }];
      openNode(n.id, false);
    }
    renderTree();
  }

  // Deep-link locate: expand the tree, frame the nearest on-plan ancestor,
  // outline it, then drill into the box and highlight the well (row/col).
  function locateFlow(locationId, row, col) {
    const unitId = onPlanAncestorId(locationId);
    const f = unitId != null ? floorOfUnit(unitId) : null;
    if (f && f !== state.floor) state.floor = f;
    state.locateUnitId = unitId;
    expandTreeTo(locationId);
    renderTree();
    const target = treeNode(locationId);
    drawFloor();
    const unit = unitId != null ? treeNode(unitId) : null;
    if (unit) frameToUnit(unit); else if (target) frameToUnit(target);
    if (target && (target.kind === "box" || (row != null && col != null))) {
      if (row != null && col != null) {
        const boxId = target.kind === "box" ? target.id : null;
        state.locateWell = boxId != null
          ? { boxId, row: Number(row), col: Number(col) } : null;
      }
      state.crumbs = [state.crumbs[0], { id: target.id, name: target.name }];
      openNode(target.id, false);
    }
  }

  // --------------------------------------------------------------
  // Tooltip helpers
  // --------------------------------------------------------------
  function showTip(html, ev) {
    tip.innerHTML = html;
    tip.classList.add("show");
    moveTip(ev);
  }
  function moveTip(ev) {
    const pad = 14;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    const r = tip.getBoundingClientRect();
    if (x + r.width > window.innerWidth) x = ev.clientX - r.width - pad;
    if (y + r.height > window.innerHeight) y = ev.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hideTip() { tip.classList.remove("show"); }

  // --------------------------------------------------------------
  // Load floors + alert overlays, then draw the floor plan
  // --------------------------------------------------------------
  async function boot() {
    stage.innerHTML = "";
    stage.appendChild(loadingNode());
    let floors, tree, misplaced, expiring, conflicts, placement;
    try {
      [floors, tree, misplaced, expiring, conflicts, placement] = await Promise.all([
        api.get("/api/floors"),
        api.get("/api/locations").catch(() => []),
        api.get("/api/alerts/misplaced").catch(() => []),
        api.get("/api/alerts/expiring?days=30").catch(() => []),
        api.get("/api/compatibility/conflicts").catch(() => []),
        api.get("/api/compatibility/placement").catch(() => []),
      ]);
    } catch (e) {
      stage.innerHTML = "";
      stage.appendChild(el("div", "map-empty", "Could not load map data: " + e.message));
      return;
    }
    state.floors = floors || [];
    state.floor = state.floors[0] || null;
    state.tree = tree || [];
    state.misplacedRaw = misplaced || [];
    state.expiringRaw = expiring || [];
    state.conflictLocIds = new Set();
    for (const cf of conflicts || []) {
      if (cf && cf.location_id != null) state.conflictLocIds.add(cf.location_id);
    }
    state.placementLocIds = new Set();
    for (const w of placement || []) {
      if (w && w.location_id != null) state.placementLocIds.add(w.location_id);
    }

    computeAlertOverlays(tree, misplaced, expiring);
    buildChildCount();
    state.crumbs[0].name = rootCrumbName();
    renderCrumbs();
    renderTree();
    if (params && (params.locationId != null)) {
      locateFlow(params.locationId, params.row, params.col);
    } else {
      drawFloor();
    }
  }

  // Refetch floors + tree after an edit and redraw (alerts reuse cached data).
  async function refreshFloors() {
    let floors, tree;
    try {
      [floors, tree] = await Promise.all([
        api.get("/api/floors"),
        api.get("/api/locations").catch(() => state.tree),
      ]);
    } catch (e) {
      ctx.toast("Could not refresh map: " + e.message, "danger");
      return;
    }
    const fid = state.floor ? state.floor.floor_id : null;
    state.floors = floors || [];
    state.floor = state.floors.find((f) => f.floor_id === fid) ||
      state.floors[0] || null;
    state.tree = tree || [];
    computeAlertOverlays(state.tree, state.misplacedRaw, state.expiringRaw);
    buildChildCount();
    state.crumbs[0].name = rootCrumbName();
    renderCrumbs();
    renderTree();
    drawFloor();
  }

  // Direct-child count per location id, from the cached tree (drives the
  // "contains N" affordance on units and the tree hints).
  function buildChildCount() {
    state.childCount = new Map();
    walkTree(state.tree, (n) => {
      state.childCount.set(n.id, (n.children || []).length);
    });
  }

  // Map alerts onto the floor-plan units (rooms/freezers/etc that have map coords).
  function computeAlertOverlays(tree, misplaced, expiring) {
    state.misplacedBoxIds = new Set();
    state.misplacedBoxNames = new Set();
    state.unitAlerts = new Map();

    // Box name -> id, and box id -> owning floor-unit id (the ancestor that has map_x).
    const boxNameToId = new Map();
    const boxToFloorUnit = new Map();
    const idToNode = new Map();
    walkTree(tree, (n, anc) => {
      idToNode.set(n.id, n);
      if (n.kind === "box") {
        boxNameToId.set(n.name, n.id);
        // nearest ancestor drawn on the floor plan
        let owner = null;
        for (let i = anc.length - 1; i >= 0; i--) {
          if (anc[i].map_x != null) { owner = anc[i].id; break; }
        }
        if (owner != null) boxToFloorUnit.set(n.id, owner);
      }
    });

    // Misplaced -> resolve to box ids and flag the owning floor unit.
    for (const m of misplaced || []) {
      // actual.box may be a name or an id depending on backend; support both.
      const boxRef = m.actual && (m.actual.box != null ? m.actual.box : m.actual.box_id);
      let boxId = null;
      if (typeof boxRef === "number") boxId = boxRef;
      else if (typeof boxRef === "string") {
        state.misplacedBoxNames.add(boxRef);
        boxId = boxNameToId.get(boxRef) ?? null;
      }
      if (m.box_id != null) boxId = m.box_id;
      if (boxId != null) {
        state.misplacedBoxIds.add(boxId);
        const unit = boxToFloorUnit.get(boxId);
        if (unit != null) flagUnit(unit, "mis");
      }
    }

    // Expiring lots are item-level; try to attribute to a unit when the alert
    // carries a box/location reference, otherwise leave it to grid-level color.
    for (const e of expiring || []) {
      const ref = e.box_id ?? e.location_id ?? null;
      if (ref != null && idToNode.has(ref)) {
        const owner = boxToFloorUnit.get(ref) ?? ref;
        flagUnit(owner, "exp");
      }
    }

    // Honor explicit per-unit alert counts if the floors endpoint provides them.
    if (state.floor) for (const u of state.floor.units || []) {
      if (u.misplaced_count > 0 || u.has_misplaced) flagUnit(u.id, "mis");
      if (u.expiring_count > 0 || u.expired_count > 0 || u.has_expiring) flagUnit(u.id, "exp");
    }
  }
  function flagUnit(id, which) {
    const a = state.unitAlerts.get(id) || { mis: false, exp: false };
    a[which === "mis" ? "mis" : "exp"] = true;
    state.unitAlerts.set(id, a);
  }

  function loadingNode() {
    return el("div", "map-empty", "Loading map...");
  }

  // --------------------------------------------------------------
  // FLOOR PLAN (SVG) with pan + zoom
  // --------------------------------------------------------------
  function drawFloor() {
    hideTip();
    hideContents();
    stage.innerHTML = "";
    stage.classList.toggle("editing", state.editMode);
    updateEditBar();
    syncFloorControls();
    if (!state.floor) {
      stage.appendChild(el("div", "map-empty", canEdit
        ? "No floors yet. Upload a floor plan to start from a real layout."
        : "No floor plan data available."));
      return;
    }
    const f = state.floor;
    state.space = floorSpace(f);
    const { W, H } = state.space;
    state.fullView = { x: 0, y: 0, w: W, h: H };
    // Static layout: every (re)draw fits everything so all locations are visible
    // without panning. Zoom buttons/wheel mutate state.view after this point;
    // callers that want to frame a specific unit (room focus, locate) set
    // state.view AFTER drawFloor returns.
    state.view = { ...state.fullView };
    state.viewFloorId = f.floor_id;

    const svg = svgEl("svg", {
      class: "map-svg" + (state.space.image ? " has-image" : ""),
      preserveAspectRatio: "xMidYMid meet",
    });
    applyView(svg);
    stage.appendChild(svg);

    // Real floor-plan image as the background, at its natural pixel size, so
    // unit rects drawn in pixel coords land exactly on the plan.
    if (state.space.image) {
      const img = svgEl("image", {
        x: 0, y: 0, width: W, height: H, preserveAspectRatio: "none",
      });
      img.setAttribute("href", f.image_url);
      img.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", f.image_url);
      svg.appendChild(img);
    }

    const units = (f.units || []).slice();
    // Rooms first (drawn underneath), then storage units.
    const rooms = units.filter(u => u.kind === "room");
    const others = units.filter(u => u.kind !== "room");

    if (state.editMode) svg.appendChild(gridLines(W, H));
    for (const u of rooms) svg.appendChild(roomGroup(u, svg));
    for (const u of others) svg.appendChild(unitGroup(u, svg));

    attachPanZoom(svg);
  }

  // Keep the floor selector + image tools in sync with current floors state.
  function syncFloorControls() {
    floorSel.innerHTML = "";
    for (const f of state.floors) {
      const o = document.createElement("option");
      o.value = String(f.floor_id);
      o.textContent = f.name || ("Floor " + f.floor_id);
      floorSel.appendChild(o);
    }
    if (state.floor) floorSel.value = String(state.floor.floor_id);
    floorSel.style.display =
      state.crumbs.length === 1 && state.floors.length > 1 ? "" : "none";
    if (removeImgBtn) {
      removeImgBtn.style.display =
        state.floor && state.floor.image_url ? "" : "none";
    }
  }

  function applyView(svg) {
    const v = state.view;
    svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  }

  // Zoom the viewBox by `factor` (<1 zooms in) toward user-space point (px,py);
  // defaults to the view center. Clamps to a sane range relative to full view.
  function zoomAt(factor, px, py) {
    const v = state.view;
    if (px == null) { px = v.x + v.w / 2; py = v.y + v.h / 2; }
    let nw = v.w * factor, nh = v.h * factor;
    const maxW = state.fullView.w * 1.4;
    const minW = state.fullView.w * (state.space.image ? 0.04 : 0.15);
    if (nw > maxW) { const s = maxW / nw; nw *= s; nh *= s; }
    if (nw < minW) { const s = minW / nw; nw *= s; nh *= s; }
    state.view = {
      w: nw, h: nh,
      x: px - ((px - v.x) / v.w) * nw,
      y: py - ((py - v.y) / v.h) * nh,
    };
    const svg = stage.querySelector(".map-svg");
    if (svg) applyView(svg);
  }

  // Convert client (screen) coords to floor-plan user coords, honoring the
  // svg's preserveAspectRatio="meet" letterboxing so drops land accurately.
  function clientToUser(svg, clientX, clientY) {
    const v = state.view;
    const r = svg.getBoundingClientRect();
    const s = Math.min(r.width / v.w, r.height / v.h) || 1;
    const offX = (r.width - v.w * s) / 2;
    const offY = (r.height - v.h * s) / 2;
    return {
      x: v.x + (clientX - r.left - offX) / s,
      y: v.y + (clientY - r.top - offY) / s,
    };
  }

  function roomGroup(u, svg) {
    const k = state.space.k;
    const cls = ["map-room"];
    if (state.locateUnitId === u.id) cls.push("map-locate");
    if (state.editMode) cls.push("editable");
    if (state.editMode && state.selectedUnitId === u.id) cls.push("selected");
    const g = svgEl("g", { class: cls.join(" ") });
    g.__unit = u; // for context-menu hit-testing
    const rect = svgEl("rect", {
      x: u.map_x, y: u.map_y, width: u.map_w, height: u.map_h, rx: 8 * k,
    });
    g.appendChild(rect);
    const t = svgEl("text", {
      x: u.map_x + 10 * k, y: u.map_y + 22 * k, "font-size": 16 * k,
    });
    t.textContent = fitLabel(u.name, u.map_w - 20 * k, 16 * k);
    g.appendChild(t);
    if (state.editMode) attachEditHandles(g, rect, u, svg);
    return g;
  }

  function unitGroup(u, svg) {
    const a = state.unitAlerts.get(u.id) || {};
    const cls = ["map-unit", "kind-" + u.kind];
    if (a.mis) cls.push("has-misplaced");
    if (a.exp) cls.push("has-expiring");
    const hasConflict = state.conflictLocIds.has(u.id);
    if (hasConflict) cls.push("has-conflict");
    if (state.placementLocIds.has(u.id)) cls.push("has-placement");
    if (state.locateUnitId === u.id) cls.push("map-locate");
    if (state.editMode) cls.push("editable");
    if (state.editMode && state.selectedUnitId === u.id) cls.push("selected");
    const g = svgEl("g", { class: cls.join(" ") });
    g.__unit = u; // for context-menu hit-testing

    const k = state.space.k;
    const rect = svgEl("rect", {
      x: u.map_x, y: u.map_y, width: u.map_w, height: u.map_h, rx: 6 * k,
    });
    g.appendChild(rect);
    // scale font to unit size but clamp (clamps scale with the space factor)
    const fs = Math.max(11 * k, Math.min(18 * k, u.map_w / 8));
    const name = svgEl("text", {
      x: u.map_x + 8 * k, y: u.map_y + fs + 6 * k, "font-size": fs,
    });
    name.textContent = fitLabel(u.name, u.map_w - 16 * k, fs);
    g.appendChild(name);
    const sub = svgEl("text", {
      x: u.map_x + 8 * k, y: u.map_y + fs * 2 + 8 * k,
      "font-size": Math.max(9 * k, fs - 4 * k), class: "sub",
    });
    sub.textContent = u.kind;
    g.appendChild(sub);

    // Suitability tag: temp rating and/or a "flammable-rated" hint. Plain text,
    // no color -- suitability is neutral information, not a problem.
    const suitBits = [];
    if (u.temp_rating) suitBits.push(String(u.temp_rating));
    if (u.allowed_hazards && String(u.allowed_hazards).trim()) {
      suitBits.push(String(u.allowed_hazards).split(",")[0].trim() + "-rated");
    }
    if (suitBits.length) {
      const tag = svgEl("text", {
        x: u.map_x + 8 * k, y: u.map_y + u.map_h - 8 * k,
        "font-size": Math.max(9 * k, fs - 5 * k), class: "u-suit-tag",
      });
      tag.textContent = fitLabel(suitBits.join(" · "), u.map_w - 16 * k,
        Math.max(9 * k, fs - 5 * k));
      g.appendChild(tag);
    }

    // Sub-container affordance: units with descendant locations show "contains N".
    const kidN = state.childCount.get(u.id) || 0;
    if (kidN > 0) {
      const badge = svgEl("text", {
        x: u.map_x + u.map_w - 8 * k, y: u.map_y + u.map_h - 8 * k,
        "font-size": Math.max(9 * k, fs - 5 * k), "text-anchor": "end",
        class: "u-sub-badge",
      });
      badge.textContent = "▸ " + kidN;
      g.appendChild(badge);
    }

    // alert dot(s)
    if (a.mis || a.exp) {
      const dot = svgEl("circle", {
        cx: u.map_x + u.map_w - 12 * k, cy: u.map_y + 12 * k, r: 6 * k,
        class: "map-alert-dot",
        fill: a.mis ? "var(--danger)" : "var(--warn)",
        stroke: "var(--bg-elev)", "stroke-width": 2,
      });
      g.appendChild(dot);
    }

    // Incompatible-hazard conflict marker: danger outline (via CSS class) plus a
    // small "!" badge in the unit's top-left corner. Only genuine problem colored.
    if (hasConflict) {
      const bx = u.map_x + 12 * k, by = u.map_y + 12 * k;
      const badge = svgEl("g", { class: "map-conflict-badge" });
      badge.appendChild(svgEl("circle", {
        cx: bx, cy: by, r: 8 * k, fill: "var(--danger)",
        stroke: "var(--bg-elev)", "stroke-width": 2,
      }));
      const bt = svgEl("text", {
        x: bx, y: by + 4 * k, "font-size": 12 * k, "text-anchor": "middle",
        "font-weight": "700", fill: "var(--bg-elev)",
      });
      bt.textContent = "!";
      badge.appendChild(bt);
      g.appendChild(badge);
    }

    g.addEventListener("click", () => {
      if (state.editMode) return; // selection is handled by the edit handles
      onUnitClick(u);
    });
    g.addEventListener("mousemove", (ev) => {
      const bits = [];
      if (hasConflict) bits.push('<span class="tr" style="color:var(--danger)">Incompatible hazards stored here</span>');
      if (a.mis) bits.push('<span class="tr" style="color:var(--danger)">Misplaced containers</span>');
      if (a.exp) bits.push('<span class="tr" style="color:var(--warn)">Expiring / expired lots</span>');
      showTip(`<div class="tt">${u.name}</div><div class="tr">${u.kind}</div>${bits.join("")}`, ev);
    });
    g.addEventListener("mouseleave", hideTip);
    if (state.editMode) attachEditHandles(g, rect, u, svg);
    return g;
  }

  async function onUnitClick(u) {
    hideTip();
    // Rooms are containers on the plan: frame the viewBox to the room instead
    // of drilling into a flat tile list.
    if (u.kind === "room") {
      state.locateWell = null;
      state.locateUnitId = u.id;
      focusRoom(u);
      renderTree();
      return;
    }
    // Any storage unit (box, freezer, fridge, cabinet, rack, ...) drills in.
    clearLocate();
    renderTree();
    state.crumbs = [state.crumbs[0], { id: u.id, name: u.name }];
    openNode(u.id, false);
  }

  // --------------------------------------------------------------
  // NODE DRILL (children tiles) and BOX GRID
  // --------------------------------------------------------------
  async function openNode(id, freshCrumb) {
    hideTip();
    stage.innerHTML = "";
    stage.appendChild(loadingNode());
    let data;
    try { data = await api.get("/api/locations/" + id); }
    catch (e) {
      stage.innerHTML = "";
      stage.appendChild(el("div", "map-empty", "Could not load location: " + e.message));
      return;
    }
    const node = data.node || data;
    if (freshCrumb) {
      // build crumb trail from floor root when deep-linking
      state.crumbs = [state.crumbs[0], { id: node.id, name: node.name }];
    } else {
      // ensure this node is the tail crumb
      const tail = state.crumbs[state.crumbs.length - 1];
      if (!tail || tail.id !== node.id) {
        state.crumbs.push({ id: node.id, name: node.name });
      }
    }
    renderCrumbs();

    if (node.kind === "box") {
      drawGrid(node, data.containers || []);
    } else {
      drawChildren(node, data.children || []);
    }
    // Any node -- box or not -- also shows the flattened contents of its subtree.
    loadContents(node);
  }

  // --------------------------------------------------------------
  // CONTENTS PANEL: table of every container stored at/under a node.
  // Powered by GET /api/locations/{id}/contents. Shown below the map.
  // --------------------------------------------------------------
  function hideContents() {
    contentsToken++; // invalidate any in-flight fetch
    contentsPanel.style.display = "none";
    contentsPanel.innerHTML = "";
  }

  // Full path (building > floor > room > ... > node) built by walking the
  // already-loaded location tree. Returns an array of names, or null if the
  // node is not found in the cached tree.
  function nodePathNames(id) {
    let found = null;
    walkTree(state.tree, (n, anc) => {
      if (n.id === id) found = anc.concat(n).map((x) => x.name);
    });
    return found;
  }

  function contentStatusClass(status) {
    const s = String(status || "").toLowerCase();
    if (s === "expired" || s === "discarded") return "c-bad";
    if (s === "expiring" || s === "low") return "c-warn";
    return "c-muted";
  }

  async function loadContents(node) {
    if (!node || node.id == null) { hideContents(); return; }
    const token = ++contentsToken;
    contentsPanel.style.display = "";
    contentsPanel.innerHTML = "";

    const head = el("div", "map-contents-head");
    head.appendChild(el("div", "map-contents-title", "Contents of " + node.name));
    const names = nodePathNames(node.id) || [node.name];
    const path = el("div", "map-path");
    names.forEach((nm, i) => {
      if (i > 0) path.appendChild(el("span", "sep", ">"));
      path.appendChild(document.createTextNode(nm));
    });
    head.appendChild(path);
    contentsPanel.appendChild(head);

    const body = el("div", "map-contents-body");
    body.appendChild(el("div", "map-empty", "Loading contents..."));
    contentsPanel.appendChild(body);

    let data;
    try {
      data = await api.get("/api/locations/" + node.id + "/contents");
    } catch (e) {
      if (token !== contentsToken) return;
      body.innerHTML = "";
      body.appendChild(el("div", "map-empty", "Could not load contents: " + e.message));
      return;
    }
    if (token !== contentsToken) return; // user navigated away mid-fetch
    const conts = (data && data.containers) || [];
    const hazards = (data && data.hazards) || [];
    const conflicts = (data && data.conflicts) || [];
    const placement = (data && data.placement) || [];
    body.innerHTML = "";

    // Safety propagation: incompatible-hazard conflicts get a danger-bordered
    // block; otherwise a plain note when hazards are merely present.
    if (conflicts.length) {
      const warn = el("div", "map-cwarn");
      warn.appendChild(el("div", "map-cwarn-title",
        "Incompatible hazards stored together"));
      for (const cf of conflicts) {
        const line = el("div", "map-cwarn-line");
        const a = cf.hazard_a || "?", b = cf.hazard_b || "?";
        let head = "Incompatible: " + a + " + " + b;
        if (cf.reason) head += " -- " + cf.reason;
        line.appendChild(el("div", "cw-head", head));
        const parts = [];
        const ia = fmtItemList(cf.items_a), ib = fmtItemList(cf.items_b);
        if (ia) parts.push(a + ": " + ia);
        if (ib) parts.push(b + ": " + ib);
        if (parts.length) line.appendChild(el("div", "cw-items", parts.join("  |  ")));
        warn.appendChild(line);
      }
      body.appendChild(warn);
    } else if (hazards.length) {
      body.appendChild(el("div", "map-haznote",
        "Hazards present: " + hazards.join(", ")));
    }

    // Placement / suitability warnings (amber-bordered block, below conflicts):
    // stored where the compartment's temp rating or allowed hazards don't fit.
    if (placement.length) {
      const pw = el("div", "map-cwarn placement");
      pw.appendChild(el("div", "map-cwarn-title", "Placement warnings"));
      for (const w of placement) {
        const detail = (w && (w.detail || w.message || w.reason)) || String(w);
        const line = el("div", "map-cwarn-line");
        line.appendChild(el("div", "cw-head", detail));
        pw.appendChild(line);
      }
      body.appendChild(pw);
    }

    if (!conts.length) {
      body.appendChild(el("div", "map-empty", "Nothing stored here."));
      return;
    }

    const table = el("table", "map-ctab");
    const thead = el("thead");
    const htr = el("tr");
    for (const h of ["Item", "Lot", "Box", "Row/Col", "Hazard", "Status"]) {
      htr.appendChild(el("th", null, h));
    }
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = el("tbody");
    for (const c of conts) {
      const tr = el("tr");
      const itemId = c.item_id != null ? c.item_id : c.itemId;
      tr.appendChild(el("td", "c-item", c.item_name || "(unknown item)"));
      tr.appendChild(el("td", "c-muted", c.lot_number != null && c.lot_number !== ""
        ? String(c.lot_number) : "-"));
      tr.appendChild(el("td", null, c.box_name || "-"));
      const pos = (c.row != null && c.col != null)
        ? (c.row + " / " + c.col) : "-";
      tr.appendChild(el("td", "c-muted", pos));
      tr.appendChild(el("td", "c-muted", c.hazard_class != null && c.hazard_class !== ""
        ? String(c.hazard_class) : "-"));
      tr.appendChild(el("td", contentStatusClass(c.status), c.status || "-"));
      if (itemId != null) {
        tr.title = "Open " + (c.item_name || "item") + " in inventory";
        tr.addEventListener("click", () => ctx.navigate("inventory", { focusItem: itemId }));
      } else {
        tr.style.cursor = "default";
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    body.appendChild(table);
  }

  function drawChildren(node, children) {
    stage.innerHTML = "";
    if (!children.length) {
      stage.appendChild(el("div", "map-empty", `${node.name} has no sub-locations.`));
      return;
    }
    const grid = el("div", "map-tiles");
    for (const c of children) {
      const hasMis = state.misplacedBoxIds.has(c.id) ||
        (c.kind === "box" && state.misplacedBoxNames.has(c.name));
      const tile = el("button", "map-tile" + (hasMis ? " has-misplaced" : ""));
      tile.type = "button";
      tile.appendChild(el("div", "t-name", c.name));
      const meta = el("div", "t-kind", c.kind +
        (c.kind === "box" && c.capacity_rows ? ` ${c.capacity_rows}x${c.capacity_cols}` : ""));
      tile.appendChild(meta);
      if (hasMis) {
        const b = el("span", "badge badge-danger", "misplaced");
        tile.appendChild(b);
      }
      tile.addEventListener("click", () => openNode(c.id, false));
      grid.appendChild(tile);
    }
    stage.appendChild(grid);
  }

  // -------- BOX GRID VIEW --------
  function drawGrid(node, containers) {
    stage.innerHTML = "";
    const rows = node.capacity_rows || inferMax(containers, "row") || 9;
    const cols = node.capacity_cols || inferMax(containers, "col") || 9;

    // detect 0- vs 1-based indexing from the data
    let base = 1;
    for (const c of containers) {
      if (c.row === 0 || c.col === 0) { base = 0; break; }
    }

    // index containers by "r,c"
    const byPos = new Map();
    for (const c of containers) {
      if (c.row == null || c.col == null) continue;
      byPos.set(c.row + "," + c.col, c);
    }

    const scroll = el("div", "map-grid-scroll");
    const grid = el("div", "map-grid");
    grid.style.gridTemplateColumns = `28px repeat(${cols}, 34px)`;
    grid.style.gridTemplateRows = `20px repeat(${rows}, 34px)`;

    // corner + column headers
    grid.appendChild(el("div", "gh", ""));
    for (let c = 0; c < cols; c++) grid.appendChild(el("div", "gh", String(c + 1)));

    for (let r = 0; r < rows; r++) {
      // row header (A, B, C ...)
      grid.appendChild(el("div", "gh", String.fromCharCode(65 + r)));
      for (let c = 0; c < cols; c++) {
        const key = (base + r) + "," + (base + c);
        const cont = byPos.get(key);
        grid.appendChild(wellCell(node, cont, r, c, base));
      }
    }
    scroll.appendChild(grid);
    stage.appendChild(scroll);
    stage.appendChild(legend());
  }

  function inferMax(containers, field) {
    let m = 0;
    for (const c of containers) if (c[field] != null && c[field] > m) m = c[field];
    return m || null;
  }

  function statusOf(node, cont) {
    if (!cont) return "empty";
    if (cont.status === "empty" || cont.status === "discarded") return "empty";
    const d = daysUntil(cont.expiry_date ?? cont.expiry);
    if (d != null && d < 0) return "expired";
    if (d != null && d <= 30) return "expiring";
    return "occupied";
  }
  function isMisplaced(node, cont) {
    if (!cont) return false;
    if (state.misplacedBoxIds.size &&
        (state.misplacedBoxIds.has(cont.id) || state.misplacedBoxIds.has(cont.container_id))) {
      // set holds box ids, not container ids; fall through to field check
    }
    const eb = cont.expected_box_id, er = cont.expected_row, ec = cont.expected_col;
    if (eb == null && er == null && ec == null) return false;
    if (eb != null && eb !== node.id) return true;
    if (er != null && er !== cont.row) return true;
    if (ec != null && ec !== cont.col) return true;
    return false;
  }

  function wellCell(node, cont, r, c, base) {
    const st = statusOf(node, cont);
    const mis = isMisplaced(node, cont);
    const classes = ["well", "well-" + st];
    if (mis) classes.push("well-misplaced");
    const lw = state.locateWell;
    if (lw && lw.boxId === node.id &&
        lw.row === (base + r) && lw.col === (base + c)) {
      classes.push("well-locate");
    }
    const occupied = st !== "empty";
    if (occupied) classes.push("clickable");
    const cell = el("div", classes.join(" "));

    const posLabel = String.fromCharCode(65 + r) + (c + 1);
    if (cont) {
      const item = cont.item_name ?? cont.item ?? cont.name ?? "(unknown item)";
      const lot = cont.lot_number ?? cont.lot ?? "-";
      const expRaw = cont.expiry_date ?? cont.expiry;
      const exp = expRaw ? ctx.fmt.date(expRaw) : "no expiry";
      const d = daysUntil(expRaw);
      let expLine = exp;
      if (d != null) expLine += d < 0 ? ` (expired ${-d}d ago)` : ` (${d}d left)`;
      const misLine = mis
        ? `<div class="tr" style="color:var(--danger)">Misplaced</div>` : "";
      cell.addEventListener("mousemove", (ev) => showTip(
        `<div class="tt">${escapeHtml(item)}</div>` +
        `<div class="tr">Lot ${escapeHtml(String(lot))}</div>` +
        `<div class="tr">${escapeHtml(expLine)}</div>` +
        `<div class="tr">Position ${posLabel}</div>` + misLine, ev));
      cell.addEventListener("mouseleave", hideTip);
      if (occupied) {
        const itemId = cont.item_id ?? cont.itemId;
        cell.addEventListener("click", () => {
          hideTip();
          if (itemId != null) ctx.navigate("inventory", { itemId });
          else ctx.toast("No linked item for this container", "warn");
        });
      }
    } else {
      cell.addEventListener("mousemove", (ev) =>
        showTip(`<div class="tr">Empty ${posLabel}</div>`, ev));
      cell.addEventListener("mouseleave", hideTip);
    }
    return cell;
  }

  function legend() {
    const l = el("div", "map-legend");
    const items = [
      ["var(--occupied)", "Occupied"],
      ["var(--warn)", "Expiring <30d"],
      ["var(--danger)", "Expired"],
      ["var(--empty)", "Empty"],
    ];
    for (const [color, label] of items) {
      const s = el("span");
      const i = el("i"); i.style.background = color; s.appendChild(i);
      s.appendChild(document.createTextNode(label));
      l.appendChild(s);
    }
    const mis = el("span");
    const mi = el("i");
    mi.style.background = "transparent";
    mi.style.outline = "3px solid var(--danger)";
    mi.style.outlineOffset = "-2px";
    mis.appendChild(mi);
    mis.appendChild(document.createTextNode("Misplaced"));
    l.appendChild(mis);
    return l;
  }

  // --------------------------------------------------------------
  // Pan + zoom on the floor-plan SVG
  // --------------------------------------------------------------
  function attachPanZoom(svg) {
    // Static layout: the plan does NOT pan on drag. Zoom stays available via the
    // mouse wheel and the zoom-in/out/reset buttons. (Manager edit-mode unit drag
    // is handled separately in attachEditHandles and is unaffected.)
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      // zoom toward the cursor (image floors allow deeper zoom; handled by zoomAt)
      const p = clientToUser(svg, ev.clientX, ev.clientY);
      zoomAt(ev.deltaY < 0 ? 0.85 : 1.18, p.x, p.y);
    }, { passive: false });

    // Right-click: context menu. On a unit -> edit/resize/add-child/delete;
    // on empty canvas -> add a location at the clicked map coords. The menu is
    // only offered to managers/admins (mutations are gated server-side anyway).
    svg.addEventListener("contextmenu", (ev) => {
      if (!canEdit) return; // let the native menu show; nothing to mutate
      ev.preventDefault();
      hideTip();
      const gEl = ev.target.closest && ev.target.closest(".map-unit, .map-room");
      const u = gEl && gEl.__unit;
      const p = clientToUser(svg, ev.clientX, ev.clientY);
      if (u) openUnitMenu(ev.clientX, ev.clientY, u, p);
      else openEmptyMenu(ev.clientX, ev.clientY, p);
    });
  }

  resetViewBtn.addEventListener("click", () => {
    state.view = { ...state.fullView };
    const svg = stage.querySelector(".map-svg");
    if (svg) applyView(svg);
  });
  zoomInBtn.addEventListener("click", () => zoomAt(0.72));
  zoomOutBtn.addEventListener("click", () => zoomAt(1 / 0.72));

  // --------------------------------------------------------------
  // LAYOUT EDIT MODE (manager+). Lives entirely on the floor plan:
  // drag to move, corner handle to resize, add/delete units.
  // --------------------------------------------------------------
  let ebSel, ebDel, kindSel, nameInp, parentSel, rowsInp, colsInp;
  let tempSel, hazBoxes = [], createBtnRef;
  if (canEdit) {
    const ebTitle = el("strong", null, "Edit mode");
    const ebHint = el("span", "eb-hint",
      "Drag units to move. Click one to select, then resize with the corner handle.");
    ebSel = el("span", "eb-sel", "No unit selected");
    const ebSpacer = el("span", "map-spacer");
    const ebAdd = el("button", "btn btn-sm", "Add unit");
    ebAdd.type = "button";
    ebDel = el("button", "btn btn-sm", "Delete");
    ebDel.type = "button";
    const ebExit = el("button", "btn btn-sm btn-ghost", "Exit edit");
    ebExit.type = "button";
    editBar.append(ebTitle, ebHint, ebSel, ebSpacer, ebAdd, ebDel, ebExit);
    ebExit.addEventListener("click", () => setEditMode(false));
    ebDel.addEventListener("click", deleteSelected);
    ebAdd.addEventListener("click", () => {
      const show = addForm.style.display === "none";
      if (show) { state.editUnitId = null; resetAddForm(); buildParentOptions(); }
      addForm.style.display = show ? "" : "none";
    });

    // add-unit form
    const mkLabel = (txt, ctrl) => {
      const l = el("label", null, txt);
      l.appendChild(ctrl);
      return l;
    };
    kindSel = document.createElement("select");
    for (const k of KINDS) {
      const o = document.createElement("option");
      o.value = k; o.textContent = k;
      kindSel.appendChild(o);
    }
    kindSel.value = "fridge";
    nameInp = document.createElement("input");
    nameInp.placeholder = "e.g. Freezer C";
    parentSel = document.createElement("select");
    rowsInp = document.createElement("input");
    rowsInp.type = "number"; rowsInp.min = "1"; rowsInp.value = "9";
    colsInp = document.createElement("input");
    colsInp.type = "number"; colsInp.min = "1"; colsInp.value = "9";
    const rowsLab = mkLabel("Rows", rowsInp);
    const colsLab = mkLabel("Cols", colsInp);
    const syncBoxFields = () => {
      const isBox = kindSel.value === "box";
      rowsLab.style.display = isBox ? "" : "none";
      colsLab.style.display = isBox ? "" : "none";
    };
    kindSel.addEventListener("change", syncBoxFields);
    // Suitability: temperature rating + allowed hazards (drives on-plan tags and
    // the backend's placement checks). Sent on both create (POST) and edit (PATCH).
    tempSel = document.createElement("select");
    for (const t of TEMP_RATINGS) {
      const o = document.createElement("option");
      o.value = t; o.textContent = t === "" ? "(none)" : t;
      tempSel.appendChild(o);
    }
    const hazGrid = el("div", "haz-grid");
    hazBoxes = [];
    for (const h of HAZARD_KINDS) {
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.value = h;
      cb.__haz = h;
      hazBoxes.push(cb);
      const lab = el("label", null, h);
      lab.insertBefore(cb, lab.firstChild);
      hazGrid.appendChild(lab);
    }
    const hazLab = mkLabel("Allowed hazards", hazGrid);
    const createBtn = el("button", "btn btn-sm btn-primary", "Create");
    createBtn.type = "button";
    createBtnRef = createBtn;
    createBtn.addEventListener("click", createUnit);
    const cancelBtn = el("button", "btn btn-sm btn-ghost", "Cancel");
    cancelBtn.type = "button";
    cancelBtn.addEventListener("click", () => {
      addForm.style.display = "none";
      state.seedRect = null;
      state.editUnitId = null;
    });
    addForm.append(mkLabel("Kind", kindSel), mkLabel("Name", nameInp),
      mkLabel("Parent", parentSel), rowsLab, colsLab,
      mkLabel("Temp rating", tempSel), hazLab, createBtn, cancelBtn);
    syncBoxFields();
  }

  // Reset the add/edit form to blank "create" defaults.
  function resetAddForm() {
    if (!canEdit) return;
    if (kindSel) kindSel.value = "fridge";
    if (nameInp) nameInp.value = "";
    if (tempSel) tempSel.value = "";
    for (const cb of hazBoxes) cb.checked = false;
    if (createBtnRef) createBtnRef.textContent = "Create";
  }

  // Prefill the form from an existing unit and switch it into edit (PATCH) mode.
  function openEditForm(u) {
    if (!canEdit || !u) return;
    if (!state.editMode) setEditMode(true);
    state.editUnitId = u.id;
    state.seedRect = null;
    buildParentOptions();
    kindSel.value = u.kind || "fridge";
    nameInp.value = u.name || "";
    tempSel.value = u.temp_rating || "";
    const set = new Set(String(u.allowed_hazards || "").split(",")
      .map((s) => s.trim()).filter(Boolean));
    for (const cb of hazBoxes) cb.checked = set.has(cb.value);
    // sync box-only fields
    kindSel.dispatchEvent(new Event("change"));
    if (u.kind === "box") {
      if (rowsInp) rowsInp.value = String(u.capacity_rows || 9);
      if (colsInp) colsInp.value = String(u.capacity_cols || 9);
    }
    if (createBtnRef) createBtnRef.textContent = "Save";
    addForm.style.display = "";
    nameInp.focus();
  }

  function setEditMode(on) {
    state.editMode = on;
    state.selectedUnitId = null;
    state.editUnitId = null;
    addForm.style.display = "none";
    if (editBtn) {
      editBtn.textContent = on ? "Exit edit" : "Edit layout";
      editBtn.classList.toggle("btn-primary", on);
      editBtn.classList.toggle("btn-ghost", !on);
    }
    state.crumbs = [state.crumbs[0]]; // editing lives on the floor-plan root
    renderCrumbs();
    drawFloor();
  }

  function updateEditBar() {
    if (!canEdit) return;
    editBar.style.display = state.editMode ? "" : "none";
    if (!state.editMode) { addForm.style.display = "none"; return; }
    const u = findUnit(state.selectedUnitId);
    ebSel.textContent = u ? `Selected: ${u.name} (${u.kind})` : "No unit selected";
    ebDel.disabled = !u;
  }

  function findUnit(id) {
    if (id == null || !state.floor) return null;
    return (state.floor.units || []).find((u) => u.id === id) || null;
  }

  function selectUnit(id) {
    state.selectedUnitId = id;
    drawFloor();
  }

  function buildParentOptions() {
    parentSel.innerHTML = "";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(top level)";
    parentSel.appendChild(none);
    // Any node may be a parent so locations can nest arbitrarily deep. A box is
    // the positional leaf (it holds containers in a grid, not sub-locations),
    // so it is the only kind excluded from the parent list.
    walkTree(state.tree, (n, anc) => {
      if (n.kind === "box") return;
      const o = document.createElement("option");
      o.value = String(n.id);
      o.textContent = "— ".repeat(anc.length) + `${n.name} (${n.kind})`;
      parentSel.appendChild(o);
    });
  }

  // Default rect for a new unit, in the current floor's user units.
  // Schematic floors keep the historical top-left drop; image floors place
  // the unit near the current view center so it lands where the user looks.
  function defaultUnitRect() {
    const sp = state.space;
    const w = Math.max(sp.snap * 2, snapTo(160 * sp.k, sp.snap));
    const h = Math.max(sp.snap, snapTo(80 * sp.k, sp.snap));
    let x = 40 * sp.k, y = 40 * sp.k;
    if (state.seedRect) {
      // Center the new unit on the point the user right-clicked.
      x = state.seedRect.x - w / 2;
      y = state.seedRect.y - h / 2;
    } else if (sp.image) {
      x = state.view.x + state.view.w / 2 - w / 2;
      y = state.view.y + state.view.h / 2 - h / 2;
    }
    x = snapTo(Math.min(Math.max(0, x), Math.max(0, sp.W - w)), sp.snap);
    y = snapTo(Math.min(Math.max(0, y), Math.max(0, sp.H - h)), sp.snap);
    return { map_x: x, map_y: y, map_w: w, map_h: h };
  }

  // Collect the suitability fields shared by create + edit.
  function suitabilityFields() {
    return {
      temp_rating: tempSel.value || "",
      allowed_hazards: hazBoxes.filter((cb) => cb.checked)
        .map((cb) => cb.value).join(","),
    };
  }

  async function createUnit() {
    const name = nameInp.value.trim();
    if (!name) { ctx.toast("Name is required", "warn"); return; }
    // Edit mode: PATCH the existing unit's editable fields.
    if (state.editUnitId != null) {
      const u = findUnit(state.editUnitId);
      const fields = Object.assign({
        name, kind: kindSel.value,
        parent_id: parentSel.value ? Number(parentSel.value) : null,
      }, suitabilityFields());
      if (kindSel.value === "box") {
        fields.capacity_rows = Math.max(1, Number(rowsInp.value) || 9);
        fields.capacity_cols = Math.max(1, Number(colsInp.value) || 9);
      }
      addForm.style.display = "none";
      const id = state.editUnitId;
      state.editUnitId = null;
      resetAddForm();
      if (u) { patchUnit(u, fields); }
      else {
        try { await api.patch("/api/locations/" + id, fields); await refreshFloors(); }
        catch (e) { ctx.toast("Save failed: " + e.message, "danger"); }
      }
      return;
    }
    const body = Object.assign({
      parent_id: parentSel.value ? Number(parentSel.value) : null,
      kind: kindSel.value,
      name,
      floor_id: state.floor ? state.floor.floor_id : 1,
      // default drop position (or the right-clicked point); user can drag it
    }, defaultUnitRect(), suitabilityFields());
    state.seedRect = null; // consumed
    if (body.kind === "box") {
      body.capacity_rows = Math.max(1, Number(rowsInp.value) || 9);
      body.capacity_cols = Math.max(1, Number(colsInp.value) || 9);
    }
    try {
      const node = await api.post("/api/locations", body);
      ctx.toast(`Added ${node.name} -- drag it into place`);
      resetAddForm();
      addForm.style.display = "none";
      state.selectedUnitId = node.id;
      await refreshFloors();
    } catch (e) {
      ctx.toast("Add failed: " + e.message, "danger");
    }
  }

  function deleteSelected() { deleteUnit(findUnit(state.selectedUnitId)); }

  async function deleteUnit(u) {
    if (!u) return;
    if (!window.confirm(`Delete "${u.name}"? This cannot be undone.`)) return;
    try {
      await apiDelete("/api/locations/" + u.id);
      ctx.toast(`Deleted ${u.name}`);
      if (state.selectedUnitId === u.id) state.selectedUnitId = null;
      await refreshFloors();
    } catch (e) {
      // surfaces the 400 "has children / holds containers" and any 403 detail
      ctx.toast("Delete blocked: " + e.message, "danger");
    }
  }

  // Rename a unit via the existing PATCH flow (the concrete "Edit" action).
  function renameUnit(u) {
    if (!u) return;
    const next = window.prompt("Rename location", u.name);
    if (next == null) return;
    const name = next.trim();
    if (!name || name === u.name) return;
    patchUnit(u, { name });
  }

  // --------------------------------------------------------------
  // Right-click context menu
  // --------------------------------------------------------------
  function closeCtxMenu() {
    if (ctxMenu.parentNode) ctxMenu.remove();
    ctxMenu.innerHTML = "";
  }
  function openCtxMenu(clientX, clientY, headText, items) {
    closeCtxMenu();
    if (headText) ctxMenu.appendChild(el("div", "cm-head", headText));
    for (const it of items) {
      const b = el("button", it.danger ? "cm-danger" : null, it.label);
      b.type = "button";
      b.addEventListener("click", () => { closeCtxMenu(); it.fn(); });
      ctxMenu.appendChild(b);
    }
    document.body.appendChild(ctxMenu);
    const r = ctxMenu.getBoundingClientRect();
    let x = clientX, y = clientY;
    if (x + r.width > window.innerWidth) x = window.innerWidth - r.width - 4;
    if (y + r.height > window.innerHeight) y = window.innerHeight - r.height - 4;
    ctxMenu.style.left = Math.max(4, x) + "px";
    ctxMenu.style.top = Math.max(4, y) + "px";
  }
  function openEmptyMenu(clientX, clientY, p) {
    openCtxMenu(clientX, clientY, rootCrumbName(), [
      { label: "Add location here", fn: () => openAddForm({ x: p.x, y: p.y }, null) },
    ]);
  }
  function openUnitMenu(clientX, clientY, u, p) {
    const items = [
      { label: "Edit (rename)", fn: () => renameUnit(u) },
      { label: "Edit details", fn: () => openEditForm(u) },
      { label: "Resize", fn: () => {
        if (!state.editMode) setEditMode(true);
        selectUnit(u.id);
      } },
    ];
    // A box is a positional leaf (holds containers, not sub-locations).
    if (u.kind !== "box") {
      items.push({ label: "Add child here",
        fn: () => openAddForm({ x: p.x, y: p.y }, u.id) });
    }
    items.push({ label: "Delete", danger: true, fn: () => deleteUnit(u) });
    openCtxMenu(clientX, clientY, u.name + " (" + u.kind + ")", items);
  }

  // Open the add-unit form seeded with a map position (and optional parent),
  // auto-enabling edit mode since the form is part of the edit UI.
  function openAddForm(seed, parentId) {
    if (!canEdit) return;
    if (!state.editMode) setEditMode(true); // triggers a redraw; then show form
    state.editUnitId = null;
    resetAddForm();
    state.seedRect = seed || null;
    buildParentOptions();
    if (parentId != null) parentSel.value = String(parentId);
    addForm.style.display = "";
    nameInp.focus();
  }

  // --------------------------------------------------------------
  // FLOOR-PLAN IMAGE + LAYOUT IMPORT/EXPORT (manager+; the buttons that call
  // these are only built for manager/admin roles).
  // --------------------------------------------------------------
  // Upload a real floor-plan image. The image is loaded locally first so we
  // can send its natural pixel dimensions alongside the file; the backend
  // stores unit coords in that pixel space from then on.
  async function uploadPlan(file) {
    try {
      let floor = state.floor;
      if (!floor) {
        // No floors yet: create one so the image has somewhere to live.
        floor = await api.post("/api/floors", { name: "Floor 1" });
      }
      const fid = floor.floor_id != null ? floor.floor_id : floor.id;
      if (fid == null) throw new Error("no floor to attach the image to");
      const dims = await readImageSize(file);
      const fd = new FormData();
      fd.append("file", file);
      fd.append("width", String(dims.w));
      fd.append("height", String(dims.h));
      await apiFetch("/api/floors/" + fid + "/image", {
        method: "POST", body: fd,
      });
      ctx.toast("Floor plan uploaded -- use Edit layout to place units on it");
      state.viewFloorId = null; // re-fit the view to the new image size
      await refreshFloors();
    } catch (e) {
      ctx.toast("Upload failed: " + e.message, "danger");
    }
  }

  async function removeImage() {
    const f = state.floor;
    if (!f || !f.image_url) return;
    if (!window.confirm("Remove this floor plan image and revert to the schematic view?")) return;
    try {
      await apiDelete("/api/floors/" + f.floor_id + "/image");
      ctx.toast("Floor plan image removed");
      state.viewFloorId = null;
      await refreshFloors();
    } catch (e) {
      ctx.toast("Remove failed: " + e.message, "danger");
    }
  }

  // Download the portable layout (floors + locations) as layout.json.
  async function exportLayout() {
    try {
      const data = await api.get("/api/layout");
      const blob = new Blob([JSON.stringify(data, null, 2)],
        { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "layout.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      ctx.toast("Layout exported");
    } catch (e) {
      ctx.toast("Export failed: " + e.message, "danger");
    }
  }

  // Import a layout produced elsewhere: parse locally, hand to the backend.
  async function importLayout(file) {
    let payload;
    try {
      payload = JSON.parse(await file.text());
    } catch (_) {
      ctx.toast("Import failed: file is not valid JSON", "danger");
      return;
    }
    if (!payload || typeof payload !== "object" ||
        !Array.isArray(payload.locations)) {
      ctx.toast("Import failed: expected {floors?, locations: [...]}", "danger");
      return;
    }
    try {
      await api.post("/api/layout", payload);
      ctx.toast("Layout imported");
      state.selectedUnitId = null;
      state.viewFloorId = null;
      await refreshFloors();
    } catch (e) {
      ctx.toast("Import failed: " + e.message, "danger");
    }
  }

  // PATCH a unit optimistically; on failure toast + refetch to reconcile.
  async function patchUnit(u, fields) {
    Object.assign(u, fields);
    drawFloor();
    try {
      const node = await api.patch("/api/locations/" + u.id, fields);
      Object.assign(u, node);
    } catch (e) {
      ctx.toast("Save failed: " + e.message, "danger");
      await refreshFloors();
    }
  }

  // Light snap grid drawn under the units in edit mode (space-aware step).
  function gridLines(W, H) {
    const g = svgEl("g", { class: "map-grid-lines" });
    const step = state.space.snap * 2;
    for (let x = 0; x <= W; x += step) {
      g.appendChild(svgEl("line", { x1: x, y1: 0, x2: x, y2: H }));
    }
    for (let y = 0; y <= H; y += step) {
      g.appendChild(svgEl("line", { x1: 0, y1: y, x2: W, y2: y }));
    }
    return g;
  }

  // Drag-to-move + click-to-select on a unit group; resize handle when selected.
  function attachEditHandles(g, rect, u, svg) {
    // preserveAspectRatio "meet" renders at a uniform scale (letterboxed),
    // so one factor converts client px deltas to floor-plan units.
    const userScale = () => {
      const r = svg.getBoundingClientRect();
      return Math.min(r.width / state.view.w, r.height / state.view.h) || 1;
    };

    g.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      if (ev.target.classList && ev.target.classList.contains("map-resize-handle")) return;
      ev.stopPropagation(); // keep the svg pan from starting
      hideTip();
      const sx = ev.clientX, sy = ev.clientY;
      let moved = false;
      const move = (mv) => {
        if (!moved && Math.abs(mv.clientX - sx) < 3 && Math.abs(mv.clientY - sy) < 3) return;
        moved = true;
        const s = userScale();
        g.setAttribute("transform",
          `translate(${(mv.clientX - sx) / s} ${(mv.clientY - sy) / s})`);
      };
      const up = (uv) => {
        g.removeEventListener("pointermove", move);
        g.removeEventListener("pointerup", up);
        g.removeEventListener("pointercancel", up);
        try { g.releasePointerCapture(ev.pointerId); } catch (_) {}
        if (!moved) { selectUnit(u.id); return; } // plain click = select
        g.removeAttribute("transform");
        const s = userScale();
        const nx = snapTo(u.map_x + (uv.clientX - sx) / s, state.space.snap);
        const ny = snapTo(u.map_y + (uv.clientY - sy) / s, state.space.snap);
        if (nx === u.map_x && ny === u.map_y) { drawFloor(); return; }
        patchUnit(u, { map_x: nx, map_y: ny });
      };
      try { g.setPointerCapture(ev.pointerId); } catch (_) {}
      g.addEventListener("pointermove", move);
      g.addEventListener("pointerup", up);
      g.addEventListener("pointercancel", up);
    });

    if (state.selectedUnitId !== u.id) return;
    const hs = 16 * state.space.k;
    const handle = svgEl("rect", {
      class: "map-resize-handle", rx: 4 * state.space.k, width: hs, height: hs,
      x: u.map_x + u.map_w - hs / 2, y: u.map_y + u.map_h - hs / 2,
    });
    handle.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      ev.stopPropagation();
      hideTip();
      const sx = ev.clientX, sy = ev.clientY;
      const size = (mv) => {
        const s = userScale();
        return {
          w: Math.max(state.space.snap * 2, u.map_w + (mv.clientX - sx) / s),
          h: Math.max(state.space.snap, u.map_h + (mv.clientY - sy) / s),
        };
      };
      const move = (mv) => {
        const { w, h } = size(mv);
        rect.setAttribute("width", w);
        rect.setAttribute("height", h);
        handle.setAttribute("x", u.map_x + w - hs / 2);
        handle.setAttribute("y", u.map_y + h - hs / 2);
      };
      const up = (uv) => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        try { handle.releasePointerCapture(ev.pointerId); } catch (_) {}
        const { w, h } = size(uv);
        const nw = snapTo(w, state.space.snap), nh = snapTo(h, state.space.snap);
        if (nw === u.map_w && nh === u.map_h) { drawFloor(); return; }
        patchUnit(u, { map_w: nw, map_h: nh });
      };
      try { handle.setPointerCapture(ev.pointerId); } catch (_) {}
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
    g.appendChild(handle);
  }

  // Render a conflict's offending items (items_a / items_b) as a plain,
  // comma-separated name list. Accepts an array of strings or of objects
  // carrying a name-ish field, or a bare string; returns "" when empty.
  function fmtItemList(items) {
    if (items == null) return "";
    if (typeof items === "string") return items;
    if (!Array.isArray(items)) return String(items);
    const names = items.map((it) => {
      if (it == null) return "";
      if (typeof it === "string" || typeof it === "number") return String(it);
      return String(it.item_name ?? it.name ?? it.item ?? "");
    }).filter((s) => s !== "");
    return names.join(", ");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  await boot();
}
