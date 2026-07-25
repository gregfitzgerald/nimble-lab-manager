// controlled.js -- DEA-style controlled-substance register.
// List of controlled items -> per-item log register with balance and a
// "record entry" form (dispense requires witness). Vanilla DOM only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "controlled", label: "Controlled", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function scheduleBadge(schedule) {
  return el("span", "badge badge-warn", schedule ? "Schedule " + schedule : "controlled");
}
function changeBadge(change, ctx) {
  const n = Number(change);
  const sign = n > 0 ? "+" : "";
  const label = sign + ctx.fmt.num(n);
  return el("span", "badge " + (n < 0 ? "badge-danger" : "badge-ok"), label);
}
function fmtDateTime(s) {
  if (!s) return "--";
  const d = new Date(s);
  if (isNaN(d.getTime())) return String(s);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  root.appendChild(el("h1", "view-title", "Controlled Substances"));
  root.appendChild(el("p", "view-sub", "DEA-style register of controlled items. Every dispense (negative change) requires a witness."));

  const container = el("div");
  root.appendChild(container);

  const focusId = params && params.itemId != null ? Number(params.itemId) : null;
  if (focusId != null) {
    await showRegister(focusId);
  } else {
    await showList();
  }

  // ---- list view ------------------------------------------------------------
  async function showList() {
    container.innerHTML = "";
    let items;
    try {
      items = await ctx.api.get("/api/controlled");
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load the controlled substance register: " + err.message));
      return;
    }

    if (!items.length) {
      container.appendChild(el("div", "empty-state", "No controlled substances on the register."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = "<thead><tr><th>Name</th><th>Schedule</th><th>Unit</th><th class=\"right\">Balance</th><th>Last entry</th></tr></thead>";
    const tbody = document.createElement("tbody");
    for (const it of items) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, it.item_name));
      const schedTd = document.createElement("td");
      schedTd.appendChild(scheduleBadge(it.controlled_schedule));
      tr.appendChild(schedTd);
      tr.appendChild(el("td", "muted", it.unit || "--"));
      tr.appendChild(el("td", "right mono", ctx.fmt.num(it.quantity_on_hand)));
      tr.appendChild(el("td", "muted", it.last_entry ? ctx.fmt.date(it.last_entry) : "--"));
      tr.addEventListener("click", () => showRegister(it.item_id));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  // ---- register (detail) view ------------------------------------------------
  async function showRegister(itemId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to register list");
    back.style.marginBottom = "14px";
    back.addEventListener("click", () => { ctx.navigate("controlled"); showList(); });
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get(`/api/controlled/${itemId}/log`);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load this register: " + err.message));
      return;
    }
    const item = data.item;
    const entries = data.entries || [];

    const header = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", item.item_name);
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    titleRow.appendChild(scheduleBadge(item.controlled_schedule));
    header.appendChild(titleRow);

    const stats = el("div", "grid");
    stats.style.gridTemplateColumns = "repeat(2, 1fr)";
    stats.style.gap = "10px";
    stats.style.margin = "12px 0";
    const balStat = el("div", "stat");
    balStat.append(el("div", "stat-value", ctx.fmt.num(item.quantity_on_hand)), el("div", "stat-label", "Current balance"));
    const unitStat = el("div", "stat");
    unitStat.append(el("div", "stat-value", item.unit || "--"), el("div", "stat-label", "Unit"));
    stats.append(balStat, unitStat);
    header.appendChild(stats);

    header.appendChild(buildEntryForm());
    container.appendChild(header);

    const logCard = el("div", "card");
    logCard.style.padding = "0";
    logCard.style.marginTop = "16px";
    if (!entries.length) {
      const empty = el("div", "empty-state", "No log entries recorded for this item yet.");
      logCard.style.padding = "";
      logCard.appendChild(empty);
    } else {
      const scroll = el("div", "table-scroll");
      const table = document.createElement("table");
      table.className = "table";
      table.innerHTML = "<thead><tr><th>When</th><th>User</th><th class=\"right\">Change</th><th class=\"right\">Balance after</th><th>Reason</th><th>Witness</th></tr></thead>";
      const tbody = document.createElement("tbody");
      const sorted = entries.slice().sort((a, b) => {
        const da = new Date(a.occurred_at).getTime();
        const db = new Date(b.occurred_at).getTime();
        return db - da;
      });
      for (const e of sorted) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", "muted", fmtDateTime(e.occurred_at)));
        tr.appendChild(el("td", null, e.username || "--"));
        const changeTd = document.createElement("td");
        changeTd.className = "right";
        changeTd.appendChild(changeBadge(e.change, ctx));
        tr.appendChild(changeTd);
        tr.appendChild(el("td", "right mono", ctx.fmt.num(e.balance_after)));
        tr.appendChild(el("td", null, e.reason || "--"));
        tr.appendChild(el("td", null, e.witness || "--"));
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      scroll.appendChild(table);
      logCard.appendChild(scroll);
    }
    container.appendChild(logCard);

    // ---- record entry form ---------------------------------------------------
    function buildEntryForm() {
      const wrap = el("div", "panel");
      wrap.style.marginTop = "8px";
      wrap.appendChild(el("div", "card-title", "Record entry"));

      const row = el("div");
      row.style.display = "flex";
      row.style.flexWrap = "wrap";
      row.style.gap = "8px";
      row.style.alignItems = "center";

      const changeInput = document.createElement("input");
      changeInput.type = "number";
      changeInput.step = "any";
      changeInput.className = "chip";
      changeInput.placeholder = "Change (e.g. -5 or 10)";
      changeInput.style.width = "160px";

      const reasonInput = document.createElement("input");
      reasonInput.type = "text";
      reasonInput.className = "chip";
      reasonInput.placeholder = "Reason";
      reasonInput.style.flex = "1 1 160px";

      const witnessInput = document.createElement("input");
      witnessInput.type = "text";
      witnessInput.className = "chip";
      witnessInput.placeholder = "Witness (required for dispense)";
      witnessInput.style.flex = "1 1 200px";

      const submitBtn = el("button", "btn btn-primary", "Submit");

      row.append(changeInput, reasonInput, witnessInput, submitBtn);
      wrap.appendChild(row);

      const errorMsg = el("div", "muted");
      errorMsg.style.marginTop = "6px";
      errorMsg.style.display = "none";
      wrap.appendChild(errorMsg);

      function showError(msg) {
        errorMsg.textContent = msg;
        errorMsg.style.color = "var(--danger, #b00020)";
        errorMsg.style.display = "block";
      }
      function clearError() {
        errorMsg.style.display = "none";
        errorMsg.textContent = "";
      }

      submitBtn.addEventListener("click", async () => {
        clearError();
        const raw = changeInput.value.trim();
        const change = Number(raw);
        if (!raw || Number.isNaN(change) || change === 0) {
          showError("Enter a non-zero change amount.");
          ctx.toast("Enter a non-zero change amount", "warn");
          return;
        }
        const witness = witnessInput.value.trim();
        if (change < 0 && !witness) {
          showError("Witness is required for a dispense (negative change).");
          ctx.toast("Witness is required for a dispense", "warn");
          return;
        }
        const body = { change, reason: reasonInput.value.trim(), witness: witness || undefined };
        submitBtn.disabled = true;
        try {
          await ctx.api.post(`/api/controlled/${itemId}/log`, body);
          ctx.toast("Entry recorded", "ok");
          await showRegister(itemId);
        } catch (err) {
          showError(err.message);
          ctx.toast("Could not record entry: " + err.message, "danger");
          submitBtn.disabled = false;
        }
      });

      return wrap;
    }
  }
}
