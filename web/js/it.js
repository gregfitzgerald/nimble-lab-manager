// it.js -- Computers / IT module: hardware assets and software licenses.
// Vanilla DOM, design-system classes only. Self-contained ES module.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "it", label: "IT", minRole: "member" };

const KINDS = [
  ["desktop", "Desktop"],
  ["laptop", "Laptop"],
  ["server", "Server"],
  ["printer", "Printer"],
  ["network", "Network"],
  ["peripheral", "Peripheral"],
  ["other", "Other"],
];
const STATUSES = [
  ["in_service", "In service"],
  ["repair", "Repair"],
  ["retired", "Retired"],
];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function statusBadge(status) {
  if (status === "in_service") return el("span", "badge badge-ok", "in service");
  if (status === "repair") return el("span", "badge badge-warn", "repair");
  if (status === "retired") return el("span", "badge badge-danger", "retired");
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
function kindLabel(k) {
  const hit = KINDS.find((p) => p[0] === k);
  return hit ? hit[1] : (k || "--");
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && (ctx.user.role === "manager" || ctx.user.role === "admin"));
  const state = { assets: [], licenses: [], assetsLoaded: false, licensesLoaded: false };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Computers / IT"));
  head.appendChild(el("p", "view-sub", "Hardware assets (computers, servers, printers, network gear) and software licenses -- track serials, warranties, seats, costs, and renewals in one place."));
  root.appendChild(head);

  // Section switch.
  const tabs = el("div");
  tabs.style.display = "flex";
  tabs.style.gap = "8px";
  tabs.style.marginBottom = "16px";
  const hwBtn = el("button", "btn btn-sm", "Hardware");
  const swBtn = el("button", "btn btn-sm", "Software");
  tabs.append(hwBtn, swBtn);
  root.appendChild(tabs);

  const container = el("div");
  root.appendChild(container);

  let active = "hardware";
  function setActive(which) {
    active = which;
    hwBtn.className = which === "hardware" ? "btn btn-primary btn-sm" : "btn btn-sm";
    swBtn.className = which === "software" ? "btn btn-primary btn-sm" : "btn btn-sm";
    if (which === "hardware") showHardware();
    else showSoftware();
  }
  hwBtn.addEventListener("click", () => setActive("hardware"));
  swBtn.addEventListener("click", () => setActive("software"));

  async function loadAssets() {
    state.assets = await ctx.api.get("/api/it-assets");
    state.assetsLoaded = true;
  }
  async function loadLicenses() {
    state.licenses = await ctx.api.get("/api/software-licenses");
    state.licensesLoaded = true;
  }

  setActive("hardware");

  // ====================================================================
  // HARDWARE
  // ====================================================================
  async function showHardware() {
    container.innerHTML = "";
    if (!state.assetsLoaded) {
      container.appendChild(el("div", "muted", "Loading assets..."));
      try {
        await loadAssets();
      } catch (err) {
        container.innerHTML = "";
        container.appendChild(el("div", "empty-state", "Could not load IT assets: " + err.message));
        return;
      }
      if (active !== "hardware") return;
      container.innerHTML = "";
    }

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search assets...";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add asset");
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
    thead.innerHTML = "<tr><th>Name</th><th>Kind</th><th>Make / model</th><th>Serial</th><th>Location</th><th>Assigned to</th><th>Warranty</th><th>Status</th></tr>";
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);

    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = 8;
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

    if (!state.assets.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No hardware assets registered yet.");
      td.colSpan = 8;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const a of state.assets) {
        const tr = el("tr", "row-link");
        tr.style.cursor = "pointer";
        tr.appendChild(el("td", null, a.name || "(unnamed)"));
        tr.appendChild(el("td", "muted", kindLabel(a.kind)));
        tr.appendChild(el("td", "muted", a.make_model || "--"));
        tr.appendChild(el("td", "muted", a.serial_number || "--"));
        tr.appendChild(el("td", "muted", a.location_path || "--"));
        tr.appendChild(el("td", "muted", a.assigned_username || "--"));
        const wTd = document.createElement("td");
        if (a.warranty_end) {
          const past = a.days_to_warranty != null && a.days_to_warranty < 0;
          if (past) wTd.appendChild(el("span", "badge badge-danger", ctx.fmt.date(a.warranty_end)));
          else if (a.warranty_soon) wTd.appendChild(el("span", "badge badge-warn", ctx.fmt.date(a.warranty_end)));
          else { wTd.className = "muted"; wTd.textContent = ctx.fmt.date(a.warranty_end); }
        } else { wTd.className = "muted"; wTd.textContent = "--"; }
        tr.appendChild(wTd);
        const stTd = document.createElement("td");
        stTd.appendChild(statusBadge(a.status));
        tr.appendChild(stTd);
        tr.addEventListener("click", () => showAssetDetail(a.id));
        tr._haystack = [a.name, kindLabel(a.kind), a.make_model, a.serial_number, a.location_path, a.assigned_username]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }

    async function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add asset"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("Asset name");
      const kindSel = selectFrom(KINDS);
      const makeInput = textInput("e.g. Dell OptiPlex 7090");
      const serialInput = textInput("Serial number");
      const purchaseInput = textInput("", "date");
      const warrantyInput = textInput("", "date");
      const statusSel = selectFrom(STATUSES);

      gridForm.append(
        field("Name *", nameInput),
        field("Kind", kindSel),
        field("Make / model", makeInput),
        field("Serial number", serialInput),
        field("Purchase date", purchaseInput),
        field("Warranty end", warrantyInput),
        field("Status", statusSel),
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
      const submit = el("button", "btn btn-primary btn-sm", "Create asset");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        const body = {
          name,
          kind: kindSel.value,
          make_model: makeInput.value.trim() || null,
          serial_number: serialInput.value.trim() || null,
          purchase_date: purchaseInput.value || null,
          warranty_end: warrantyInput.value || null,
          status: statusSel.value,
          note: noteArea.value.trim() || null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/it-assets", body);
          ctx.toast("Asset created", "ok");
          addFormHost.innerHTML = "";
          try { await loadAssets(); } catch (_) { /* best-effort */ }
          showHardware();
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

  // ---- asset detail -------------------------------------------------------
  async function showAssetDetail(assetId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to hardware");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showHardware);
    container.appendChild(back);

    let a;
    try {
      a = await ctx.api.get("/api/it-assets/" + assetId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load asset: " + err.message));
      return;
    }

    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", a.name || "(unnamed)");
    title.style.marginBottom = "0";
    titleRow.append(title, statusBadge(a.status));

    let editForm = null;
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => { if (editForm) editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete \"" + (a.name || "this asset") + "\"?")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/it-assets/" + assetId);
          ctx.toast("Asset deleted", "ok");
          try { await loadAssets(); } catch (_) { /* best-effort */ }
          showHardware();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.appendChild(delBtn);
    }
    card.appendChild(titleRow);

    const rows = [
      ["Kind", kindLabel(a.kind)],
      ["Make / model", a.make_model || "--"],
      ["Serial number", a.serial_number || "--"],
      ["Location", a.location_path || "--"],
      ["Assigned to", a.assigned_username || "--"],
      ["Purchased", a.purchase_date ? ctx.fmt.date(a.purchase_date) : "--"],
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
    // Warranty row, colored on problem.
    const wRow = el("div");
    wRow.style.display = "flex";
    wRow.style.justifyContent = "space-between";
    wRow.style.gap = "12px";
    wRow.style.padding = "3px 0";
    wRow.appendChild(el("span", "muted", "Warranty end"));
    if (a.warranty_end) {
      const past = a.days_to_warranty != null && a.days_to_warranty < 0;
      if (past) wRow.appendChild(el("span", "badge badge-danger", ctx.fmt.date(a.warranty_end)));
      else if (a.warranty_soon) wRow.appendChild(el("span", "badge badge-warn", ctx.fmt.date(a.warranty_end)));
      else wRow.appendChild(el("span", null, ctx.fmt.date(a.warranty_end)));
    } else {
      wRow.appendChild(el("span", "muted", "--"));
    }
    dl.appendChild(wRow);
    card.appendChild(dl);

    if (a.note) {
      const noteBox = el("div", "panel");
      noteBox.style.marginTop = "10px";
      noteBox.style.whiteSpace = "pre-wrap";
      noteBox.textContent = a.note;
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

      const nameInput = textInput("Name"); nameInput.value = a.name || "";
      const kindSel = selectFrom(KINDS);
      if (a.kind && !KINDS.some((p) => p[0] === a.kind)) {
        const opt = el("option", null, a.kind); opt.value = a.kind; kindSel.appendChild(opt);
      }
      kindSel.value = a.kind || "other";
      const makeInput = textInput("Make / model"); makeInput.value = a.make_model || "";
      const serialInput = textInput("Serial"); serialInput.value = a.serial_number || "";
      const purchaseInput = textInput("", "date"); purchaseInput.value = a.purchase_date || "";
      const warrantyInput = textInput("", "date"); warrantyInput.value = a.warranty_end || "";
      const statusSel = selectFrom(STATUSES);
      if (a.status && !STATUSES.some((p) => p[0] === a.status)) {
        const opt = el("option", null, a.status); opt.value = a.status; statusSel.appendChild(opt);
      }
      statusSel.value = a.status || "in_use";

      gridForm.append(
        field("Name", nameInput),
        field("Kind", kindSel),
        field("Make / model", makeInput),
        field("Serial number", serialInput),
        field("Purchase date", purchaseInput),
        field("Warranty end", warrantyInput),
        field("Status", statusSel),
      );
      editForm.appendChild(gridForm);

      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.style.width = "100%";
      noteArea.style.marginTop = "8px";
      noteArea.value = a.note || "";
      editForm.appendChild(field("Note", noteArea));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save changes");
      saveBtn.style.marginTop = "10px";
      saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/it-assets/" + assetId, {
            name,
            kind: kindSel.value,
            make_model: makeInput.value.trim() || null,
            serial_number: serialInput.value.trim() || null,
            purchase_date: purchaseInput.value || null,
            warranty_end: warrantyInput.value || null,
            status: statusSel.value,
            note: noteArea.value.trim() || null,
          });
          ctx.toast("Asset updated", "ok");
          try { await loadAssets(); } catch (_) { /* best-effort */ }
          showAssetDetail(assetId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });
      editForm.appendChild(saveBtn);
      card.appendChild(editForm);
    }

    container.appendChild(card);
  }

  // ====================================================================
  // SOFTWARE
  // ====================================================================
  async function showSoftware() {
    container.innerHTML = "";
    if (!state.licensesLoaded) {
      container.appendChild(el("div", "muted", "Loading licenses..."));
      try {
        await loadLicenses();
      } catch (err) {
        container.innerHTML = "";
        container.appendChild(el("div", "empty-state", "Could not load software licenses: " + err.message));
        return;
      }
      if (active !== "software") return;
      container.innerHTML = "";
    }

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search licenses...";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add license");
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
    thead.innerHTML = "<tr><th>Name</th><th>Vendor</th><th>Product code</th><th>Seats</th><th>Assigned to</th><th>Annual cost</th><th>Server cost</th><th>Expiry</th></tr>";
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);

    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = 8;
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

    if (!state.licenses.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No software licenses registered yet.");
      td.colSpan = 8;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const l of state.licenses) {
        const tr = el("tr", "row-link");
        tr.style.cursor = "pointer";
        tr.appendChild(el("td", null, l.name || "(unnamed)"));
        tr.appendChild(el("td", "muted", l.vendor || "--"));
        tr.appendChild(el("td", "muted", l.product_code || "--"));
        tr.appendChild(el("td", "muted", l.seats != null ? String(l.seats) : "--"));
        tr.appendChild(el("td", "muted", l.assigned_asset_name || "--"));
        tr.appendChild(el("td", "right mono", l.annual_cost != null ? ctx.fmt.money(l.annual_cost) : "--"));
        tr.appendChild(el("td", "right mono", l.server_cost != null ? ctx.fmt.money(l.server_cost) : "--"));
        const eTd = document.createElement("td");
        if (l.expiry_date) {
          if (l.expiry_flag === "expired") eTd.appendChild(el("span", "badge badge-danger", ctx.fmt.date(l.expiry_date)));
          else if (l.expiry_flag === "expiring") eTd.appendChild(el("span", "badge badge-warn", ctx.fmt.date(l.expiry_date)));
          else { eTd.className = "muted"; eTd.textContent = ctx.fmt.date(l.expiry_date); }
        } else { eTd.className = "muted"; eTd.textContent = "--"; }
        tr.appendChild(eTd);
        tr.addEventListener("click", () => showLicenseDetail(l.id));
        tr._haystack = [l.name, l.vendor, l.product_code, l.assigned_asset_name]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }

    async function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add license"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = textInput("License / product name");
      const vendorInput = textInput("Vendor");
      const codeInput = textInput("Product / license key");
      const seatsInput = textInput("Seats", "number");
      const expiryInput = textInput("", "date");
      const annualInput = textInput("0.00", "number");
      const serverInput = textInput("0.00", "number");
      const assetSel = selectFrom([["", "-- unassigned --"]].concat(
        (state.assetsLoaded ? state.assets : []).map((a) => [String(a.id), a.name || ("#" + a.id)]),
      ));

      gridForm.append(
        field("Name *", nameInput),
        field("Vendor", vendorInput),
        field("Product code", codeInput),
        field("Seats", seatsInput),
        field("Expiry date", expiryInput),
        field("Annual cost", annualInput),
        field("Server cost", serverInput),
        field("Assigned asset", assetSel),
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
      const submit = el("button", "btn btn-primary btn-sm", "Create license");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        const body = {
          name,
          vendor: vendorInput.value.trim() || null,
          product_code: codeInput.value.trim() || null,
          seats: seatsInput.value.trim() === "" ? null : (Number(seatsInput.value) || 0),
          expiry_date: expiryInput.value || null,
          annual_cost: annualInput.value.trim() === "" ? null : (Number(annualInput.value) || 0),
          server_cost: serverInput.value.trim() === "" ? null : (Number(serverInput.value) || 0),
          assigned_asset_id: assetSel.value ? Number(assetSel.value) : null,
          note: noteArea.value.trim() || null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/software-licenses", body);
          ctx.toast("License created", "ok");
          addFormHost.innerHTML = "";
          try { await loadLicenses(); } catch (_) { /* best-effort */ }
          showSoftware();
        } catch (err) {
          ctx.toast("Create failed: " + err.message, "danger");
          submit.disabled = false;
        }
      });
      btnRow.append(submit, cancel);
      card.appendChild(btnRow);
      addFormHost.appendChild(card);

      // Ensure assets are available for the assignment select.
      if (!state.assetsLoaded) {
        try {
          await loadAssets();
          for (const a of state.assets) {
            const opt = el("option", null, a.name || ("#" + a.id));
            opt.value = String(a.id);
            assetSel.appendChild(opt);
          }
        } catch (_) { /* select stays with just "unassigned" */ }
      }
      nameInput.focus();
    }
  }

  // ---- license detail -----------------------------------------------------
  async function showLicenseDetail(licenseId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to software");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showSoftware);
    container.appendChild(back);

    let l;
    try {
      l = await ctx.api.get("/api/software-licenses/" + licenseId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load license: " + err.message));
      return;
    }

    const card = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", l.name || "(unnamed)");
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    if (l.expiry_flag === "expired") titleRow.appendChild(el("span", "badge badge-danger", "expired"));
    else if (l.expiry_flag === "expiring") titleRow.appendChild(el("span", "badge badge-warn", "expiring"));

    let editForm = null;
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => { if (editForm) editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete \"" + (l.name || "this license") + "\"?")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/software-licenses/" + licenseId);
          ctx.toast("License deleted", "ok");
          try { await loadLicenses(); } catch (_) { /* best-effort */ }
          showSoftware();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.appendChild(delBtn);
    }
    card.appendChild(titleRow);

    const rows = [
      ["Vendor", l.vendor || "--"],
      ["Product code", l.product_code || "--"],
      ["Seats", l.seats != null ? String(l.seats) : "--"],
      ["Assigned to", l.assigned_asset_name || "--"],
      ["Annual cost", l.annual_cost != null ? ctx.fmt.money(l.annual_cost) : "--"],
      ["Server cost", l.server_cost != null ? ctx.fmt.money(l.server_cost) : "--"],
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
    const eRow = el("div");
    eRow.style.display = "flex";
    eRow.style.justifyContent = "space-between";
    eRow.style.gap = "12px";
    eRow.style.padding = "3px 0";
    eRow.appendChild(el("span", "muted", "Expiry"));
    if (l.expiry_date) {
      if (l.expiry_flag === "expired") eRow.appendChild(el("span", "badge badge-danger", ctx.fmt.date(l.expiry_date)));
      else if (l.expiry_flag === "expiring") eRow.appendChild(el("span", "badge badge-warn", ctx.fmt.date(l.expiry_date)));
      else eRow.appendChild(el("span", null, ctx.fmt.date(l.expiry_date)));
    } else {
      eRow.appendChild(el("span", "muted", "--"));
    }
    dl.appendChild(eRow);
    card.appendChild(dl);

    if (l.note) {
      const noteBox = el("div", "panel");
      noteBox.style.marginTop = "10px";
      noteBox.style.whiteSpace = "pre-wrap";
      noteBox.textContent = l.note;
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

      const nameInput = textInput("Name"); nameInput.value = l.name || "";
      const vendorInput = textInput("Vendor"); vendorInput.value = l.vendor || "";
      const codeInput = textInput("Product code"); codeInput.value = l.product_code || "";
      const seatsInput = textInput("Seats", "number");
      if (l.seats != null) seatsInput.value = String(l.seats);
      const expiryInput = textInput("", "date"); expiryInput.value = l.expiry_date || "";
      const annualInput = textInput("0.00", "number");
      if (l.annual_cost != null) annualInput.value = String(l.annual_cost);
      const serverInput = textInput("0.00", "number");
      if (l.server_cost != null) serverInput.value = String(l.server_cost);
      const assetSel = selectFrom([["", "-- unassigned --"]].concat(
        (state.assetsLoaded ? state.assets : []).map((a) => [String(a.id), a.name || ("#" + a.id)]),
      ));
      // If the current asset isn't in the loaded list, add a stub so it shows.
      if (l.assigned_asset_id != null && !(state.assetsLoaded && state.assets.some((a) => a.id === l.assigned_asset_id))) {
        const opt = el("option", null, l.assigned_asset_name || ("#" + l.assigned_asset_id));
        opt.value = String(l.assigned_asset_id);
        assetSel.appendChild(opt);
      }
      assetSel.value = l.assigned_asset_id != null ? String(l.assigned_asset_id) : "";

      gridForm.append(
        field("Name", nameInput),
        field("Vendor", vendorInput),
        field("Product code", codeInput),
        field("Seats", seatsInput),
        field("Expiry date", expiryInput),
        field("Annual cost", annualInput),
        field("Server cost", serverInput),
        field("Assigned asset", assetSel),
      );
      editForm.appendChild(gridForm);

      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.style.width = "100%";
      noteArea.style.marginTop = "8px";
      noteArea.value = l.note || "";
      editForm.appendChild(field("Note", noteArea));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save changes");
      saveBtn.style.marginTop = "10px";
      saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Name is required", "warn"); nameInput.focus(); return; }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/software-licenses/" + licenseId, {
            name,
            vendor: vendorInput.value.trim() || null,
            product_code: codeInput.value.trim() || null,
            seats: seatsInput.value.trim() === "" ? null : (Number(seatsInput.value) || 0),
            expiry_date: expiryInput.value || null,
            annual_cost: annualInput.value.trim() === "" ? null : (Number(annualInput.value) || 0),
            server_cost: serverInput.value.trim() === "" ? null : (Number(serverInput.value) || 0),
            assigned_asset_id: assetSel.value ? Number(assetSel.value) : null,
            note: noteArea.value.trim() || null,
          });
          ctx.toast("License updated", "ok");
          try { await loadLicenses(); } catch (_) { /* best-effort */ }
          showLicenseDetail(licenseId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });
      editForm.appendChild(saveBtn);

      // Load assets for the select if not already available.
      if (!state.assetsLoaded) {
        loadAssets().then(() => {
          for (const a of state.assets) {
            if ([...assetSel.options].some((o) => o.value === String(a.id))) continue;
            const opt = el("option", null, a.name || ("#" + a.id));
            opt.value = String(a.id);
            assetSel.appendChild(opt);
          }
        }).catch(() => { /* select stays as-is */ });
      }

      card.appendChild(editForm);
    }

    container.appendChild(card);
  }
}
