// equipment.js -- equipment registry, reservations/booking, and maintenance log.
// Vanilla DOM, design-system classes only. Self-contained ES module.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "equipment", label: "Equipment", minRole: "member" };

const CATEGORIES = [
  "microscope", "centrifuge", "incubator", "freezer", "analyzer",
  "pipette", "balance", "hood", "other",
];
const STATUSES = [
  ["operational", "Operational"],
  ["maintenance", "Maintenance"],
  ["out_of_service", "Out of service"],
];
const KINDS = ["calibration", "preventive", "repair", "inspection"];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function statusBadge(status) {
  if (status === "operational") return el("span", "badge badge-ok", "operational");
  if (status === "maintenance") return el("span", "badge badge-warn", "maintenance");
  if (status === "out_of_service") return el("span", "badge badge-danger", "out of service");
  return el("span", "badge", status || "unknown");
}
// Flatten the nested location tree into "-- indented" options with full-ish labels.
function flattenLocations(roots) {
  const out = [];
  function walk(nodes, depth) {
    for (const n of nodes || []) {
      out.push({ id: n.id, label: " ".repeat(depth * 2) + (n.name || ("#" + n.id)) + " (" + (n.kind || "?") + ")" });
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

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && (ctx.user.role === "manager" || ctx.user.role === "admin"));
  const state = { equipment: [], locations: [] };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Equipment"));
  head.appendChild(el("p", "view-sub", "Instruments and shared equipment with reservations and service history. Click a row for details, to book time, or to log maintenance."));
  root.appendChild(head);

  const container = el("div");
  root.appendChild(container);

  async function loadEquipment() {
    state.equipment = await ctx.api.get("/api/equipment");
  }

  try {
    await loadEquipment();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load equipment: " + err.message));
    return;
  }

  // Deep link straight to a piece of equipment.
  const focusId = params && (params.focusEquipment != null ? params.focusEquipment : params.equipmentId);
  if (focusId != null) {
    await showDetail(Number(focusId));
    return;
  }
  showList();

  // ---- list view ----------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search equipment...";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add equipment");
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
    thead.innerHTML = "<tr><th>Name</th><th>Category</th><th>Make / model</th><th>Location</th><th>Status</th><th>Next service</th></tr>";
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
    noMatchTd.colSpan = 6;
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

    if (!state.equipment.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No equipment registered yet.");
      td.colSpan = 6;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const eq of state.equipment) {
        const tr = el("tr", "row-link");
        tr.style.cursor = "pointer";
        const nameTd = document.createElement("td");
        nameTd.appendChild(document.createTextNode(eq.name || "(unnamed)"));
        if (eq.open_reservations) {
          nameTd.appendChild(document.createTextNode(" "));
          nameTd.appendChild(el("span", "badge", eq.open_reservations + " booked"));
        }
        tr.appendChild(nameTd);
        tr.appendChild(el("td", "muted", eq.category || "--"));
        tr.appendChild(el("td", "muted", eq.make_model || "--"));
        tr.appendChild(el("td", "muted", eq.location_path || "--"));
        const stTd = document.createElement("td");
        stTd.appendChild(statusBadge(eq.status));
        tr.appendChild(stTd);
        const svcTd = document.createElement("td");
        if (eq.next_service_date) {
          if (eq.service_due) {
            const b = el("span", "badge badge-danger", ctx.fmt.date(eq.next_service_date));
            svcTd.appendChild(b);
          } else {
            svcTd.className = "muted";
            svcTd.textContent = ctx.fmt.date(eq.next_service_date);
          }
        } else {
          svcTd.className = "muted";
          svcTd.textContent = "--";
        }
        tr.appendChild(svcTd);
        tr.addEventListener("click", () => showDetail(eq.id));
        tr._haystack = [eq.name, eq.category, eq.make_model, eq.location_path]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }

    // Managers/admins: inline "Add equipment" form.
    async function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add equipment"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Equipment name");
      const catSel = selectFrom(CATEGORIES);
      const makeInput = textInput("e.g. Zeiss LSM 900");
      const serialInput = textInput("Serial number");
      const locSel = selectFrom([["", "-- none --"]].concat(state.locations.map((l) => [String(l.id), l.label])));
      const statusSel = selectFrom(STATUSES);
      const purchaseInput = textInput("", "date");
      const intervalInput = textInput("days", "number");
      const nextSvcInput = textInput("", "date");
      const cleanupInput = textInput("https://... cleaning / decon SOP");

      gridForm.append(
        field("Name *", nameInput),
        field("Category", catSel),
        field("Make / model", makeInput),
        field("Serial number", serialInput),
        field("Location", locSel),
        field("Status", statusSel),
        field("Purchase date", purchaseInput),
        field("Service interval (days)", intervalInput),
        field("Next service date", nextSvcInput),
        field("Cleanup procedure URL", cleanupInput),
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
      const submit = el("button", "btn btn-primary btn-sm", "Create equipment");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        const body = {
          name,
          category: catSel.value || null,
          make_model: makeInput.value.trim() || null,
          serial_number: serialInput.value.trim() || null,
          location_id: locSel.value ? Number(locSel.value) : null,
          status: statusSel.value,
          purchase_date: purchaseInput.value || null,
          service_interval_days: intervalInput.value.trim() === "" ? null : (Number(intervalInput.value) || 0),
          next_service_date: nextSvcInput.value || null,
          cleanup_url: cleanupInput.value.trim() || null,
          note: noteArea.value.trim() || null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/equipment", body);
          ctx.toast("Equipment created", "ok");
          addFormHost.innerHTML = "";
          try { await loadEquipment(); } catch (_) { /* best-effort refresh */ }
          showList();
        } catch (err) {
          ctx.toast("Create failed: " + err.message, "danger");
          submit.disabled = false;
        }
      });
      btnRow.append(submit, cancel);
      card.appendChild(btnRow);

      addFormHost.appendChild(card);
      // Load locations lazily for the select if not already present.
      if (!state.locations.length) {
        try {
          const roots = await ctx.api.get("/api/locations");
          state.locations = flattenLocations(roots);
          for (const l of state.locations) {
            const opt = el("option", null, l.label);
            opt.value = String(l.id);
            locSel.appendChild(opt);
          }
        } catch (_) { /* location select stays with just "none" */ }
      }
      nameInput.focus();
    }
  }

  // ---- detail view --------------------------------------------------------
  async function showDetail(equipmentId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to equipment");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/equipment/" + equipmentId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load equipment: " + err.message));
      return;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(320px, 1fr))";
    container.appendChild(grid);

    grid.appendChild(buildSummaryCard(data, equipmentId));
    grid.appendChild(buildReservationsCard(data, equipmentId));
    grid.appendChild(buildMaintenanceCard(data, equipmentId));
  }

  // Summary / fields card, with edit + delete + status control for managers.
  function buildSummaryCard(eq, equipmentId) {
    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", eq.name || "(unnamed)");
    title.style.marginBottom = "0";
    titleRow.append(title, statusBadge(eq.status));
    if (eq.service_due) titleRow.appendChild(el("span", "badge badge-danger", "service due"));

    let editForm = null;
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => { if (editForm) editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete \"" + (eq.name || "this equipment") + "\"? Reservations and service records are removed too.")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/equipment/" + equipmentId);
          ctx.toast("Equipment deleted", "ok");
          try { await loadEquipment(); } catch (_) { /* best-effort */ }
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
    const rows = [
      ["Category", eq.category || "--"],
      ["Make / model", eq.make_model || "--"],
      ["Serial number", eq.serial_number || "--"],
      ["Location", eq.location_path || "--"],
      ["Purchased", eq.purchase_date ? ctx.fmt.date(eq.purchase_date) : "--"],
      ["Service schedule", eq.service_interval_days != null && eq.service_interval_days !== "" ? ("Service every " + eq.service_interval_days + " days") : "--"],
      ["Last service", eq.last_service_date ? ctx.fmt.date(eq.last_service_date) : "--"],
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
    // Next service, colored red when due.
    const nsRow = el("div");
    nsRow.style.display = "flex";
    nsRow.style.justifyContent = "space-between";
    nsRow.style.gap = "12px";
    nsRow.style.padding = "3px 0";
    nsRow.appendChild(el("span", "muted", "Next service"));
    if (eq.next_service_date) {
      if (eq.service_due) nsRow.appendChild(el("span", "badge badge-danger", ctx.fmt.date(eq.next_service_date)));
      else nsRow.appendChild(el("span", null, ctx.fmt.date(eq.next_service_date)));
    } else {
      nsRow.appendChild(el("span", "muted", "--"));
    }
    dl.appendChild(nsRow);
    card.appendChild(dl);

    // Cleaning / decontamination procedure link (only when set).
    if (eq.cleanup_url) {
      const cleanRow = el("div");
      cleanRow.style.marginTop = "10px";
      const a = el("a", null, "Cleaning / decontamination procedure");
      a.href = eq.cleanup_url;
      a.target = "_blank";
      a.rel = "noopener";
      cleanRow.appendChild(a);
      card.appendChild(cleanRow);
    }

    if (eq.note) {
      const noteBox = el("div", "panel");
      noteBox.style.marginTop = "10px";
      noteBox.style.whiteSpace = "pre-wrap";
      noteBox.textContent = eq.note;
      card.appendChild(noteBox);
    }

    // Manager edit form: fields + status control -> PATCH.
    if (canManage) {
      editForm = el("div");
      editForm.hidden = true;
      editForm.style.marginTop = "12px";
      editForm.style.borderTop = "1px solid var(--border, #ccc)";
      editForm.style.paddingTop = "10px";

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Name"); nameInput.value = eq.name || "";
      const catSel = selectFrom(CATEGORIES);
      if (eq.category && !CATEGORIES.includes(eq.category)) {
        const opt = el("option", null, eq.category); opt.value = eq.category; catSel.appendChild(opt);
      }
      catSel.value = eq.category || "other";
      const makeInput = textInput("Make / model"); makeInput.value = eq.make_model || "";
      const serialInput = textInput("Serial"); serialInput.value = eq.serial_number || "";
      const statusSel = selectFrom(STATUSES); statusSel.value = eq.status || "operational";
      const purchaseInput = textInput("", "date"); purchaseInput.value = eq.purchase_date || "";
      const intervalInput = textInput("days", "number");
      if (eq.service_interval_days != null) intervalInput.value = String(eq.service_interval_days);
      const nextSvcInput = textInput("", "date"); nextSvcInput.value = eq.next_service_date || "";
      const cleanupInput = textInput("https://... cleaning / decon SOP"); cleanupInput.value = eq.cleanup_url || "";

      gridForm.append(
        field("Name", nameInput),
        field("Category", catSel),
        field("Make / model", makeInput),
        field("Serial number", serialInput),
        field("Status", statusSel),
        field("Purchase date", purchaseInput),
        field("Service interval (days)", intervalInput),
        field("Next service date", nextSvcInput),
        field("Cleanup procedure URL", cleanupInput),
      );
      editForm.appendChild(gridForm);

      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.style.width = "100%";
      noteArea.style.marginTop = "8px";
      noteArea.value = eq.note || "";
      editForm.appendChild(field("Note", noteArea));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save changes");
      saveBtn.style.marginTop = "10px";
      saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/equipment/" + equipmentId, {
            name,
            category: catSel.value || null,
            make_model: makeInput.value.trim() || null,
            serial_number: serialInput.value.trim() || null,
            status: statusSel.value,
            purchase_date: purchaseInput.value || null,
            service_interval_days: intervalInput.value.trim() === "" ? null : (Number(intervalInput.value) || 0),
            next_service_date: nextSvcInput.value || null,
            cleanup_url: cleanupInput.value.trim() || null,
            note: noteArea.value.trim() || null,
          });
          ctx.toast("Equipment updated", "ok");
          try { await loadEquipment(); } catch (_) { /* best-effort */ }
          showDetail(equipmentId);
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

  // Reservations: upcoming bookings + a booking form.
  function buildReservationsCard(eq, equipmentId) {
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "Reservations"));

    const list = el("div");
    const reservations = eq.reservations || [];
    if (!reservations.length) {
      list.appendChild(el("div", "muted", "No upcoming reservations."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>User</th><th>Start</th><th>End</th><th>Purpose</th><th></th></tr>";
      t.appendChild(thead);
      const tb = document.createElement("tbody");
      for (const r of reservations) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, r.username || ("user " + r.user_id)));
        tr.appendChild(el("td", "muted", r.starts_at ? ctx.fmt.date(r.starts_at) : "--"));
        tr.appendChild(el("td", "muted", r.ends_at ? ctx.fmt.date(r.ends_at) : "--"));
        tr.appendChild(el("td", "muted", r.purpose || "--"));
        const actTd = document.createElement("td");
        const mine = ctx.user && r.user_id === ctx.user.id;
        if (canManage || mine) {
          const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
          cancel.addEventListener("click", async () => {
            if (!confirm("Cancel this reservation?")) return;
            cancel.disabled = true;
            try {
              await ctx.api.del("/api/equipment/" + equipmentId + "/reservations/" + r.id);
              ctx.toast("Reservation cancelled", "ok");
              showDetail(equipmentId);
            } catch (err) {
              ctx.toast("Cancel failed: " + err.message, "danger");
              cancel.disabled = false;
            }
          });
          actTd.appendChild(cancel);
        }
        tr.appendChild(actTd);
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      list.appendChild(scroll);
    }
    card.appendChild(list);

    // Book this equipment form.
    const form = el("div");
    form.style.marginTop = "12px";
    form.style.borderTop = "1px solid var(--border, #ccc)";
    form.style.paddingTop = "10px";
    form.appendChild(el("div", "muted", "Book this equipment"));

    const gridForm = el("div", "grid");
    gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
    gridForm.style.gap = "10px";
    gridForm.style.marginTop = "8px";
    const startInput = textInput("", "datetime-local");
    const endInput = textInput("", "datetime-local");
    const purposeInput = textInput("Purpose (optional)");
    gridForm.append(
      field("Start", startInput),
      field("End", endInput),
      field("Purpose", purposeInput),
    );
    form.appendChild(gridForm);

    const bookBtn = el("button", "btn btn-primary btn-sm", "Book");
    bookBtn.style.marginTop = "10px";
    bookBtn.addEventListener("click", async () => {
      if (!startInput.value || !endInput.value) { ctx.toast("Start and end are required", "warn"); return; }
      if (startInput.value >= endInput.value) { ctx.toast("End must be after start", "warn"); return; }
      bookBtn.disabled = true;
      try {
        await ctx.api.post("/api/equipment/" + equipmentId + "/reservations", {
          starts_at: startInput.value,
          ends_at: endInput.value,
          purpose: purposeInput.value.trim() || null,
        });
        ctx.toast("Booked", "ok");
        showDetail(equipmentId);
      } catch (err) {
        // Server 400s on overlap / invalid range with a message; surface it.
        ctx.toast(err.message || "Booking failed", "danger");
        bookBtn.disabled = false;
      }
    });
    form.appendChild(bookBtn);
    card.appendChild(form);
    return card;
  }

  // Maintenance / calibration log + (managers) an "Add service" form.
  function buildMaintenanceCard(eq, equipmentId) {
    const card = el("div", "card");
    card.appendChild(el("div", "card-title", "Maintenance / calibration log"));

    const records = eq.maintenance || [];
    if (!records.length) {
      card.appendChild(el("div", "muted", "No service records yet."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Kind</th><th class='nowrap'>Performed</th><th>By</th><th class='nowrap'>Next due</th><th>Note</th></tr>";
      t.appendChild(thead);
      const tb = document.createElement("tbody");
      const nowrapCell = (cls, txt) => {
        const td = el("td", cls, txt);
        td.style.whiteSpace = "nowrap";
        return td;
      };
      for (const m of records) {
        const tr = document.createElement("tr");
        const kindTd = document.createElement("td");
        kindTd.appendChild(el("span", "badge", m.kind || "service"));
        tr.appendChild(kindTd);
        tr.appendChild(nowrapCell("muted", m.performed_at ? ctx.fmt.date(m.performed_at) : "--"));
        tr.appendChild(el("td", "muted", m.performed_by || "--"));
        tr.appendChild(nowrapCell("muted", m.next_due ? ctx.fmt.date(m.next_due) : "--"));
        tr.appendChild(el("td", "muted", m.note || "--"));
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      card.appendChild(scroll);
    }

    if (!canManage) return card;

    const form = el("div");
    form.style.marginTop = "12px";
    form.style.borderTop = "1px solid var(--border, #ccc)";
    form.style.paddingTop = "10px";
    form.appendChild(el("div", "muted", "Add service record"));

    const gridForm = el("div", "grid");
    gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(160px, 1fr))";
    gridForm.style.gap = "10px";
    gridForm.style.marginTop = "8px";
    const kindSel = selectFrom(KINDS);
    const performedInput = textInput("", "date");
    const byInput = textInput("Performed by");
    const nextDueInput = textInput("", "date");
    gridForm.append(
      field("Kind", kindSel),
      field("Performed at", performedInput),
      field("Performed by", byInput),
      field("Next due", nextDueInput),
    );
    form.appendChild(gridForm);

    const noteArea = document.createElement("textarea");
    noteArea.className = "chip";
    noteArea.rows = 2;
    noteArea.style.width = "100%";
    noteArea.style.marginTop = "8px";
    noteArea.placeholder = "Note (optional)";
    form.appendChild(field("Note", noteArea));

    const addBtn = el("button", "btn btn-primary btn-sm", "Add service");
    addBtn.style.marginTop = "10px";
    addBtn.addEventListener("click", async () => {
      addBtn.disabled = true;
      try {
        await ctx.api.post("/api/equipment/" + equipmentId + "/maintenance", {
          kind: kindSel.value,
          performed_at: performedInput.value || null,
          performed_by: byInput.value.trim() || null,
          next_due: nextDueInput.value || null,
          note: noteArea.value.trim() || null,
        });
        ctx.toast("Service recorded", "ok");
        try { await loadEquipment(); } catch (_) { /* best-effort */ }
        showDetail(equipmentId);
      } catch (err) {
        ctx.toast("Add service failed: " + err.message, "danger");
        addBtn.disabled = false;
      }
    });
    form.appendChild(addBtn);
    card.appendChild(form);
    return card;
  }
}
