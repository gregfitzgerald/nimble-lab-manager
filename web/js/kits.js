// kits.js -- kit (BOM) list, detail with assemble action, and manager CRUD.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "kits", label: "Kits", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && ["manager", "admin"].includes(ctx.user.role));
  const state = { kits: [], items: [] };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Kits"));
  head.appendChild(el("p", "view-sub", "Bills of materials -- assemble a kit from component stock, optionally producing an output item."));
  root.appendChild(head);

  const container = el("div");
  root.appendChild(container);

  async function loadKits() {
    state.kits = await ctx.api.get("/api/kits");
  }
  async function loadItems() {
    if (state.items.length) return;
    state.items = await ctx.api.get("/api/items");
  }

  try {
    await loadKits();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load kits: " + err.message));
    return;
  }

  const focusId = params && params.kitId;
  if (focusId != null) {
    await showDetail(Number(focusId));
  } else {
    showList();
  }

  // ---- list view ------------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.justifyContent = "space-between";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "12px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search kits...";
    searchInput.style.minWidth = "200px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ New kit");
      addBtn.addEventListener("click", () => openKitForm(null));
      toolbar.appendChild(addBtn);
    }
    container.appendChild(toolbar);

    const formHost = el("div");
    container.appendChild(formHost);
    formHost.id = "kitFormHost";

    // Client-side search over the already-loaded kits.
    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = 4;
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

    if (!state.kits.length) {
      container.appendChild(el("div", "empty-state", "No kits defined yet."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = "<thead><tr><th>Name</th><th class=\"right\">Components</th><th>Output</th><th class=\"right\">Total cost</th></tr></thead>";
    const tb = document.createElement("tbody");
    for (const k of state.kits) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, k.name));
      tr.appendChild(el("td", "right mono", String(k.line_count)));
      tr.appendChild(el("td", "muted", k.output_item_name || "--"));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(k.total_cost)));
      tr.addEventListener("click", () => showDetail(k.id));
      tr._haystack = [k.name, k.description, k.output_item_name]
        .filter(Boolean).join(" ").toLowerCase();
      dataRows.push(tr);
      tb.appendChild(tr);
    }
    tb.appendChild(noMatchRow);
    t.appendChild(tb);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  // ---- detail view ------------------------------------------------------------
  async function showDetail(kitId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to kits");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/kits/" + kitId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load kit: " + err.message));
      return;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(320px, 1fr))";
    container.appendChild(grid);

    // summary card
    const summary = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", data.name);
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => openKitForm(data));
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete kit \"" + data.name + "\"?")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/kits/" + kitId);
          ctx.toast("Kit deleted", "ok");
          try { await loadKits(); } catch (_) { /* best-effort */ }
          showList();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.append(editBtn, delBtn);
    }
    summary.appendChild(titleRow);

    if (data.description) {
      summary.appendChild(el("div", "muted", data.description));
    }

    if (data.output_item_id) {
      const producesRow = el("div");
      producesRow.style.margin = "8px 0";
      producesRow.textContent = "Produces: " + (data.output_item_name || ("item #" + data.output_item_id)) + " x" + data.output_qty;
      summary.appendChild(producesRow);
    }

    const maxRow = el("div");
    maxRow.style.margin = "10px 0";
    maxRow.style.fontWeight = "600";
    const maxVal = el("span", null, String(data.max_assemblies));
    if (data.max_assemblies === 0) maxVal.style.color = "var(--danger, red)";
    maxRow.appendChild(document.createTextNode("Max assemblies with current stock: "));
    maxRow.appendChild(maxVal);
    summary.appendChild(maxRow);

    // assemble control
    const assembleRow = el("div");
    assembleRow.style.display = "flex";
    assembleRow.style.gap = "8px";
    assembleRow.style.alignItems = "center";
    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "1";
    countInput.max = String(Math.max(data.max_assemblies, 1));
    countInput.value = "1";
    countInput.className = "chip";
    countInput.style.width = "84px";
    const assembleBtn = el("button", "btn btn-primary btn-sm", "Assemble");
    assembleBtn.style.flex = "1 1 auto";
    if (data.max_assemblies <= 0) assembleBtn.disabled = true;
    assembleBtn.addEventListener("click", async () => {
      const count = parseInt(countInput.value, 10);
      if (!count || count <= 0) { ctx.toast("Enter a positive count", "warn"); return; }
      assembleBtn.disabled = true;
      try {
        const res = await ctx.api.post("/api/kits/" + kitId + "/assemble", { count });
        const consumedText = (res.consumed || [])
          .map((c) => `${c.qty} ${c.item_name}`)
          .join(", ");
        let msg = "Assembled " + count + "x " + data.name + (consumedText ? " (consumed " + consumedText + ")" : "");
        if (res.produced) msg += "; produced " + res.produced.qty + " " + res.produced.item_name;
        ctx.toast(msg, "ok");
        try { await loadKits(); } catch (_) { /* best-effort */ }
        showDetail(kitId);
      } catch (err) {
        ctx.toast("Assemble failed: " + err.message, "danger");
        assembleBtn.disabled = false;
      }
    });
    assembleRow.append(countInput, assembleBtn);
    summary.appendChild(assembleRow);
    grid.appendChild(summary);

    // components card
    const compCard = el("div", "card");
    compCard.appendChild(el("div", "card-title", "Components"));
    if (!data.lines || !data.lines.length) {
      compCard.appendChild(el("div", "muted", "No components defined."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = "<thead><tr><th>Item</th><th class=\"right\">Qty needed</th><th class=\"right\">On hand</th><th class=\"right\">Unit cost</th></tr></thead>";
      const tb = document.createElement("tbody");
      for (const line of data.lines) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, line.item_name));
        tr.appendChild(el("td", "right mono", String(line.quantity)));
        const onHandTd = el("td", "right mono", String(line.on_hand));
        if (line.on_hand < line.quantity) onHandTd.style.color = "var(--danger, red)";
        tr.appendChild(onHandTd);
        tr.appendChild(el("td", "right mono", ctx.fmt.money(line.unit_cost)));
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      compCard.appendChild(scroll);
    }
    const totalRow = el("div");
    totalRow.style.marginTop = "10px";
    totalRow.style.fontWeight = "600";
    totalRow.textContent = "Total cost: " + ctx.fmt.money(data.total_cost);
    compCard.appendChild(totalRow);
    grid.appendChild(compCard);
  }

  // ---- manager: new/edit kit form --------------------------------------------
  async function openKitForm(existing) {
    try {
      await loadItems();
    } catch (err) {
      ctx.toast("Could not load items: " + err.message, "danger");
      return;
    }

    const isEdit = !!existing;
    const backdrop = el("div", "card");
    backdrop.style.marginBottom = "16px";
    backdrop.appendChild(el("div", "card-title", isEdit ? "Edit kit" : "New kit"));

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
    nameInput.placeholder = "Kit name";
    nameInput.value = isEdit ? existing.name : "";

    const outputSel = document.createElement("select");
    outputSel.className = "chip";
    const noneOpt = el("option", null, "(none)");
    noneOpt.value = "";
    outputSel.appendChild(noneOpt);
    for (const it of state.items) {
      const opt = el("option", null, it.item_name);
      opt.value = String(it.item_id);
      outputSel.appendChild(opt);
    }
    if (isEdit && existing.output_item_id) outputSel.value = String(existing.output_item_id);

    const outputQtyInput = document.createElement("input");
    outputQtyInput.type = "number";
    outputQtyInput.min = "1";
    outputQtyInput.className = "chip";
    outputQtyInput.value = isEdit && existing.output_qty ? String(existing.output_qty) : "1";

    gridForm.append(
      field("Kit name *", nameInput),
      field("Output item (optional)", outputSel),
      field("Output qty", outputQtyInput),
    );
    backdrop.appendChild(gridForm);

    const descInput = document.createElement("textarea");
    descInput.className = "chip";
    descInput.rows = 2;
    descInput.style.width = "100%";
    descInput.style.marginTop = "10px";
    descInput.placeholder = "Description";
    descInput.value = isEdit ? (existing.description || "") : "";
    const descWrap = el("div");
    descWrap.style.display = "flex";
    descWrap.style.flexDirection = "column";
    descWrap.style.gap = "3px";
    descWrap.appendChild(el("label", "muted", "Description"));
    descWrap.appendChild(descInput);
    backdrop.appendChild(descWrap);

    // component line rows
    const linesTitle = el("div", "muted");
    linesTitle.style.marginTop = "14px";
    linesTitle.textContent = "Components";
    backdrop.appendChild(linesTitle);

    const linesHost = el("div");
    linesHost.style.display = "flex";
    linesHost.style.flexDirection = "column";
    linesHost.style.gap = "8px";
    linesHost.style.marginTop = "8px";
    backdrop.appendChild(linesHost);

    function addLineRow(itemId, qty) {
      const row = el("div");
      row.style.display = "flex";
      row.style.gap = "8px";
      row.style.alignItems = "center";

      const itemSel = document.createElement("select");
      itemSel.className = "chip";
      itemSel.style.flex = "1 1 220px";
      for (const it of state.items) {
        const opt = el("option", null, it.item_name);
        opt.value = String(it.item_id);
        itemSel.appendChild(opt);
      }
      if (itemId != null) itemSel.value = String(itemId);

      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "1";
      qtyInput.className = "chip";
      qtyInput.style.width = "90px";
      qtyInput.value = qty != null ? String(qty) : "1";

      const removeBtn = el("button", "btn btn-ghost btn-sm", "Remove");
      removeBtn.addEventListener("click", () => row.remove());

      row.append(itemSel, qtyInput, removeBtn);
      row._itemSel = itemSel;
      row._qtyInput = qtyInput;
      linesHost.appendChild(row);
    }

    if (isEdit && existing.lines && existing.lines.length) {
      for (const line of existing.lines) addLineRow(line.item_id, line.quantity);
    } else {
      addLineRow(state.items[0] && state.items[0].item_id, 1);
    }

    const addLineBtn = el("button", "btn btn-ghost btn-sm", "+ Add component");
    addLineBtn.style.marginTop = "8px";
    addLineBtn.addEventListener("click", () => addLineRow(state.items[0] && state.items[0].item_id, 1));
    backdrop.appendChild(addLineBtn);

    const btnRow = el("div");
    btnRow.style.display = "flex";
    btnRow.style.gap = "8px";
    btnRow.style.marginTop = "14px";
    const submit = el("button", "btn btn-primary btn-sm", isEdit ? "Save kit" : "Create kit");
    const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
    cancel.addEventListener("click", () => { formHost.innerHTML = ""; });
    submit.addEventListener("click", async () => {
      const name = nameInput.value.trim();
      if (!name) { ctx.toast("Kit name is required", "warn"); nameInput.focus(); return; }
      const lines = [];
      for (const row of Array.from(linesHost.children)) {
        const itemId = Number(row._itemSel.value);
        const qty = Number(row._qtyInput.value);
        if (!itemId || !qty || qty <= 0) continue;
        lines.push({ item_id: itemId, quantity: qty });
      }
      if (!lines.length) { ctx.toast("Add at least one component", "warn"); return; }
      const body = {
        name,
        description: descInput.value.trim() || null,
        output_item_id: outputSel.value ? Number(outputSel.value) : null,
        output_qty: outputSel.value ? (Number(outputQtyInput.value) || 1) : null,
        lines,
      };
      submit.disabled = true;
      try {
        if (isEdit) {
          await ctx.api.patch("/api/kits/" + existing.id, body);
          ctx.toast("Kit updated", "ok");
        } else {
          await ctx.api.post("/api/kits", body);
          ctx.toast("Kit created", "ok");
        }
        formHost.innerHTML = "";
        try { await loadKits(); } catch (_) { /* best-effort */ }
        if (isEdit) showDetail(existing.id);
        else showList();
      } catch (err) {
        ctx.toast((isEdit ? "Update" : "Create") + " failed: " + err.message, "danger");
        submit.disabled = false;
      }
    });
    btnRow.append(submit, cancel);
    backdrop.appendChild(btnRow);

    const formHost = container.querySelector("#kitFormHost") || (() => {
      // On detail view there is no formHost; render list first.
      showList();
      return container.querySelector("#kitFormHost");
    })();
    formHost.innerHTML = "";
    formHost.appendChild(backdrop);
    nameInput.focus();
  }
}
