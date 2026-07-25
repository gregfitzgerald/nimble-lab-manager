// maintenance.js -- recurring lab chores (cleaning, autoclaving, DI-water fills,
// calibration, stocking, other). Vanilla DOM, design-system classes only.
// Self-contained ES module.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "maintenance", label: "Maintenance", minRole: "member" };

const CATEGORIES = ["cleaning", "autoclave", "water", "calibration", "stocking", "other"];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
// Flatten the nested location tree into "-- indented" options with full-ish labels.
function flattenLocations(roots) {
  const out = [];
  function walk(nodes, depth) {
    for (const n of nodes || []) {
      out.push({ id: n.id, label: " ".repeat(depth * 2) + (n.name || ("#" + n.id)) + " (" + (n.kind || "?") + ")" });
      if (n.children && n.children.length) walk(n.children, depth + 1);
    }
  }
  walk(roots, 0);
  return out;
}
// A labelled field wrapper (vertical) for forms.
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
function dueCell(chore, ctx) {
  const td = document.createElement("td");
  if (!chore.next_due) { td.className = "muted"; td.textContent = "--"; return td; }
  const dateStr = ctx.fmt.date(chore.next_due);
  if (chore.overdue) {
    td.appendChild(el("span", "badge badge-danger", dateStr + " (overdue)"));
  } else if (chore.days_to_due != null && chore.days_to_due <= 3) {
    td.appendChild(el("span", "badge badge-warn", dateStr));
  } else {
    td.textContent = dateStr;
  }
  return td;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && (ctx.user.role === "manager" || ctx.user.role === "admin"));
  const state = { chores: [], locations: [], includeDeprecated: false };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Maintenance"));
  head.appendChild(el("p", "view-sub", "Recurring lab chores: cleaning, autoclaving, DI-water fills, calibration, and stocking."));
  root.appendChild(head);

  const container = el("div");
  root.appendChild(container);

  async function loadChores() {
    const qs = state.includeDeprecated ? "?include_deprecated=true" : "";
    state.chores = await ctx.api.get("/api/chores" + qs);
  }

  try {
    await loadChores();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load chores: " + err.message));
    return;
  }

  const focusId = params && (params.focusChore != null ? params.focusChore : params.choreId);
  if (focusId != null) {
    await showDetail(Number(focusId));
    return;
  }
  showList();
  // Global "+ New" quick-create opens the add-chore form (manager+).
  if (params && params.create && canManage) {
    const addBtn = document.getElementById("maint-add-btn");
    if (addBtn) addBtn.click();
  }

  // ---- list view ------------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    // Summary: overdue / due-soon counts.
    const overdueCount = state.chores.filter((c) => c.overdue).length;
    const dueSoonCount = state.chores.filter((c) => !c.overdue && c.days_to_due != null && c.days_to_due <= 3).length;
    const summary = el("div");
    summary.style.display = "flex";
    summary.style.gap = "18px";
    summary.style.marginBottom = "14px";
    const overdueSpan = el("span", overdueCount > 0 ? "badge badge-danger" : null, overdueCount + " overdue");
    const soonSpan = el("span", dueSoonCount > 0 ? "badge badge-warn" : null, dueSoonCount + " due soon");
    summary.append(overdueSpan, soonSpan);
    container.appendChild(summary);

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search chores...";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    // Show-deprecated toggle: retired chores are hidden by default.
    const depLabel = el("label", "muted");
    depLabel.style.display = "flex";
    depLabel.style.alignItems = "center";
    depLabel.style.gap = "6px";
    const depCheck = document.createElement("input");
    depCheck.type = "checkbox";
    depCheck.checked = state.includeDeprecated;
    depCheck.addEventListener("change", async () => {
      state.includeDeprecated = depCheck.checked;
      try { await loadChores(); } catch (_) { /* best-effort */ }
      showList();
    });
    depLabel.append(depCheck, document.createTextNode("Show deprecated"));
    toolbar.appendChild(depLabel);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add chore");
      addBtn.id = "maint-add-btn";
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
    thead.innerHTML = "<tr><th>Name</th><th>Category</th><th>Location</th><th>Interval</th><th>Last done</th><th>Next due</th><th></th></tr>";
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);

    // Client-side search over the already-loaded rows.
    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = 7;
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

    if (!state.chores.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No chores registered yet.");
      td.colSpan = 7;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      const sorted = state.chores.slice().sort((a, b) => {
        if (!a.next_due && !b.next_due) return 0;
        if (!a.next_due) return 1;
        if (!b.next_due) return -1;
        return a.next_due < b.next_due ? -1 : a.next_due > b.next_due ? 1 : 0;
      });
      for (const chore of sorted) {
        const tr = el("tr");
        const nameTd = el("td", null, chore.name || "(unnamed)");
        nameTd.style.cursor = "pointer";
        nameTd.addEventListener("click", () => showDetail(chore.id));
        tr.appendChild(nameTd);
        tr.appendChild(el("td", "muted", chore.category || "--"));
        tr.appendChild(el("td", "muted", chore.location_path || "--"));
        tr.appendChild(el("td", "muted", chore.interval_days ? ("every " + chore.interval_days + " days") : "--"));
        tr.appendChild(el("td", "muted", chore.last_done ? ctx.fmt.date(chore.last_done) : "--"));
        tr.appendChild(dueCell(chore, ctx));

        const actTd = document.createElement("td");
        const doneBtn = el("button", "btn btn-sm", "Mark done");
        doneBtn.addEventListener("click", async () => {
          const note = window.prompt("Note (optional):", "") || "";
          doneBtn.disabled = true;
          try {
            await ctx.api.post("/api/chores/" + chore.id + "/complete", { note: note.trim() || undefined });
            ctx.toast("Chore marked done", "ok");
            await loadChores();
            showList();
          } catch (err) {
            ctx.toast("Mark done failed: " + err.message, "danger");
            doneBtn.disabled = false;
          }
        });
        actTd.appendChild(doneBtn);
        const detailBtn = el("button", "btn btn-ghost btn-sm", "Detail");
        detailBtn.style.marginLeft = "6px";
        detailBtn.addEventListener("click", () => showDetail(chore.id));
        actTd.appendChild(detailBtn);
        tr.appendChild(actTd);

        tr._haystack = [chore.name, chore.category, chore.location_path]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }

    // Managers/admins: inline "Add chore" form.
    async function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add chore"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Chore name");
      const catSel = selectFrom(CATEGORIES);
      const locSel = selectFrom([["", "-- none --"]]);
      const intervalInput = textInput("days", "number");
      const nextDueInput = textInput("", "date");

      gridForm.append(
        field("Name *", nameInput),
        field("Category", catSel),
        field("Location", locSel),
        field("Interval (days)", intervalInput),
        field("Next due", nextDueInput),
      );
      card.appendChild(gridForm);

      const instrArea = document.createElement("textarea");
      instrArea.className = "chip";
      instrArea.rows = 3;
      instrArea.placeholder = "Instructions (optional)";
      instrArea.style.width = "100%";
      instrArea.style.marginTop = "10px";
      card.appendChild(field("Instructions", instrArea));

      const btnRow = el("div");
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      btnRow.style.marginTop = "10px";
      const submit = el("button", "btn btn-primary btn-sm", "Create chore");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        const body = {
          name,
          category: catSel.value || null,
          location_id: locSel.value ? Number(locSel.value) : null,
          interval_days: intervalInput.value.trim() === "" ? null : (Number(intervalInput.value) || 0),
          next_due: nextDueInput.value || null,
          instructions: instrArea.value.trim() || null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/chores", body);
          ctx.toast("Chore created", "ok");
          addFormHost.innerHTML = "";
          try { await loadChores(); } catch (_) { /* best-effort refresh */ }
          showList();
        } catch (err) {
          ctx.toast("Create failed: " + err.message, "danger");
          submit.disabled = false;
        }
      });
      btnRow.append(submit, cancel);
      card.appendChild(btnRow);

      addFormHost.appendChild(card);
      if (!state.locations.length) {
        try {
          const roots = await ctx.api.get("/api/locations");
          state.locations = flattenLocations(roots);
        } catch (_) { /* location select stays with just "none" */ }
      }
      for (const l of state.locations) {
        const opt = el("option", null, l.label);
        opt.value = String(l.id);
        locSel.appendChild(opt);
      }
      nameInput.focus();
    }
  }

  // ---- detail view ------------------------------------------------------------
  async function showDetail(choreId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to maintenance");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/chores/" + choreId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load chore: " + err.message));
      return;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(320px, 1fr))";
    container.appendChild(grid);

    grid.appendChild(buildSummaryCard(data, choreId));
    grid.appendChild(buildLogCard(data, choreId));
  }

  // Summary / fields card, with mark-done, edit + delete for managers.
  function buildSummaryCard(chore, choreId) {
    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", chore.name || "(unnamed)");
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    if (chore.status === "deprecated") titleRow.appendChild(el("span", "badge badge-danger", "deprecated"));
    else if (chore.overdue) titleRow.appendChild(el("span", "badge badge-danger", "overdue"));
    else if (chore.days_to_due != null && chore.days_to_due <= 3) titleRow.appendChild(el("span", "badge badge-warn", "due soon"));

    const doneBtn = el("button", "btn btn-sm", "Mark done");
    doneBtn.addEventListener("click", async () => {
      const note = window.prompt("Note (optional):", "") || "";
      doneBtn.disabled = true;
      try {
        await ctx.api.post("/api/chores/" + choreId + "/complete", { note: note.trim() || undefined });
        ctx.toast("Chore marked done", "ok");
        try { await loadChores(); } catch (_) { /* best-effort */ }
        showDetail(choreId);
      } catch (err) {
        ctx.toast("Mark done failed: " + err.message, "danger");
        doneBtn.disabled = false;
      }
    });
    titleRow.appendChild(doneBtn);

    let editForm = null;
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => { if (editForm) editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      // Deprecate (retire, keep history) / Restore.
      const isDeprecated = chore.status === "deprecated";
      const depBtn = el("button", "btn btn-ghost btn-sm", isDeprecated ? "Restore" : "Deprecate");
      depBtn.addEventListener("click", async () => {
        depBtn.disabled = true;
        try {
          await ctx.api.post("/api/chores/" + choreId + "/" + (isDeprecated ? "restore" : "deprecate"), {});
          ctx.toast(isDeprecated ? "Chore restored" : "Chore deprecated", "ok");
          try { await loadChores(); } catch (_) { /* best-effort */ }
          showDetail(choreId);
        } catch (err) {
          ctx.toast("Action failed: " + err.message, "danger");
          depBtn.disabled = false;
        }
      });
      titleRow.appendChild(depBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete \"" + (chore.name || "this chore") + "\"? Its completion log is removed too.")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/chores/" + choreId);
          ctx.toast("Chore deleted", "ok");
          try { await loadChores(); } catch (_) { /* best-effort */ }
          showList();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.appendChild(delBtn);
    }
    card.appendChild(titleRow);

    // Field list.
    const dl = el("div");
    dl.style.marginTop = "10px";
    const rows = [
      ["Category", chore.category || "--"],
      ["Location", chore.location_path || "--"],
      ["Interval", chore.interval_days ? (chore.interval_days + " days") : "--"],
      ["Last done", chore.last_done ? ctx.fmt.date(chore.last_done) : "--"],
    ];
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
    // Next due, colored red/amber.
    const ndRow = el("div");
    ndRow.style.display = "flex";
    ndRow.style.justifyContent = "space-between";
    ndRow.style.gap = "12px";
    ndRow.style.padding = "3px 0";
    ndRow.appendChild(el("span", "muted", "Next due"));
    if (chore.next_due) {
      if (chore.overdue) ndRow.appendChild(el("span", "badge badge-danger", ctx.fmt.date(chore.next_due)));
      else if (chore.days_to_due != null && chore.days_to_due <= 3) ndRow.appendChild(el("span", "badge badge-warn", ctx.fmt.date(chore.next_due)));
      else ndRow.appendChild(el("span", null, ctx.fmt.date(chore.next_due)));
    } else {
      ndRow.appendChild(el("span", "muted", "--"));
    }
    dl.appendChild(ndRow);
    card.appendChild(dl);

    if (chore.instructions) {
      const noteBox = el("div", "panel");
      noteBox.style.marginTop = "10px";
      noteBox.style.whiteSpace = "pre-wrap";
      noteBox.textContent = chore.instructions;
      card.appendChild(noteBox);
    }

    // Manager edit form -> PATCH.
    if (canManage) {
      editForm = el("div");
      editForm.hidden = true;
      editForm.style.marginTop = "12px";
      editForm.style.borderTop = "1px solid var(--border, #ccc)";
      editForm.style.paddingTop = "10px";

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Name"); nameInput.value = chore.name || "";
      const catSel = selectFrom(CATEGORIES);
      if (chore.category && !CATEGORIES.includes(chore.category)) {
        const opt = el("option", null, chore.category); opt.value = chore.category; catSel.appendChild(opt);
      }
      catSel.value = chore.category || "other";
      const locSel = selectFrom([["", "-- none --"]]);
      if (chore.location_id != null) locSel.value = "";
      const intervalInput = textInput("days", "number");
      if (chore.interval_days != null) intervalInput.value = String(chore.interval_days);
      const nextDueInput = textInput("", "date"); nextDueInput.value = chore.next_due || "";

      gridForm.append(
        field("Name", nameInput),
        field("Category", catSel),
        field("Location", locSel),
        field("Interval (days)", intervalInput),
        field("Next due", nextDueInput),
      );
      editForm.appendChild(gridForm);

      const instrArea = document.createElement("textarea");
      instrArea.className = "chip";
      instrArea.rows = 3;
      instrArea.style.width = "100%";
      instrArea.style.marginTop = "8px";
      instrArea.value = chore.instructions || "";
      editForm.appendChild(field("Instructions", instrArea));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save changes");
      saveBtn.style.marginTop = "10px";
      saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/chores/" + choreId, {
            name,
            category: catSel.value || null,
            location_id: locSel.value ? Number(locSel.value) : null,
            interval_days: intervalInput.value.trim() === "" ? null : (Number(intervalInput.value) || 0),
            next_due: nextDueInput.value || null,
            instructions: instrArea.value.trim() || null,
          });
          ctx.toast("Chore updated", "ok");
          try { await loadChores(); } catch (_) { /* best-effort */ }
          showDetail(choreId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });
      editForm.appendChild(saveBtn);
      card.appendChild(editForm);

      // Populate location select lazily.
      (async () => {
        if (!state.locations.length) {
          try {
            const roots = await ctx.api.get("/api/locations");
            state.locations = flattenLocations(roots);
          } catch (_) { /* location select stays with just "none" */ }
        }
        for (const l of state.locations) {
          const opt = el("option", null, l.label);
          opt.value = String(l.id);
          locSel.appendChild(opt);
        }
        if (chore.location_id != null) locSel.value = String(chore.location_id);
      })();
    }
    return card;
  }

  // Completion log card.
  function buildLogCard(chore, choreId) {
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "Completion log"));

    const log = chore.log || [];
    if (!log.length) {
      card.appendChild(el("div", "muted", "No completions recorded yet."));
      return card;
    }
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Done by</th><th>Done at</th><th>Note</th></tr>";
    t.appendChild(thead);
    const tb = document.createElement("tbody");
    t.appendChild(tb);
    scroll.appendChild(t);
    card.appendChild(scroll);
    // A long completion log renders in pages so it never dominates the screen.
    const footer = el("div");
    footer.style.padding = "8px 0";
    card.appendChild(footer);
    ctx.windowedList(log, (entry) => {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, entry.done_by_username || "--"));
      tr.appendChild(el("td", "muted", entry.done_at ? ctx.fmt.date(entry.done_at) : "--"));
      tr.appendChild(el("td", "muted", entry.note || "--"));
      return tr;
    }, { host: tb, footer, pageSize: 25 });
    return card;
  }
}
