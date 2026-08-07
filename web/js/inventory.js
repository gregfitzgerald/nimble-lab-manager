// inventory.js -- inventory list, expiry/low-stock triage, and item detail
// with real consume / restock actions. Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label}; export function render(root, ctx, params).

export const view = { id: "inventory", label: "Inventory", minRole: "viewer" };

// Categories the backend accepts (PATCH /api/items/{id} whitelist).
const CATEGORIES = [
  "reagent", "supply", "chemical", "antibody", "enzyme",
  "media", "animal", "equipment", "office", "other",
];

// Admins can define a canonical category list in the UI config (Settings ->
// Item categories). When present it drives the create/edit dropdowns; otherwise
// the built-in defaults are used.
function catList(ctx) {
  const cfg = (ctx && ctx.getConfig && ctx.getConfig()) || {};
  const cats = cfg.item_categories;
  return (Array.isArray(cats) && cats.length) ? cats : CATEGORIES;
}

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function expiryBadge(flag) {
  if (flag === "expired") return el("span", "badge badge-danger", "expired");
  if (flag === "expiring") return el("span", "badge badge-warn", "expiring");
  if (flag === "ok") return el("span", "badge badge-ok", "ok");
  return el("span", "badge", "no expiry");
}
function categoryBadge(category) {
  return el("span", "badge", category || "uncategorized");
}
// Amber "controlled" badge (optionally with DEA schedule), shown for controlled items.
function controlledBadge(item) {
  const label = item.controlled_schedule
    ? "controlled " + item.controlled_schedule
    : "controlled";
  return el("span", "badge badge-warn", label);
}
// Amber "hazard" badge for items with a non-empty hazard_class (title = the classes).
function hazardBadge(item) {
  const b = el("span", "badge badge-warn", "hazard");
  if (item.hazard_class) b.title = item.hazard_class;
  return b;
}
// "min X / max Y" reorder label when reorder_max is set, else just the threshold.
function reorderText(item) {
  if (item.reorder_max != null && item.reorder_max !== "") {
    return `min ${item.reorder_threshold} / max ${item.reorder_max}`;
  }
  return String(item.reorder_threshold);
}
// Location cell: full path in a title tooltip, truncated display for long paths.
// Very long paths collapse to their last two segments prefixed with ".../".
function locationCell(loc) {
  const td = document.createElement("td");
  td.className = "muted";
  if (!loc) { td.textContent = "--"; return td; }
  td.title = loc;
  const segs = loc.split("/").map((s) => s.trim()).filter(Boolean);
  let display = loc;
  if (loc.length > 30 && segs.length > 2) {
    display = ".../" + segs.slice(-2).join(" / ");
  }
  td.textContent = display;
  td.style.maxWidth = "200px";
  td.style.overflow = "hidden";
  td.style.textOverflow = "ellipsis";
  td.style.whiteSpace = "nowrap";
  return td;
}
// External document link (SDS / CoA). New tab, no opener handle.
function docLink(label, url) {
  const a = el("a", null, label);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const state = {
    items: [], categories: [], category: "", filter: "all", search: "",
    sortKey: null, sortDir: 1, includeDeprecated: false,
  };
  const canEdit = !!(ctx.user && (ctx.user.role === "manager" || ctx.user.role === "admin"));

  // Re-bound to openAddForm on every showList() render so the global "+ New"
  // shortcut always opens the current (attached) add-item form host.
  let openAddFormRef = null;

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Inventory"));
  head.appendChild(el("p", "view-sub", "Reagents and consumables with lot-level expiry and reorder health. Click an item to consume, restock, or see where it lives."));
  root.appendChild(head);

  const container = el("div");
  root.appendChild(container);

  async function loadItems() {
    const parts = [];
    if (state.category) parts.push("category=" + encodeURIComponent(state.category));
    if (state.includeDeprecated) parts.push("include_deprecated=true");
    const qs = parts.length ? "?" + parts.join("&") : "";
    state.items = await ctx.api.get("/api/items" + qs);
  }

  try {
    const [, cats] = await Promise.all([
      loadItems(),
      ctx.api.get("/api/categories").catch(() => null),
    ]);
    state.categories = (cats && cats.categories) || [];
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load inventory: " + err.message));
    return;
  }

  // Deep link straight to an item detail (from map / analytics / game / scanned QR).
  const focusId = params && (params.focusItem != null ? params.focusItem : params.itemId);
  if (focusId != null) {
    await showDetail(Number(focusId));
    return;
  }
  showList();
  // Global "+ New" quick-create opens the add form directly (manager+).
  if (params && params.create && canEdit && openAddFormRef) openAddFormRef();

  // ---- list view ----------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    // Keep the add-form opener ref current (used by the global "+ New" shortcut).
    // The topbar primary-action slot is intentionally not used here anymore -- the
    // global "+ New" menu covers item creation, so we avoid two adjacent buttons.
    openAddFormRef = openAddForm;

    const toolbar = el("div", "card");
    toolbar.style.display = "flex";
    toolbar.style.flexWrap = "wrap";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";

    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search items...";
    searchInput.style.minWidth = "200px";
    searchInput.value = state.search;
    searchInput.addEventListener("input", () => { state.search = searchInput.value; drawTable(); });
    toolbar.appendChild(searchInput);

    // Category filter -- server-side (?category=...), populated with counts.
    const catSelect = document.createElement("select");
    catSelect.className = "chip";
    const totalCount = state.categories.reduce((n, c) => n + (c.count || 0), 0);
    const allOpt = el("option", null, totalCount ? `All categories (${totalCount})` : "All categories");
    allOpt.value = "";
    catSelect.appendChild(allOpt);
    for (const c of state.categories) {
      const opt = el("option", null, `${c.name} (${c.count})`);
      opt.value = c.name;
      catSelect.appendChild(opt);
    }
    catSelect.value = state.category;
    catSelect.addEventListener("change", async () => {
      state.category = catSelect.value;
      catSelect.disabled = true;
      try {
        await loadItems();
      } catch (err) {
        ctx.toast("Could not load items: " + err.message, "danger");
      }
      catSelect.disabled = false;
      showList();
    });
    toolbar.appendChild(catSelect);

    // "Show deprecated" toggle -- reloads items including soft-deleted rows.
    const depLabel = el("label", "muted");
    depLabel.style.display = "flex";
    depLabel.style.gap = "5px";
    depLabel.style.alignItems = "center";
    depLabel.style.cursor = "pointer";
    const depCheck = document.createElement("input");
    depCheck.type = "checkbox";
    depCheck.checked = state.includeDeprecated;
    depCheck.addEventListener("change", async () => {
      state.includeDeprecated = depCheck.checked;
      depCheck.disabled = true;
      try {
        await loadItems();
      } catch (err) {
        ctx.toast("Could not load items: " + err.message, "danger");
      }
      depCheck.disabled = false;
      showList();
    });
    depLabel.append(depCheck, document.createTextNode("Show deprecated"));
    toolbar.appendChild(depLabel);

    const spacer = el("div", "spacer");
    toolbar.appendChild(spacer);

    // Managers/admins can create a new item.
    if (canEdit) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ Add item");
      addBtn.addEventListener("click", () => openAddForm());
      toolbar.appendChild(addBtn);
    }

    const filters = [
      ["all", "All"],
      ["low", "Low stock"],
      ["expiring", "Expiring"],
      ["expired", "Expired"],
    ];
    for (const [key, label] of filters) {
      const b = el("button", "btn btn-sm " + (state.filter === key ? "btn-primary" : "btn-ghost"), label);
      b.addEventListener("click", () => { state.filter = key; showList(); });
      toolbar.appendChild(b);
    }
    container.appendChild(toolbar);

    // Host for the inline "Add item" form (managers/admins); hidden until opened.
    const addFormHost = el("div");
    container.appendChild(addFormHost);

    // Sortable column headers. key maps to a value accessor; clicking toggles dir.
    // Declared before the table is built below (buildTablePlaceholder reads it).
    const COLUMNS = [
      { key: "item_name", label: "Item", get: (it) => (it.item_name || "").toLowerCase() },
      { key: "catalog_number", label: "Cat #", get: (it) => (it.catalog_number || "").toLowerCase() },
      { key: "category", label: "Category", get: (it) => (it.category || "").toLowerCase() },
      { key: "vendor", label: "Vendor", get: (it) => (it.vendor || "").toLowerCase() },
      { key: "size", label: "Size", sortable: false },
      { key: "quantity_on_hand", label: "Amount", get: (it) => Number(it.quantity_on_hand) },
      { key: "location", label: "Location", get: (it) => (it.location || "").toLowerCase() },
      { key: "reorder_threshold", label: "Reorder", right: true, sortable: false },
      { key: "nearest_expiry", label: "Nearest expiry", get: (it) => it.nearest_expiry || "" },
      { key: "sds", label: "SDS", sortable: false },
      { key: "coa", label: "CoA", sortable: false },
      { key: "status", label: "Status", get: (it) => statusRank(it) },
    ];
    // Rank items for the Status column: worst problems sort first when descending.
    function statusRank(it) {
      let r = 0;
      if (it.status === "deprecated") r += 100;
      if (it.expiry_flag === "expired") r += 8;
      else if (it.expiry_flag === "expiring") r += 4;
      if (it.is_low_stock) r += 2;
      return r;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    scroll.appendChild(buildTablePlaceholder());
    tableWrap.appendChild(scroll);
    const tableFooter = el("div");
    tableFooter.style.padding = "8px 12px";
    tableWrap.appendChild(tableFooter);
    container.appendChild(tableWrap);

    function buildTablePlaceholder() {
      const t = document.createElement("table");
      t.className = "table";
      const thead = document.createElement("thead");
      const htr = document.createElement("tr");
      for (const col of COLUMNS) {
        const th = document.createElement("th");
        if (col.right) th.className = "right";
        th.appendChild(document.createTextNode(col.label));
        if (col.sortable !== false) {
          th.style.cursor = "pointer";
          th.style.userSelect = "none";
          if (state.sortKey === col.key) {
            th.appendChild(document.createTextNode(state.sortDir === 1 ? " ▲" : " ▼"));
          }
          th.addEventListener("click", () => {
            if (state.sortKey === col.key) state.sortDir = -state.sortDir;
            else { state.sortKey = col.key; state.sortDir = 1; }
            rebuildHead();
            drawTable();
          });
        }
        htr.appendChild(th);
      }
      thead.appendChild(htr);
      t.appendChild(thead);
      t.appendChild(document.createElement("tbody"));
      return t;
    }
    function rebuildHead() {
      const table = scroll.querySelector("table");
      const fresh = buildTablePlaceholder();
      table.replaceChild(fresh.querySelector("thead"), table.querySelector("thead"));
    }

    function drawTable() {
      const table = scroll.querySelector("table");
      const tbody = table.querySelector("tbody");
      tbody.innerHTML = "";
      tableFooter.innerHTML = "";
      const rows = filtered();
      if (!rows.length) {
        const tr = document.createElement("tr");
        const td = el("td", "muted", "No items match this filter.");
        td.colSpan = COLUMNS.length;
        td.style.textAlign = "center";
        td.style.padding = "28px";
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      // Render in pages so a few thousand items don't freeze the table.
      ctx.windowedList(rows, buildRow, { host: tbody, footer: tableFooter, pageSize: 100 });
    }

    function buildRow(it) {
      {
        const tr = el("tr", "row-link");
        if (it.status === "deprecated") tr.style.opacity = "0.55";
        const nameTd = document.createElement("td");
        nameTd.appendChild(document.createTextNode(it.item_name));
        if (it.is_controlled) { nameTd.appendChild(document.createTextNode(" ")); nameTd.appendChild(controlledBadge(it)); }
        if (it.hazard_class) { nameTd.appendChild(document.createTextNode(" ")); nameTd.appendChild(hazardBadge(it)); }
        tr.appendChild(nameTd);
        tr.appendChild(el("td", "mono muted", it.catalog_number || "--"));
        const catTd = document.createElement("td");
        catTd.appendChild(categoryBadge(it.category));
        tr.appendChild(catTd);
        tr.appendChild(el("td", "muted", it.vendor || "--"));
        tr.appendChild(el("td", "muted", it.size || "--"));
        tr.appendChild(el("td", "mono", it.amount != null && it.amount !== "" ? String(it.amount) : String(it.quantity_on_hand)));
        tr.appendChild(locationCell(it.location));
        tr.appendChild(el("td", "right muted", reorderText(it)));
        tr.appendChild(el("td", "muted", it.nearest_expiry ? ctx.fmt.date(it.nearest_expiry) : "--"));
        const sdsTd = document.createElement("td");
        if (it.sds_url) sdsTd.appendChild(docLink("SDS", it.sds_url));
        else sdsTd.appendChild(el("span", "muted", "--"));
        tr.appendChild(sdsTd);
        const coaTd = document.createElement("td");
        if (it.coa_url) coaTd.appendChild(docLink("CoA", it.coa_url));
        else coaTd.appendChild(el("span", "muted", "--"));
        tr.appendChild(coaTd);
        const status = document.createElement("td");
        status.style.display = "flex";
        status.style.gap = "6px";
        status.style.flexWrap = "wrap";
        status.style.alignItems = "center";
        if (it.status === "deprecated") status.appendChild(el("span", "badge badge-danger", "deprecated"));
        if (it.is_low_stock) status.appendChild(el("span", "badge badge-warn", it.quantity_on_hand <= 0 ? "out" : "low"));
        status.appendChild(expiryBadge(it.expiry_flag));
        tr.appendChild(status);
        tr.addEventListener("click", () => openProductModal(it.item_id, it.item_name));
        tr.addEventListener("contextmenu", (e) => { e.preventDefault(); openRowMenu(e, it); });
        return tr;
      }
    }

    function filtered() {
      const q = state.search.trim().toLowerCase();
      const rows = state.items.filter((it) => {
        if (q && !(it.item_name || "").toLowerCase().includes(q) && !(it.vendor || "").toLowerCase().includes(q)) return false;
        if (state.filter === "low") return it.is_low_stock;
        if (state.filter === "expiring") return it.expiry_flag === "expiring";
        if (state.filter === "expired") return it.expiry_flag === "expired";
        return true;
      });
      if (state.sortKey) {
        const col = COLUMNS.find((c) => c.key === state.sortKey);
        if (col) {
          rows.sort((a, b) => {
            const av = col.get(a), bv = col.get(b);
            if (av < bv) return -1 * state.sortDir;
            if (av > bv) return 1 * state.sortDir;
            return 0;
          });
        }
      }
      return rows;
    }

    // Managers/admins: inline spartan form to create a new item (POST /api/items).
    function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "Add item"));

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      function field(labelText, inputEl) {
        const w = el("div");
        w.style.display = "flex";
        w.style.flexDirection = "column";
        w.style.gap = "3px";
        w.appendChild(el("label", "muted", labelText));
        inputEl.className = inputEl.className || "chip";
        w.appendChild(inputEl);
        return w;
      }

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "chip";
      nameInput.placeholder = "Item name";

      const catSel = document.createElement("select");
      catSel.className = "chip";
      for (const c of catList(ctx)) {
        const opt = el("option", null, c);
        opt.value = c;
        catSel.appendChild(opt);
      }

      const vendorInput = document.createElement("input");
      vendorInput.type = "text"; vendorInput.className = "chip";
      const unitInput = document.createElement("input");
      unitInput.type = "text"; unitInput.className = "chip";
      unitInput.placeholder = "e.g. mL, box, vial";
      const packSizeInput = document.createElement("input");
      packSizeInput.type = "text"; packSizeInput.className = "chip";
      packSizeInput.placeholder = "e.g. 500 mL";
      const qtyInput = document.createElement("input");
      qtyInput.type = "number"; qtyInput.className = "chip"; qtyInput.value = "0";
      const reorderInput = document.createElement("input");
      reorderInput.type = "number"; reorderInput.className = "chip"; reorderInput.value = "0";
      const reorderMaxInput = document.createElement("input");
      reorderMaxInput.type = "number"; reorderMaxInput.className = "chip"; reorderMaxInput.placeholder = "(optional)";
      const costInput = document.createElement("input");
      costInput.type = "number"; costInput.step = "0.01"; costInput.className = "chip"; costInput.value = "0";
      const sdsInput = document.createElement("input");
      sdsInput.type = "url"; sdsInput.className = "chip"; sdsInput.placeholder = "https://...";
      const hazardInput = document.createElement("input");
      hazardInput.type = "text"; hazardInput.className = "chip"; hazardInput.placeholder = "e.g. flammable,toxic";
      const casInput = document.createElement("input");
      casInput.type = "text"; casInput.className = "chip"; casInput.placeholder = "e.g. 67-56-1";

      const tempSel = document.createElement("select");
      tempSel.className = "chip";
      for (const t of ["", "RT", "4C", "-20C", "-80C", "LN2", "other"]) {
        const opt = el("option", null, t || "-- storage temp --");
        opt.value = t;
        tempSel.appendChild(opt);
      }
      const lightWrap = el("label", "muted");
      lightWrap.style.display = "flex";
      lightWrap.style.alignItems = "center";
      lightWrap.style.gap = "6px";
      const lightCheck = document.createElement("input");
      lightCheck.type = "checkbox";
      lightWrap.appendChild(lightCheck);
      lightWrap.appendChild(document.createTextNode("Light-sensitive (store in dark)"));

      gridForm.append(
        field("Item name *", nameInput),
        field("Category", catSel),
        field("Vendor", vendorInput),
        field("Unit", unitInput),
        field("Size (e.g. 500 mL)", packSizeInput),
        field("Quantity on hand", qtyInput),
        field("Reorder threshold (min)", reorderInput),
        field("Reorder max (top up to)", reorderMaxInput),
        field("Unit cost", costInput),
        field("SDS URL", sdsInput),
        field("Hazard class", hazardInput),
        field("CAS number", casInput),
        field("Storage temperature", tempSel),
        field("Light sensitivity", lightWrap),
      );
      card.appendChild(gridForm);

      const disposalInput = document.createElement("textarea");
      disposalInput.className = "chip";
      disposalInput.rows = 2;
      disposalInput.placeholder = "Disposal instructions (from the product SDS)";
      disposalInput.style.width = "100%";
      disposalInput.style.marginTop = "10px";
      const disposalWrap = el("div");
      disposalWrap.style.display = "flex";
      disposalWrap.style.flexDirection = "column";
      disposalWrap.style.gap = "3px";
      disposalWrap.appendChild(el("label", "muted", "Disposal instructions"));
      disposalWrap.appendChild(disposalInput);
      card.appendChild(disposalWrap);

      // Controlled-substance toggle reveals a schedule field.
      const ctrlRow = el("label", "muted");
      ctrlRow.style.display = "flex";
      ctrlRow.style.gap = "6px";
      ctrlRow.style.alignItems = "center";
      ctrlRow.style.margin = "10px 0";
      ctrlRow.style.cursor = "pointer";
      const ctrlCheck = document.createElement("input");
      ctrlCheck.type = "checkbox";
      ctrlRow.append(ctrlCheck, document.createTextNode("controlled substance?"));
      card.appendChild(ctrlRow);

      const schedInput = document.createElement("input");
      schedInput.type = "text";
      schedInput.className = "chip";
      schedInput.placeholder = "Schedule (e.g. II)";
      schedInput.style.maxWidth = "200px";
      const schedWrap = el("div");
      schedWrap.hidden = true;
      schedWrap.style.marginBottom = "10px";
      schedWrap.style.display = "flex";
      schedWrap.style.flexDirection = "column";
      schedWrap.style.gap = "3px";
      schedWrap.appendChild(el("label", "muted", "Controlled schedule"));
      schedWrap.appendChild(schedInput);
      card.appendChild(schedWrap);
      ctrlCheck.addEventListener("change", () => { schedWrap.hidden = !ctrlCheck.checked; });

      const btnRow = el("div");
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      const submit = el("button", "btn btn-primary btn-sm", "Create item");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) { ctx.toast("Item name is required", "warn"); nameInput.focus(); return; }
        const body = {
          item_name: name,
          category: catSel.value,
          vendor: vendorInput.value.trim() || null,
          unit: unitInput.value.trim() || null,
          pack_size: packSizeInput.value.trim() || null,
          quantity_on_hand: Number(qtyInput.value) || 0,
          reorder_threshold: Number(reorderInput.value) || 0,
          reorder_max: reorderMaxInput.value.trim() === "" ? null : (Number(reorderMaxInput.value) || 0),
          unit_cost: Number(costInput.value) || 0,
          sds_url: sdsInput.value.trim() || null,
          hazard_class: hazardInput.value.trim() || null,
          cas_number: casInput.value.trim() || null,
          storage_temp: tempSel.value || null,
          light_sensitive: lightCheck.checked,
          disposal_instructions: disposalInput.value.trim() || null,
          is_controlled: ctrlCheck.checked,
          controlled_schedule: ctrlCheck.checked ? (schedInput.value.trim() || null) : null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/items", body);
          ctx.toast("Item created", "ok");
          addFormHost.innerHTML = "";
          try { await loadItems(); } catch (_) { /* best-effort refresh */ }
          showList();
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

    drawTable();
  }

  // ---- row interactions: product modal + right-click actions (Wave B) -------
  // Left-clicking a row opens a lightweight product modal. The full in-view
  // record (edit / restock / consume / documents / QR) stays reachable through
  // "Open full record" -> showDetail.
  async function openProductModal(itemId, itemName) {
    const handle = ctx.modal({
      title: itemName || "Item",
      render(body) { body.appendChild(el("div", "muted", "Loading...")); },
      actions: [
        { label: "Open full record", primary: true, onClick: (h) => { h.close(); showDetail(itemId); } },
        { label: "Close", onClick: (h) => h.close() },
      ],
    });

    let data;
    try {
      data = await ctx.api.get("/api/items/" + itemId);
    } catch (err) {
      handle.body.innerHTML = "";
      handle.body.appendChild(el("div", "empty-state", "Could not load item: " + err.message));
      return;
    }
    const item = data.item || {};
    handle.body.innerHTML = "";

    // Prominent link into the product database, only when linked to a catalog row.
    if (item.catalog_id != null) {
      const dbLink = el("button", "btn btn-ghost btn-sm", "View in product database");
      dbLink.style.marginBottom = "10px";
      dbLink.addEventListener("click", () => { handle.close(); ctx.navigate("catalog", { catalogId: item.catalog_id }); });
      handle.body.appendChild(dbLink);
    }

    // Two columns: facts (left) + a product photo panel (right).
    const cols = el("div");
    cols.style.display = "flex";
    cols.style.gap = "14px";
    cols.style.flexWrap = "wrap";
    const leftCol = el("div");
    leftCol.style.flex = "1 1 260px";
    leftCol.style.minWidth = "0";
    const rightCol = el("div");
    rightCol.style.flex = "0 0 160px";
    cols.append(leftCol, rightCol);
    handle.body.appendChild(cols);

    // Facts (label / value); each row is shown only when it has a value.
    const facts = el("div");
    facts.style.marginBottom = "10px";
    function row(label, value) {
      if (value == null || value === "") return;
      const r = el("div");
      r.style.display = "flex";
      r.style.gap = "10px";
      r.style.padding = "3px 0";
      const l = el("div", "muted", label);
      l.style.flex = "0 0 130px";
      const v = el("div");
      v.textContent = String(value);
      r.append(l, v);
      facts.appendChild(r);
    }
    const money = (n) => (n == null || n === "" ? null : ctx.fmt.money(n));
    row("Vendor", item.vendor);
    row("Catalog #", item.catalog_number);
    row("Size", item.size || item.pack_size);
    row("Unit", item.unit);
    row("List price", money(item.list_price));
    row("Unit cost", money(item.unit_cost));
    row("On hand", item.quantity_on_hand);
    if (item.amount != null && item.amount !== "") row("Amount", item.amount);
    row("Category", item.category);
    row("Location", item.location);
    row("Storage temp", item.storage_temp);
    if (item.light_sensitive) row("Light", "store in dark");
    row("CAS", item.cas_number);
    row("Hazard class", item.hazard_class);
    if (item.is_controlled) row("Controlled", item.controlled_schedule ? "schedule " + item.controlled_schedule : "yes");
    leftCol.appendChild(facts);

    // Document / product links (new tab, no opener).
    const sdsUrl = item.sds_url || item.catalog_sds_url;
    const lots = (data && data.lots) || [];
    const coaLot = lots.find((l) => l && l.coa_url);
    const links = el("div");
    links.style.display = "flex";
    links.style.gap = "12px";
    links.style.flexWrap = "wrap";
    if (sdsUrl) links.appendChild(docLink("SDS", sdsUrl));
    if (coaLot) links.appendChild(docLink("CoA", coaLot.coa_url));
    if (item.product_url) links.appendChild(docLink("Product page", item.product_url));
    if (links.childNodes.length) leftCol.appendChild(links);

    // Product photo panel (right): shows the uploaded photo or a placeholder,
    // with an upload/replace control for members+.
    buildPhotoPanel(rightCol, item);
  }

  // Photo panel used inside the product modal. Uploads to /api/items/{id}/photo.
  function buildPhotoPanel(host, item) {
    host.innerHTML = "";
    const frame = el("div", "panel");
    frame.style.padding = "6px";
    frame.style.textAlign = "center";
    const img = document.createElement("img");
    img.style.maxWidth = "100%";
    img.style.display = item.photo_url ? "block" : "none";
    img.alt = "Product photo";
    if (item.photo_url) img.src = item.photo_url;
    const placeholder = el("div", "muted", "No photo");
    placeholder.style.padding = "24px 0";
    placeholder.style.display = item.photo_url ? "none" : "block";
    frame.append(img, placeholder);
    host.appendChild(frame);

    const canEditPhoto = !!(ctx.user && ctx.user.role &&
      ["member", "manager", "admin"].includes(ctx.user.role));
    if (!canEditPhoto) return;

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.style.display = "none";
    const upBtn = el("button", "btn btn-ghost btn-sm", item.photo_url ? "Replace photo" : "Upload photo");
    upBtn.style.marginTop = "6px";
    upBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      upBtn.disabled = true;
      try {
        const res = await fetch("/api/items/" + item.item_id + "/photo", {
          method: "POST", body: fd, credentials: "same-origin",
        });
        if (!res.ok) throw new Error("upload failed (" + res.status + ")");
        const out = await res.json();
        item.photo_url = out.photo_url;
        ctx.toast("Photo uploaded", "ok");
        buildPhotoPanel(host, item); // re-render with the new photo
      } catch (err) {
        ctx.toast("Photo upload failed: " + (err.message || err), "danger");
      } finally {
        upBtn.disabled = false;
      }
    });
    host.append(upBtn, fileInput);
  }

  // Right-click a row -> role-/data-gated product actions.
  function openRowMenu(e, it) {
    const role = ctx.user && ctx.user.role;
    const canOrder = role === "member" || role === "manager" || role === "admin";
    const items = [];
    items.push({ label: "View details", onClick: () => openProductModal(it.item_id, it.item_name) });
    if (canOrder) items.push({ label: "Order / reorder", onClick: () => orderItem(it) });
    items.push({ label: "Log usage", onClick: () => logUsage(it) });
    if (canOrder) items.push({ label: "Set actual quantity (count)", onClick: () => setActualQuantity(it) });
    if (it.sds_url) items.push({ label: "View SDS", onClick: () => window.open(it.sds_url, "_blank", "noopener") });
    if (it.coa_url) items.push({ label: "View CoA", onClick: () => window.open(it.coa_url, "_blank", "noopener") });
    if (it.product_url) items.push({ label: "View product page", onClick: () => window.open(it.product_url, "_blank", "noopener") });
    if (it.catalog_number) {
      items.push({ label: "Copy catalog #", onClick: () => {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(it.catalog_number)
            .then(() => ctx.toast("Copied", "ok"))
            .catch(() => ctx.toast("Copy failed", "danger"));
        } else {
          ctx.toast("Copy failed", "danger");
        }
      } });
    }
    if (canEdit) {
      items.push({ divider: true });
      items.push({ label: "Edit", onClick: () => showDetail(it.item_id) });
      if (it.status === "deprecated") {
        items.push({ label: "Restore", onClick: () => setItemStatus(it, "active") });
      } else {
        items.push({ label: "Deprecate (archive)", onClick: () => setItemStatus(it, "deprecated") });
      }
    }
    ctx.contextMenu(e.clientX, e.clientY, items, it.item_name);
  }

  // Edit a lot's identity (number / expiry / CoA). Opening balances and CSV
  // imports create a lot with no expiry, so this is what lets that stock become
  // visible to expiry tracking.
  function editLot(lot, itemId) {
    let numInput, expInput, coaInput;
    ctx.modal({
      title: "Edit lot",
      render: (body) => {
        const mk = (labelText, value, type, placeholder) => {
          const lab = document.createElement("label");
          lab.textContent = labelText;
          lab.style.display = "block";
          lab.style.marginTop = "8px";
          const inp = document.createElement("input");
          inp.className = "chip";
          if (type) inp.type = type;
          if (placeholder) inp.placeholder = placeholder;
          inp.value = value || "";
          lab.appendChild(inp);
          body.appendChild(lab);
          return inp;
        };
        numInput = mk("Lot number", lot.lot_number, "text", "e.g. LOT-1234");
        expInput = mk("Expiry date", lot.expiry_date, "date", "YYYY-MM-DD");
        coaInput = mk("CoA URL", lot.coa_url, "url", "https://...");
        const hint = el("p", "muted",
          "Setting an expiry puts this lot's stock into expiry alerts and the "
          + "dashboard's expiring/expired counts.");
        hint.style.marginTop = "10px";
        body.appendChild(hint);
      },
      actions: [
        { label: "Cancel", onClick: (h) => h.close() },
        {
          label: "Save lot",
          primary: true,
          onClick: async (h) => {
            const payload = {
              lot_number: numInput.value.trim() || null,
              expiry_date: expInput.value.trim() || null,
              coa_url: coaInput.value.trim() || null,
            };
            try {
              await ctx.api.patch("/api/lots/" + lot.id, payload);
              h.close();
              ctx.toast("Lot updated", "ok");
              showDetail(itemId);
            } catch (err) {
              ctx.toast("Could not update lot: "
                + (err && err.message ? err.message : err), "danger");
            }
          },
        },
      ],
    });
  }

  // Reconcile the record to a physical count. This is deliberately NOT
  // "consume the difference": the delta is stored as an adjustment, so a
  // recount never shows up as usage in the analytics.
  function setActualQuantity(it) {
    let qtyInput, reasonInput;
    const handle = ctx.modal({
      title: "Set actual quantity -- " + it.item_name,
      render: (body) => {
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "The record currently says " + it.quantity_on_hand
          + " " + (it.unit || "units") + ". Enter what is physically there; "
          + "the difference is recorded as an audited adjustment.";
        body.appendChild(p);

        const qLabel = document.createElement("label");
        qLabel.textContent = "Counted quantity";
        qLabel.style.display = "block";
        qLabel.style.marginTop = "8px";
        qtyInput = document.createElement("input");
        qtyInput.className = "chip";
        qtyInput.type = "number";
        qtyInput.min = "0";
        qtyInput.value = String(it.quantity_on_hand);
        qLabel.appendChild(qtyInput);
        body.appendChild(qLabel);

        const rLabel = document.createElement("label");
        rLabel.textContent = "Reason (optional)";
        rLabel.style.display = "block";
        rLabel.style.marginTop = "8px";
        reasonInput = document.createElement("input");
        reasonInput.className = "chip";
        reasonInput.placeholder = "e.g. annual count, breakage, found extra";
        rLabel.appendChild(reasonInput);
        body.appendChild(rLabel);
      },
      actions: [
        { label: "Cancel", onClick: (h) => h.close() },
        {
          label: "Save count",
          primary: true,
          onClick: async (h) => {
            const qty = parseInt(qtyInput.value, 10);
            if (!Number.isFinite(qty) || qty < 0) {
              ctx.toast("Enter a quantity of zero or more", "warn");
              return;
            }
            try {
              const res = await ctx.api.post(
                "/api/items/" + it.item_id + "/set-quantity",
                { quantity: qty, reason: reasonInput.value.trim() || null },
              );
              h.close();
              const d = res.delta;
              ctx.toast(
                it.item_name + " set to " + res.quantity_on_hand
                + (d ? " (" + (d > 0 ? "+" : "") + d + ")" : " (no change)"),
                "ok",
              );
              if (res.untracked_by_lot > 0) {
                ctx.toast(
                  res.untracked_by_lot + " unit(s) have no lot/expiry recorded"
                  + " -- restock with a lot to track expiry.",
                  "warn",
                );
              }
              await loadItems();
              drawTable();
            } catch (err) {
              ctx.toast("Could not set quantity: "
                + (err && err.message ? err.message : err), "danger");
            }
          },
        },
      ],
    });
    setTimeout(() => { if (qtyInput) { qtyInput.focus(); qtyInput.select(); } }, 0);
    return handle;
  }

  // Soft-archive / restore an item. Deprecating hides it from active pick-lists
  // while preserving all its history (lots, usage, orders); it is fully
  // reversible via Restore (surface deprecated rows with the "Show deprecated"
  // toggle). Backed by PATCH /api/items/{id} { status }.
  async function setItemStatus(it, status) {
    try {
      await ctx.api.patch("/api/items/" + it.item_id, { status });
      ctx.toast(
        status === "deprecated"
          ? it.item_name + " deprecated (archived)"
          : it.item_name + " restored",
        "ok",
      );
      await loadItems();
      drawTable();
    } catch (err) {
      ctx.toast(
        "Could not update: " + (err && err.message ? err.message : err),
        "danger",
      );
    }
  }

  // Order / reorder: append a line to the caller's draft PO (member+). Default
  // quantity = the reorder threshold when set, else 1. Non-intrusive; toast only.
  async function orderItem(it) {
    const qty = (Number(it.reorder_threshold) > 0) ? Number(it.reorder_threshold) : 1;
    try {
      const res = await ctx.api.post("/api/purchase-orders/draft-line", { item_id: it.item_id, quantity: qty });
      ctx.toast("Added to draft PO #" + res.po_id, "ok");
    } catch (err) {
      ctx.toast("Order failed: " + err.message, "danger");
    }
  }

  // Log usage: minimal quantity prompt, then the existing consume endpoint.
  async function logUsage(it) {
    const raw = window.prompt("Log usage of " + it.item_name + " -- quantity to consume:", "1");
    if (raw == null) return;
    const qty = parseInt(raw, 10);
    if (!qty || qty <= 0) { ctx.toast("Enter a positive quantity", "warn"); return; }
    try {
      await ctx.api.post("/api/items/" + it.item_id + "/consume", { quantity: qty });
      ctx.toast("Consumed " + qty + " " + it.item_name, "ok");
      try { await loadItems(); } catch (_) { /* best-effort refresh */ }
      showList();
    } catch (err) {
      ctx.toast("Log usage failed: " + err.message, "danger");
    }
  }

  // ---- detail view --------------------------------------------------------
  async function showDetail(itemId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to inventory");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/items/" + itemId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load item: " + err.message));
      return;
    }
    const item = data.item;

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(300px, 1fr))";
    container.appendChild(grid);

    // summary + actions card
    const summary = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", item.item_name);
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    titleRow.appendChild(categoryBadge(item.category));
    if (item.is_controlled) titleRow.appendChild(controlledBadge(item));
    if (item.hazard_class) titleRow.appendChild(hazardBadge(item));
    if (item.status === "deprecated") titleRow.appendChild(el("span", "badge badge-danger", "deprecated"));
    if (canEdit) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => {
        editForm.hidden = !editForm.hidden;
      });
      titleRow.appendChild(editBtn);

      // Deprecate (soft-delete) or Restore, depending on current status.
      if (item.status === "deprecated") {
        const restoreBtn = el("button", "btn btn-ghost btn-sm", "Restore");
        restoreBtn.addEventListener("click", async () => {
          restoreBtn.disabled = true;
          try {
            await ctx.api.patch("/api/items/" + itemId, { status: "active" });
            ctx.toast("Item restored", "ok");
            try { await loadItems(); } catch (_) { /* best-effort */ }
            showList();
          } catch (err) {
            ctx.toast("Restore failed: " + err.message, "danger");
            restoreBtn.disabled = false;
          }
        });
        titleRow.appendChild(restoreBtn);
      } else {
        const depBtn = el("button", "btn btn-ghost btn-sm", "Deprecate item");
        depBtn.addEventListener("click", async () => {
          if (!confirm("Deprecate \"" + item.item_name + "\"? It will be hidden from the default list.")) return;
          depBtn.disabled = true;
          try {
            await ctx.api.patch("/api/items/" + itemId, { status: "deprecated" });
            ctx.toast("Item deprecated", "ok");
            try { await loadItems(); } catch (_) { /* best-effort */ }
            showList();
          } catch (err) {
            ctx.toast("Deprecate failed: " + err.message, "danger");
            depBtn.disabled = false;
          }
        });
        titleRow.appendChild(depBtn);
      }
    }
    summary.appendChild(titleRow);

    // SDS link (or muted absence marker)
    const sdsRow = el("div");
    sdsRow.style.margin = "4px 0 2px";
    if (item.sds_url) {
      sdsRow.appendChild(docLink("SDS", item.sds_url));
    } else {
      sdsRow.appendChild(el("span", "muted", "no SDS"));
    }
    summary.appendChild(sdsRow);

    const meta = el("div", "muted");
    meta.style.marginBottom = "12px";
    meta.textContent = `${item.vendor || "Unknown vendor"} · ${item.unit || "unit"} · ${ctx.fmt.money(item.unit_cost)} each`;
    summary.appendChild(meta);

    // manager/admin inline edit form: category + SDS URL -> PATCH
    const editForm = el("div");
    editForm.hidden = true;
    if (canEdit) {
      editForm.style.display = "flex";
      editForm.style.flexWrap = "wrap";
      editForm.style.gap = "8px";
      editForm.style.alignItems = "center";
      editForm.style.marginBottom = "12px";

      const catSel = document.createElement("select");
      catSel.className = "chip";
      const editCats = catList(ctx);
      for (const c of editCats) {
        const opt = el("option", null, c);
        opt.value = c;
        catSel.appendChild(opt);
      }
      if (item.category && !editCats.includes(item.category)) {
        const opt = el("option", null, item.category);
        opt.value = item.category;
        catSel.appendChild(opt);
      }
      catSel.value = item.category || "other";

      const sdsInput = document.createElement("input");
      sdsInput.type = "url";
      sdsInput.className = "chip";
      sdsInput.placeholder = "SDS URL";
      sdsInput.style.flex = "1 1 180px";
      sdsInput.value = item.sds_url || "";

      const reorderMaxEdit = document.createElement("input");
      reorderMaxEdit.type = "number";
      reorderMaxEdit.className = "chip";
      reorderMaxEdit.placeholder = "Reorder max";
      reorderMaxEdit.title = "Reorder max (top up to)";
      reorderMaxEdit.style.flex = "1 1 120px";
      reorderMaxEdit.value = item.reorder_max != null ? String(item.reorder_max) : "";

      const hazardEdit = document.createElement("input");
      hazardEdit.type = "text";
      hazardEdit.className = "chip";
      hazardEdit.placeholder = "Hazard class (e.g. flammable,toxic)";
      hazardEdit.style.flex = "1 1 160px";
      hazardEdit.value = item.hazard_class || "";

      const casEdit = document.createElement("input");
      casEdit.type = "text";
      casEdit.className = "chip";
      casEdit.placeholder = "CAS number";
      casEdit.style.flex = "1 1 120px";
      casEdit.value = item.cas_number || "";

      const packSizeEdit = document.createElement("input");
      packSizeEdit.type = "text";
      packSizeEdit.className = "chip";
      packSizeEdit.placeholder = "Size (e.g. 500 mL)";
      packSizeEdit.title = "Size (e.g. 500 mL)";
      packSizeEdit.style.flex = "1 1 120px";
      packSizeEdit.value = item.size || "";

      const tempEdit = document.createElement("select");
      tempEdit.className = "chip";
      tempEdit.title = "Storage temperature";
      tempEdit.style.flex = "0 0 120px";
      for (const t of ["", "RT", "4C", "-20C", "-80C", "LN2", "other"]) {
        const opt = el("option", null, t || "-- temp --");
        opt.value = t;
        tempEdit.appendChild(opt);
      }
      tempEdit.value = item.storage_temp || "";

      const lightEditWrap = el("label", "muted");
      lightEditWrap.style.display = "flex";
      lightEditWrap.style.alignItems = "center";
      lightEditWrap.style.gap = "5px";
      const lightEdit = document.createElement("input");
      lightEdit.type = "checkbox";
      lightEdit.checked = !!item.light_sensitive;
      lightEditWrap.append(lightEdit, document.createTextNode("Light-sensitive"));

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save");
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/items/" + itemId, {
            category: catSel.value,
            sds_url: sdsInput.value.trim() || null,
            reorder_max: reorderMaxEdit.value.trim() === "" ? null : (Number(reorderMaxEdit.value) || 0),
            hazard_class: hazardEdit.value.trim() || null,
            cas_number: casEdit.value.trim() || null,
            pack_size: packSizeEdit.value.trim() || null,
            storage_temp: tempEdit.value || null,
            light_sensitive: lightEdit.checked ? 1 : 0,
          });
          ctx.toast("Item updated", "ok");
          try { await loadItems(); } catch (_) { /* list refresh is best-effort */ }
          showDetail(itemId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });

      editForm.append(catSel, sdsInput, reorderMaxEdit, hazardEdit, casEdit, packSizeEdit, tempEdit, lightEditWrap, saveBtn);
      summary.appendChild(editForm);
    }

    const stats = el("div", "grid");
    stats.style.gridTemplateColumns = "repeat(2, 1fr)";
    stats.style.gap = "10px";
    stats.style.marginBottom = "14px";
    const onHandStat = el("div", "stat");
    const onHandVal = el("div", "stat-value", String(item.quantity_on_hand));
    if (item.quantity_on_hand <= item.reorder_threshold) onHandVal.style.color = "var(--warn)";
    onHandStat.append(onHandVal, el("div", "stat-label", "On hand"));
    const reorderStat = el("div", "stat");
    const reorderHasMax = item.reorder_max != null && item.reorder_max !== "";
    reorderStat.append(
      el("div", "stat-value", reorderHasMax ? `${item.reorder_threshold} / ${item.reorder_max}` : String(item.reorder_threshold)),
      el("div", "stat-label", reorderHasMax ? "Reorder min / max" : "Reorder at"),
    );
    stats.append(onHandStat, reorderStat);
    summary.appendChild(stats);

    // action forms
    const actions = el("div");
    actions.style.display = "flex";
    actions.style.flexDirection = "column";
    actions.style.gap = "10px";

    const consumeRow = actionRow("Consume", "btn-primary", async (qty) => {
      await ctx.api.post(`/api/items/${itemId}/consume`, { quantity: qty });
      ctx.toast(`Consumed ${qty} ${item.item_name}`, "ok");
      showDetail(itemId);
    });
    actions.append(consumeRow, buildRestockForm());
    summary.appendChild(actions);
    grid.appendChild(summary);

    // Disposal panel: SDS-derived disposal instructions; managers can edit inline.
    const disposalCard = el("div", "card");
    const dispTitleRow = el("div");
    dispTitleRow.style.display = "flex";
    dispTitleRow.style.alignItems = "baseline";
    dispTitleRow.style.gap = "8px";
    const dispTitle = el("div", "card-title", "Disposal");
    dispTitle.style.marginBottom = "0";
    dispTitleRow.append(dispTitle, el("span", "muted", "(from the product SDS)"));
    disposalCard.appendChild(dispTitleRow);

    const dispBody = el("div");
    dispBody.style.marginTop = "8px";
    if (item.disposal_instructions) {
      dispBody.textContent = item.disposal_instructions;
    } else {
      dispBody.className = "muted";
      dispBody.textContent = "-- not specified --";
    }
    disposalCard.appendChild(dispBody);

    if (canEdit) {
      const editDisp = el("button", "btn btn-ghost btn-sm", "Edit disposal");
      editDisp.style.marginTop = "10px";
      const dispEditWrap = el("div");
      dispEditWrap.hidden = true;
      dispEditWrap.style.marginTop = "10px";
      const dispArea = document.createElement("textarea");
      dispArea.className = "chip";
      dispArea.rows = 3;
      dispArea.style.width = "100%";
      dispArea.value = item.disposal_instructions || "";
      const dispSave = el("button", "btn btn-primary btn-sm", "Save disposal");
      dispSave.style.marginTop = "8px";
      dispSave.addEventListener("click", async () => {
        dispSave.disabled = true;
        try {
          await ctx.api.patch("/api/items/" + itemId, {
            disposal_instructions: dispArea.value.trim() || null,
          });
          ctx.toast("Disposal instructions updated", "ok");
          try { await loadItems(); } catch (_) { /* best-effort */ }
          showDetail(itemId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          dispSave.disabled = false;
        }
      });
      dispEditWrap.append(dispArea, dispSave);
      editDisp.addEventListener("click", () => { dispEditWrap.hidden = !dispEditWrap.hidden; });
      disposalCard.append(editDisp, dispEditWrap);
    }
    grid.appendChild(disposalCard);

    // Documents panel: SDS / CoA / invoice / other, as links; attach via URL or upload.
    grid.appendChild(buildDocumentsCard());

    // QR label: scannable deep link to this item, with a print button.
    const qrCard = el("div", "card");
    qrCard.appendChild(el("div", "card-title", "QR label"));
    const qrImg = document.createElement("img");
    qrImg.src = "/api/items/" + itemId + "/qr.svg";
    qrImg.width = 110;
    qrImg.height = 110;
    qrImg.alt = "QR code for " + item.item_name;
    qrImg.style.display = "block";
    qrCard.appendChild(qrImg);
    qrCard.appendChild(el("div", "muted", "Scan to open this item"));
    const printBtn = el("button", "btn btn-ghost btn-sm", "Print label");
    printBtn.style.marginTop = "8px";
    printBtn.addEventListener("click", () => window.print());
    qrCard.appendChild(printBtn);
    grid.appendChild(qrCard);

    // Restock: quantity (required) plus optional lot number / expiry / CoA URL
    // so a restock can record a new lot with its certificate of analysis.
    function buildRestockForm() {
      const wrap = el("div");
      wrap.style.display = "flex";
      wrap.style.flexDirection = "column";
      wrap.style.gap = "8px";

      const row = el("div");
      row.style.display = "flex";
      row.style.gap = "8px";
      row.style.alignItems = "center";
      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "1";
      qtyInput.value = "1";
      qtyInput.className = "chip";
      qtyInput.style.width = "84px";
      const btn = el("button", "btn btn-ghost", "Restock");
      btn.style.flex = "1 1 auto";
      row.append(qtyInput, btn);

      const extras = el("div");
      extras.style.display = "flex";
      extras.style.flexWrap = "wrap";
      extras.style.gap = "8px";
      const lotInput = document.createElement("input");
      lotInput.type = "text";
      lotInput.className = "chip";
      lotInput.placeholder = "Lot # (optional)";
      lotInput.style.flex = "1 1 120px";
      const expiryInput = document.createElement("input");
      expiryInput.type = "date";
      expiryInput.className = "chip";
      expiryInput.title = "Expiry date (optional)";
      expiryInput.style.flex = "1 1 130px";
      const coaInput = document.createElement("input");
      coaInput.type = "url";
      coaInput.className = "chip";
      coaInput.placeholder = "CoA URL (optional)";
      coaInput.style.flex = "1 1 160px";
      extras.append(lotInput, expiryInput, coaInput);

      btn.addEventListener("click", async () => {
        const qty = parseInt(qtyInput.value, 10);
        if (!qty || qty <= 0) { ctx.toast("Enter a positive quantity", "warn"); return; }
        // Preserve prior behavior: auto-generate a lot number when none given.
        const lotNumber = lotInput.value.trim() || `RS-${itemId}-${Date.now().toString().slice(-5)}`;
        const body = { quantity: qty, lot_number: lotNumber };
        if (expiryInput.value) body.expiry_date = expiryInput.value;
        if (coaInput.value.trim()) body.coa_url = coaInput.value.trim();
        btn.disabled = true;
        try {
          await ctx.api.post(`/api/items/${itemId}/restock`, body);
          ctx.toast(`Restocked ${qty} ${item.item_name}`, "ok");
          showDetail(itemId);
        } catch (err) {
          ctx.toast(`Restock failed: ${err.message}`, "danger");
          btn.disabled = false;
        }
      });

      wrap.append(row, extras);
      return wrap;
    }

    // Documents panel: list attached docs (SDS/CoA/invoice/other) as links, with
    // controls to attach a URL link or upload a file, and delete (managers/admins).
    function buildDocumentsCard() {
      const role = ctx.user && ctx.user.role;
      const canContribute = role === "member" || role === "manager" || role === "admin";
      const card = el("div", "card");
      card.appendChild(el("div", "card-title", "Documents"));
      card.appendChild(el("div", "muted", "SDS, certificates of analysis, invoices, and other files for this item."));

      const list = el("div");
      list.style.marginTop = "10px";
      const docs = (data && data.documents) || [];
      if (!docs.length) {
        list.appendChild(el("div", "muted", "No documents attached."));
      } else {
        for (const doc of docs) {
          const rowEl = el("div");
          rowEl.style.display = "flex";
          rowEl.style.alignItems = "center";
          rowEl.style.gap = "8px";
          rowEl.style.flexWrap = "wrap";
          rowEl.style.padding = "4px 0";
          rowEl.appendChild(el("span", "badge", doc.kind || "other"));
          const linkText = doc.label || doc.filename || doc.url || "document";
          rowEl.appendChild(docLink(linkText, doc.href || doc.url));
          if (canEdit) {
            const del = el("button", "btn btn-ghost btn-sm", "Delete");
            del.addEventListener("click", async () => {
              if (!confirm("Delete this document?")) return;
              del.disabled = true;
              try {
                await ctx.api.del("/api/documents/" + doc.id);
                ctx.toast("Document deleted", "ok");
                showDetail(itemId);
              } catch (err) {
                ctx.toast("Delete failed: " + err.message, "danger");
                del.disabled = false;
              }
            });
            rowEl.appendChild(del);
          }
          list.appendChild(rowEl);
        }
      }
      card.appendChild(list);

      if (!canContribute) return card;

      // --- Attach control (member+): kind + label, then EITHER a URL or a file. ---
      const attach = el("div");
      attach.style.marginTop = "12px";
      attach.style.borderTop = "1px solid var(--border, #ccc)";
      attach.style.paddingTop = "10px";
      attach.appendChild(el("div", "muted", "Attach a document"));

      const topRow = el("div");
      topRow.style.display = "flex";
      topRow.style.gap = "8px";
      topRow.style.flexWrap = "wrap";
      topRow.style.margin = "8px 0";
      const kindSel = document.createElement("select");
      kindSel.className = "chip";
      for (const k of [["sds", "SDS"], ["coa", "CoA"], ["invoice", "Invoice"], ["other", "Other"]]) {
        const opt = el("option", null, k[1]);
        opt.value = k[0];
        kindSel.appendChild(opt);
      }
      kindSel.title = "Document kind";
      const labelInput = document.createElement("input");
      labelInput.type = "text";
      labelInput.className = "chip";
      labelInput.placeholder = "Label (optional)";
      labelInput.style.flex = "1 1 160px";
      topRow.append(kindSel, labelInput);
      attach.appendChild(topRow);

      // Option A: external URL link.
      const urlRow = el("div");
      urlRow.style.display = "flex";
      urlRow.style.gap = "8px";
      urlRow.style.flexWrap = "wrap";
      urlRow.style.marginBottom = "8px";
      const urlInput = document.createElement("input");
      urlInput.type = "url";
      urlInput.className = "chip";
      urlInput.placeholder = "https://... (link)";
      urlInput.style.flex = "1 1 200px";
      const addLinkBtn = el("button", "btn btn-ghost btn-sm", "Add link");
      addLinkBtn.addEventListener("click", async () => {
        const url = urlInput.value.trim();
        if (!url) { ctx.toast("Enter a document URL", "warn"); urlInput.focus(); return; }
        addLinkBtn.disabled = true;
        try {
          await ctx.api.post("/api/documents", {
            item_id: itemId,
            kind: kindSel.value,
            label: labelInput.value.trim() || null,
            url,
          });
          ctx.toast("Document linked", "ok");
          showDetail(itemId);
        } catch (err) {
          ctx.toast("Attach failed: " + err.message, "danger");
          addLinkBtn.disabled = false;
        }
      });
      urlRow.append(urlInput, addLinkBtn);
      attach.appendChild(urlRow);

      // Option B: file upload (multipart; ctx.api only sends JSON, so use fetch).
      const fileRow = el("div");
      fileRow.style.display = "flex";
      fileRow.style.gap = "8px";
      fileRow.style.flexWrap = "wrap";
      fileRow.style.alignItems = "center";
      const fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.className = "chip";
      fileInput.style.flex = "1 1 200px";
      const uploadBtn = el("button", "btn btn-ghost btn-sm", "Upload file");
      uploadBtn.addEventListener("click", async () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) { ctx.toast("Choose a file to upload", "warn"); return; }
        const fd = new FormData();
        fd.append("item_id", String(itemId));
        fd.append("kind", kindSel.value);
        if (labelInput.value.trim()) fd.append("label", labelInput.value.trim());
        fd.append("file", file);
        uploadBtn.disabled = true;
        try {
          const resp = await fetch("/api/documents/upload", {
            method: "POST",
            body: fd,
            credentials: "same-origin",
          });
          if (!resp.ok) {
            let detail;
            try { detail = (await resp.json()).detail; } catch (_) { /* non-JSON error */ }
            throw new Error(detail || ("Upload failed (" + resp.status + ")"));
          }
          ctx.toast("File uploaded", "ok");
          showDetail(itemId);
        } catch (err) {
          ctx.toast("Upload failed: " + err.message, "danger");
          uploadBtn.disabled = false;
        }
      });
      fileRow.append(fileInput, uploadBtn);
      attach.appendChild(fileRow);

      card.appendChild(attach);
      return card;
    }

    // lots card
    const lotsCard = el("div", "card");
    lotsCard.appendChild(el("div", "card-title", "Lots"));
    if (!data.lots.length) {
      lotsCard.appendChild(el("div", "muted", "No lots recorded."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = `<thead><tr><th>Lot number</th><th class="right">Qty</th><th>Expiry</th><th>Received</th><th>CoA</th>${canEdit ? "<th></th>" : ""}</tr></thead>`;
      const tb = document.createElement("tbody");
      for (const lot of data.lots) {
        const tr = document.createElement("tr");
        const lotCell = el("td", "mono");
        if (lot.lot_number) {
          lotCell.style.fontWeight = "600";
          lotCell.textContent = lot.lot_number;
        } else {
          lotCell.className = "mono muted";
          lotCell.textContent = "(no lot number)";
        }
        tr.appendChild(lotCell);
        tr.appendChild(el("td", "right mono", String(lot.quantity)));
        const exp = document.createElement("td");
        if (lot.expiry_date) {
          exp.appendChild(document.createTextNode(ctx.fmt.date(lot.expiry_date) + " "));
          const today = new Date().toISOString().slice(0, 10);
          if (lot.expiry_date < today) exp.appendChild(el("span", "badge badge-danger", "expired"));
        } else {
          exp.textContent = "--";
        }
        tr.appendChild(exp);
        tr.appendChild(el("td", "muted", lot.received_date ? ctx.fmt.date(lot.received_date) : "--"));
        const coa = document.createElement("td");
        if (lot.coa_url) coa.appendChild(docLink("CoA", lot.coa_url));
        else coa.appendChild(el("span", "muted", "--"));
        tr.appendChild(coa);
        // Stock that arrived as an opening balance or a CSV import has a lot
        // with no expiry; without this there is no way to ever add one, and
        // expiry alerts (which read lots) can never see that stock.
        if (canEdit) {
          const actionTd = document.createElement("td");
          const editBtn = el("button", "btn btn-sm", "Edit");
          editBtn.addEventListener("click", () => editLot(lot, itemId));
          actionTd.appendChild(editBtn);
          tr.appendChild(actionTd);
        }
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      lotsCard.appendChild(scroll);
    }
    grid.appendChild(lotsCard);

    // containers card (where it physically lives)
    if (data.containers && data.containers.length) {
      const contCard = el("div", "card");
      contCard.style.gridColumn = "1 / -1";
      contCard.appendChild(el("div", "card-title", "Physical containers"));
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = `<thead><tr><th>Location</th><th>Well</th><th>Lot</th><th>Status</th><th></th></tr></thead>`;
      const tb = document.createElement("tbody");
      for (const cc of data.containers) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, cc.location_path || "--"));
        tr.appendChild(el("td", "mono", `${String.fromCharCode(64 + cc.row)}${cc.col}`));
        tr.appendChild(el("td", "mono", cc.lot_number || "--"));
        const st = document.createElement("td");
        const misplaced = cc.expected_box_id != null &&
          (cc.box_id !== cc.expected_box_id || cc.row !== cc.expected_row || cc.col !== cc.expected_col);
        if (misplaced) st.appendChild(el("span", "badge badge-danger", "misplaced"));
        else st.appendChild(el("span", "badge", cc.status));
        tr.appendChild(st);
        // Locate this container on the floor plan (deep-links to the Map tab).
        const locTd = document.createElement("td");
        if (cc.box_id != null) {
          const locBtn = el("button", "btn btn-ghost btn-sm", "Locate on floor plan");
          locBtn.addEventListener("click", () => {
            ctx.navigate("map", { locationId: cc.box_id, row: cc.row, col: cc.col });
          });
          locTd.appendChild(locBtn);
        }
        tr.appendChild(locTd);
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      contCard.appendChild(scroll);
      grid.appendChild(contCard);
    }
  }

  // A labelled qty input + action button. onRun(qty) may throw -> toast danger.
  function actionRow(label, btnCls, onRun) {
    const row = el("div");
    row.style.display = "flex";
    row.style.gap = "8px";
    row.style.alignItems = "center";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.value = "1";
    input.className = "chip";
    input.style.width = "84px";
    const btn = el("button", "btn " + btnCls, label);
    btn.style.flex = "1 1 auto";
    btn.addEventListener("click", async () => {
      const qty = parseInt(input.value, 10);
      if (!qty || qty <= 0) { ctx.toast("Enter a positive quantity", "warn"); return; }
      btn.disabled = true;
      try {
        await onRun(qty);
      } catch (err) {
        ctx.toast(`${label} failed: ${err.message}`, "danger");
        btn.disabled = false;
      }
    });
    row.append(input, btn);
    return row;
  }
}
