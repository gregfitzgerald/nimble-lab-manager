// preparations.js -- recipe (BOM) list for lab preparations with dated, expiring
// batches: list, detail with "make a batch" + batch status actions, and manager CRUD.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "preparations", label: "Preparations", minRole: "member" };

const CATEGORIES = ["buffer", "fixative", "media", "other"];

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

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = !!(ctx.user && ["manager", "admin"].includes(ctx.user.role));
  const state = { preps: [], items: [] };

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Preparations"));
  head.appendChild(el("p", "view-sub", "Recipes for buffers, fixatives, and media -- make a dated batch from component stock and track it to expiry or use."));
  root.appendChild(head);

  const container = el("div");
  root.appendChild(container);

  async function loadPreps() {
    state.preps = await ctx.api.get("/api/preparations");
  }
  async function loadItems() {
    if (state.items.length) return;
    state.items = await ctx.api.get("/api/items");
  }

  try {
    await loadPreps();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load preparations: " + err.message));
    return;
  }

  const focusId = params && params.prepId;
  if (focusId != null) {
    await showDetail(Number(focusId));
  } else {
    showList();
    // Global "+ New" quick-create opens the add-preparation form (manager+).
    if (params && params.create && canManage) {
      const addBtn = document.getElementById("prep-add-btn");
      if (addBtn) addBtn.click();
    }
  }

  // ---- list view ------------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    if (canManage) {
      const toolbar = el("div");
      toolbar.style.display = "flex";
      toolbar.style.justifyContent = "flex-end";
      toolbar.style.marginBottom = "12px";
      const addBtn = el("button", "btn btn-primary btn-sm", "+ New preparation");
      addBtn.id = "prep-add-btn";
      addBtn.addEventListener("click", () => openPrepForm(null));
      toolbar.appendChild(addBtn);
      container.appendChild(toolbar);
    }

    const formHost = el("div");
    container.appendChild(formHost);
    formHost.id = "prepFormHost";

    if (!state.preps.length) {
      container.appendChild(el("div", "empty-state", "No preparations defined yet."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = "<thead><tr><th>Name</th><th>Category</th><th class=\"right\">Components</th><th class=\"right\">Active batches</th><th>Soonest expiry</th></tr></thead>";
    const tb = document.createElement("tbody");
    for (const p of state.preps) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, p.name));
      tr.appendChild(el("td", "muted", p.category || "--"));
      tr.appendChild(el("td", "right mono", String(p.line_count)));
      tr.appendChild(el("td", "right mono", String(p.batches_active)));
      const expTd = document.createElement("td");
      if (p.next_batch_expiry) {
        const today = new Date().toISOString().slice(0, 10);
        const span = el("span", null, ctx.fmt.date(p.next_batch_expiry));
        if (p.next_batch_expiry < today) span.style.color = "var(--danger, red)";
        else {
          const in30 = new Date();
          in30.setDate(in30.getDate() + 30);
          if (p.next_batch_expiry <= in30.toISOString().slice(0, 10)) span.style.color = "var(--warn, #b8860b)";
        }
        expTd.appendChild(span);
      } else {
        expTd.className = "muted";
        expTd.textContent = "--";
      }
      tr.appendChild(expTd);
      tr.addEventListener("click", () => showDetail(p.id));
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  // ---- detail view ------------------------------------------------------------
  async function showDetail(prepId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to preparations");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/preparations/" + prepId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load preparation: " + err.message));
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
    if (data.category) titleRow.appendChild(el("span", "badge", data.category));
    if (canManage) {
      const editBtn = el("button", "btn btn-ghost btn-sm", "Edit");
      editBtn.addEventListener("click", () => openPrepForm(data));
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete preparation \"" + data.name + "\"?")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/preparations/" + prepId);
          ctx.toast("Preparation deleted", "ok");
          try { await loadPreps(); } catch (_) { /* best-effort */ }
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
    if (data.shelf_life_days) {
      const shelfRow = el("div", "muted");
      shelfRow.style.margin = "6px 0";
      shelfRow.textContent = "Shelf life: " + data.shelf_life_days + " days";
      summary.appendChild(shelfRow);
    }
    if (data.sop_url) {
      const sopRow = el("div");
      sopRow.style.margin = "6px 0";
      const a = el("a", null, "Lab-approved SOP for making this");
      a.href = data.sop_url;
      a.target = "_blank";
      a.rel = "noopener";
      sopRow.appendChild(a);
      summary.appendChild(sopRow);
    }

    const maxRow = el("div");
    maxRow.style.margin = "10px 0";
    maxRow.style.fontWeight = "600";
    const maxVal = el("span", null, String(data.max_batches));
    if (data.max_batches === 0) maxVal.style.color = "var(--danger, red)";
    maxRow.appendChild(document.createTextNode("Max batches with current stock: "));
    maxRow.appendChild(maxVal);
    summary.appendChild(maxRow);

    // make-a-batch form
    const makeForm = el("div");
    makeForm.style.display = "flex";
    makeForm.style.flexDirection = "column";
    makeForm.style.gap = "8px";
    makeForm.style.marginTop = "10px";
    makeForm.appendChild(el("div", "muted", "Make a batch"));

    const makeRow = el("div");
    makeRow.style.display = "flex";
    makeRow.style.flexWrap = "wrap";
    makeRow.style.gap = "8px";
    const amountInput = document.createElement("input");
    amountInput.type = "text";
    amountInput.className = "chip";
    amountInput.placeholder = "Amount (e.g. 1 L)";
    amountInput.style.flex = "1 1 130px";
    const lotInput = document.createElement("input");
    lotInput.type = "text";
    lotInput.className = "chip";
    lotInput.placeholder = "Lot label (optional)";
    lotInput.style.flex = "1 1 140px";
    const expiryInput = document.createElement("input");
    expiryInput.type = "date";
    expiryInput.className = "chip";
    expiryInput.title = "Expiry date (optional)";
    expiryInput.style.flex = "1 1 140px";
    makeRow.append(amountInput, lotInput, expiryInput);
    makeForm.appendChild(makeRow);
    const expiryNote = el("div", "muted", "Expiry defaults to shelf life if left blank.");
    makeForm.appendChild(expiryNote);

    const makeBtn = el("button", "btn btn-primary btn-sm", "Make batch");
    if (data.max_batches <= 0) makeBtn.disabled = true;
    makeBtn.addEventListener("click", async () => {
      const body = {};
      if (amountInput.value.trim()) body.amount = amountInput.value.trim();
      if (lotInput.value.trim()) body.lot_label = lotInput.value.trim();
      if (expiryInput.value) body.expiry_date = expiryInput.value;
      makeBtn.disabled = true;
      try {
        await ctx.api.post("/api/preparations/" + prepId + "/make-batch", body);
        ctx.toast("Batch made", "ok");
        try { await loadPreps(); } catch (_) { /* best-effort */ }
        showDetail(prepId);
      } catch (err) {
        ctx.toast("Make batch failed: " + err.message, "danger");
        makeBtn.disabled = false;
      }
    });
    makeForm.appendChild(makeBtn);
    summary.appendChild(makeForm);
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
      t.innerHTML = "<thead><tr><th>Item</th><th class=\"right\">Qty needed</th><th class=\"right\">On hand</th></tr></thead>";
      const tb = document.createElement("tbody");
      for (const line of data.lines) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, line.item_name + (line.unit ? " (" + line.unit + ")" : "")));
        tr.appendChild(el("td", "right mono", String(line.quantity)));
        const onHandTd = el("td", "right mono", String(line.on_hand));
        if (line.on_hand < line.quantity) onHandTd.style.color = "var(--danger, red)";
        tr.appendChild(onHandTd);
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      compCard.appendChild(scroll);
    }
    grid.appendChild(compCard);

    // batches card
    const batchCard = el("div", "card");
    batchCard.style.gridColumn = "1 / -1";
    batchCard.appendChild(el("div", "card-title", "Batches"));
    if (!data.batches || !data.batches.length) {
      batchCard.appendChild(el("div", "muted", "No batches made yet."));
    } else {
      const scroll = el("div", "table-scroll");
      const t = document.createElement("table");
      t.className = "table";
      t.innerHTML = "<thead><tr><th>Lot</th><th>Made by</th><th>Made at</th><th>Expiry</th><th>Amount</th><th>Status</th><th></th></tr></thead>";
      const tb = document.createElement("tbody");
      for (const b of data.batches) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", "mono", b.lot_label || "--"));
        tr.appendChild(el("td", "muted", b.made_by_username || "--"));
        tr.appendChild(el("td", "muted", b.made_at ? ctx.fmt.date(b.made_at) : "--"));
        const expTd = document.createElement("td");
        if (b.expiry_date) {
          expTd.appendChild(document.createTextNode(ctx.fmt.date(b.expiry_date) + " "));
          expTd.appendChild(expiryBadge(b.expiry_flag));
        } else {
          expTd.textContent = "--";
        }
        tr.appendChild(expTd);
        tr.appendChild(el("td", "mono", b.amount != null ? String(b.amount) : "--"));
        tr.appendChild(el("td", null, b.status));
        const actionsTd = document.createElement("td");
        actionsTd.style.display = "flex";
        actionsTd.style.gap = "6px";
        if (b.status === "in_use") {
          const useBtn = el("button", "btn btn-ghost btn-sm", "Mark used");
          useBtn.addEventListener("click", () => patchBatchStatus(b.id, "used", useBtn));
          const discardBtn = el("button", "btn btn-ghost btn-sm", "Discard");
          discardBtn.addEventListener("click", () => patchBatchStatus(b.id, "discarded", discardBtn));
          actionsTd.append(useBtn, discardBtn);
        }
        tr.appendChild(actionsTd);
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      scroll.appendChild(t);
      batchCard.appendChild(scroll);
    }
    grid.appendChild(batchCard);

    async function patchBatchStatus(batchId, status, btn) {
      btn.disabled = true;
      try {
        await ctx.api.patch("/api/preparation-batches/" + batchId, { status });
        ctx.toast("Batch updated", "ok");
        try { await loadPreps(); } catch (_) { /* best-effort */ }
        showDetail(prepId);
      } catch (err) {
        ctx.toast("Update failed: " + err.message, "danger");
        btn.disabled = false;
      }
    }
  }

  // ---- manager: new/edit preparation form --------------------------------------------
  async function openPrepForm(existing) {
    try {
      await loadItems();
    } catch (err) {
      ctx.toast("Could not load items: " + err.message, "danger");
      return;
    }

    const isEdit = !!existing;
    const backdrop = el("div", "card");
    backdrop.style.marginBottom = "16px";
    backdrop.appendChild(el("div", "card-title", isEdit ? "Edit preparation" : "New preparation"));

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
    nameInput.placeholder = "Preparation name";
    nameInput.value = isEdit ? existing.name : "";

    const catSel = document.createElement("select");
    catSel.className = "chip";
    for (const c of CATEGORIES) {
      const opt = el("option", null, c);
      opt.value = c;
      catSel.appendChild(opt);
    }
    if (isEdit && existing.category && !CATEGORIES.includes(existing.category)) {
      const opt = el("option", null, existing.category);
      opt.value = existing.category;
      catSel.appendChild(opt);
    }
    if (isEdit) catSel.value = existing.category || "other";

    const shelfInput = document.createElement("input");
    shelfInput.type = "number";
    shelfInput.min = "0";
    shelfInput.className = "chip";
    shelfInput.value = isEdit && existing.shelf_life_days != null ? String(existing.shelf_life_days) : "";
    shelfInput.placeholder = "Shelf life (days)";

    const sopInput = document.createElement("input");
    sopInput.type = "url";
    sopInput.className = "chip";
    sopInput.value = isEdit ? (existing.sop_url || "") : "";
    sopInput.placeholder = "https://.../sop.pdf";

    gridForm.append(
      field("Name *", nameInput),
      field("Category", catSel),
      field("Shelf life (days)", shelfInput),
      field("Lab-approved SOP URL", sopInput),
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
      qtyInput.min = "0.01";
      qtyInput.step = "any";
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
    const submit = el("button", "btn btn-primary btn-sm", isEdit ? "Save preparation" : "Create preparation");
    const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
    cancel.addEventListener("click", () => { formHost.innerHTML = ""; });
    submit.addEventListener("click", async () => {
      const name = nameInput.value.trim();
      if (!name) { ctx.toast("Preparation name is required", "warn"); nameInput.focus(); return; }
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
        category: catSel.value,
        shelf_life_days: shelfInput.value.trim() === "" ? null : (Number(shelfInput.value) || null),
        sop_url: sopInput.value.trim() || null,
        lines,
      };
      submit.disabled = true;
      try {
        if (isEdit) {
          await ctx.api.patch("/api/preparations/" + existing.id, body);
          ctx.toast("Preparation updated", "ok");
        } else {
          await ctx.api.post("/api/preparations", body);
          ctx.toast("Preparation created", "ok");
        }
        formHost.innerHTML = "";
        try { await loadPreps(); } catch (_) { /* best-effort */ }
        if (isEdit) showDetail(existing.id);
        else showList();
      } catch (err) {
        ctx.toast((isEdit ? "Update" : "Create") + " failed: " + err.message, "danger");
        submit.disabled = false;
      }
    });
    btnRow.append(submit, cancel);
    backdrop.appendChild(btnRow);

    const formHost = container.querySelector("#prepFormHost") || (() => {
      // On detail view there is no formHost; render list first.
      showList();
      return container.querySelector("#prepFormHost");
    })();
    formHost.innerHTML = "";
    formHost.appendChild(backdrop);
    nameInput.focus();
  }
}
