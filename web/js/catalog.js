// catalog.js -- vendor catalog browser + substitute groups.
// Vanilla DOM, design-system classes only. Self-contained (no cross-view imports).
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "catalog", label: "Catalog", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function availabilityBadge(av) {
  if (av === "in_stock") return el("span", "badge badge-ok", "in stock");
  if (av === "backorder") return el("span", "badge badge-warn", "backorder");
  if (av === "discontinued") {
    const b = el("span", "badge badge-danger", "discontinued");
    b.style.opacity = "0.65";
    return b;
  }
  return el("span", "badge", av || "unknown");
}
function docLink(label, url) {
  const a = el("a", null, label);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}
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

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && ["manager", "admin"].includes(ctx.user.role));

  const state = {
    tab: "browse",
    rows: [], vendors: [],
    q: "", category: "", vendor: "",
  };

  root.appendChild(el("h1", "view-title", "Catalog"));
  root.appendChild(el("p", "view-sub", "Browse the vendor catalog, compare substitute products, and add items into inventory."));

  const tabRow = el("div");
  tabRow.style.display = "flex";
  tabRow.style.gap = "8px";
  tabRow.style.marginBottom = "16px";
  const browseTabBtn = el("button", "btn btn-sm btn-primary", "Browse catalog");
  const groupsTabBtn = el("button", "btn btn-sm btn-ghost", "Substitute groups");
  browseTabBtn.addEventListener("click", () => switchTab("browse"));
  groupsTabBtn.addEventListener("click", () => switchTab("groups"));
  tabRow.append(browseTabBtn, groupsTabBtn);
  root.appendChild(tabRow);

  const container = el("div");
  root.appendChild(container);

  function switchTab(tab) {
    state.tab = tab;
    browseTabBtn.className = "btn btn-sm " + (tab === "browse" ? "btn-primary" : "btn-ghost");
    groupsTabBtn.className = "btn btn-sm " + (tab === "groups" ? "btn-primary" : "btn-ghost");
    if (tab === "browse") showBrowseList();
    else showGroupsList();
  }

  // Deep link straight to a catalog product detail (e.g. from the inventory
  // product modal). Falls back to the normal browse list when absent.
  const focusCatalogId = params && params.catalogId;
  if (focusCatalogId != null) {
    showCatalogDetail(Number(focusCatalogId));
  } else {
    switchTab("browse");
  }

  // =========================================================================
  // BROWSE CATALOG
  // =========================================================================
  async function loadCatalog() {
    const parts = [];
    if (state.q.trim()) parts.push("q=" + encodeURIComponent(state.q.trim()));
    if (state.category) parts.push("category=" + encodeURIComponent(state.category));
    if (state.vendor) parts.push("vendor=" + encodeURIComponent(state.vendor));
    const qs = parts.length ? "?" + parts.join("&") : "";
    state.rows = await ctx.api.get("/api/catalog" + qs);
  }

  async function showBrowseList() {
    container.innerHTML = "";
    const loading = el("div", "muted", "Loading catalog...");
    container.appendChild(loading);

    try {
      const [, vendors] = await Promise.all([
        loadCatalog(),
        ctx.api.get("/api/catalog/vendors").catch(() => []),
      ]);
      state.vendors = vendors || [];
    } catch (err) {
      container.innerHTML = "";
      container.appendChild(el("div", "empty-state", "Could not load catalog: " + err.message));
      return;
    }
    container.innerHTML = "";

    const toolbar = el("div", "card");
    toolbar.style.display = "flex";
    toolbar.style.flexWrap = "wrap";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "16px";

    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search product, catalog #, vendor...";
    searchInput.style.minWidth = "220px";
    searchInput.value = state.q;
    let searchTimer = null;
    searchInput.addEventListener("input", () => {
      state.q = searchInput.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        try {
          await loadCatalog();
        } catch (err) {
          ctx.toast("Search failed: " + err.message, "danger");
          return;
        }
        drawTable();
      }, 250);
    });
    toolbar.appendChild(searchInput);

    const categories = Array.from(new Set(state.rows.map((r) => r.category).filter(Boolean))).sort();
    const catSelect = document.createElement("select");
    catSelect.className = "chip";
    const allCatOpt = el("option", null, "All categories");
    allCatOpt.value = "";
    catSelect.appendChild(allCatOpt);
    for (const c of categories) {
      const opt = el("option", null, c);
      opt.value = c;
      catSelect.appendChild(opt);
    }
    catSelect.value = state.category;
    catSelect.addEventListener("change", async () => {
      state.category = catSelect.value;
      catSelect.disabled = true;
      try { await loadCatalog(); } catch (err) { ctx.toast("Filter failed: " + err.message, "danger"); }
      catSelect.disabled = false;
      showBrowseList();
    });
    toolbar.appendChild(catSelect);

    const vendorSelect = document.createElement("select");
    vendorSelect.className = "chip";
    const allVendorOpt = el("option", null, "All vendors");
    allVendorOpt.value = "";
    vendorSelect.appendChild(allVendorOpt);
    for (const v of state.vendors) {
      const opt = el("option", null, `${v.vendor} (${v.count})`);
      opt.value = v.vendor;
      vendorSelect.appendChild(opt);
    }
    vendorSelect.value = state.vendor;
    vendorSelect.addEventListener("change", async () => {
      state.vendor = vendorSelect.value;
      vendorSelect.disabled = true;
      try { await loadCatalog(); } catch (err) { ctx.toast("Filter failed: " + err.message, "danger"); }
      vendorSelect.disabled = false;
      showBrowseList();
    });
    toolbar.appendChild(vendorSelect);

    container.appendChild(toolbar);

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = "<thead><tr><th>Product</th><th>Vendor</th><th>Catalog #</th><th>Pack size</th><th class=\"right\">List price</th><th>Availability</th><th>Group</th></tr></thead>";
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    scroll.appendChild(table);
    tableWrap.appendChild(scroll);
    const tableFooter = el("div");
    tableFooter.style.padding = "8px 12px";
    tableWrap.appendChild(tableFooter);
    container.appendChild(tableWrap);

    function buildRow(r) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, r.product_name));
      tr.appendChild(el("td", "muted", r.vendor || "--"));
      tr.appendChild(el("td", "mono", r.catalog_number || "--"));
      tr.appendChild(el("td", "muted", r.pack_size || "--"));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(r.list_price)));
      const availTd = document.createElement("td");
      availTd.appendChild(availabilityBadge(r.availability));
      tr.appendChild(availTd);
      tr.appendChild(el("td", "muted", r.group_name || "--"));
      tr.addEventListener("click", () => showCatalogDetail(r.id));
      return tr;
    }

    function drawTable() {
      tbody.innerHTML = "";
      tableFooter.innerHTML = "";
      if (!state.rows.length) {
        const tr = document.createElement("tr");
        const td = el("td", "muted", "No catalog items match this filter.");
        td.colSpan = 7;
        td.style.textAlign = "center";
        td.style.padding = "28px";
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      // The vendor catalog can hold thousands of products -- render in pages.
      ctx.windowedList(state.rows, buildRow, { host: tbody, footer: tableFooter, pageSize: 100 });
    }
    drawTable();
  }

  // ---- catalog item detail --------------------------------------------------
  async function showCatalogDetail(catalogId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to catalog");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showBrowseList);
    container.appendChild(back);

    let row;
    try {
      row = await ctx.api.get("/api/catalog/" + catalogId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load catalog item: " + err.message));
      return;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(300px, 1fr))";
    container.appendChild(grid);

    // summary card
    const summary = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", row.product_name);
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    titleRow.appendChild(availabilityBadge(row.availability));
    summary.appendChild(titleRow);

    const meta = el("div", "muted");
    meta.style.margin = "6px 0 10px";
    meta.textContent = `${row.vendor || "Unknown vendor"} · catalog # ${row.catalog_number || "--"} · ${row.pack_size || "--"} · ${ctx.fmt.money(row.list_price)}`;
    summary.appendChild(meta);

    if (row.category) {
      const catRow = el("div", "muted");
      catRow.style.marginBottom = "6px";
      catRow.textContent = "Category: " + row.category;
      summary.appendChild(catRow);
    }
    if (row.group_name) {
      const grpRow = el("div", "muted");
      grpRow.style.marginBottom = "6px";
      grpRow.textContent = "Substitute group: " + row.group_name;
      summary.appendChild(grpRow);
    }
    if (row.cas_number) {
      const casRow = el("div", "muted");
      casRow.style.marginBottom = "6px";
      casRow.textContent = "CAS #: " + row.cas_number;
      summary.appendChild(casRow);
    }
    if (row.hazard_class) {
      const hazRow = el("div");
      hazRow.style.marginBottom = "6px";
      hazRow.appendChild(el("span", "badge badge-warn", row.hazard_class));
      summary.appendChild(hazRow);
    }

    const linkRow = el("div");
    linkRow.style.display = "flex";
    linkRow.style.gap = "12px";
    linkRow.style.margin = "8px 0";
    if (row.sds_url) linkRow.appendChild(docLink("SDS", row.sds_url));
    else linkRow.appendChild(el("span", "muted", "no SDS"));
    if (row.product_url) linkRow.appendChild(docLink("Product page", row.product_url));
    summary.appendChild(linkRow);

    // manager: inline availability edit
    if (canManage) {
      const availRow = el("div");
      availRow.style.display = "flex";
      availRow.style.gap = "8px";
      availRow.style.alignItems = "center";
      availRow.style.margin = "10px 0";
      availRow.appendChild(el("label", "muted", "Availability:"));
      const availSel = document.createElement("select");
      availSel.className = "chip";
      for (const opt of ["in_stock", "backorder", "discontinued"]) {
        const o = el("option", null, opt.replace("_", " "));
        o.value = opt;
        availSel.appendChild(o);
      }
      availSel.value = row.availability;
      availSel.addEventListener("change", async () => {
        availSel.disabled = true;
        try {
          await ctx.api.patch("/api/catalog/" + catalogId, { availability: availSel.value });
          ctx.toast("Availability updated", "ok");
          showCatalogDetail(catalogId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          availSel.disabled = false;
        }
      });
      availRow.appendChild(availSel);
      summary.appendChild(availRow);
    }

    // manager: add to inventory
    if (canManage) {
      const addWrap = el("div");
      addWrap.style.marginTop = "12px";
      addWrap.style.paddingTop = "12px";
      addWrap.style.borderTop = "1px solid var(--border, #ccc)";

      const addBtn = el("button", "btn btn-primary btn-sm", "Add to inventory");
      const form = el("div");
      form.hidden = true;
      form.style.marginTop = "10px";
      form.style.display = "flex";
      form.style.flexWrap = "wrap";
      form.style.gap = "8px";
      form.style.alignItems = "flex-end";

      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "0";
      qtyInput.value = "0";
      const reorderInput = document.createElement("input");
      reorderInput.type = "number";
      reorderInput.min = "0";
      reorderInput.value = "0";

      form.append(field("Starting quantity", qtyInput), field("Reorder point", reorderInput));

      const confirmBtn = el("button", "btn btn-primary btn-sm", "Create item");
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        try {
          const created = await ctx.api.post("/api/catalog/" + catalogId + "/add-to-inventory", {
            quantity: Number(qtyInput.value) || 0,
            reorder_threshold: Number(reorderInput.value) || 0,
          });
          ctx.toast("Added to inventory: " + (created.item_name || "item"), "ok");
          const goBtn = el("button", "btn btn-ghost btn-sm", "View in inventory →");
          goBtn.addEventListener("click", () => ctx.navigate("inventory", { focusItem: created.item_id }));
          form.hidden = true;
          addWrap.appendChild(goBtn);
        } catch (err) {
          ctx.toast("Add to inventory failed: " + err.message, "danger");
          confirmBtn.disabled = false;
        }
      });
      form.appendChild(confirmBtn);

      addBtn.addEventListener("click", () => { form.hidden = !form.hidden; });
      addWrap.append(addBtn, form);
      summary.appendChild(addWrap);
    }

    grid.appendChild(summary);

    // substitutes panel -- sibling members for price comparison
    const subsCard = el("div", "card");
    subsCard.appendChild(el("div", "card-title", "Substitutes"));
    const siblings = row.siblings || [];
    if (!siblings.length) {
      subsCard.appendChild(el("div", "muted", row.group_name ? "No other members in this substitute group." : "Not part of a substitute group."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = "<thead><tr><th>Product</th><th>Vendor</th><th class=\"right\">Price</th><th>Availability</th></tr></thead>";
      const tb = document.createElement("tbody");
      for (const sib of siblings) {
        const tr = el("tr", "row-link");
        tr.appendChild(el("td", null, sib.product_name));
        tr.appendChild(el("td", "muted", sib.vendor || "--"));
        tr.appendChild(el("td", "right mono", ctx.fmt.money(sib.list_price)));
        const av = document.createElement("td");
        av.appendChild(availabilityBadge(sib.availability));
        tr.appendChild(av);
        tr.addEventListener("click", () => showCatalogDetail(sib.id));
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      subsCard.appendChild(scroll);
    }
    grid.appendChild(subsCard);
  }

  // =========================================================================
  // SUBSTITUTE GROUPS
  // =========================================================================
  async function showGroupsList() {
    container.innerHTML = "";
    const loading = el("div", "muted", "Loading substitute groups...");
    container.appendChild(loading);

    let groups;
    try {
      groups = await ctx.api.get("/api/substitute-groups");
    } catch (err) {
      container.innerHTML = "";
      container.appendChild(el("div", "empty-state", "Could not load substitute groups: " + err.message));
      return;
    }
    container.innerHTML = "";

    if (canManage) {
      const toolbar = el("div", "card");
      toolbar.style.display = "flex";
      toolbar.style.justifyContent = "flex-end";
      toolbar.style.marginBottom = "16px";
      const addBtn = el("button", "btn btn-primary btn-sm", "+ New group");
      const formHost = el("div");
      addBtn.addEventListener("click", () => {
        if (formHost.firstChild) { formHost.innerHTML = ""; return; }
        const nameInput = document.createElement("input");
        nameInput.placeholder = "Group name";
        const descInput = document.createElement("input");
        descInput.placeholder = "Description (optional)";
        const catInput = document.createElement("input");
        catInput.placeholder = "Category (optional)";
        const row = el("div");
        row.style.display = "flex";
        row.style.flexWrap = "wrap";
        row.style.gap = "8px";
        row.style.alignItems = "flex-end";
        row.append(field("Name", nameInput), field("Category", catInput), field("Description", descInput));
        const createBtn = el("button", "btn btn-primary btn-sm", "Create");
        createBtn.addEventListener("click", async () => {
          const name = nameInput.value.trim();
          if (!name) { ctx.toast("Group name is required", "warn"); return; }
          createBtn.disabled = true;
          try {
            await ctx.api.post("/api/substitute-groups", {
              name,
              category: catInput.value.trim() || null,
              description: descInput.value.trim() || null,
            });
            ctx.toast("Substitute group created", "ok");
            showGroupsList();
          } catch (err) {
            ctx.toast("Create failed: " + err.message, "danger");
            createBtn.disabled = false;
          }
        });
        row.appendChild(createBtn);
        formHost.appendChild(row);
      });
      toolbar.append(formHost, addBtn);
      container.appendChild(toolbar);
    }

    if (!groups.length) {
      container.appendChild(el("div", "empty-state", "No substitute groups yet."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = "<thead><tr><th>Name</th><th class=\"right\">Members</th><th>Preferred vendor</th><th class=\"right\">Preferred price</th><th class=\"right\">In stock</th></tr></thead>";
    const tb = document.createElement("tbody");
    for (const g of groups) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, g.name));
      tr.appendChild(el("td", "right mono", String(g.member_count)));
      tr.appendChild(el("td", "muted", g.preferred ? g.preferred.vendor : "--"));
      tr.appendChild(el("td", "right mono", g.preferred ? ctx.fmt.money(g.preferred.list_price) : "--"));
      const stockTd = el("td", "right mono", String(g.in_stock_count));
      if (g.in_stock_count === 0) stockTd.style.color = "var(--danger)";
      tr.appendChild(stockTd);
      tr.addEventListener("click", () => showGroupDetail(g.id));
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  async function showGroupDetail(groupId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to substitute groups");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showGroupsList);
    container.appendChild(back);

    let group;
    try {
      group = await ctx.api.get("/api/substitute-groups/" + groupId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load group: " + err.message));
      return;
    }

    const headerCard = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", group.name);
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    if (group.category) titleRow.appendChild(el("span", "badge", group.category));
    headerCard.appendChild(titleRow);
    if (group.description) headerCard.appendChild(el("div", "muted", group.description));

    if (canManage) {
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete group");
      delBtn.style.marginTop = "10px";
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Delete substitute group "${group.name}"? Members will be unlinked, not deleted.`)) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/substitute-groups/" + groupId);
          ctx.toast("Substitute group deleted", "ok");
          showGroupsList();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      headerCard.appendChild(delBtn);
    }
    container.appendChild(headerCard);

    const membersCard = el("div", "card");
    membersCard.style.marginTop = "16px";
    membersCard.appendChild(el("div", "card-title", "Members"));
    const members = group.members || [];
    if (!members.length) {
      membersCard.appendChild(el("div", "muted", "No members in this group yet."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      const headCells = "<th>Product</th><th>Vendor</th><th class=\"right\">Price</th><th>Availability</th><th class=\"right\">Preference rank</th>" + (canManage ? "<th></th>" : "");
      t.innerHTML = "<thead><tr>" + headCells + "</tr></thead>";
      const tb = document.createElement("tbody");
      for (const m of members) {
        const tr = document.createElement("tr");
        const nameTd = el("td", null, m.product_name);
        if (m.id === group.preferred_catalog_id) {
          nameTd.appendChild(document.createTextNode(" "));
          nameTd.appendChild(el("span", "badge badge-ok", "preferred"));
        }
        tr.appendChild(nameTd);
        tr.appendChild(el("td", "muted", m.vendor || "--"));
        tr.appendChild(el("td", "right mono", ctx.fmt.money(m.list_price)));
        if (canManage) {
          const availTd = document.createElement("td");
          const availSel = document.createElement("select");
          availSel.className = "chip";
          for (const opt of ["in_stock", "backorder", "discontinued"]) {
            const o = el("option", null, opt.replace("_", " "));
            o.value = opt;
            availSel.appendChild(o);
          }
          availSel.value = m.availability;
          availSel.addEventListener("change", async () => {
            availSel.disabled = true;
            try {
              await ctx.api.patch("/api/catalog/" + m.id, { availability: availSel.value });
              ctx.toast("Availability updated", "ok");
              showGroupDetail(groupId);
            } catch (err) {
              ctx.toast("Update failed: " + err.message, "danger");
              availSel.disabled = false;
            }
          });
          availTd.appendChild(availSel);
          tr.appendChild(availTd);

          const rankTd = document.createElement("td");
          rankTd.className = "right";
          const rankInput = document.createElement("input");
          rankInput.type = "number";
          rankInput.className = "chip";
          rankInput.style.width = "70px";
          rankInput.value = m.preference_rank != null ? String(m.preference_rank) : "";
          rankInput.addEventListener("change", async () => {
            const val = rankInput.value.trim();
            rankInput.disabled = true;
            try {
              await ctx.api.post(`/api/substitute-groups/${groupId}/members`, {
                catalog_id: m.id,
                preference_rank: val === "" ? null : Number(val),
              });
              ctx.toast("Preference rank updated", "ok");
              showGroupDetail(groupId);
            } catch (err) {
              ctx.toast("Update failed: " + err.message, "danger");
              rankInput.disabled = false;
            }
          });
          rankTd.appendChild(rankInput);
          tr.appendChild(rankTd);

          const actionTd = document.createElement("td");
          const removeBtn = el("button", "btn btn-ghost btn-sm", "Remove");
          removeBtn.addEventListener("click", async () => {
            removeBtn.disabled = true;
            try {
              await ctx.api.del(`/api/substitute-groups/${groupId}/members/${m.id}`);
              ctx.toast("Removed from group", "ok");
              showGroupDetail(groupId);
            } catch (err) {
              ctx.toast("Remove failed: " + err.message, "danger");
              removeBtn.disabled = false;
            }
          });
          actionTd.appendChild(removeBtn);
          tr.appendChild(actionTd);
        } else {
          const availTd = document.createElement("td");
          availTd.appendChild(availabilityBadge(m.availability));
          tr.appendChild(availTd);
          tr.appendChild(el("td", "right muted", m.preference_rank != null ? String(m.preference_rank) : "--"));
        }
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      membersCard.appendChild(scroll);
    }
    container.appendChild(membersCard);

    if (canManage) {
      const addCard = el("div", "card");
      addCard.style.marginTop = "16px";
      addCard.appendChild(el("div", "card-title", "Add a member"));
      addCard.appendChild(el("div", "muted", "Search the catalog and add a matching product to this group."));

      const searchRow = el("div");
      searchRow.style.display = "flex";
      searchRow.style.gap = "8px";
      searchRow.style.margin = "10px 0";
      const searchInput = document.createElement("input");
      searchInput.className = "chip";
      searchInput.placeholder = "Search product / catalog # / vendor...";
      searchInput.style.flex = "1 1 auto";
      const searchBtn = el("button", "btn btn-ghost btn-sm", "Search");
      searchRow.append(searchInput, searchBtn);
      addCard.appendChild(searchRow);

      const resultsHost = el("div");
      addCard.appendChild(resultsHost);

      async function runSearch() {
        const q = searchInput.value.trim();
        resultsHost.innerHTML = "";
        if (!q) return;
        let results;
        try {
          results = await ctx.api.get("/api/catalog?q=" + encodeURIComponent(q));
        } catch (err) {
          resultsHost.appendChild(el("div", "muted", "Search failed: " + err.message));
          return;
        }
        const currentIds = new Set(members.map((m) => m.id));
        results = results.filter((r) => !currentIds.has(r.id));
        if (!results.length) {
          resultsHost.appendChild(el("div", "muted", "No matching catalog items."));
          return;
        }
        const scroll = el("div", "table-scroll");
        const t = document.createElement("table");
        t.className = "table";
        t.innerHTML = "<thead><tr><th>Product</th><th>Vendor</th><th class=\"right\">Price</th><th></th></tr></thead>";
        const tb = document.createElement("tbody");
        for (const r of results) {
          const tr = document.createElement("tr");
          tr.appendChild(el("td", null, r.product_name));
          tr.appendChild(el("td", "muted", r.vendor || "--"));
          tr.appendChild(el("td", "right mono", ctx.fmt.money(r.list_price)));
          const actionTd = document.createElement("td");
          const addBtn = el("button", "btn btn-primary btn-sm", "Add");
          addBtn.addEventListener("click", async () => {
            addBtn.disabled = true;
            try {
              await ctx.api.post(`/api/substitute-groups/${groupId}/members`, { catalog_id: r.id });
              ctx.toast("Added to group", "ok");
              showGroupDetail(groupId);
            } catch (err) {
              ctx.toast("Add failed: " + err.message, "danger");
              addBtn.disabled = false;
            }
          });
          actionTd.appendChild(addBtn);
          tr.appendChild(actionTd);
          tb.appendChild(tr);
        }
        t.appendChild(tb);
        scroll.appendChild(t);
        resultsHost.appendChild(scroll);
      }
      searchBtn.addEventListener("click", runSearch);
      searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });
      container.appendChild(addCard);
    }
  }
}
