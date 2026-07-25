// safety.js -- chemical/hazard storage compatibility view.
// Vanilla DOM, design-system classes only. Self-contained (no cross-view imports).
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "safety", label: "Safety", minRole: "member" };

// Static fallback reference (used only if GET /api/compatibility/rules 404s).
const STATIC_RULES = [
  { hazard_a: "flammable", hazard_b: "oxidizer", severity: "danger",
    reason: "Flammables must be segregated from oxidizers (fire/explosion risk)." },
  { hazard_a: "acid", hazard_b: "base", severity: "danger",
    reason: "Acids and bases must not be co-stored (violent neutralization)." },
  { hazard_a: "flammable", hazard_b: "corrosive", severity: "warn",
    reason: "Keep flammables away from corrosives." },
  { hazard_a: "oxidizer", hazard_b: "corrosive", severity: "warn",
    reason: "Oxidizers and corrosives should be separated." },
  { hazard_a: "water-reactive", hazard_b: "acid", severity: "danger",
    reason: "Water-reactives must be isolated from aqueous acids." },
];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function severityBadge(severity) {
  if (severity === "danger") return el("span", "badge badge-danger", "danger");
  if (severity === "warn") return el("span", "badge badge-warn", "warn");
  return el("span", "badge", severity || "unknown");
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  root.appendChild(el("h1", "view-title", "Safety"));
  root.appendChild(el("p", "view-sub", "Storage-compatibility conflicts and hazard-class segregation reference."));

  const container = el("div");
  root.appendChild(container);

  // ---- Storage compatibility section --------------------------------------
  const conflictsCard = el("div", "card");
  conflictsCard.appendChild(el("div", "card-title", "Storage compatibility"));
  container.appendChild(conflictsCard);

  let conflicts = null;
  try {
    conflicts = await ctx.api.get("/api/compatibility/conflicts");
  } catch (err) {
    conflictsCard.appendChild(el("div", "empty-state", "Could not load storage-compatibility conflicts: " + err.message));
  }

  if (conflicts) {
    if (!conflicts.length) {
      conflictsCard.appendChild(el("div", "empty-state", "No storage-compatibility conflicts -- hazards are properly segregated."));
    } else {
      const tableWrap = el("div", "card");
      tableWrap.style.padding = "0";
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Location</th><th>Hazard A</th><th>Hazard B</th><th>Items involved</th><th>Severity</th></tr>";
      t.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const c of conflicts) {
        const tr = el("tr", "row-link");

        const locTd = document.createElement("td");
        locTd.appendChild(document.createTextNode(c.location_path || "(unknown location)"));
        if (c.reason) {
          const reasonEl = el("div", "muted", c.reason);
          reasonEl.style.fontSize = "0.9em";
          reasonEl.style.marginTop = "2px";
          locTd.appendChild(reasonEl);
        }
        tr.appendChild(locTd);

        tr.appendChild(el("td", null, c.hazard_a || "--"));
        tr.appendChild(el("td", null, c.hazard_b || "--"));

        const itemsTd = document.createElement("td");
        const itemsA = Array.isArray(c.items_a) ? c.items_a : [];
        const itemsB = Array.isArray(c.items_b) ? c.items_b : [];
        const aLine = el("div", null, (c.hazard_a || "A") + ": " + (itemsA.length ? itemsA.join(", ") : "--"));
        const bLine = el("div", null, (c.hazard_b || "B") + ": " + (itemsB.length ? itemsB.join(", ") : "--"));
        itemsTd.append(aLine, bLine);
        tr.appendChild(itemsTd);

        const sevTd = document.createElement("td");
        sevTd.appendChild(severityBadge(c.severity));
        tr.appendChild(sevTd);

        tr.style.cursor = "pointer";
        tr.addEventListener("click", () => ctx.navigate("map"));
        tbody.appendChild(tr);
      }
      t.appendChild(tbody);
      scroll.appendChild(t);
      tableWrap.appendChild(scroll);
      conflictsCard.appendChild(tableWrap);
    }
  }

  // ---- Hazard incompatibility reference section ---------------------------
  const spacer = el("div", "section-gap");
  container.appendChild(spacer);

  const rulesCard = el("div", "card");
  rulesCard.appendChild(el("div", "card-title", "Hazard incompatibility reference"));
  rulesCard.appendChild(el("div", "muted", "Hazard classes that must not be co-stored."));
  container.appendChild(rulesCard);

  let rules = null;
  let rulesAreFallback = false;
  try {
    rules = await ctx.api.get("/api/compatibility/rules");
  } catch (err) {
    rules = STATIC_RULES;
    rulesAreFallback = true;
  }

  if (rulesAreFallback) {
    const note = el("div", "muted", "Live rules endpoint unavailable -- showing the standard reference list.");
    note.style.marginTop = "8px";
    rulesCard.appendChild(note);
  }

  if (!rules || !rules.length) {
    rulesCard.appendChild(el("div", "empty-state", "No hazard incompatibility rules configured."));
  } else {
    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    tableWrap.style.marginTop = "8px";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Hazard A</th><th>Hazard B</th><th>Severity</th><th>Reason</th></tr>";
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const r of rules) {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, r.hazard_a || "--"));
      tr.appendChild(el("td", null, r.hazard_b || "--"));
      const sevTd = document.createElement("td");
      sevTd.appendChild(severityBadge(r.severity));
      tr.appendChild(sevTd);
      tr.appendChild(el("td", "muted", r.reason || "--"));
      tbody.appendChild(tr);
    }
    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    rulesCard.appendChild(tableWrap);
  }
}
