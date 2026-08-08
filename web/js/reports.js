// reports.js -- "at a glance" dashboard summary + CSV data exports.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "reports", label: "Reports", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Headline counts to show, in order. `problem: true` means the row is flagged
// amber/red when its value is > 0; otherwise it's plain neutral text.
const COUNT_ROWS = [
  { key: "items", label: "Items", problem: false },
  { key: "low_stock", label: "Low stock", problem: true },
  { key: "expiring_soon", label: "Expiring soon", problem: true },
  { key: "expired", label: "Expired", problem: true },
  { key: "misplaced", label: "Misplaced", problem: true },
  { key: "compat_conflicts", label: "Compatibility conflicts", problem: true },
  { key: "pos_pending", label: "POs pending", problem: true },
  { key: "equipment_due", label: "Equipment due", problem: true },
  { key: "open_counts", label: "Open stocktakes", problem: true },
];

const EXPORTS = [
  {
    name: "inventory",
    label: "Inventory",
    desc: "Full item list with quantities, reorder thresholds, and expiry status.",
    minRole: "member",
  },
  {
    name: "usage",
    label: "Usage / consumption",
    desc: "Consumption events across tickets and manual usage.",
    minRole: "member",
  },
  {
    name: "equipment",
    label: "Equipment",
    desc: "Equipment registry with maintenance and booking status.",
    minRole: "member",
  },
  {
    name: "funds",
    label: "Funds / budget",
    desc: "Grant and budget burn-down by fund.",
    minRole: "manager",
  },
  {
    name: "audit",
    label: "Audit trail",
    desc: "Full history of actions taken across the system.",
    minRole: "manager",
  },
];

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = ["manager", "admin"].includes(ctx.user.role);

  root.appendChild(el("h1", "view-title", "Reports"));
  root.appendChild(el("p", "view-sub", "At-a-glance lab health and CSV data exports."));

  // ---- at a glance ----
  const glance = el("div", "card section-gap");
  glance.appendChild(el("div", "card-title", "At a glance"));
  root.appendChild(glance);

  try {
    const data = await ctx.api.get("/api/dashboard");
    const counts = (data && data.counts) || {};
    const wrap = el("div", "table-scroll");
    const table = el("table", "table");
    const tbody = el("tbody");
    let any = false;
    for (const row of COUNT_ROWS) {
      if (!(row.key in counts)) continue;
      any = true;
      const tr = el("tr");
      tr.appendChild(el("td", null, row.label));
      const val = counts[row.key];
      const td = el("td", "right mono");
      const isProblem = row.problem && Number(val) > 0;
      const span = el("span", isProblem ? "badge badge-warn" : null, String(val));
      if (isProblem && (row.key === "expired" || row.key === "misplaced" || row.key === "compat_conflicts")) {
        span.className = "badge badge-danger";
      }
      td.appendChild(span);
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    if (any) {
      glance.appendChild(wrap);
    } else {
      glance.appendChild(el("p", "muted", "No summary counts available."));
    }
  } catch (err) {
    glance.appendChild(el("p", "muted", "Could not load summary counts: " + (err && err.message ? err.message : String(err))));
  }

  // ---- data health (manager+) ----
  // The stock figure and the per-lot quantities are separate numbers. When they
  // disagree the app is telling two different stories -- stock with no lot is
  // invisible to expiry alerts, and lots claiming more than the item holds is a
  // real error. Surface it instead of letting it rot.
  if (canManage) {
    const healthCard = el("div", "card section-gap");
    healthCard.appendChild(el("div", "card-title", "Data health"));
    root.appendChild(healthCard);
    try {
      const rep = await ctx.api.get("/api/integrity/stock");
      if (!rep.count) {
        healthCard.appendChild(el("p", "muted",
          "Every item's lots add up to its recorded stock."));
      } else {
        const p = el("p", "muted",
          rep.count + " item" + (rep.count === 1 ? "" : "s")
          + " where the lots do not add up to the recorded stock. "
          + "\"Untracked\" is stock with no lot behind it, so expiry alerts "
          + "cannot see it -- add a lot expiry from the item's Lots card. "
          + "\"Over-lotted\" means lots claim more than the item holds; "
          + "reconcile with Set actual quantity.");
        healthCard.appendChild(p);
        const wrap = el("div", "table-scroll");
        const table = el("table", "table");
        table.innerHTML = "<thead><tr><th>Item</th><th class=\"right\">On hand</th>"
          + "<th class=\"right\">In lots</th><th>Issue</th></tr></thead>";
        const tb = el("tbody");
        for (const r of rep.items) {
          const tr = el("tr", "row-link");
          tr.appendChild(el("td", null, r.item_name));
          tr.appendChild(el("td", "right mono", String(r.quantity_on_hand)));
          tr.appendChild(el("td", "right mono", String(r.lot_total)));
          const issue = el("td");
          if (r.untracked) {
            issue.appendChild(el("span", "badge badge-warn",
              r.untracked + " untracked"));
          }
          if (r.over_lotted) {
            issue.appendChild(el("span", "badge badge-danger",
              r.over_lotted + " over-lotted"));
          }
          tr.appendChild(issue);
          tr.addEventListener("click", () => ctx.navigate("inventory", { itemId: r.item_id }));
          tb.appendChild(tr);
        }
        table.appendChild(tb);
        wrap.appendChild(table);
        healthCard.appendChild(wrap);
      }
    } catch (err) {
      healthCard.appendChild(el("p", "muted", "Could not load data health: "
        + (err && err.message ? err.message : String(err))));
    }
  }

  // ---- data exports ----
  const exportsCard = el("div", "card section-gap");
  exportsCard.appendChild(el("div", "card-title", "Data exports"));
  root.appendChild(exportsCard);

  const list = el("div");
  for (const exp of EXPORTS) {
    if (exp.minRole === "manager" && !canManage) continue;
    const row = el("div", "card");
    row.style.marginTop = "8px";
    const nameEl = el("div");
    nameEl.appendChild(el("strong", null, exp.label));
    row.appendChild(nameEl);
    row.appendChild(el("p", "muted", exp.desc));
    const a = el("a", "btn btn-sm", "Download CSV");
    a.href = "/api/export/" + exp.name + ".csv";
    a.setAttribute("download", "");
    row.appendChild(a);
    list.appendChild(row);
  }
  if (!list.childElementCount) {
    list.appendChild(el("p", "empty-state", "No exports available for your role."));
  }
  exportsCard.appendChild(list);

  // ---- import inventory (manager/admin only) ----
  if (canManage) {
    renderImportPanel(root, ctx, glance);
  }
}

// ---- import inventory panel ------------------------------------------------
function renderImportPanel(root, ctx, glanceCard) {
  const card = el("div", "card section-gap");
  card.appendChild(el("div", "card-title", "Import inventory"));

  const cols = [
    "item_name (required)", "category", "vendor", "unit", "quantity_on_hand",
    "reorder_threshold", "reorder_max", "unit_cost", "sds_url", "hazard_class",
    "cas_number", "disposal_instructions",
  ];
  const note = el("p", "muted");
  note.textContent =
    "Accepted CSV columns: " + cols.join(", ") +
    ". Rows are matched to existing items by item_name (matches update the item; " +
    "unmatched rows create a new item). Mirrors the Inventory export format.";
  card.appendChild(note);

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".csv";
  card.appendChild(fileInput);

  const dryRunLabel = el("label", "muted");
  dryRunLabel.style.display = "block";
  dryRunLabel.style.marginTop = "8px";
  const dryRunCheckbox = document.createElement("input");
  dryRunCheckbox.type = "checkbox";
  dryRunCheckbox.checked = true;
  dryRunLabel.appendChild(dryRunCheckbox);
  dryRunLabel.appendChild(document.createTextNode(" Preview (dry run)"));
  card.appendChild(dryRunLabel);

  const importBtn = el("button", "btn btn-primary btn-sm", "Import");
  importBtn.style.marginTop = "8px";
  card.appendChild(importBtn);

  const resultBox = el("div");
  resultBox.style.marginTop = "12px";
  card.appendChild(resultBox);

  importBtn.addEventListener("click", () => {
    runImport(fileInput, dryRunCheckbox.checked, resultBox, ctx, glanceCard, {
      importBtn, fileInput, dryRunCheckbox,
    });
  });

  root.appendChild(card);
}

async function runImport(fileInput, dryRun, resultBox, ctx, glanceCard, controls) {
  resultBox.textContent = "";
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    ctx.toast("Choose a CSV file first.", "warn");
    return;
  }

  const fd = new FormData();
  fd.append("file", file);
  fd.append("dry_run", String(dryRun));

  controls.importBtn.disabled = true;
  try {
    const resp = await fetch("/api/import/inventory", {
      method: "POST",
      body: fd,
      credentials: "same-origin",
    });
    let payload = null;
    try {
      payload = await resp.json();
    } catch (parseErr) {
      payload = null;
    }
    if (!resp.ok) {
      const detail = (payload && payload.detail) ? payload.detail : ("Import failed (" + resp.status + ")");
      ctx.toast(typeof detail === "string" ? detail : JSON.stringify(detail), "danger");
      resultBox.appendChild(el("p", null, typeof detail === "string" ? detail : "Import failed."));
      return;
    }
    renderImportResult(payload || {}, dryRun, resultBox, ctx, glanceCard, controls);
  } catch (err) {
    ctx.toast("Import failed: " + (err && err.message ? err.message : String(err)), "danger");
    resultBox.appendChild(el("p", null, "Import failed: " + (err && err.message ? err.message : String(err))));
  } finally {
    controls.importBtn.disabled = false;
  }
}

function renderImportResult(result, wasDryRun, resultBox, ctx, glanceCard, controls) {
  resultBox.textContent = "";

  const created = Number(result.created || 0);
  const updated = Number(result.updated || 0);
  const errors = Array.isArray(result.errors) ? result.errors : [];

  if (wasDryRun) {
    resultBox.appendChild(el("p", null, "Preview -- nothing saved"));
  }
  resultBox.appendChild(el("p", null, created + " created, " + updated + " updated"));

  if (errors.length) {
    const errWrap = el("div");
    errWrap.style.color = "var(--danger, #b00020)";
    const list = el("ul");
    list.className = "mono";
    for (const e of errors) {
      const rowNum = e && e.row != null ? e.row : "?";
      const msg = e && e.message ? e.message : String(e);
      list.appendChild(el("li", null, "row " + rowNum + ": " + msg));
    }
    errWrap.appendChild(list);
    resultBox.appendChild(errWrap);
  }

  if (wasDryRun) {
    const runBtn = el("button", "btn btn-sm", "Run import");
    runBtn.style.marginTop = "8px";
    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      try {
        await runImport(controls.fileInput, false, resultBox, ctx, glanceCard, controls);
        await refreshGlance(glanceCard, ctx);
      } finally {
        runBtn.disabled = false;
      }
    });
    resultBox.appendChild(runBtn);
  }
}

async function refreshGlance(glanceCard, ctx) {
  const rows = glanceCard.querySelectorAll(":scope > *:not(.card-title)");
  rows.forEach((r) => r.remove());
  try {
    const data = await ctx.api.get("/api/dashboard");
    const counts = (data && data.counts) || {};
    const wrap = el("div", "table-scroll");
    const table = el("table", "table");
    const tbody = el("tbody");
    let any = false;
    for (const row of COUNT_ROWS) {
      if (!(row.key in counts)) continue;
      any = true;
      const tr = el("tr");
      tr.appendChild(el("td", null, row.label));
      const val = counts[row.key];
      const td = el("td", "right mono");
      const isProblem = row.problem && Number(val) > 0;
      const span = el("span", isProblem ? "badge badge-warn" : null, String(val));
      if (isProblem && (row.key === "expired" || row.key === "misplaced" || row.key === "compat_conflicts")) {
        span.className = "badge badge-danger";
      }
      td.appendChild(span);
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    if (any) {
      glanceCard.appendChild(wrap);
    } else {
      glanceCard.appendChild(el("p", "muted", "No summary counts available."));
    }
  } catch (err) {
    glanceCard.appendChild(el("p", "muted", "Could not load summary counts: " + (err && err.message ? err.message : String(err))));
  }
}
