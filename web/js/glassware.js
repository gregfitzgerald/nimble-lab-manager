// glassware.js -- shared labware / dishware check-out tracker.
// See who currently holds each piece; check out / return; managers add/edit/delete.
// Vanilla DOM, design-system classes only. Self-contained ES module.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "glassware", label: "Glassware", minRole: "member" };

const KINDS = ["flask", "beaker", "bottle", "dish", "cylinder", "graduated", "other"];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function statusBadge(status) {
  if (status === "available") return el("span", "badge badge-ok", "available");
  if (status === "checked_out") return el("span", "badge badge-warn", "checked out");
  if (status === "broken") return el("span", "badge badge-danger", "broken");
  if (status === "retired") return el("span", "badge", "retired");
  return el("span", "badge", status || "unknown");
}
function field(labelText, inputEl) {
  const w = el("div");
  w.style.display = "flex";
  w.style.flexDirection = "column";
  w.style.gap = "3px";
  w.appendChild(el("label", "muted", labelText));
  if (!inputEl.className) inputEl.className = "chip";
  w.appendChild(inputEl);
  return w;
}
function textInput(placeholder, type) {
  const i = document.createElement("input");
  i.type = type || "text";
  i.className = "chip";
  if (placeholder) i.placeholder = placeholder;
  return i;
}
function selectFrom(pairs) {
  const s = document.createElement("select");
  s.className = "chip";
  for (const p of pairs) {
    const [val, label] = Array.isArray(p) ? p : [p, p];
    const opt = el("option", null, label);
    opt.value = val;
    s.appendChild(opt);
  }
  return s;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = ["manager", "admin"].includes(ctx.user && ctx.user.role);
  const state = { items: [], open: [] };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Glassware"));
  head.appendChild(el("p", "view-sub", "Shared labware and dishware check-out. See who currently holds each piece, check items out, and return them."));
  root.appendChild(head);

  const boardHost = el("div", "section-gap");
  root.appendChild(boardHost);

  const container = el("div");
  root.appendChild(container);

  async function loadItems() {
    state.items = await ctx.api.get("/api/glassware");
  }
  async function loadOpen() {
    state.open = await ctx.api.get("/api/glassware/checkouts?open=true");
  }
  async function refreshAll() {
    try { await loadItems(); } catch (_) { /* best-effort */ }
    try { await loadOpen(); } catch (_) { /* best-effort */ }
    renderBoard();
    showList();
  }

  try {
    await Promise.all([loadItems(), loadOpen()]);
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load glassware: " + err.message));
    return;
  }

  renderBoard();
  showList();
  // Global "+ New" quick-create opens the add-glassware form (manager+).
  if (params && params.create && canManage) {
    const addBtn = document.getElementById("glass-add-btn");
    if (addBtn) addBtn.click();
  }

  // ---- "Currently out" board ---------------------------------------------
  function renderBoard() {
    boardHost.innerHTML = "";
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "Currently out"));

    if (!state.open.length) {
      card.appendChild(el("div", "muted", "Nothing checked out."));
      boardHost.appendChild(card);
      return;
    }

    const wrap = el("div");
    wrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Item</th><th>Held by</th><th>Due</th><th></th></tr>";
    t.appendChild(thead);
    const tb = document.createElement("tbody");
    for (const c of state.open) {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, c.name || c.item_name || ("#" + (c.item_id != null ? c.item_id : "?"))));
      tr.appendChild(el("td", "muted", c.held_by_username || c.user_username || "--"));
      const dueTd = document.createElement("td");
      if (c.due_at) {
        dueTd.className = "muted";
        dueTd.textContent = ctx.fmt.date(c.due_at);
      } else {
        dueTd.className = "muted";
        dueTd.textContent = "--";
      }
      tr.appendChild(dueTd);
      const flagTd = document.createElement("td");
      if (c.overdue) flagTd.appendChild(el("span", "badge badge-danger", "overdue"));
      tr.appendChild(flagTd);
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    scroll.appendChild(t);
    wrap.appendChild(scroll);
    card.appendChild(wrap);
    boardHost.appendChild(card);
  }

  // ---- main list ----------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search glassware...";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add glassware");
      addBtn.id = "glass-add-btn";
      addBtn.addEventListener("click", () => openAddForm());
      toolbar.appendChild(addBtn);
    }
    container.appendChild(toolbar);

    const addFormHost = el("div");
    container.appendChild(addFormHost);

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Name</th><th>Kind</th><th>Identifier</th><th>Home location</th><th>Status</th><th>Held by</th><th>Due</th><th></th></tr>";
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);

    const COLS = 8;
    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = COLS;
    noMatchTd.style.textAlign = "center";
    noMatchTd.style.padding = "28px";
    noMatchRow.appendChild(noMatchTd);
    noMatchRow.style.display = "none";
    function applySearch() {
      const q = searchInput.value.trim().toLowerCase();
      let visible = 0;
      for (const r of dataRows) {
        const match = !q || r._haystack.includes(q);
        r.style.display = match ? "" : "none";
        if (match) visible++;
      }
      noMatchRow.style.display = q && visible === 0 ? "" : "none";
    }

    if (!state.items.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No glassware registered yet.");
      td.colSpan = COLS;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const g of state.items) {
        const tr = document.createElement("tr");

        const nameTd = document.createElement("td");
        if (canManage) {
          const link = el("a", "card-link", g.name || "(unnamed)");
          link.href = "#";
          link.addEventListener("click", (e) => { e.preventDefault(); showDetail(g.id); });
          nameTd.appendChild(link);
        } else {
          nameTd.appendChild(document.createTextNode(g.name || "(unnamed)"));
        }
        tr.appendChild(nameTd);

        tr.appendChild(el("td", "muted", g.kind || "--"));
        tr.appendChild(el("td", "muted", g.identifier || "--"));
        tr.appendChild(el("td", "muted", g.location_path || "--"));

        const stTd = document.createElement("td");
        stTd.appendChild(statusBadge(g.status));
        tr.appendChild(stTd);

        tr.appendChild(el("td", "muted", g.held_by_username || "--"));

        const dueTd = document.createElement("td");
        if (g.status === "checked_out" && g.due_at) {
          if (g.overdue) dueTd.appendChild(el("span", "badge badge-danger", ctx.fmt.date(g.due_at)));
          else { dueTd.className = "muted"; dueTd.textContent = ctx.fmt.date(g.due_at); }
        } else {
          dueTd.className = "muted";
          dueTd.textContent = "--";
        }
        tr.appendChild(dueTd);

        const actTd = document.createElement("td");
        if (g.status === "available") {
          const btn = el("button", "btn btn-primary btn-sm", "Check out");
          btn.addEventListener("click", () => openCheckoutForm(g, actTd, btn));
          actTd.appendChild(btn);
        } else if (g.status === "checked_out") {
          const btn = el("button", "btn btn-ghost btn-sm", "Return");
          btn.addEventListener("click", async () => {
            btn.disabled = true;
            try {
              await ctx.api.post("/api/glassware/" + g.id + "/return", {});
              ctx.toast("Returned", "ok");
              await refreshAll();
            } catch (err) {
              ctx.toast(err.message || "Return failed", "danger");
              btn.disabled = false;
            }
          });
          actTd.appendChild(btn);
        }
        tr.appendChild(actTd);

        tr._haystack = [g.name, g.kind, g.identifier, g.location_path, g.status, g.held_by_username]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }

    // Inline check-out form (optional due date + purpose).
    function openCheckoutForm(g, cell, triggerBtn) {
      triggerBtn.disabled = true;
      const box = el("div", "well");
      box.style.marginTop = "6px";
      box.style.textAlign = "left";

      const dueInput = textInput("", "date");
      const purposeInput = textInput("Purpose (optional)");
      box.appendChild(field("Due date (optional)", dueInput));
      const purposeWrap = field("Purpose", purposeInput);
      purposeWrap.style.marginTop = "6px";
      box.appendChild(purposeWrap);

      const btnRow = el("div");
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      btnRow.style.marginTop = "8px";
      const confirm = el("button", "btn btn-primary btn-sm", "Confirm");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { box.remove(); triggerBtn.disabled = false; });
      confirm.addEventListener("click", async () => {
        confirm.disabled = true;
        try {
          await ctx.api.post("/api/glassware/" + g.id + "/checkout", {
            due_at: dueInput.value || null,
            purpose: purposeInput.value.trim() || null,
          });
          ctx.toast("Checked out", "ok");
          await refreshAll();
        } catch (err) {
          ctx.toast(err.message || "Check out failed", "danger");
          confirm.disabled = false;
        }
      });
      btnRow.append(confirm, cancel);
      box.appendChild(btnRow);
      cell.appendChild(box);
      dueInput.focus();
    }

    // Managers: inline "Add glassware" form.
    function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add glassware"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("e.g. 500 mL Erlenmeyer flask");
      const kindSel = selectFrom(KINDS);
      const identInput = textInput("Identifier / asset tag");

      gridForm.append(
        field("Name *", nameInput),
        field("Kind", kindSel),
        field("Identifier", identInput),
      );
      card.appendChild(gridForm);

      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.placeholder = "Note (optional)";
      noteArea.style.width = "100%";
      noteArea.style.marginTop = "10px";
      card.appendChild(field("Note", noteArea));

      const btnRow = el("div");
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      btnRow.style.marginTop = "10px";
      const submit = el("button", "btn btn-primary btn-sm", "Create glassware");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        submit.disabled = true;
        try {
          await ctx.api.post("/api/glassware", {
            name,
            kind: kindSel.value || null,
            identifier: identInput.value.trim() || null,
            note: noteArea.value.trim() || null,
          });
          ctx.toast("Glassware created", "ok");
          addFormHost.innerHTML = "";
          await refreshAll();
        } catch (err) {
          ctx.toast("Create failed: " + err.message, "danger");
          submit.disabled = false;
        }
      });
      btnRow.append(submit, cancel);
      card.appendChild(btnRow);
      addFormHost.appendChild(card);
      nameInput.focus();
    }
  }

  // ---- detail view (managers) --------------------------------------------
  async function showDetail(itemId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to glassware");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/glassware/" + itemId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load glassware: " + err.message));
      return;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(320px, 1fr))";
    container.appendChild(grid);
    grid.appendChild(buildSummaryCard(data, itemId));
    grid.appendChild(buildHistoryCard(data));
  }

  function buildSummaryCard(g, itemId) {
    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", g.name || "(unnamed)");
    title.style.marginBottom = "0";
    titleRow.append(title, statusBadge(g.status));
    if (g.overdue) titleRow.appendChild(el("span", "badge badge-danger", "overdue"));

    let editForm = null;
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => { if (editForm) editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete \"" + (g.name || "this item") + "\"? Its check-out history is removed too.")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/glassware/" + itemId);
          ctx.toast("Glassware deleted", "ok");
          await refreshAll();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.appendChild(delBtn);
    }
    card.appendChild(titleRow);

    const rows = [
      ["Kind", g.kind || "--"],
      ["Identifier", g.identifier || "--"],
      ["Home location", g.location_path || "--"],
      ["Held by", g.held_by_username || "--"],
      ["Checked out", g.checked_out_at ? ctx.fmt.date(g.checked_out_at) : "--"],
      ["Due", g.due_at ? ctx.fmt.date(g.due_at) : "--"],
    ];
    const dl = el("div");
    dl.style.marginTop = "10px";
    for (const [k, v] of rows) {
      const r = el("div");
      r.style.display = "flex";
      r.style.justifyContent = "space-between";
      r.style.gap = "12px";
      r.style.padding = "3px 0";
      r.appendChild(el("span", "muted", k));
      r.appendChild(el("span", null, v));
      dl.appendChild(r);
    }
    card.appendChild(dl);

    if (g.note) {
      const noteBox = el("div", "well");
      noteBox.style.marginTop = "10px";
      noteBox.style.whiteSpace = "pre-wrap";
      noteBox.textContent = g.note;
      card.appendChild(noteBox);
    }

    if (canManage) {
      editForm = el("div");
      editForm.hidden = true;
      editForm.style.marginTop = "12px";
      editForm.style.borderTop = "1px solid var(--border, #ccc)";
      editForm.style.paddingTop = "10px";

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Name"); nameInput.value = g.name || "";
      const kindSel = selectFrom(KINDS);
      if (g.kind && !KINDS.includes(g.kind)) {
        const opt = el("option", null, g.kind); opt.value = g.kind; kindSel.appendChild(opt);
      }
      kindSel.value = g.kind || "other";
      const identInput = textInput("Identifier"); identInput.value = g.identifier || "";

      gridForm.append(
        field("Name", nameInput),
        field("Kind", kindSel),
        field("Identifier", identInput),
      );
      editForm.appendChild(gridForm);

      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.style.width = "100%";
      noteArea.style.marginTop = "8px";
      noteArea.value = g.note || "";
      editForm.appendChild(field("Note", noteArea));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save changes");
      saveBtn.style.marginTop = "10px";
      saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/glassware/" + itemId, {
            name,
            kind: kindSel.value || null,
            identifier: identInput.value.trim() || null,
            note: noteArea.value.trim() || null,
          });
          ctx.toast("Glassware updated", "ok");
          try { await loadItems(); } catch (_) { /* best-effort */ }
          try { await loadOpen(); } catch (_) { /* best-effort */ }
          renderBoard();
          showDetail(itemId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });
      editForm.appendChild(saveBtn);
      card.appendChild(editForm);
    }
    return card;
  }

  function buildHistoryCard(g) {
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "Check-out history"));
    const checkouts = g.checkouts || [];
    if (!checkouts.length) {
      card.appendChild(el("div", "muted", "No check-outs recorded yet."));
      return card;
    }
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>User</th><th>Out</th><th>Due</th><th>Returned</th><th>Purpose</th></tr>";
    t.appendChild(thead);
    const tb = document.createElement("tbody");
    for (const c of checkouts) {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, c.user_username || "--"));
      tr.appendChild(el("td", "muted", c.checked_out_at ? ctx.fmt.date(c.checked_out_at) : "--"));
      tr.appendChild(el("td", "muted", c.due_at ? ctx.fmt.date(c.due_at) : "--"));
      const retTd = document.createElement("td");
      if (c.returned_at) { retTd.className = "muted"; retTd.textContent = ctx.fmt.date(c.returned_at); }
      else { retTd.appendChild(el("span", "badge badge-warn", "open")); }
      tr.appendChild(retTd);
      tr.appendChild(el("td", "muted", c.purpose || "--"));
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    scroll.appendChild(t);
    card.appendChild(scroll);
    return card;
  }
}
