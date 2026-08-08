// app.js -- the only module that runs on load.
// Owns: api client, ctx, router, the Dashboard view, auth gate, theme + reset wiring.
// Imports the view modules; they never import each other or this file.

import * as inventory from "./inventory.js";
import * as catalog from "./catalog.js";
import * as kits from "./kits.js";
import * as preparations from "./preparations.js";
import * as counts from "./counts.js";
import * as tickets from "./tickets.js";
import * as map from "./map.js";
import * as equipment from "./equipment.js";
import * as it from "./it.js";
import * as glassware from "./glassware.js";
import * as maintenance from "./maintenance.js";
import * as purchasing from "./purchasing.js";
import * as funds from "./funds.js";
import * as controlled from "./controlled.js";
import * as safety from "./safety.js";
import * as labels from "./labels.js";
import * as analytics from "./analytics.js";
import * as reports from "./reports.js";
import * as usage from "./usage.js";
import * as people from "./people.js";
import * as history from "./history.js";
import * as game from "./game.js";
import * as settings from "./settings.js";
import * as sql from "./sql.js";
import * as help from "./help.js";
import * as auth from "./auth.js";
import { openScanner } from "./scanner.js";

// --------------------------------------------------------------------------- //
// api client -- paths are absolute ("/api/..."), same origin as the SPA.
// Each call returns parsed JSON and throws on non-2xx (message = detail).
// A 401 on anything but /api/login drops the app back to the login gate.
// --------------------------------------------------------------------------- //
function readCookie(name) {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

// Attach the CSRF token to every state-changing same-origin fetch -- including the
// raw multipart uploads in view modules (document/floor/CSV) that bypass the api
// client -- so a single wrapper keeps the whole app compatible with CSRF enforcement.
const _nlmFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  init = init || {};
  const method = (init.method ||
    (typeof input === "object" && input && input.method) || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.startsWith("/") || url.startsWith(location.origin)) {
      const csrf = readCookie("nlm_csrf");
      if (csrf) {
        const h = new Headers(init.headers ||
          (typeof input === "object" && input && input.headers) || {});
        if (!h.has("X-CSRF-Token")) h.set("X-CSRF-Token", csrf);
        init = Object.assign({}, init, { headers: h });
      }
    }
  }
  return _nlmFetch(input, init);
};

async function request(path, method, body) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  // CSRF token is attached by the global fetch wrapper above.
  const res = await fetch(path, opts);
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch (_) { data = text; }
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/login") handleUnauthorized();
    const detail = data && data.detail ? data.detail : (typeof data === "string" && data) || res.statusText;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data;
}

const api = {
  get: (path) => request(path, "GET"),
  post: (path, body) => request(path, "POST", body === undefined ? {} : body),
  patch: (path, body) => request(path, "PATCH", body === undefined ? {} : body),
  del: (path) => request(path, "DELETE"),
};

// --------------------------------------------------------------------------- //
// formatting helpers
// --------------------------------------------------------------------------- //
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const fmt = {
  date(s) {
    if (!s) return "";
    const iso = String(s).slice(0, 10);
    const p = iso.split("-");
    if (p.length !== 3) return String(s);
    const y = +p[0], m = +p[1], d = +p[2];
    if (!m || !d) return String(s);
    return `${MONTHS[m - 1] || p[1]} ${d}, ${y}`;
  },
  money(n) {
    const v = Number(n) || 0;
    return "$" + Math.round(v).toLocaleString("en-US");
  },
  num(n) {
    const v = Number(n) || 0;
    return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  },
};

// --------------------------------------------------------------------------- //
// toast
// --------------------------------------------------------------------------- //
function toast(msg, kind = "ok") {
  const host = document.getElementById("toast-host");
  if (!host) return;
  const t = document.createElement("div");
  t.className = "toast toast-" + (kind || "ok");
  t.textContent = msg;
  host.appendChild(t);
  setTimeout(() => {
    t.style.transition = "opacity .2s";
    t.style.opacity = "0";
    setTimeout(() => t.remove(), 220);
  }, 3200);
}

// --------------------------------------------------------------------------- //
// views registry -- Dashboard is local; the rest are imported modules.
// --------------------------------------------------------------------------- //
const dashboard = {
  view: { id: "dashboard", label: "Dashboard" },
  render: renderDashboard,
};

const ROLE_RANK = { viewer: 0, member: 1, manager: 2, admin: 3 };

// Every view module, keyed by its own id. Views are no longer top-level nav
// items -- each is mounted as a tab inside one of the 8 hub pages defined below.
const CHILD_MODULES = [
  dashboard, analytics, reports, inventory, catalog, kits, counts, controlled,
  safety, labels, preparations, purchasing, funds, map, equipment, maintenance,
  it, glassware, tickets, usage, settings, people, history, game, help, sql,
];
const CHILDREN = new Map(CHILD_MODULES.map((m) => [m.view.id, m]));

// Views declare a minimum role (default "viewer").
function viewMinRole(mod) {
  return (mod && mod.view && mod.view.minRole) || "viewer";
}

// The consolidated information architecture: 8 hubs, each a landing page with
// tabs. Each tab is [childViewId, tabLabel, fullBleed?]. A hub that exposes only
// one visible tab renders it without a tab strip.
const HUB_DEFS = [
  { id: "home", label: "Home", tabs: [
    ["dashboard", "Overview"], ["analytics", "Analytics"], ["reports", "Reports"],
  ] },
  { id: "inventory", label: "Inventory", tabs: [
    ["inventory", "Items"], ["catalog", "Catalog"], ["kits", "Kits"],
    ["glassware", "Glassware"], ["stocktake", "Stocktake"],
    ["controlled", "Controlled"], ["safety", "Safety"], ["labels", "Labels"],
  ] },
  { id: "preparations", label: "Preparations", tabs: [
    ["preparations", "Preparations"],
  ] },
  { id: "procurement", label: "Procurement", tabs: [
    ["purchasing", "Purchase Orders"], ["funds", "Funds"],
  ] },
  { id: "facilities", label: "Facilities", tabs: [
    ["map", "Floor Plan", true], ["equipment", "Equipment"],
    ["it", "IT"], ["maintenance", "Maintenance"],
  ] },
  { id: "usage", label: "Usage", tabs: [
    ["tickets", "Log Usage"], ["usage", "Usage Analytics"],
  ] },
  { id: "admin", label: "Admin", tabs: [
    ["settings", "Settings"], ["people", "People"], ["history", "Audit log"],
    ["sql", "SQL"],
  ] },
  { id: "help", label: "Help", tabs: [
    ["game", "Tutorial"], ["help", "Guide"],
  ] },
];

function buildHub(def) {
  const tabs = def.tabs
    .map(([cid, label, fullBleed]) => {
      const mod = CHILDREN.get(cid);
      return mod ? { id: cid, label, mod, fullBleed: !!fullBleed } : null;
    })
    .filter(Boolean);
  const minRank = tabs.length
    ? Math.min(...tabs.map((t) => ROLE_RANK[viewMinRole(t.mod)] || 0)) : 0;
  return { id: def.id, label: def.label, tabs, minRank };
}
const HUBS = HUB_DEFS.map(buildHub);
const HUBS_BY_ID = new Map(HUBS.map((h) => [h.id, h]));
const HUB_ORDER = HUBS.map((h) => h.id);
// child view id -> owning hub id (first hub that lists it).
const CHILD_TO_HUB = new Map();
HUBS.forEach((h) => h.tabs.forEach((t) => {
  if (!CHILD_TO_HUB.has(t.id)) CHILD_TO_HUB.set(t.id, h.id);
}));

// A navigable target is a hub id or a child view id (which resolves to its
// owning hub + that tab). Child ids are checked first, so the names shared by a
// hub and its primary child (inventory/preparations/usage/help) still land on
// the right tab.
function isNavTarget(id) {
  return CHILD_TO_HUB.has(id) || HUBS_BY_ID.has(id);
}
function canSeeRank(rank) {
  if (!ctx.user) return false;
  return (ROLE_RANK[ctx.user.role] || 0) >= (rank || 0);
}
function canSee(mod) { // child view visibility
  return canSeeRank(ROLE_RANK[viewMinRole(mod)] || 0);
}
function canSeeHub(hub) { return canSeeRank(hub.minRank); }
// A tab may also require a ui_config flag (view.requiresConfig), which is how
// the opt-in SQL console stays invisible until an admin turns it on.
function tabEnabled(mod) {
  const key = mod && mod.view && mod.view.requiresConfig;
  return !key || uiConfig[key] === true;
}
function visibleTabs(hub) {
  return hub.tabs.filter((t) => canSee(t.mod) && tabEnabled(t.mod));
}
function firstVisibleTabId(hub) {
  const t = visibleTabs(hub)[0];
  return t ? t.id : null;
}

// --------------------------------------------------------------------------- //
// admin-configurable modularity (Wave 3): the ui_config blob can rename the lab
// and, per HUB, override the nav label, hide it, or reorder it. Home + Admin are
// never hide-able so an admin can always reach the dashboard + configuration.
// Stale keys from the pre-hub (per-view) config are simply ignored.
// --------------------------------------------------------------------------- //
let uiConfig = {};
const NON_DISABLEABLE = new Set(["home", "admin"]);

function modConfig(id) {
  return (uiConfig && uiConfig.modules && uiConfig.modules[id]) || {};
}
function moduleEnabled(id) {
  if (NON_DISABLEABLE.has(id)) return true;
  return modConfig(id).enabled !== false;
}
function hubNavLabel(hub) {
  const lbl = modConfig(hub.id).label;
  return (lbl && String(lbl).trim()) || hub.label;
}
function effectiveOrder() {
  return HUB_ORDER.slice().sort((a, b) => {
    const oa = modConfig(a).order, ob = modConfig(b).order;
    const na = (typeof oa === "number") ? oa : HUB_ORDER.indexOf(a);
    const nb = (typeof ob === "number") ? ob : HUB_ORDER.indexOf(b);
    if (na !== nb) return na - nb;
    return HUB_ORDER.indexOf(a) - HUB_ORDER.indexOf(b);
  });
}
function applyLabName() {
  const el = document.getElementById("lab-name");
  const name = uiConfig && uiConfig.lab_name && String(uiConfig.lab_name).trim();
  if (el && name) el.textContent = name;
}
async function loadUiConfig() {
  try {
    const cfg = await api.get("/api/config");
    uiConfig = (cfg && typeof cfg === "object") ? cfg : {};
  } catch (_) { uiConfig = {}; }
}
// Re-pull the config and re-apply it live (used by the Settings view after a save).
async function reloadConfig() {
  await loadUiConfig();
  applyLabName();
  paintNav();
}
// The hub list (default order) for the Settings view to configure, so
// settings.js never has to hardcode or import the registry.
function moduleCatalog() {
  const rankRole = ["viewer", "member", "manager", "admin"];
  return HUB_ORDER.map((id) => {
    const hub = HUBS_BY_ID.get(id);
    return {
      id,
      defaultLabel: hub.label,
      minRole: rankRole[hub.minRank] || "viewer",
      fixed: NON_DISABLEABLE.has(id), // Home + Admin can't be hidden
    };
  });
}

// --------------------------------------------------------------------------- //
// router
// --------------------------------------------------------------------------- //
const root = document.getElementById("view-root");
let current = { hubId: null, tabId: null, params: {} };

// Resolve a navigation target (hub id or child view id) to {hubId, tabId}.
function resolveTarget(id) {
  if (CHILD_TO_HUB.has(id)) return { hubId: CHILD_TO_HUB.get(id), tabId: id };
  if (HUBS_BY_ID.has(id)) {
    return { hubId: id, tabId: firstVisibleTabId(HUBS_BY_ID.get(id)) };
  }
  return null;
}

function navigate(targetId, params = {}) {
  if (!ctx.user) return; // login gate owns the screen until a session exists
  let t = resolveTarget(targetId) || { hubId: "home", tabId: null };
  let hub = HUBS_BY_ID.get(t.hubId) || HUBS_BY_ID.get("home");
  // role + admin-disabled gate: fall back to Home.
  if (!canSeeHub(hub) || !moduleEnabled(hub.id)) {
    hub = HUBS_BY_ID.get("home");
    t = { hubId: "home", tabId: null };
  }
  // ensure the requested tab is visible, else use the first visible tab.
  const vis = visibleTabs(hub);
  let tabId = t.tabId;
  if (!tabId || !vis.some((x) => x.id === tabId)) tabId = vis.length ? vis[0].id : null;
  current = { hubId: hub.id, tabId, params: params || {} };
  // Reflect in the hash without retriggering a param-losing re-render.
  const target = "#" + (tabId || hub.id);
  if (location.hash !== target) {
    suppressHash = true;
    location.hash = target;
  }
  paintNav();
  renderCurrent();
  if (notifWired) refreshNotifCount();
}

let suppressHash = false;

// Accessibility autofix: give every form control an accessible name so screen
// readers can announce it. Views build controls with placeholders (not <label>s);
// this derives a name from the placeholder, an adjacent label, or the field type,
// clearing axe's select-name / label violations across all views from one place.
function enhanceA11y(scope) {
  const controls = scope.querySelectorAll(
    "input:not([type=hidden]), select, textarea"
  );
  controls.forEach((el) => {
    if (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") ||
        el.getAttribute("title")) return;
    if (el.closest("label")) return;
    if (el.id) {
      try { if (scope.querySelector('label[for="' + CSS.escape(el.id) + '"]')) return; }
      catch (_) { /* CSS.escape edge case: fall through */ }
    }
    let name = (el.getAttribute("placeholder") || "").trim();
    if (!name) {
      const prev = el.previousElementSibling;
      const txt = prev && prev.textContent ? prev.textContent.trim() : "";
      if (txt && txt.length <= 40) name = txt;
    }
    if (!name && el.tagName === "SELECT" && el.options.length) {
      name = "Select " + (el.options[el.selectedIndex] || el.options[0]).textContent.trim();
    }
    if (!name) {
      name = el.tagName === "SELECT" ? "Select"
        : el.type === "number" ? "Number"
        : el.type === "checkbox" ? "Toggle"
        : "Input";
    }
    el.setAttribute("aria-label", name.replace(/[:*]\s*$/, "").slice(0, 80));
  });
}

// Reflect the current location in the topbar breadcrumb, with a clickable hub
// segment (jumps to the hub's first tab). "Hub" or "Hub > Tab".
function setCrumb(hub, tab, tabCount) {
  const c = document.getElementById("crumb");
  if (!c) return;
  c.innerHTML = "";
  const hubSeg = document.createElement("button");
  hubSeg.className = "crumb-seg";
  hubSeg.textContent = hubNavLabel(hub);
  hubSeg.title = "Go to " + hubNavLabel(hub);
  hubSeg.addEventListener("click", () => navigate(firstVisibleTabId(hub) || hub.id));
  c.appendChild(hubSeg);
  if (tab && tabCount > 1) {
    c.appendChild(el2("span", "crumb-sep", "›"));
    c.appendChild(el2("span", "crumb-seg crumb-current", tab.label));
  }
}
// tiny element helper local to the shell.
function el2(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Contextual primary action in the topbar. Cleared on every render; a view opts
// in during its own render() via ctx.setPrimaryAction(label, handler).
let primaryActionHandler = null;
function clearPrimaryAction() {
  primaryActionHandler = null;
  const btn = document.getElementById("primary-action");
  if (btn) { btn.hidden = true; btn.textContent = ""; }
}
function setPrimaryAction(label, handler) {
  const btn = document.getElementById("primary-action");
  if (!btn) return;
  btn.textContent = label;
  btn.hidden = false;
  primaryActionHandler = handler;
}
function initPrimaryAction() {
  const btn = document.getElementById("primary-action");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (typeof primaryActionHandler === "function") primaryActionHandler();
  });
}

async function renderCurrent() {
  const hub = HUBS_BY_ID.get(current.hubId) || HUBS_BY_ID.get("home");
  const vis = visibleTabs(hub);
  const tab = vis.find((t) => t.id === current.tabId) || vis[0] || null;
  root.innerHTML = "";
  // A full-bleed tab (the Map floor plan) fills the content column below the strip.
  root.classList.toggle("full-bleed", !!(tab && tab.fullBleed));
  setCrumb(hub, tab, vis.length);
  clearPrimaryAction(); // a view may re-populate it during render()
  if (!tab) return; // hub with no visible tab for this role

  // Tab strip only when the hub exposes more than one visible tab.
  if (vis.length > 1) {
    const strip = document.createElement("div");
    strip.className = "hub-tabs";
    strip.setAttribute("role", "tablist");
    for (const t of vis) {
      const b = document.createElement("button");
      b.className = "hub-tab" + (t.id === tab.id ? " active" : "");
      b.textContent = t.label;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", t.id === tab.id ? "true" : "false");
      b.addEventListener("click", () => { if (t.id !== current.tabId) navigate(t.id); });
      strip.appendChild(b);
    }
    root.appendChild(strip);
  }

  const body = document.createElement("div");
  body.className = "hub-body";
  root.appendChild(body);
  try {
    await tab.mod.render(body, ctx, current.params);
    enhanceA11y(body);
  } catch (err) {
    body.innerHTML = "";
    const box = document.createElement("div");
    box.className = "card";
    box.innerHTML = `<div class="card-title">Could not render this view</div>
      <div class="muted">${String(err && err.message ? err.message : err)}</div>`;
    body.appendChild(box);
    console.error(err);
  }
}

function paintNav() {
  const nav = document.getElementById("nav");
  nav.innerHTML = "";
  for (const id of effectiveOrder()) {
    const hub = HUBS_BY_ID.get(id);
    if (!hub) continue;
    if (!canSeeHub(hub)) continue; // hide hubs above this user's role
    if (!moduleEnabled(id)) continue; // admin-disabled hub
    const b = document.createElement("button");
    b.className = "nav-item" + (id === current.hubId ? " active" : "");
    b.textContent = hubNavLabel(hub);
    // Navigate to the hub's first visible tab. (Targeting the hub id directly
    // would mis-route the hubs whose id collides with a non-first child id, e.g.
    // "usage" -> Usage Analytics or "help" -> Guide instead of the first tab.)
    b.addEventListener("click", () => {
      navigate(firstVisibleTabId(hub) || id);
      closeNavOnMobile();
    });
    nav.appendChild(b);
  }
}

function onHashChange() {
  if (suppressHash) { suppressHash = false; return; }
  const id = (location.hash || "").replace(/^#/, "") || "home";
  navigate(isNavTarget(id) ? id : "home");
}

// --------------------------------------------------------------------------- //
// sidebar -- collapsible left nav. State persists in localStorage; on a phone it
// defaults to collapsed (off-canvas) and closes after you pick a view.
// --------------------------------------------------------------------------- //
const shell = document.body; // .app-shell
function setNavCollapsed(collapsed, save = true) {
  shell.classList.toggle("nav-collapsed", collapsed);
  const expanded = collapsed ? "false" : "true";
  const toggle = document.getElementById("sidebar-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", expanded);
  const collapseBtn = document.getElementById("sidebar-collapse");
  if (collapseBtn) collapseBtn.setAttribute("aria-expanded", expanded);
  if (save) localStorage.setItem("nlm-nav", collapsed ? "collapsed" : "open");
}
function closeNavOnMobile() {
  if (window.matchMedia("(max-width: 768px)").matches) setNavCollapsed(true);
}
function initSidebar() {
  const saved = localStorage.getItem("nlm-nav");
  const collapsed = saved
    ? saved === "collapsed"
    : window.matchMedia("(max-width: 768px)").matches; // default: open on desktop, closed on phone
  setNavCollapsed(collapsed, false);
  const toggle = () => setNavCollapsed(!shell.classList.contains("nav-collapsed"));
  // Mobile hamburger (off-canvas), desktop sidebar-edge chevron, and the thin
  // edge handle that reappears when the sidebar is collapsed -- all toggle it.
  ["sidebar-toggle", "sidebar-collapse", "rail-toggle"].forEach((id) => {
    const b = document.getElementById(id);
    if (b) b.addEventListener("click", toggle);
  });
  const backdrop = document.getElementById("nav-backdrop");
  if (backdrop) backdrop.addEventListener("click", () => setNavCollapsed(true));
}

// Account dropdown menu (identity + reset/theme/logout), replacing the old
// scattered topbar buttons. Reuses the notif-panel positioning idiom.
function initUserMenu() {
  const btn = document.getElementById("user-btn");
  const menu = document.getElementById("user-menu");
  if (!btn || !menu) return;
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const open = () => { menu.hidden = false; btn.setAttribute("aria-expanded", "true"); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (menu.hidden) open(); else close();
  });
  // Menu items (reset/theme/logout) keep their own handlers; close after a pick.
  menu.addEventListener("click", () => close());
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) close();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

// Global "+ New" quick-create menu: role-gated shortcuts that jump to the right
// tab and open its add form (via a `{create:true}` param the view understands).
const QUICK_NEW = [
  { label: "New item", target: "inventory", minRank: 2 },
  { label: "New purchase order", target: "purchasing", minRank: 1 },
  { label: "New preparation", target: "preparations", minRank: 2 },
  { label: "New chore", target: "maintenance", minRank: 2 },
  { label: "New glassware", target: "glassware", minRank: 2 },
];
function buildQuickNewMenu(menu, close) {
  menu.innerHTML = "";
  const rank = ROLE_RANK[(ctx.user || {}).role] || 0;
  let any = false;
  for (const q of QUICK_NEW) {
    if (rank < q.minRank || !isNavTarget(q.target)) continue;
    any = true;
    const b = document.createElement("button");
    b.className = "quicknew-item";
    b.setAttribute("role", "menuitem");
    b.textContent = q.label;
    b.addEventListener("click", () => { close(); navigate(q.target, { create: true }); });
    menu.appendChild(b);
  }
  if (!any) {
    const d = document.createElement("div");
    d.className = "quicknew-item muted";
    d.textContent = "Nothing to create";
    menu.appendChild(d);
  }
}
function initQuickNew() {
  const btn = document.getElementById("quicknew-btn");
  const menu = document.getElementById("quicknew-menu");
  if (!btn || !menu) return;
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (menu.hidden) {
      buildQuickNewMenu(menu, close);
      menu.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    } else { close(); }
  });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) close();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

// --------------------------------------------------------------------------- //
// shared UI primitives: a modal dialog and a right-click context menu, exposed
// to every view via ctx.modal / ctx.contextMenu so views stop rolling their own.
// --------------------------------------------------------------------------- //
// ctx.modal(opts) -> {close, card, body}. opts:
//   title   -- heading text
//   body    -- a DOM Node to place in the body, OR
//   render  -- function(bodyEl) to fill the body
//   actions -- [{label, onClick(handle), primary?, danger?}] footer buttons
//   onClose -- called when dismissed
// Dismiss via the X, backdrop click, or Escape.
let modalSeq = 0;
function openModal(opts) {
  opts = opts || {};
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  const card = document.createElement("div");
  card.className = "modal-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");

  const head = document.createElement("div");
  head.className = "modal-head";
  const h = document.createElement("div");
  h.className = "modal-title";
  h.id = "modal-title-" + (++modalSeq);
  h.textContent = opts.title || "";
  card.setAttribute("aria-labelledby", h.id);
  const x = document.createElement("button");
  x.className = "modal-close";
  x.setAttribute("aria-label", "Close");
  x.textContent = "×";
  head.appendChild(h);
  head.appendChild(x);
  card.appendChild(head);

  const body = document.createElement("div");
  body.className = "modal-body";
  if (opts.body instanceof Node) body.appendChild(opts.body);
  else if (typeof opts.render === "function") opts.render(body);
  card.appendChild(body);

  let closed = false;
  const opener = document.activeElement;   // restore focus here on close
  const handle = { close, card, body };
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    // Returning focus to whatever opened the dialog keeps keyboard users where
    // they were instead of dropping them at the top of the page. When the opener
    // has since gone (a context-menu item, a re-rendered row), fall back to the
    // main region rather than leaving focus on <body>.
    if (opener && opener.isConnected && typeof opener.focus === "function") {
      opener.focus();
    } else {
      const main = document.getElementById("view-root");
      if (main) main.focus();
    }
    if (typeof opts.onClose === "function") opts.onClose();
  }
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),'
    + 'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  function onKey(e) {
    if (e.key === "Escape") { e.stopPropagation(); close(); return; }
    // A dialog must contain Tab, or the user tabs into the page behind it.
    if (e.key !== "Tab" || closed) return;
    const items = [...card.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    } else if (!card.contains(document.activeElement)) {
      e.preventDefault(); first.focus();
    }
  }

  if (opts.actions && opts.actions.length) {
    const foot = document.createElement("div");
    foot.className = "modal-foot";
    for (const a of opts.actions) {
      const btn = document.createElement("button");
      btn.className = "btn btn-sm " + (a.primary ? "btn-primary" : "btn-ghost");
      btn.textContent = a.label;
      btn.addEventListener("click", () => { if (a.onClick) a.onClick(handle); });
      foot.appendChild(btn);
    }
    card.appendChild(foot);
  }

  x.addEventListener("click", close);
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onKey, true);
  backdrop.appendChild(card);
  document.body.appendChild(backdrop);
  enhanceA11y(card);
  x.focus();
  return handle;
}

// ctx.contextMenu(x, y, items, headText?) -> the menu element. items:
//   [{label, onClick, danger?, disabled?}] or {divider:true}. Body-anchored,
//   viewport-clamped, dismissed by outside pointerdown or Escape.
let ctxMenuEl = null;
function closeContextMenu() {
  if (ctxMenuEl) { ctxMenuEl.remove(); ctxMenuEl = null; }
}
function openContextMenu(x, y, items, headText) {
  closeContextMenu();
  const menu = document.createElement("div");
  menu.className = "ctxmenu";
  menu.setAttribute("role", "menu");
  if (headText) {
    const hd = document.createElement("div");
    hd.className = "ctxmenu-head";
    hd.textContent = headText;
    menu.appendChild(hd);
  }
  for (const it of items || []) {
    if (!it) continue;
    if (it.divider) {
      const d = document.createElement("div");
      d.className = "ctxmenu-divider";
      menu.appendChild(d);
      continue;
    }
    const b = document.createElement("button");
    b.className = "ctxmenu-item" + (it.danger ? " ctxmenu-danger" : "");
    b.textContent = it.label;
    b.setAttribute("role", "menuitem");
    if (it.disabled) b.disabled = true;
    else b.addEventListener("click", () => { closeContextMenu(); if (it.onClick) it.onClick(); });
    menu.appendChild(b);
  }
  document.body.appendChild(menu);
  // viewport-clamp so it never overflows the window.
  const r = menu.getBoundingClientRect();
  let px = x, py = y;
  if (px + r.width > window.innerWidth - 4) px = Math.max(4, window.innerWidth - r.width - 4);
  if (py + r.height > window.innerHeight - 4) py = Math.max(4, window.innerHeight - r.height - 4);
  menu.style.left = px + "px";
  menu.style.top = py + "px";
  ctxMenuEl = menu;
  return menu;
}
document.addEventListener("pointerdown", (e) => {
  if (ctxMenuEl && !ctxMenuEl.contains(e.target)) closeContextMenu();
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeContextMenu(); });

// ctx.windowedList(items, renderItem, {host, footer, pageSize}) -- renders long
// lists in pages so a few thousand rows don't freeze the UI. `host` receives the
// rendered nodes (e.g. a <tbody>); `footer` holds the "Show more" control. Call
// it fresh each time the underlying list/filter changes.
function windowedList(items, renderItem, opts) {
  opts = opts || {};
  const host = opts.host;
  const footer = opts.footer;
  const pageSize = opts.pageSize || 100;
  if (!host || !footer) return;
  let shown = 0;
  function renderMore() {
    const next = items.slice(shown, shown + pageSize);
    for (const it of next) {
      const node = renderItem(it);
      if (node) host.appendChild(node);
    }
    shown += next.length;
    footer.innerHTML = "";
    if (shown < items.length) {
      const remaining = items.length - shown;
      const btn = document.createElement("button");
      btn.className = "btn btn-ghost btn-sm";
      btn.textContent = `Show more (${shown} of ${items.length}, ${remaining} hidden)`;
      btn.addEventListener("click", renderMore);
      footer.appendChild(btn);
    } else if (items.length > pageSize) {
      const done = document.createElement("div");
      done.className = "muted";
      done.style.fontSize = "12px";
      done.textContent = `Showing all ${items.length}`;
      footer.appendChild(done);
    }
  }
  renderMore();
}

// ctx passed to every module. user is {id, username, full_name, role} once
// signed in (null before); onLogin is called by the auth view on success.
const ctx = {
  api, navigate, toast, fmt, user: null, onLogin: onAuthed,
  // Settings view reads the current UI config and asks the shell to re-apply it.
  getConfig: () => uiConfig,
  reloadConfig,
  moduleCatalog,
  // A view may set a contextual primary action in the topbar during render().
  setPrimaryAction,
  // Shared UI primitives.
  modal: openModal,
  contextMenu: openContextMenu,
  windowedList,
};

// --------------------------------------------------------------------------- //
// auth gate -- app.js swaps between the login view and the normal chrome.
// --------------------------------------------------------------------------- //
let authGateShown = false;

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function setChrome(on) {
  const nav = document.getElementById("nav");
  const userWrap = document.getElementById("user-wrap");
  const logoutBtn = document.getElementById("logout-btn");
  const resetBtn = document.getElementById("reset-btn");
  const searchWrap = document.getElementById("search-wrap");
  const notifWrap = document.getElementById("notif-wrap");
  const divider = document.getElementById("topbar-divider");
  const quicknew = document.getElementById("quicknew-wrap");
  const crumb = document.getElementById("crumb");
  if (!on) {
    nav.innerHTML = "";
    if (userWrap) userWrap.hidden = true;
    logoutBtn.hidden = true;
    resetBtn.hidden = true;
    if (searchWrap) searchWrap.hidden = true;
    if (notifWrap) notifWrap.hidden = true;
    if (divider) divider.hidden = true;
    if (quicknew) quicknew.hidden = true;
    if (crumb) crumb.textContent = "";
    clearPrimaryAction();
    return;
  }
  if (searchWrap) searchWrap.hidden = false;
  if (notifWrap) notifWrap.hidden = false;
  if (divider) divider.hidden = false;
  // "+ New" is for anyone who can create something (member+ can raise a PO).
  if (quicknew) quicknew.hidden = (ROLE_RANK[ctx.user.role] || 0) < ROLE_RANK.member;
  // Populate the account menu: avatar initials, name, and the identity header.
  const avatar = document.getElementById("user-avatar");
  const uname = document.getElementById("user-name");
  const head = document.getElementById("user-menu-head");
  if (avatar) avatar.textContent = initials(ctx.user.full_name);
  if (uname) uname.textContent = ctx.user.full_name;
  if (head) head.textContent = `${ctx.user.full_name} · ${ctx.user.role}`;
  if (userWrap) userWrap.hidden = false;
  logoutBtn.hidden = false;
  // Reset requires manager+ server-side; hide it from lower roles.
  resetBtn.hidden = (ROLE_RANK[ctx.user.role] || 0) < ROLE_RANK.manager;
}

function showLogin() {
  ctx.user = null;
  authGateShown = true;
  current = { id: null, params: {} };
  setChrome(false);
  root.innerHTML = "";
  auth.render(root, ctx);
}

function handleUnauthorized() {
  if (authGateShown) return; // one gate, no toast spam
  showLogin();
}

async function onAuthed(user) {
  ctx.user = user;
  authGateShown = false;
  setChrome(true);
  // Pull the admin UI config before the first paint so nav order/labels/hidden
  // modules and the lab name are correct on the initial render.
  await loadUiConfig();
  applyLabName();
  initSearch();
  initNotifications();
  // A scanned QR label lands here as ?item=<id>: open that item directly.
  const qsItem = new URLSearchParams(location.search).get("item");
  if (qsItem && /^\d+$/.test(qsItem)) {
    navigate("inventory", { focusItem: parseInt(qsItem, 10) });
    return;
  }
  const startId = (location.hash || "").replace(/^#/, "");
  navigate(isNavTarget(startId) ? startId : "home");
}

function initLogout() {
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api.post("/api/logout", {}); } catch (_) { /* session may already be gone */ }
    showLogin();
  });
}

// --------------------------------------------------------------------------- //
// global search -- one box in the top bar; hits /api/search and drops a grouped
// result list. Wired once (idempotent), lazily on first successful auth.
// --------------------------------------------------------------------------- //
// The top-bar search field is a launcher: focusing/clicking it, or pressing "/"
// or Ctrl/Cmd-K, opens a centered command palette (search + jump-to + create).
let searchWired = false;
function initSearch() {
  if (searchWired) return;
  const input = document.getElementById("search-input");
  if (!input) return;
  searchWired = true;
  input.readOnly = true;
  // Deliberately NOT on 'focus': opening the palette when the input merely
  // receives focus made Tab a keyboard trap -- tabbing into the search stole
  // focus into the palette, and dismissing it dropped focus to <body>, so the
  // main content could never be reached by keyboard at all. Click and Enter/Space
  // are explicit intent; '/' and Ctrl-K are wired below.
  input.addEventListener("click", openCommandPalette);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openCommandPalette();
    }
  });
  document.addEventListener("keydown", (e) => {
    const isSlash = e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey;
    const isK = (e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey);
    if (!isSlash && !isK) return;
    const t = e.target;
    const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
      t.tagName === "SELECT" || t.isContentEditable);
    const wrap = document.getElementById("search-wrap");
    if (!wrap || wrap.hidden) return;
    if (isSlash && typing) return; // "/" must not hijack typing; Ctrl/Cmd-K may
    e.preventDefault();
    openCommandPalette();
  });
}

const _CMDK_TYPE_ALIASES = {
  item: "items", items: "items", location: "locations", locations: "locations",
  loc: "locations", ticket: "tickets", tickets: "tickets", equipment: "equipment",
  equip: "equipment", fund: "funds", funds: "funds", kit: "kits", kits: "kits",
};
function _cmdkParse(raw) {
  const filters = {}, terms = [];
  for (const tok of raw.split(/\s+/)) {
    const m = /^(type|cat|category|vendor|loc):(.+)$/i.exec(tok);
    if (m) { let k = m[1].toLowerCase(); if (k === "category") k = "cat"; filters[k] = m[2].toLowerCase(); }
    else if (tok) terms.push(tok);
  }
  return { text: terms.join(" "), filters };
}
function _has(v, n) { return String(v || "").toLowerCase().includes(n); }

let paletteEl = null;
let paletteOpener = null;   // element to restore focus to when the palette closes
function closeCommandPalette() {
  if (!paletteEl) return;
  paletteEl.remove();
  paletteEl = null;
  // Return focus where the user left it, so dismissing the palette does not
  // dump them back at the top of the tab order.
  const back = paletteOpener;
  paletteOpener = null;
  if (back && back.isConnected && typeof back.focus === "function") {
    back.focus();
  } else {
    const si = document.getElementById("search-input");
    if (si) si.blur();
  }
}
// Scan a printed label and open that item. The server owns code parsing (QR
// deep link / item id / vendor catalog number) via /api/scan/resolve, so the
// client stays dumb about formats.
function scanToItem() {
  openScanner(ctx, {
    title: "Scan a label",
    hint: "Point the camera at an item's QR label to open its record.",
    onCode: async (code) => {
      const res = await ctx.api.post("/api/scan/resolve", { code });
      if (!res.matched) {
        ctx.toast("That code does not match anything on file", "warn");
        return true;  // keep scanning
      }
      ctx.toast("Opening " + res.item.item_name, "ok");
      navigate("inventory", { itemId: res.item.item_id });
      return false;  // close the scanner
    },
  });
}

function openCommandPalette() {
  if (!paletteEl) paletteOpener = document.activeElement;
  if (paletteEl) return;
  const backdrop = el2("div", "cmdk-backdrop");
  const box = el2("div", "cmdk-box");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Command palette");
  const input = document.createElement("input");
  input.className = "cmdk-input";
  input.type = "text";
  input.placeholder = "Search items, locations, orders… or jump to a page";
  input.setAttribute("aria-label", "Command palette");
  input.autocomplete = "off";
  const results = el2("div", "cmdk-results");
  const foot = el2("div", "cmdk-foot",
    "↑↓ navigate · Enter open · Esc close · filters: type:items, cat:chemical, vendor:sigma");
  box.append(input, results, foot);
  backdrop.appendChild(box);
  document.body.appendChild(backdrop);
  paletteEl = backdrop;

  let rows = [], sel = -1, timer = null;

  function setSel(i) {
    if (!rows.length) { sel = -1; return; }
    i = Math.max(0, Math.min(i, rows.length - 1));
    if (sel >= 0 && rows[sel]) rows[sel].el.classList.remove("active");
    sel = i;
    rows[sel].el.classList.add("active");
    rows[sel].el.scrollIntoView({ block: "nearest" });
  }
  function activate(i) {
    if (i < 0 || !rows[i]) return;
    const run = rows[i].run;
    closeCommandPalette();
    run();
  }
  function group(name) { results.appendChild(el2("div", "cmdk-group", name)); }
  function item(label, sub, run) {
    const r = el2("div", "cmdk-item");
    r.appendChild(el2("div", "cmdk-item-main", label));
    if (sub) r.appendChild(el2("div", "cmdk-item-sub", sub));
    const idx = rows.length;
    r.addEventListener("mousedown", (e) => { e.preventDefault(); activate(idx); });
    r.addEventListener("mousemove", () => setSel(idx));
    rows.push({ el: r, run });
    results.appendChild(r);
  }

  // Command list: role-gated "Create" shortcuts + every reachable hub/tab.
  function commandList(q) {
    const out = [];
    const rank = ROLE_RANK[(ctx.user || {}).role] || 0;
    // Scan a printed label to jump straight to that item -- the bench workflow
    // the QR labels were always for.
    out.push({
      grp: "Create", label: "Scan a label (camera)", key: "scan barcode qr camera",
      run: () => scanToItem(),
    });
    for (const qn of QUICK_NEW) {
      if (rank < qn.minRank || !isNavTarget(qn.target)) continue;
      out.push({ grp: "Create", label: qn.label, key: qn.label.toLowerCase(),
        run: ((t) => () => navigate(t, { create: true }))(qn.target) });
    }
    for (const hub of HUBS) {
      if (!canSeeHub(hub) || !moduleEnabled(hub.id)) continue;
      const tabs = visibleTabs(hub);
      for (const t of tabs) {
        const label = "Go to " + hubNavLabel(hub) + (tabs.length > 1 ? " › " + t.label : "");
        out.push({ grp: "Jump to", label, key: (hubNavLabel(hub) + " " + t.label).toLowerCase(),
          run: ((id) => () => navigate(id))(t.id) });
      }
    }
    const needle = q.toLowerCase();
    return out.filter((c) => !needle || c.key.includes(needle) || c.label.toLowerCase().includes(needle));
  }

  async function render(raw) {
    results.innerHTML = "";
    rows = [];
    sel = -1;
    const { text, filters } = _cmdkParse(raw);
    const cmds = commandList(raw.trim());
    const create = cmds.filter((c) => c.grp === "Create").slice(0, 6);
    const jump = cmds.filter((c) => c.grp === "Jump to").slice(0, 8);
    if (create.length) { group("Create"); for (const c of create) item(c.label, null, c.run); }
    if (jump.length) { group("Jump to"); for (const c of jump) item(c.label, null, c.run); }

    if (text.length >= 1) {
      let data = null;
      try { data = await api.get("/api/search?q=" + encodeURIComponent(text)); } catch (_) { data = null; }
      if (paletteEl !== backdrop) return; // closed while awaiting
      if (data) {
        let items = data.items || [], locs = data.locations || [], tix = data.tickets || [];
        let equip = data.equipment || [], fnds = data.funds || [], kts = data.kits || [];
        if (filters.cat) items = items.filter((it) => _has(it.category, filters.cat));
        if (filters.vendor) {
          items = items.filter((it) => _has(it.vendor, filters.vendor));
          equip = equip.filter((e) => _has(e.make_model, filters.vendor) || _has(e.category, filters.vendor));
        }
        if (filters.loc) locs = locs.filter((l) => _has(l.name, filters.loc));
        const ta = (k) => !filters.type || _CMDK_TYPE_ALIASES[filters.type] === k;
        const groups = [
          ["Items", ta("items") ? items : [], (it) => item(it.item_name,
            (it.vendor || it.category || "") + (it.status === "deprecated" ? " · deprecated" : ""),
            () => navigate("inventory", { focusItem: it.item_id }))],
          ["Locations", ta("locations") ? locs : [], (l) => item(l.name, l.kind,
            () => navigate("map", { locationId: l.id }))],
          ["Equipment", ta("equipment") ? equip : [], (e) => item(e.name,
            [e.category, e.make_model].filter(Boolean).join(" · "),
            () => navigate("equipment", { focusEquipment: e.id }))],
          ["Funds", ta("funds") ? fnds : [], (f) => item(f.name, f.sponsor || "",
            () => navigate("funds", {}))],
          ["Kits", ta("kits") ? kts : [], (k) => item(k.name, "kit", () => navigate("kits", {}))],
          ["Usage log", ta("tickets") ? tix : [], (t) => item(
            (t.task || "ticket") + (t.purpose ? " -- " + t.purpose : ""),
            (t.username || "") + " · " + fmt.date(t.ticket_date), () => navigate("tickets", {}))],
        ];
        for (const [head, arr, mk] of groups) { if (!arr.length) continue; group(head); for (const o of arr) mk(o); }
      }
    }
    if (!rows.length) results.appendChild(el2("div", "cmdk-empty", "No matches."));
    if (rows.length) setSel(0);
  }

  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    const q = input.value;
    timer = setTimeout(() => render(q), 130);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel(sel + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel(sel - 1); }
    else if (e.key === "Enter") { e.preventDefault(); activate(sel); }
    else if (e.key === "Escape") { e.preventDefault(); closeCommandPalette(); }
  });
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) closeCommandPalette(); });
  render("");
  input.focus();
}

// --------------------------------------------------------------------------- //
// notifications -- "Alerts" bell in the top bar. Polls /api/notifications, badges
// the unread count, and drops a panel; clicking an item marks it read and jumps
// to the relevant view. Wired once; refreshed on nav and on a slow poll.
// --------------------------------------------------------------------------- //
let notifWired = false;
let notifTimer = null;
function initNotifications() {
  const btn = document.getElementById("notif-btn");
  const panel = document.getElementById("notif-panel");
  const count = document.getElementById("notif-count");
  if (!btn || !panel || !count) return;
  if (!notifWired) {
    notifWired = true;
    btn.addEventListener("click", () => {
      if (panel.hidden) { renderNotifPanel(); panel.hidden = false; }
      else panel.hidden = true;
    });
    document.addEventListener("click", (e) => {
      if (!panel.hidden && !e.target.closest("#notif-wrap")) panel.hidden = true;
    });
  }
  refreshNotifCount();
  if (notifTimer) clearInterval(notifTimer);
  notifTimer = setInterval(refreshNotifCount, 90000); // slow poll
}

let notifCache = { unread_count: 0, notifications: [] };
async function refreshNotifCount() {
  if (!ctx.user) return;
  try {
    notifCache = await api.get("/api/notifications?limit=30");
  } catch (_) { return; }
  const count = document.getElementById("notif-count");
  if (!count) return;
  const n = notifCache.unread_count || 0;
  if (n > 0) { count.textContent = String(n); count.hidden = false; }
  else { count.hidden = true; }
  const panel = document.getElementById("notif-panel");
  if (panel && !panel.hidden) renderNotifPanel();
}

function renderNotifPanel() {
  const panel = document.getElementById("notif-panel");
  if (!panel) return;
  panel.innerHTML = "";
  const head = elc("div", "notif-head");
  head.appendChild(elc("span", null, "Alerts"));
  const markAll = elc("button", "btn btn-ghost btn-sm", "Mark all read");
  markAll.addEventListener("click", async (e) => {
    e.stopPropagation();
    try { await api.post("/api/notifications/read-all", {}); } catch (_) {}
    await refreshNotifCount();
    renderNotifPanel();
  });
  head.appendChild(markAll);
  panel.appendChild(head);

  const list = notifCache.notifications || [];
  if (!list.length) {
    panel.appendChild(elc("div", "notif-item muted", "No alerts."));
    return;
  }
  for (const nt of list) {
    const item = elc("div", "notif-item" + (nt.read_at ? " notif-read" : ""));
    const dot = elc("span", "dot dot-" + (nt.severity === "danger" ? "danger" : nt.severity === "warn" ? "warn" : "ok"));
    dot.style.marginRight = "6px";
    const msg = elc("span", null, nt.message);
    const line = elc("div");
    line.appendChild(dot); line.appendChild(msg);
    item.appendChild(line);
    item.addEventListener("click", async () => {
      try { if (!nt.read_at) await api.post(`/api/notifications/${nt.id}/read`, {}); } catch (_) {}
      panel.hidden = true;
      if (nt.link_view && isNavTarget(nt.link_view)) navigate(nt.link_view);
      await refreshNotifCount();
    });
    panel.appendChild(item);
  }
}

// --------------------------------------------------------------------------- //
// Dashboard view (owned by app.js)
// --------------------------------------------------------------------------- //
// Command-center stat cards. Neutral items first, then the actionable exceptions
// across every subsystem, each tinted only when the number is a problem (>0).
const COUNT_CARDS = [
  { key: "items", label: "Active items", to: "inventory" },
  { key: "low_stock", label: "Low stock", to: "inventory", tone: "warn" },
  { key: "expiring_soon", label: "Expiring < 30d", to: "inventory", tone: "warn" },
  { key: "expired", label: "Expired lots", to: "inventory", tone: "danger" },
  { key: "misplaced", label: "Misplaced", to: "map", tone: "danger" },
  { key: "compat_conflicts", label: "Storage conflicts", to: "safety", tone: "danger" },
  { key: "pos_pending", label: "POs to approve", to: "purchasing", tone: "warn" },
  { key: "equipment_due", label: "Service due", to: "equipment", tone: "warn" },
  { key: "open_counts", label: "Open counts", to: "stocktake", tone: "warn" },
  { key: "funds_attention", label: "Funds near budget", to: "funds", tone: "danger" },
];

function elc(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Dashboard is user-customizable: each stat card + the two lower panels has a
// key; the user's hidden set persists in localStorage per username.
function dashHiddenSet() {
  try {
    const raw = localStorage.getItem("nlm-dash-" + (ctx.user ? ctx.user.username : ""));
    return new Set(raw ? JSON.parse(raw) : []);
  } catch (_) { return new Set(); }
}
function dashSaveHidden(set) {
  localStorage.setItem(
    "nlm-dash-" + (ctx.user ? ctx.user.username : ""), JSON.stringify([...set])
  );
}

async function renderDashboard(mount, c) {
  const hidden = dashHiddenSet();

  const head = elc("div");
  head.style.display = "flex";
  head.style.justifyContent = "space-between";
  head.style.alignItems = "flex-start";
  head.style.gap = "10px";
  const heads = elc("div");
  heads.appendChild(elc("h1", "view-title", "Dashboard"));
  heads.appendChild(elc("p", "view-sub", "Command center: stock, expiry, spatial and safety exceptions, approvals, equipment service, counts, and budgets at a glance."));
  head.appendChild(heads);
  const customizeBtn = elc("button", "btn btn-ghost btn-sm", "Customize");
  head.appendChild(customizeBtn);
  mount.appendChild(head);

  // Customize panel: a checklist of every card + panel; toggling re-renders.
  const customize = elc("div", "card");
  customize.hidden = true;
  customize.style.marginBottom = "14px";
  customize.appendChild(elc("div", "card-title", "Show on dashboard"));
  const choices = [
    ...COUNT_CARDS.map((s) => ({ key: s.key, label: s.label })),
    { key: "recent", label: "Recent activity" },
    { key: "attention", label: "Attention needed" },
  ];
  const cwrap = elc("div");
  cwrap.style.display = "flex";
  cwrap.style.flexWrap = "wrap";
  cwrap.style.gap = "6px 16px";
  for (const ch of choices) {
    const lab = elc("label", "muted");
    lab.style.display = "flex"; lab.style.gap = "5px"; lab.style.alignItems = "center"; lab.style.cursor = "pointer";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !hidden.has(ch.key);
    cb.addEventListener("change", () => {
      if (cb.checked) hidden.delete(ch.key); else hidden.add(ch.key);
      dashSaveHidden(hidden);
      renderCurrent();
    });
    lab.append(cb, document.createTextNode(ch.label));
    cwrap.appendChild(lab);
  }
  customize.appendChild(cwrap);
  mount.appendChild(customize);
  customizeBtn.addEventListener("click", () => { customize.hidden = !customize.hidden; });

  const cards = elc("div", "grid grid-cards");
  mount.appendChild(cards);

  const showRecent = !hidden.has("recent");
  const showAttention = !hidden.has("attention");
  const lower = elc("div", "grid");
  lower.style.gridTemplateColumns = "repeat(auto-fit, minmax(320px, 1fr))";
  lower.style.marginTop = "22px";
  mount.appendChild(lower);

  const recentCard = elc("div", "card");
  recentCard.appendChild(elc("div", "card-title", "Recent activity"));
  const recentBody = elc("div");
  recentBody.appendChild(elc("div", "muted", "Loading..."));
  recentCard.appendChild(recentBody);

  const alertsCard = elc("div", "card");
  alertsCard.appendChild(elc("div", "card-title", "Attention needed"));
  const alertsBody = elc("div");
  alertsBody.appendChild(elc("div", "muted", "Loading..."));
  alertsCard.appendChild(alertsBody);

  if (showRecent) lower.appendChild(recentCard);
  if (showAttention) lower.appendChild(alertsCard);

  let data;
  try {
    data = await c.api.get("/api/dashboard");
  } catch (err) {
    cards.innerHTML = "";
    cards.appendChild(elc("div", "empty-state", "Could not load dashboard: " + err.message));
    return;
  }

  const counts = data.counts || {};
  for (const spec of COUNT_CARDS) {
    if (hidden.has(spec.key)) continue;
    const card = elc("div", "card card-link stat");
    const val = elc("div", "stat-value", c.fmt.num(counts[spec.key] || 0));
    if (spec.tone && (counts[spec.key] || 0) > 0) {
      val.style.color = spec.tone === "danger" ? "var(--danger)" : "var(--warn)";
    }
    card.appendChild(val);
    card.appendChild(elc("div", "stat-label", spec.label));
    card.addEventListener("click", () => c.navigate(spec.to));
    cards.appendChild(card);
  }

  // recent events (only if the panel is shown)
  if (showRecent) {
  recentBody.innerHTML = "";
  const events = data.recent_events || [];
  if (!events.length) {
    recentBody.appendChild(elc("div", "muted", "No activity yet."));
  } else {
    const tbl = document.createElement("table");
    tbl.className = "table";
    const tb = document.createElement("tbody");
    for (const e of events) {
      const tr = document.createElement("tr");
      const kind = e.event_type;
      const badgeCls = kind === "consume" ? "badge" :
        kind === "restock" ? "badge badge-ok" :
        kind === "move" ? "badge" :
        kind === "expire" ? "badge badge-danger" : "badge badge-warn";
      const td1 = document.createElement("td");
      const b = elc("span", badgeCls, kind);
      td1.appendChild(b);
      const td2 = elc("td", null, e.item_name || "--");
      const td3 = elc("td", "right mono", e.quantity != null ? String(e.quantity) : "");
      const td4 = elc("td", "right muted", c.fmt.date(e.occurred_at));
      tr.append(td1, td2, td3, td4);
      tb.appendChild(tr);
    }
    tbl.appendChild(tb);
    const scroll = elc("div", "table-scroll");
    scroll.appendChild(tbl);
    recentBody.appendChild(scroll);
  }
  }

  // Aggregated attention panel: one line per subsystem that has an exception,
  // pulling a short detail from each domain endpoint. Each call is guarded so a
  // single failure (or a role without access) never breaks the panel.
  if (!showAttention) return;
  alertsBody.innerHTML = "";
  try {
    const [expiring, lowstock, misplaced, conflicts, pos, equip, openCounts, allFunds] =
      await Promise.all([
        c.api.get("/api/alerts/expiring?days=30").catch(() => []),
        c.api.get("/api/alerts/lowstock").catch(() => []),
        c.api.get("/api/alerts/misplaced").catch(() => []),
        c.api.get("/api/compatibility/conflicts").catch(() => []),
        c.api.get("/api/purchase-orders").catch(() => []),
        c.api.get("/api/equipment").catch(() => []),
        c.api.get("/api/counts").catch(() => []),
        c.api.get("/api/funds").catch(() => []),
      ]);
    const pendingPos = (pos || []).filter((p) => p.status === "pending_approval");
    const dueEquip = (equip || []).filter((e) => e.service_due);
    const openSessions = (openCounts || []).filter((s) => s.status === "open");
    const hotFunds = (allFunds || []).filter((f) => f.budget > 0 && f.pct_spent > 90);

    const groups = [
      { title: "Expiring / expired", tone: "danger", to: "inventory",
        items: (expiring || []).slice(0, 4).map((r) => `${r.item_name} (${r.days_left < 0 ? "expired" : r.days_left + "d"})`) },
      { title: "Low stock", tone: "warn", to: "inventory",
        items: (lowstock || []).slice(0, 4).map((r) => `${r.item_name} (${r.quantity_on_hand}/${r.reorder_threshold})`) },
      { title: "Misplaced containers", tone: "danger", to: "map",
        items: (misplaced || []).slice(0, 4).map((r) => `${r.item_name} in ${r.actual.box}`) },
      { title: "Storage compatibility conflicts", tone: "danger", to: "safety",
        items: (conflicts || []).slice(0, 3).map((x) => `${x.hazard_a} + ${x.hazard_b} @ ${(x.location_path || "").split(" / ").pop()}`) },
      { title: "Purchase orders awaiting approval", tone: "warn", to: "purchasing",
        items: pendingPos.slice(0, 4).map((p) => `PO #${p.id} ${p.vendor || ""}`.trim()) },
      { title: "Equipment service due", tone: "warn", to: "equipment",
        items: dueEquip.slice(0, 4).map((e) => `${e.name}${e.next_service_date ? " (" + c.fmt.date(e.next_service_date) + ")" : ""}`) },
      { title: "Open stock counts", tone: "warn", to: "stocktake",
        items: openSessions.slice(0, 4).map((s) => s.name || s.location_name || `count #${s.id}`) },
      { title: "Funds near budget", tone: "danger", to: "funds",
        items: hotFunds.slice(0, 4).map((f) => `${f.name} (${Math.round(f.pct_spent)}%)`) },
    ];
    for (const g of groups) {
      if (!g.items.length) continue;
      const row = elc("div");
      row.style.margin = "10px 0";
      const head = elc("div");
      head.style.display = "flex";
      head.style.alignItems = "center";
      head.style.gap = "8px";
      head.style.marginBottom = "4px";
      head.appendChild(elc("span", "dot dot-" + g.tone));
      const link = elc("span", null, g.title);
      link.style.fontWeight = "600";
      link.style.cursor = "pointer";
      link.addEventListener("click", () => c.navigate(g.to));
      head.appendChild(link);
      row.appendChild(head);
      const ul = elc("div", "muted");
      ul.style.fontSize = "13px";
      ul.textContent = g.items.join(" · ");
      row.appendChild(ul);
      alertsBody.appendChild(row);
    }
    if (!alertsBody.childNodes.length) {
      alertsBody.appendChild(elc("div", "muted", "Everything looks healthy -- no exceptions."));
    }
  } catch (_) {
    alertsBody.appendChild(elc("div", "muted", "Could not load alerts."));
  }
}

// --------------------------------------------------------------------------- //
// theme
// --------------------------------------------------------------------------- //
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("nlm-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "dark" ? "Light" : "Dark";
}

function initTheme() {
  const saved = localStorage.getItem("nlm-theme");
  const theme = saved || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    applyTheme(cur === "dark" ? "light" : "dark");
  });
}

// --------------------------------------------------------------------------- //
// reset
// --------------------------------------------------------------------------- //
function initReset() {
  document.getElementById("reset-btn").addEventListener("click", async () => {
    if (!confirm("Rebuild the demo database from seed data? Any changes you made will be lost.")) return;
    try {
      await api.post("/api/reset", {});
      toast("Demo data reset", "ok");
    } catch (err) {
      toast("Reset failed: " + err.message, "danger");
      return;
    }
    renderCurrent();
  });
}

// --------------------------------------------------------------------------- //
// boot -- resolve the session first; render the app or the login gate.
// --------------------------------------------------------------------------- //
initTheme();
initSidebar();
initReset();
initLogout();
initPrimaryAction();
initUserMenu();
initQuickNew();
window.addEventListener("hashchange", onHashChange);

// Re-label controls that views inject AFTER first render (forms opened on click,
// added line rows, etc.), debounced so it stays cheap.
(function observeA11y() {
  let pending = null;
  const obs = new MutationObserver(() => {
    if (pending) return;
    pending = setTimeout(() => { pending = null; enhanceA11y(root); }, 200);
  });
  obs.observe(root, { childList: true, subtree: true });
})();

(async () => {
  try {
    const data = await api.get("/api/me");
    await onAuthed(data.user);
  } catch (_) {
    handleUnauthorized();
  }
})();
