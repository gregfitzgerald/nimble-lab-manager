// help.js -- static Help/About page for Nimble Lab Manager.
// Vanilla DOM, design-system classes only. No imports, no server dependency.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "help", label: "Help", minRole: "viewer" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function card(titleText) {
  const c = el("div", "card section-gap");
  if (titleText) c.appendChild(el("div", "card-title", titleText));
  return c;
}

// Feature guide: view id, label, one-line description.
const FEATURES = [
  ["inventory", "Inventory", "Reagents and consumables with lot-level expiry and reorder health."],
  ["catalog", "Catalog", "Master list of items available to stock, order, and kit."],
  ["kits", "Kits", "Bundled sets of items assembled together for a common task."],
  ["stocktake", "Stocktake", "Physical stock counts reconciled against on-hand quantities."],
  ["tickets", "Tickets", "Daily usage logs of what was consumed, for what task and purpose."],
  ["map", "Map", "Spatial layout of where containers and items physically live."],
  ["equipment", "Equipment", "Shared instrument booking and maintenance scheduling."],
  ["purchasing", "Purchasing", "Purchase orders with PI approval and receiving workflow."],
  ["funds", "Funds", "Grant budgets and spending tracked against purchase orders."],
  ["controlled", "Controlled", "DEA-style dispense register for controlled substances."],
  ["safety", "Safety", "Hazard classes and chemical compatibility checks."],
  ["labels", "Labels", "Printable QR label sheets that deep-link to items when scanned."],
  ["analytics", "Analytics", "Cost and usage trends across items, tasks, and purposes."],
  ["reports", "Reports", "Summary reports for stock, spend, and compliance."],
  ["usage", "Usage", "Per-member usage totals and breakdown by purpose."],
  ["people", "People", "Lab members, roles, and account management."],
  ["history", "History", "Audit trail of actions taken across the system."],
];

// Roles table: role, capability summary.
const ROLES = [
  ["viewer", "Read-only access to all views."],
  ["member", "+ Log usage and daily tickets, raise requisitions, book equipment, assemble kits, run stock counts."],
  ["manager", "+ Manage items and catalog, approve purchase orders, manage funds, kits, and task templates."],
  ["admin", "+ User management and system settings."],
];

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  root.appendChild(el("h1", "view-title", "Help"));
  root.appendChild(el("p", "view-sub", "About Nimble Lab Manager, roles, demo logins, and a guide to every view."));

  // 1. Overview
  const overview = card("Overview");
  overview.appendChild(el(
    "p",
    null,
    "Nimble Lab Manager is a lab inventory and operations management demo. It covers " +
    "inventory with lots and expiry tracking, spatial maps of where items live, purchasing " +
    "with PI approvals, grant budgets, equipment booking and maintenance, safety and " +
    "chemical compatibility, analytics, and an interactive tutorial (under Help > " +
    "Tutorial) that teaches the app hands-on. This is a portfolio " +
    "demonstration and runs entirely offline."
  ));
  root.appendChild(overview);

  // 2. Roles
  const rolesCard = card("Roles");
  const rolesTableWrap = el("div", "card");
  rolesTableWrap.style.padding = "0";
  const rolesScroll = el("div", "table-scroll");
  const rolesTable = el("table", "table");
  const rolesThead = el("thead");
  const rolesHeadRow = el("tr");
  rolesHeadRow.appendChild(el("th", null, "Role"));
  rolesHeadRow.appendChild(el("th", null, "Capabilities"));
  rolesThead.appendChild(rolesHeadRow);
  rolesTable.appendChild(rolesThead);
  const rolesTbody = el("tbody");
  ROLES.forEach(([role, summary]) => {
    const tr = el("tr");
    const roleCell = el("td", "mono", role);
    tr.appendChild(roleCell);
    tr.appendChild(el("td", null, summary));
    rolesTbody.appendChild(tr);
  });
  rolesTable.appendChild(rolesTbody);
  rolesScroll.appendChild(rolesTable);
  rolesTableWrap.appendChild(rolesScroll);
  rolesCard.appendChild(rolesTableWrap);
  root.appendChild(rolesCard);

  // 3. Demo logins
  const loginsCard = card("Demo logins");
  const loginsTableWrap = el("div", "card");
  loginsTableWrap.style.padding = "0";
  const loginsScroll = el("div", "table-scroll");
  const loginsTable = el("table", "table");
  const loginsThead = el("thead");
  const loginsHeadRow = el("tr");
  loginsHeadRow.appendChild(el("th", null, "Username"));
  loginsHeadRow.appendChild(el("th", null, "Password"));
  loginsThead.appendChild(loginsHeadRow);
  loginsTable.appendChild(loginsThead);
  const loginsTbody = el("tbody");
  [["admin", "admin"], ["manager", "manager"], ["member", "member"], ["viewer", "viewer"]].forEach(
    ([user, pass]) => {
      const tr = el("tr");
      tr.appendChild(el("td", "mono", user));
      tr.appendChild(el("td", "mono", pass));
      loginsTbody.appendChild(tr);
    }
  );
  loginsTable.appendChild(loginsTbody);
  loginsScroll.appendChild(loginsTable);
  loginsTableWrap.appendChild(loginsScroll);
  loginsCard.appendChild(loginsTableWrap);
  loginsCard.appendChild(el(
    "p",
    "muted",
    "These credentials apply when authentication is enabled. The open demo instance " +
    "auto-logs-in as admin."
  ));
  root.appendChild(loginsCard);

  // 4. Feature guide
  const guideCard = card("Feature guide");
  const guideList = el("div");
  FEATURES.forEach(([id, label, desc]) => {
    const row = el("div");
    row.style.display = "flex";
    row.style.gap = "10px";
    row.style.alignItems = "baseline";
    row.style.padding = "6px 0";
    row.style.borderBottom = "1px solid #ccc";

    const link = el("a", "card-link", label);
    link.href = "#";
    link.style.minWidth = "110px";
    link.addEventListener("click", (ev) => {
      ev.preventDefault();
      ctx.navigate(id);
    });
    row.appendChild(link);
    row.appendChild(el("span", "muted", desc));
    guideList.appendChild(row);
  });
  guideCard.appendChild(guideList);
  root.appendChild(guideCard);

  // 5. Keyboard & tips
  const tipsCard = card("Keyboard & tips");
  const tipsList = el("ul");
  tipsList.style.margin = "0";
  tipsList.style.paddingLeft = "20px";
  [
    '"/" or Ctrl/Cmd-K opens the command palette; type to search, use tokens like ' +
      '"cat:chemical" or "vendor:sigma", and arrow-keys + Enter to jump.',
    "Right-click an inventory item for quick actions (order, log usage, SDS, edit).",
    "Esc closes open menus, dialogs, and dropdowns.",
    "The Alerts bell shows live low-stock, expiry, approval, service, and safety notifications.",
    "QR labels deep-link to items when scanned with a phone camera.",
  ].forEach((tip) => {
    tipsList.appendChild(el("li", null, tip));
  });
  tipsCard.appendChild(tipsList);
  root.appendChild(tipsCard);

  // 6. Roadmap
  const roadmapCard = card("Roadmap");
  roadmapCard.appendChild(el(
    "p", null,
    "Planned next: a mobile/PWA experience so lab members can update inventory from " +
    "their phone at the bench -- scan a QR label to log usage or mark a delivery " +
    "received -- against this same backend. The API is already unified, so the path " +
    "is an installable, offline-capable responsive app rather than a separate native one."
  ));
  root.appendChild(roadmapCard);
}
