// sql.js -- read-only SQL console over the lab database (admin, opt-in).
//
// The backend is a single SQLite file, so an admin who knows SQL can answer
// questions no built-in report anticipates. The server enforces the safety
// (read-only handle + SQLite authorizer + secret redaction + row/time caps);
// this view is just a good place to type a query and read the answer.
//
// Hidden unless ui_config.sql_console_enabled is true -- see view.requiresConfig.

export const view = {
  id: "sql",
  label: "SQL",
  minRole: "admin",
  requiresConfig: "sql_console_enabled",
};

const SAMPLES = [
  {
    label: "Spend by month",
    sql: "SELECT strftime('%Y-%m', po.ordered_at) AS month,\n"
      + "       ROUND(SUM(pl.quantity * pl.unit_cost), 2) AS spend\n"
      + "  FROM purchase_order po\n"
      + "  JOIN po_line pl ON pl.po_id = po.id\n"
      + " WHERE po.ordered_at IS NOT NULL\n"
      + " GROUP BY month\n"
      + " ORDER BY month",
  },
  {
    label: "Most-used items (90 days)",
    sql: "SELECT i.item_name, SUM(e.quantity) AS used\n"
      + "  FROM usage_event e\n"
      + "  JOIN inventory i ON i.item_id = e.item_id\n"
      + " WHERE e.event_type = 'consume'\n"
      + "   AND date(e.occurred_at) >= date('now', '-90 day')\n"
      + " GROUP BY i.item_id\n"
      + " ORDER BY used DESC\n"
      + " LIMIT 20",
  },
  {
    label: "Lots expiring in 60 days",
    sql: "SELECT i.item_name, l.lot_number, l.expiry_date, l.quantity\n"
      + "  FROM item_lot l\n"
      + "  JOIN inventory i ON i.item_id = l.item_id\n"
      + " WHERE l.quantity > 0 AND l.expiry_date IS NOT NULL\n"
      + "   AND l.expiry_date <= date('now', '+60 day')\n"
      + " ORDER BY l.expiry_date",
  },
];

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

const isNumber = (v) => typeof v === "number";

export async function render(root, ctx) {
  root.appendChild(el("h1", "view-title", "SQL"));
  root.appendChild(el("p", "view-sub",
    "Read-only queries against the lab database. Writes, schema changes and "
    + "credentials are refused by the server; results are capped and every query "
    + "is recorded in the audit log."));

  // ---- editor ----
  const editorCard = el("div", "card");
  editorCard.appendChild(el("div", "card-title", "Query"));

  const area = document.createElement("textarea");
  area.className = "chip sql-editor";
  area.rows = 8;
  area.spellcheck = false;
  area.setAttribute("aria-label", "SQL query");
  area.placeholder = "SELECT item_name, quantity_on_hand FROM inventory ORDER BY item_name";
  editorCard.appendChild(area);

  const bar = el("div", "sql-bar");
  const runBtn = el("button", "btn btn-primary btn-sm", "Run query");
  const hint = el("span", "muted", "Ctrl+Enter to run");
  bar.append(runBtn, hint);
  editorCard.appendChild(bar);

  const samples = el("div", "sql-samples");
  samples.appendChild(el("span", "muted", "Examples:"));
  for (const s of SAMPLES) {
    const b = el("button", "btn btn-sm", s.label);
    b.addEventListener("click", () => { area.value = s.sql; area.focus(); });
    samples.appendChild(b);
  }
  editorCard.appendChild(samples);
  root.appendChild(editorCard);

  // ---- results ----
  const resultCard = el("div", "card section-gap");
  resultCard.appendChild(el("div", "card-title", "Result"));
  const status = el("div", "muted", "Run a query to see results.");
  resultCard.appendChild(status);
  const resultBody = el("div");
  resultCard.appendChild(resultBody);
  root.appendChild(resultCard);

  async function run() {
    const sql = area.value.trim();
    if (!sql) { ctx.toast("Enter a query", "warn"); return; }
    runBtn.disabled = true;
    status.className = "muted";
    status.textContent = "Running...";
    resultBody.innerHTML = "";
    try {
      const res = await ctx.api.post("/api/sql/query", { sql });
      renderResult(res);
    } catch (err) {
      status.className = "sql-error";
      status.textContent = (err && err.message) ? err.message : String(err);
    } finally {
      runBtn.disabled = false;
    }
  }

  function renderResult(res) {
    const parts = [
      res.row_count + (res.row_count === 1 ? " row" : " rows"),
      res.elapsed_ms + " ms",
    ];
    if (res.truncated) parts.push("truncated to the first " + res.row_count);
    status.className = res.truncated ? "sql-warn" : "muted";
    status.textContent = parts.join(" · ");

    if (!res.row_count) {
      resultBody.appendChild(el("p", "muted", "No rows matched."));
      return;
    }
    const scroll = el("div", "table-scroll");
    const table = el("table", "table");
    const thead = el("thead");
    const hr = el("tr");
    for (const c of res.columns) hr.appendChild(el("th", null, c));
    thead.appendChild(hr);
    table.appendChild(thead);
    const tb = el("tbody");
    for (const row of res.rows) {
      const tr = el("tr");
      for (const value of row) {
        // textContent throughout: query results are data, never markup.
        const td = el("td", isNumber(value) ? "right mono" : null);
        if (value === null) {
          td.appendChild(el("span", "muted", "null"));
        } else {
          td.textContent = String(value);
        }
        tr.appendChild(td);
      }
      tb.appendChild(tr);
    }
    table.appendChild(tb);
    scroll.appendChild(table);
    resultBody.appendChild(scroll);
  }

  runBtn.addEventListener("click", run);
  area.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); run(); }
  });

  // ---- schema reference ----
  const schemaCard = el("div", "card section-gap");
  schemaCard.appendChild(el("div", "card-title", "Tables"));
  const schemaBody = el("div", "muted", "Loading schema...");
  schemaCard.appendChild(schemaBody);
  root.appendChild(schemaCard);

  try {
    const { tables } = await ctx.api.get("/api/sql/schema");
    schemaBody.innerHTML = "";
    schemaBody.className = "sql-schema";
    for (const t of tables) {
      const det = document.createElement("details");
      const sum = document.createElement("summary");
      sum.textContent = t.name + " (" + t.columns.length + ")";
      det.appendChild(sum);
      const cols = el("div", "sql-cols");
      for (const c of t.columns) {
        const chip = el("button", "btn btn-sm mono", c);
        chip.title = "Insert " + t.name + "." + c;
        chip.addEventListener("click", () => {
          const insert = t.name + "." + c;
          const at = area.selectionStart != null ? area.selectionStart : area.value.length;
          area.value = area.value.slice(0, at) + insert + area.value.slice(at);
          area.focus();
        });
        cols.appendChild(chip);
      }
      det.appendChild(cols);
      schemaBody.appendChild(det);
    }
  } catch (err) {
    schemaBody.textContent = "Could not load the schema: "
      + (err && err.message ? err.message : err);
  }

  area.focus();
}
