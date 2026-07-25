// tickets.js -- daily usage tickets: log a day's consumption against tasks,
// browse past tickets, and (manager+) manage reusable task templates.
// Vanilla DOM, design-system classes only. Self-contained ES module.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "tickets", label: "Tickets", minRole: "member" };

// Common units a member might log usage in. The item's own unit is always added
// first (and pre-selected); the rest let them record in whatever's easiest.
const COMMON_UNITS = [
  "unit", "each", "µL", "mL", "L", "mg", "g", "kg",
  "vial", "tube", "bottle", "box", "plate", "well", "rxn", "pack",
];
// Build a unit <select> defaulting to the item's tracked unit.
function unitSelect(itemUnit) {
  const sel = document.createElement("select");
  sel.className = "chip ticket-unit";
  sel.style.flex = "0 0 82px";
  const seen = new Set();
  const opts = [itemUnit, ...COMMON_UNITS].filter((u) => {
    const v = (u || "").trim();
    if (!v || seen.has(v.toLowerCase())) return false;
    seen.add(v.toLowerCase());
    return true;
  });
  for (const u of opts) {
    const o = el("option", null, u);
    o.value = u;
    sel.appendChild(o);
  }
  sel.value = (itemUnit && itemUnit.trim()) || opts[0] || "unit";
  return sel;
}

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = ["manager", "admin"].includes(ctx.user && ctx.user.role);

  root.appendChild(el("h1", "view-title", "Tickets"));
  root.appendChild(el("p", "view-sub", "Log a day's reagent and supply usage against a task. Start from a template, adjust the quantities, and submit -- stock is deducted automatically."));

  // Shared item list (used by line pickers and the template editor).
  let items = [];
  const container = el("div");
  root.appendChild(container);

  try {
    items = await ctx.api.get("/api/items");
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load items: " + err.message));
    return;
  }
  const itemById = new Map(items.map((it) => [it.item_id, it]));

  showList();

  // ======================================================================
  // LIST + NEW TICKET FORM
  // ======================================================================
  async function showList() {
    container.innerHTML = "";

    // ---- New ticket form ----
    container.appendChild(buildNewTicketForm());

    // ---- Task-template management (manager+) ----
    if (canManage) {
      container.appendChild(buildTemplatePanel());
    }

    // ---- Past tickets ----
    const listCard = el("div", "card");
    listCard.appendChild(el("div", "card-title", "Recent tickets"));
    const listBody = el("div");
    listCard.appendChild(listBody);
    container.appendChild(listCard);

    listBody.appendChild(el("div", "muted", "Loading tickets..."));
    let data;
    try {
      data = await ctx.api.get("/api/tickets");
    } catch (err) {
      listBody.innerHTML = "";
      listBody.appendChild(el("div", "empty-state", "Could not load tickets: " + err.message));
      return;
    }
    listBody.innerHTML = "";

    if (!data.can_see_all) {
      listBody.appendChild(el("div", "muted", "Showing only your tickets."));
    }

    const tickets = data.tickets || [];
    if (!tickets.length) {
      listBody.appendChild(el("div", "empty-state", "No tickets yet. Log your first day's usage above."));
      return;
    }

    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = `<thead><tr>
      <th>Date</th><th>Member</th><th>Task</th>
      <th class="right">Lines</th><th class="right">Total qty</th>
    </tr></thead>`;
    const tb = document.createElement("tbody");
    for (const tk of tickets) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, tk.ticket_date ? ctx.fmt.date(tk.ticket_date) : "--"));
      tr.appendChild(el("td", null, tk.full_name || tk.username || "--"));
      tr.appendChild(el("td", null, tk.task || "--"));
      tr.appendChild(el("td", "right mono", String(tk.line_count)));
      tr.appendChild(el("td", "right mono", ctx.fmt.num(tk.total_qty)));
      tr.addEventListener("click", () => showDetail(tk.id));
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    scroll.appendChild(t);
    listCard.style.padding = "0";
    // keep the title padded even though the card is flush for the table
    listCard.firstChild.style.padding = "16px 16px 0";
    listBody.style.padding = "0 16px 4px";
    listBody.appendChild(scroll);
  }

  // ---- Ticket detail ----
  async function showDetail(ticketId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to tickets");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let tk;
    try {
      tk = await ctx.api.get("/api/tickets/" + ticketId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load ticket: " + err.message));
      return;
    }

    const card = el("div", "card");
    card.appendChild(el("div", "card-title", tk.task || "Ticket #" + tk.id));
    const meta = el("div", "muted");
    meta.style.marginBottom = "12px";
    const who = tk.full_name || tk.username || "unknown";
    const when = tk.ticket_date ? ctx.fmt.date(tk.ticket_date) : "--";
    meta.textContent = `${when} · ${who}` + (tk.purpose ? ` · ${tk.purpose}` : "");
    card.appendChild(meta);
    if (tk.note) {
      const note = el("div", "panel", tk.note);
      note.style.marginBottom = "12px";
      card.appendChild(note);
    }

    const lines = tk.lines || [];
    if (!lines.length) {
      card.appendChild(el("div", "muted", "This ticket has no lines."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = `<thead><tr>
        <th>Item</th><th class="right">Qty</th><th>Unit</th><th class="right">Cost</th>
      </tr></thead>`;
      const tb = document.createElement("tbody");
      for (const ln of lines) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, ln.item_name || ("#" + ln.item_id)));
        tr.appendChild(el("td", "right mono", ctx.fmt.num(ln.quantity)));
        tr.appendChild(el("td", "muted", ln.unit || "--"));
        const cost = ln.unit_cost != null ? ln.unit_cost * ln.quantity : null;
        tr.appendChild(el("td", "right mono", cost != null ? ctx.fmt.money(cost) : "--"));
        tb.appendChild(tr);
      }
      const foot = document.createElement("tr");
      foot.appendChild(el("td", null, "Total"));
      foot.appendChild(el("td", "right mono", ctx.fmt.num(tk.total_qty)));
      foot.appendChild(el("td", null, ""));
      foot.appendChild(el("td", "right mono", tk.total_cost != null ? ctx.fmt.money(tk.total_cost) : "--"));
      foot.style.fontWeight = "600";
      foot.style.borderTop = "2px solid var(--border, #ccc)";
      tb.appendChild(foot);
      t.appendChild(tb);
      scroll.appendChild(t);
      card.appendChild(scroll);
    }
    container.appendChild(card);
  }

  // ======================================================================
  // NEW TICKET FORM
  // ======================================================================
  function buildNewTicketForm() {
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "New ticket"));

    // top fields row
    const fields = el("div");
    fields.style.display = "flex";
    fields.style.flexWrap = "wrap";
    fields.style.gap = "8px";
    fields.style.marginBottom = "12px";

    const dateInput = document.createElement("input");
    dateInput.type = "date";
    dateInput.className = "chip";
    dateInput.value = todayISO();
    dateInput.title = "Ticket date";

    const taskInput = document.createElement("input");
    taskInput.type = "text";
    taskInput.className = "chip";
    taskInput.placeholder = "Task (e.g. mouse perfusions)";
    taskInput.style.flex = "1 1 180px";

    const purposeInput = document.createElement("input");
    purposeInput.type = "text";
    purposeInput.className = "chip";
    purposeInput.placeholder = "Purpose / why (e.g. western blot)";
    purposeInput.style.flex = "1 1 180px";

    fields.append(dateInput, taskInput, purposeInput);
    card.appendChild(fields);

    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.className = "chip";
    noteInput.placeholder = "Note (optional)";
    noteInput.style.width = "100%";
    noteInput.style.marginBottom = "12px";
    card.appendChild(noteInput);

    // template picker
    const tmplRow = el("div");
    tmplRow.style.display = "flex";
    tmplRow.style.flexWrap = "wrap";
    tmplRow.style.gap = "8px";
    tmplRow.style.alignItems = "center";
    tmplRow.style.marginBottom = "12px";
    tmplRow.appendChild(el("span", "muted", "Start from task template:"));
    const tmplSelect = document.createElement("select");
    tmplSelect.className = "chip";
    const optNone = el("option", null, "-- none --");
    optNone.value = "";
    tmplSelect.appendChild(optNone);
    tmplRow.appendChild(tmplSelect);
    card.appendChild(tmplRow);

    let templates = [];
    ctx.api.get("/api/task-templates").then((tt) => {
      templates = tt || [];
      for (const tmpl of templates) {
        const opt = el("option", null, tmpl.name);
        opt.value = String(tmpl.id);
        tmplSelect.appendChild(opt);
      }
    }).catch(() => {
      tmplRow.appendChild(el("span", "muted", "(templates unavailable)"));
    });

    // lines area
    const linesWrap = el("div");
    linesWrap.style.marginBottom = "12px";
    card.appendChild(linesWrap);

    // Each line row: item name label + editable qty + remove.
    function addLine(itemId, qty) {
      const item = itemById.get(itemId);
      if (!item) return;
      const row = el("div");
      row.dataset.itemId = String(itemId);
      row.style.display = "flex";
      row.style.gap = "8px";
      row.style.alignItems = "center";
      row.style.marginBottom = "6px";

      const name = el("div", null, item.item_name);
      name.style.flex = "1 1 160px";

      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "0";
      qtyInput.step = "any";
      qtyInput.className = "chip";
      qtyInput.style.width = "90px";
      qtyInput.value = String(qty != null ? qty : 1);

      // Unit selector: default to the item's unit, toggle to whatever's easiest.
      const unit = unitSelect(item.unit);

      const rm = el("button", "btn btn-ghost btn-sm", "Remove");
      rm.addEventListener("click", () => row.remove());

      row.append(name, qtyInput, unit, rm);
      linesWrap.appendChild(row);
    }

    function clearLines() {
      linesWrap.innerHTML = "";
    }

    tmplSelect.addEventListener("change", () => {
      const id = tmplSelect.value;
      if (!id) return;
      const tmpl = templates.find((x) => String(x.id) === id);
      if (!tmpl) return;
      clearLines();
      for (const ln of tmpl.lines || []) {
        addLine(ln.item_id, ln.default_quantity);
      }
    });

    // add-a-line controls
    const addRow = el("div");
    addRow.style.display = "flex";
    addRow.style.flexWrap = "wrap";
    addRow.style.gap = "8px";
    addRow.style.alignItems = "center";
    addRow.style.marginBottom = "12px";

    const itemSelect = document.createElement("select");
    itemSelect.className = "chip";
    itemSelect.style.flex = "1 1 180px";
    const pick = el("option", null, "-- pick an item --");
    pick.value = "";
    itemSelect.appendChild(pick);
    for (const it of items) {
      const opt = el("option", null, `${it.item_name}${it.unit ? " (" + it.unit + ")" : ""}`);
      opt.value = String(it.item_id);
      itemSelect.appendChild(opt);
    }
    const addQty = document.createElement("input");
    addQty.type = "number";
    addQty.min = "0";
    addQty.step = "any";
    addQty.className = "chip";
    addQty.style.width = "90px";
    addQty.value = "1";
    const addBtn = el("button", "btn btn-ghost btn-sm", "Add line");
    addBtn.addEventListener("click", () => {
      if (!itemSelect.value) { ctx.toast("Pick an item first", "warn"); return; }
      const q = parseFloat(addQty.value);
      addLine(Number(itemSelect.value), isNaN(q) ? 1 : q);
      itemSelect.value = "";
      addQty.value = "1";
    });
    addRow.append(itemSelect, addQty, addBtn);
    card.appendChild(addRow);

    // submit
    const submit = el("button", "btn btn-primary", "Submit ticket");
    submit.addEventListener("click", async () => {
      const lines = [];
      for (const row of linesWrap.children) {
        const itemId = Number(row.dataset.itemId);
        const q = parseFloat(row.querySelector("input").value);
        if (!q || q <= 0) continue;
        const unitSel = row.querySelector("select.ticket-unit");
        lines.push({ item_id: itemId, quantity: q, unit: unitSel ? unitSel.value : null });
      }
      if (!lines.length) {
        ctx.toast("Add at least one line with a positive quantity", "warn");
        return;
      }
      const body = {
        task: taskInput.value.trim() || null,
        purpose: purposeInput.value.trim() || null,
        note: noteInput.value.trim() || null,
        ticket_date: dateInput.value || todayISO(),
        lines,
      };
      submit.disabled = true;
      try {
        await ctx.api.post("/api/tickets", body);
        ctx.toast("Ticket logged", "ok");
        showList();
      } catch (err) {
        ctx.toast(err.message || "Could not submit ticket", "danger");
        submit.disabled = false;
      }
    });
    card.appendChild(submit);

    return card;
  }

  // ======================================================================
  // TASK-TEMPLATE MANAGEMENT (manager+)
  // ======================================================================
  function buildTemplatePanel() {
    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    const title = el("div", "card-title", "Task templates");
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    const toggle = el("button", "btn btn-ghost btn-sm", "Show");
    titleRow.appendChild(toggle);
    card.appendChild(titleRow);

    const body = el("div");
    body.hidden = true;
    body.style.marginTop = "12px";
    card.appendChild(body);

    let loaded = false;
    toggle.addEventListener("click", () => {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden ? "Show" : "Hide";
      if (!body.hidden && !loaded) {
        loaded = true;
        reloadTemplates();
      }
    });

    async function reloadTemplates() {
      body.innerHTML = "";
      body.appendChild(buildTemplateEditor(null, reloadTemplates));

      let templates;
      try {
        templates = await ctx.api.get("/api/task-templates");
      } catch (err) {
        body.appendChild(el("div", "empty-state", "Could not load templates: " + err.message));
        return;
      }
      if (!templates.length) {
        body.appendChild(el("div", "muted", "No templates yet. Create one above."));
        return;
      }
      for (const tmpl of templates) {
        body.appendChild(buildTemplateCard(tmpl, reloadTemplates));
      }
    }

    return card;
  }

  // A read view of one template with edit/delete actions.
  function buildTemplateCard(tmpl, reload) {
    const wrap = el("div", "panel");
    wrap.style.marginTop = "10px";

    const head = el("div");
    head.style.display = "flex";
    head.style.alignItems = "center";
    head.style.gap = "10px";
    head.style.marginBottom = "6px";
    const name = el("div", null, tmpl.name);
    name.style.fontWeight = "600";
    name.style.flex = "1 1 auto";
    const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
    const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
    delBtn.style.color = "var(--danger, #b00)";
    head.append(name, editBtn, delBtn);
    wrap.appendChild(head);

    if (tmpl.description) {
      wrap.appendChild(el("div", "muted", tmpl.description));
    }

    const lines = tmpl.lines || [];
    if (lines.length) {
      const ul = el("div", "muted");
      ul.style.marginTop = "4px";
      ul.textContent = lines
        .map((l) => `${l.item_name || "#" + l.item_id} × ${l.default_quantity}${l.unit ? " " + l.unit : ""}`)
        .join(", ");
      wrap.appendChild(ul);
    } else {
      wrap.appendChild(el("div", "muted", "(no lines)"));
    }

    const editSlot = el("div");
    wrap.appendChild(editSlot);

    editBtn.addEventListener("click", () => {
      if (editSlot.firstChild) { editSlot.innerHTML = ""; return; }
      editSlot.appendChild(buildTemplateEditor(tmpl, reload));
    });

    delBtn.addEventListener("click", async () => {
      delBtn.disabled = true;
      try {
        await ctx.api.del("/api/task-templates/" + tmpl.id);
        ctx.toast("Template deleted", "ok");
        reload();
      } catch (err) {
        ctx.toast(err.message || "Delete failed", "danger");
        delBtn.disabled = false;
      }
    });

    return wrap;
  }

  // Create (tmpl==null) or edit an existing template. Replaces lines wholesale.
  function buildTemplateEditor(tmpl, reload) {
    const isNew = !tmpl;
    const box = el("div");
    box.style.marginTop = "10px";
    box.style.paddingTop = "10px";
    box.style.borderTop = "1px solid var(--border, #ccc)";

    box.appendChild(el("div", "muted", isNew ? "New template" : "Edit template"));

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "chip";
    nameInput.placeholder = "Template name";
    nameInput.style.width = "100%";
    nameInput.style.margin = "6px 0";
    nameInput.value = tmpl ? (tmpl.name || "") : "";
    box.appendChild(nameInput);

    const descInput = document.createElement("input");
    descInput.type = "text";
    descInput.className = "chip";
    descInput.placeholder = "Description (optional)";
    descInput.style.width = "100%";
    descInput.style.marginBottom = "6px";
    descInput.value = tmpl ? (tmpl.description || "") : "";
    box.appendChild(descInput);

    const linesWrap = el("div");
    linesWrap.style.marginBottom = "6px";
    box.appendChild(linesWrap);

    function addLine(itemId, qty) {
      const item = itemById.get(itemId);
      if (!item) return;
      const row = el("div");
      row.dataset.itemId = String(itemId);
      row.style.display = "flex";
      row.style.gap = "8px";
      row.style.alignItems = "center";
      row.style.marginBottom = "6px";
      const nm = el("div", null, item.item_name);
      nm.style.flex = "1 1 140px";
      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "0";
      qtyInput.step = "any";
      qtyInput.className = "chip";
      qtyInput.style.width = "90px";
      qtyInput.value = String(qty != null ? qty : 1);
      const rm = el("button", "btn btn-ghost btn-sm", "Remove");
      rm.addEventListener("click", () => row.remove());
      row.append(nm, qtyInput, rm);
      linesWrap.appendChild(row);
    }

    for (const ln of (tmpl && tmpl.lines) || []) {
      addLine(ln.item_id, ln.default_quantity);
    }

    // add-line controls
    const addRow = el("div");
    addRow.style.display = "flex";
    addRow.style.flexWrap = "wrap";
    addRow.style.gap = "8px";
    addRow.style.marginBottom = "8px";
    const itemSelect = document.createElement("select");
    itemSelect.className = "chip";
    itemSelect.style.flex = "1 1 160px";
    const pick = el("option", null, "-- pick an item --");
    pick.value = "";
    itemSelect.appendChild(pick);
    for (const it of items) {
      const opt = el("option", null, it.item_name);
      opt.value = String(it.item_id);
      itemSelect.appendChild(opt);
    }
    const addQty = document.createElement("input");
    addQty.type = "number";
    addQty.min = "0";
    addQty.step = "any";
    addQty.className = "chip";
    addQty.style.width = "90px";
    addQty.value = "1";
    const addBtn = el("button", "btn btn-ghost btn-sm", "Add line");
    addBtn.addEventListener("click", () => {
      if (!itemSelect.value) { ctx.toast("Pick an item first", "warn"); return; }
      const q = parseFloat(addQty.value);
      addLine(Number(itemSelect.value), isNaN(q) ? 1 : q);
      itemSelect.value = "";
      addQty.value = "1";
    });
    addRow.append(itemSelect, addQty, addBtn);
    box.appendChild(addRow);

    const saveBtn = el("button", "btn btn-primary btn-sm", isNew ? "Create template" : "Save changes");
    saveBtn.addEventListener("click", async () => {
      const name = nameInput.value.trim();
      if (!name) { ctx.toast("Template needs a name", "warn"); return; }
      const lines = [];
      for (const row of linesWrap.children) {
        const q = parseFloat(row.querySelector("input").value);
        if (!q || q <= 0) continue;
        lines.push({ item_id: Number(row.dataset.itemId), default_quantity: q });
      }
      const bodyPayload = { name, description: descInput.value.trim() || null, lines };
      saveBtn.disabled = true;
      try {
        if (isNew) {
          await ctx.api.post("/api/task-templates", bodyPayload);
          ctx.toast("Template created", "ok");
          nameInput.value = "";
          descInput.value = "";
          linesWrap.innerHTML = "";
        } else {
          await ctx.api.patch("/api/task-templates/" + tmpl.id, bodyPayload);
          ctx.toast("Template saved", "ok");
        }
        reload();
      } catch (err) {
        ctx.toast(err.message || "Save failed", "danger");
        saveBtn.disabled = false;
      }
    });
    box.appendChild(saveBtn);

    return box;
  }
}
