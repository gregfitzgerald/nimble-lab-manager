// purchasing.js -- purchase order list, detail, status workflow, receiving,
// document attachments, and creation.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "purchasing", label: "Purchasing", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

function statusLabel(status) {
  return String(status || "unknown").replace(/_/g, " ");
}

function statusBadge(status) {
  if (status === "received") return el("span", "badge badge-ok", "received");
  if (status === "cancelled" || status === "rejected") {
    const b = el("span", "badge badge-danger", statusLabel(status));
    b.style.opacity = "0.65";
    return b;
  }
  if (["pending_approval", "approved", "submitted", "ordered"].includes(status)) {
    return el("span", "badge badge-warn", statusLabel(status));
  }
  // draft / unknown -> neutral
  return el("span", "badge", statusLabel(status));
}

const DOC_KINDS = ["po", "invoice", "packing_slip", "other"];

// True when a PO is awaiting arrival and its expected_arrival date has passed.
function isPastDue(po) {
  if (!po || !po.expected_arrival) return false;
  if (["received", "cancelled", "rejected"].includes(po.status)) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(po.expected_arrival + "T00:00:00");
  return !isNaN(d.getTime()) && d < today;
}

// ---- render ----------------------------------------------------------------
export async function render(root, ctx, params) {
  const state = { orders: [], items: [], funds: [], settings: null };
  const canManage = ["manager", "admin"].includes(ctx.user.role);

  async function loadFunds() {
    if (state.funds.length) return;
    try {
      state.funds = await ctx.api.get("/api/funds");
    } catch (_) {
      state.funds = [];
    }
  }

  // Build a fund <select> with a blank "no fund" option; preselect selectedId.
  function buildFundSelect(selectedId) {
    const sel = document.createElement("select");
    sel.className = "chip";
    const blank = el("option", null, "-- no fund --");
    blank.value = "";
    sel.appendChild(blank);
    for (const f of state.funds) {
      const txt = f.sponsor ? f.name + " (" + f.sponsor + ")" : f.name;
      const opt = el("option", null, txt);
      opt.value = String(f.id);
      sel.appendChild(opt);
    }
    if (selectedId != null) sel.value = String(selectedId);
    return sel;
  }

  async function loadSettings() {
    try {
      state.settings = await ctx.api.get("/api/settings");
    } catch (_) {
      state.settings = null;
    }
  }

  // Inline toolbar control for the auto-approval spend threshold.
  function buildThresholdControl() {
    const wrap = el("div");
    wrap.style.display = "flex";
    wrap.style.gap = "8px";
    wrap.style.alignItems = "center";
    wrap.style.marginLeft = "auto";
    const raw = state.settings ? state.settings.po_approval_threshold : null;
    const num = raw != null && raw !== "" && !isNaN(Number(raw)) ? Number(raw) : null;

    if (ctx.user.role === "admin") {
      wrap.appendChild(el("span", "muted", "Auto-approval under"));
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "1";
      input.className = "chip";
      input.style.width = "110px";
      if (num != null) input.value = String(num);
      const saveBtn = el("button", "btn btn-ghost btn-sm", "Save");
      saveBtn.addEventListener("click", async () => {
        const v = input.value.trim();
        if (v === "" || isNaN(Number(v)) || Number(v) < 0) {
          ctx.toast("Enter a non-negative number", "warn");
          return;
        }
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/settings", { po_approval_threshold: v });
          if (state.settings) state.settings.po_approval_threshold = v;
          else state.settings = { po_approval_threshold: v };
          ctx.toast("Auto-approval threshold updated", "ok");
        } catch (err) {
          ctx.toast("Could not update threshold: " + err.message, "danger");
        } finally {
          saveBtn.disabled = false;
        }
      });
      wrap.append(input, saveBtn);
    } else {
      const label = num != null
        ? "Auto-approval under " + ctx.fmt.money(num)
        : "Auto-approval threshold not set";
      wrap.appendChild(el("span", "muted", label));
    }
    return wrap;
  }

  root.appendChild(el("h1", "view-title", "Purchasing"));
  root.appendChild(el("p", "view-sub", "Purchase orders from draft through approval, ordering, and receiving. Receiving restocks inventory automatically."));

  const container = el("div");
  root.appendChild(container);

  async function loadOrders() {
    state.orders = await ctx.api.get("/api/purchase-orders");
  }
  async function loadItems() {
    if (state.items.length) return;
    try {
      state.items = await ctx.api.get("/api/items");
    } catch (_) {
      state.items = [];
    }
  }

  try {
    await loadOrders();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load purchase orders: " + err.message));
    return;
  }
  await loadSettings();
  await loadFunds();

  const focusId = params && params.poId != null ? params.poId : null;
  if (focusId != null) {
    await showDetail(Number(focusId));
  } else {
    showList();
    // Global "+ New" quick-create: jump to the (always-present) new-PO form.
    if (params && params.create) {
      const form = document.getElementById("new-po-form");
      if (form) {
        form.scrollIntoView({ block: "center" });
        const first = form.querySelector("input, select");
        if (first) first.focus();
      }
    }
  }

  // ---- list view -----------------------------------------------------------
  function showList() {
    container.innerHTML = "";

    // Toolbar
    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.gap = "10px";
    toolbar.style.flexWrap = "wrap";
    toolbar.style.marginBottom = "14px";
    const autoBtn = el("button", "btn btn-ghost btn-sm", "Auto-draft from low stock");
    autoBtn.addEventListener("click", async () => {
      autoBtn.disabled = true;
      try {
        const res = await ctx.api.post("/api/purchase-orders/auto", {});
        if (res && res.created === false) {
          ctx.toast(res.reason || "Nothing below reorder point", "warn");
          autoBtn.disabled = false;
          return;
        }
        ctx.toast("Draft purchase order created from low stock", "ok");
        try { await loadOrders(); } catch (_) { /* best effort */ }
        const newId = res && res.po ? res.po.id : null;
        if (newId != null) {
          showDetail(newId);
        } else {
          autoBtn.disabled = false;
          showList();
        }
      } catch (err) {
        ctx.toast("Auto-draft failed: " + err.message, "danger");
        autoBtn.disabled = false;
      }
    });
    toolbar.appendChild(autoBtn);

    // Review what would be ordered (and why) before drafting. Surfaces
    // GET /api/reorder/suggestions, which resolves each low item to its
    // preferred in-stock vendor and a suggested top-up quantity.
    const suggestBtn = el("button", "btn btn-ghost btn-sm", "Review reorder suggestions");
    suggestBtn.addEventListener("click", async () => {
      suggestBtn.disabled = true;
      try {
        const rows = await ctx.api.get("/api/reorder/suggestions");
        showSuggestions(rows || []);
      } catch (err) {
        ctx.toast("Could not load suggestions: "
          + (err && err.message ? err.message : err), "danger");
      } finally {
        suggestBtn.disabled = false;
      }
    });
    toolbar.appendChild(suggestBtn);

    // Read-only review of what auto-draft would order: every active item at or
    // below its reorder point, the vendor the engine picked (preferred
    // substitute when the usual one is unavailable), and the top-up quantity.
    function showSuggestions(rows) {
      ctx.modal({
        title: "Reorder suggestions",
        render: (body) => {
          if (!rows.length) {
            body.appendChild(el("p", "muted",
              "Nothing is at or below its reorder point."));
            return;
          }
          const intro = el("p", "muted",
            rows.length + " item" + (rows.length === 1 ? "" : "s")
            + " at or below the reorder point. \"Auto-draft from low stock\" "
            + "creates a draft purchase order from this list.");
          body.appendChild(intro);
          const table = el("table", "table");
          const thead = el("thead");
          const hr = el("tr");
          ["Item", "On hand", "Reorder at", "Suggested", "Vendor", "Est. cost"]
            .forEach((h) => hr.appendChild(el("th", null, h)));
          thead.appendChild(hr);
          table.appendChild(thead);
          const tb = el("tbody");
          let total = 0;
          for (const r of rows) {
            const tr = el("tr");
            tr.appendChild(el("td", null, r.item_name));
            tr.appendChild(el("td", null, String(r.quantity_on_hand)));
            tr.appendChild(el("td", null, String(r.reorder_threshold)));
            tr.appendChild(el("td", null, String(r.suggested_qty)));
            const vend = el("td", null, r.vendor || "--");
            if (r.preferred_vendor && r.preferred_vendor !== r.vendor) {
              vend.appendChild(el("span", "badge badge-warn", "substitute"));
            }
            tr.appendChild(vend);
            const cost = (r.unit_cost || 0) * (r.suggested_qty || 0);
            total += cost;
            tr.appendChild(el("td", null, ctx.fmt.money(cost)));
            tb.appendChild(tr);
          }
          table.appendChild(tb);
          body.appendChild(table);
          const totalLine = el("p", null, "Estimated total: " + ctx.fmt.money(total));
          totalLine.style.fontWeight = "600";
          body.appendChild(totalLine);
        },
        actions: [
          { label: "Close", onClick: (h) => h.close() },
          {
            label: "Draft purchase order",
            primary: true,
            onClick: (h) => { h.close(); autoBtn.click(); },
          },
        ],
      });
    }

    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search orders...";
    searchInput.style.minWidth = "200px";
    searchInput.addEventListener("input", applyOrderSearch);
    toolbar.appendChild(searchInput);
    toolbar.appendChild(buildThresholdControl());
    container.appendChild(toolbar);

    buildActiveOrders();

    const listCard = el("div", "card");
    listCard.style.padding = "0";
    listCard.style.marginBottom = "20px";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `<thead><tr>
      <th>PO #</th><th>Vendor</th><th>Status</th><th>Created</th>
      <th class="right">Lines</th><th class="right">Total cost</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");

    // Client-side search over the already-loaded orders.
    const dataRows = [];
    const noMatchRow = document.createElement("tr");
    const noMatchTd = el("td", "muted", "No matches");
    noMatchTd.colSpan = 6;
    noMatchTd.style.textAlign = "center";
    noMatchTd.style.padding = "28px";
    noMatchRow.appendChild(noMatchTd);
    noMatchRow.style.display = "none";
    function applyOrderSearch() {
      const q = searchInput.value.trim().toLowerCase();
      let visible = 0;
      for (const r of dataRows) {
        const match = !q || r._haystack.includes(q);
        r.style.display = match ? "" : "none";
        if (match) visible++;
      }
      noMatchRow.style.display = q && visible === 0 ? "" : "none";
    }

    if (!state.orders.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No purchase orders yet.");
      td.colSpan = 6;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const po of state.orders) {
        const tr = el("tr", "row-link");
        tr.appendChild(el("td", "mono", "#" + po.id));
        tr.appendChild(el("td", null, po.vendor || "--"));
        const statusTd = document.createElement("td");
        statusTd.appendChild(statusBadge(po.status));
        tr.appendChild(statusTd);
        tr.appendChild(el("td", "muted", po.created_at ? ctx.fmt.date(po.created_at) : "--"));
        tr.appendChild(el("td", "right mono", String(po.line_count != null ? po.line_count : 0)));
        tr.appendChild(el("td", "right mono", ctx.fmt.money(po.total_cost || 0)));
        tr.addEventListener("click", () => showDetail(po.id));
        tr._haystack = ["#" + po.id, po.vendor, statusLabel(po.status), po.fund_name]
          .filter(Boolean).join(" ").toLowerCase();
        dataRows.push(tr);
        tbody.appendChild(tr);
      }
      tbody.appendChild(noMatchRow);
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    listCard.appendChild(scroll);
    container.appendChild(listCard);

    container.appendChild(buildNewPoForm());
  }

  // ---- active orders (awaiting arrival) --------------------------------------
  function buildActiveOrders() {
    const active = state.orders.filter((po) => ["submitted", "ordered"].includes(po.status));

    const wrap = el("div");
    wrap.style.marginBottom = "20px";
    wrap.appendChild(el("div", "card-title", "Active orders (awaiting arrival)"));

    if (!active.length) {
      wrap.appendChild(el("p", "muted", "No active orders."));
      container.appendChild(wrap);
      return;
    }

    const listCard = el("div", "card");
    listCard.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `<thead><tr>
      <th>PO #</th><th>Vendor</th><th>Fund</th><th>Expected arrival</th>
      <th class="right">Total</th><th></th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");

    for (const po of active) {
      const tr = document.createElement("tr");
      const idTd = el("td", "mono", "#" + po.id);
      idTd.style.cursor = "pointer";
      idTd.addEventListener("click", () => showDetail(po.id));
      tr.appendChild(idTd);
      tr.appendChild(el("td", null, po.vendor || "--"));
      tr.appendChild(el("td", null, po.fund_name || "--"));

      const etaTd = el("td", null, po.expected_arrival ? ctx.fmt.date(po.expected_arrival) : "--");
      if (isPastDue(po)) {
        etaTd.style.color = "var(--danger, #b00020)";
        etaTd.style.fontWeight = "600";
        etaTd.appendChild(el("span", "muted", " (past due)"));
      }
      tr.appendChild(etaTd);

      tr.appendChild(el("td", "right mono", ctx.fmt.money(po.total_cost || 0)));

      const actTd = el("td", "right");
      const recvBtn = el("button", "btn btn-ghost btn-sm", "Receive");
      recvBtn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        if (!window.confirm("Receiving PO #" + po.id + " will restock inventory. Continue?")) return;
        recvBtn.disabled = true;
        try {
          await ctx.api.patch("/api/purchase-orders/" + po.id, { status: "received" });
          ctx.toast("Purchase order received", "ok");
          try { await loadOrders(); } catch (_) { /* best effort */ }
          showList();
        } catch (err) {
          ctx.toast("Receive failed: " + err.message, "danger");
          recvBtn.disabled = false;
        }
      });
      actTd.appendChild(recvBtn);
      tr.appendChild(actTd);

      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    listCard.appendChild(scroll);
    wrap.appendChild(listCard);
    container.appendChild(wrap);
  }

  // ---- detail view -----------------------------------------------------------
  async function showDetail(poId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to purchase orders");
    back.style.marginBottom = "14px";
    back.addEventListener("click", async () => {
      try { await loadOrders(); } catch (_) { /* best effort */ }
      showList();
    });
    container.appendChild(back);

    let po;
    try {
      po = await ctx.api.get("/api/purchase-orders/" + poId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load purchase order: " + err.message));
      return;
    }

    const headerCard = el("div", "card");
    headerCard.style.marginBottom = "16px";

    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", "PO #" + po.id + " -- " + (po.vendor || "Unknown vendor"));
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    titleRow.appendChild(statusBadge(po.status));
    headerCard.appendChild(titleRow);

    // Timeline of who did what and when.
    const timeline = el("div", "muted");
    timeline.style.margin = "8px 0 12px";
    timeline.style.lineHeight = "1.7";
    const requester = po.username || po.full_name || "unknown";
    function tlLine(txt) {
      const d = el("div", null, txt);
      timeline.appendChild(d);
    }
    tlLine("Requested by " + requester + (po.created_at ? " on " + ctx.fmt.date(po.created_at) : ""));
    if (po.auto_approved) {
      tlLine("Auto-approved (under threshold)" + (po.approved_at ? " on " + ctx.fmt.date(po.approved_at) : ""));
    } else if (po.approved_at || po.approved_by_username) {
      const who = po.approved_by_username || "unknown";
      tlLine("Approved by " + who + (po.approved_at ? " on " + ctx.fmt.date(po.approved_at) : ""));
    }
    if (po.submitted_at) tlLine("Submitted " + ctx.fmt.date(po.submitted_at));
    if (po.ordered_at) tlLine("Ordered " + ctx.fmt.date(po.ordered_at));
    if (po.received_at) tlLine("Received " + ctx.fmt.date(po.received_at));
    headerCard.appendChild(timeline);

    // ---- funding source + expected arrival ----
    const meta = el("div");
    meta.style.display = "flex";
    meta.style.gap = "28px";
    meta.style.flexWrap = "wrap";
    meta.style.margin = "4px 0 12px";

    const fundBlock = el("div");
    fundBlock.appendChild(el("div", "muted", "Funding source"));
    fundBlock.appendChild(el("div", null, po.fund_name || "--"));

    const etaBlock = el("div");
    etaBlock.appendChild(el("div", "muted", "Expected arrival"));
    const etaVal = el("div", null, po.expected_arrival ? ctx.fmt.date(po.expected_arrival) : "--");
    if (isPastDue(po)) {
      etaVal.style.color = "var(--danger, #b00020)";
      etaVal.style.fontWeight = "600";
      etaVal.appendChild(el("span", "muted", " (past due)"));
    }
    etaBlock.appendChild(etaVal);

    meta.append(fundBlock, etaBlock);
    headerCard.appendChild(meta);

    if (canManage && !["received", "cancelled", "rejected"].includes(po.status)) {
      const editPanel = el("div", "panel");
      editPanel.style.margin = "0 0 12px";
      editPanel.style.maxWidth = "560px";
      editPanel.appendChild(el("div", "muted", "Set funding source & expected arrival"));

      const editRow = el("div");
      editRow.style.display = "flex";
      editRow.style.gap = "8px";
      editRow.style.flexWrap = "wrap";
      editRow.style.alignItems = "center";
      editRow.style.marginTop = "8px";

      const fundSel = buildFundSelect(po.fund_id != null ? po.fund_id : null);
      fundSel.style.flex = "1 1 200px";

      const etaInput = document.createElement("input");
      etaInput.type = "date";
      etaInput.className = "chip";
      if (po.expected_arrival) etaInput.value = po.expected_arrival;

      const saveMeta = el("button", "btn btn-ghost btn-sm", "Save");
      saveMeta.addEventListener("click", async () => {
        saveMeta.disabled = true;
        try {
          await ctx.api.patch("/api/purchase-orders/" + poId, {
            fund_id: fundSel.value ? Number(fundSel.value) : null,
            expected_arrival: etaInput.value ? etaInput.value : null,
          });
          ctx.toast("Purchase order updated", "ok");
          try { await loadOrders(); } catch (_) { /* best effort */ }
          showDetail(poId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveMeta.disabled = false;
        }
      });

      editRow.append(fundSel, etaInput, saveMeta);
      editPanel.appendChild(editRow);
      editPanel.appendChild(el("div", "muted", "Receiving a fund-linked purchase order charges that fund automatically."));
      headerCard.appendChild(editPanel);
    } else if (po.fund_name) {
      const chargeNote = el("div", "muted", "Receiving this purchase order charges " + po.fund_name + " automatically.");
      chargeNote.style.margin = "0 0 12px";
      headerCard.appendChild(chargeNote);
    }

    if (po.note) {
      const noteEl = el("div", "panel", po.note);
      noteEl.style.marginBottom = "12px";
      headerCard.appendChild(noteEl);
    }
    if (po.approver_note) {
      const an = el("div", "panel");
      an.style.marginBottom = "12px";
      an.appendChild(el("div", "muted", "Approver note"));
      an.appendChild(el("div", null, po.approver_note));
      headerCard.appendChild(an);
    }

    // ---- status action buttons ----
    const actions = el("div");
    actions.style.display = "flex";
    actions.style.gap = "10px";
    actions.style.flexWrap = "wrap";
    headerCard.appendChild(actions);

    // Generic transition helper.
    async function transition(targetStatus, approverNote, confirmMsg) {
      if (confirmMsg && !window.confirm(confirmMsg)) return false;
      const body = { status: targetStatus };
      if (approverNote != null && approverNote !== "") body.approver_note = approverNote;
      await ctx.api.patch("/api/purchase-orders/" + poId, body);
      try { await loadOrders(); } catch (_) { /* best effort */ }
      showDetail(poId);
      return true;
    }

    function simpleAction(label, targetStatus, primary) {
      const btn = el("button", "btn btn-sm " + (primary ? "btn-primary" : "btn-ghost"), label);
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await transition(targetStatus);
          ctx.toast("Purchase order " + statusLabel(targetStatus), "ok");
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          btn.disabled = false;
        }
      });
      return btn;
    }

    if (po.status === "draft") {
      const reqBtn = el("button", "btn btn-primary btn-sm", "Request approval");
      reqBtn.addEventListener("click", async () => {
        reqBtn.disabled = true;
        try {
          const updated = await ctx.api.patch("/api/purchase-orders/" + poId, { status: "pending_approval" });
          try { await loadOrders(); } catch (_) { /* best effort */ }
          if (updated && updated.status === "approved" && updated.auto_approved) {
            ctx.toast("Auto-approved (under threshold)", "ok");
          } else {
            ctx.toast("Pending approval", "ok");
          }
          showDetail(poId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          reqBtn.disabled = false;
        }
      });
      actions.appendChild(reqBtn);
    } else if (po.status === "pending_approval") {
      // Approve / Reject both reveal a shared note field.
      const notePanel = el("div", "panel");
      notePanel.style.display = "none";
      notePanel.style.margin = "12px 0";
      notePanel.style.maxWidth = "520px";
      const noteHead = el("div", "muted", "Approver note (optional)");
      const noteArea = document.createElement("textarea");
      noteArea.className = "chip";
      noteArea.rows = 2;
      noteArea.style.width = "100%";
      noteArea.style.margin = "6px 0";
      const confirmBtn = el("button", "btn btn-primary btn-sm", "Confirm");
      let pendingTarget = null;
      notePanel.appendChild(noteHead);
      notePanel.appendChild(noteArea);
      notePanel.appendChild(confirmBtn);

      const approveBtn = el("button", "btn btn-primary btn-sm", "Approve / sign off");
      approveBtn.addEventListener("click", () => {
        pendingTarget = "approved";
        confirmBtn.textContent = "Confirm approval";
        notePanel.style.display = "";
        noteArea.focus();
      });
      const rejectBtn = el("button", "btn btn-sm", "Reject");
      rejectBtn.style.borderColor = "var(--danger, #b00020)";
      rejectBtn.style.color = "var(--danger, #b00020)";
      rejectBtn.addEventListener("click", () => {
        pendingTarget = "rejected";
        confirmBtn.textContent = "Confirm rejection";
        notePanel.style.display = "";
        noteArea.focus();
      });
      confirmBtn.addEventListener("click", async () => {
        if (!pendingTarget) return;
        confirmBtn.disabled = true;
        try {
          await transition(pendingTarget, noteArea.value.trim());
          ctx.toast("Purchase order " + statusLabel(pendingTarget), "ok");
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          confirmBtn.disabled = false;
        }
      });
      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      // note panel goes right after actions
      headerCard.appendChild(notePanel);
    } else if (po.status === "approved") {
      actions.appendChild(simpleAction("Mark submitted", "submitted", true));
    } else if (po.status === "submitted") {
      actions.appendChild(simpleAction("Mark ordered", "ordered", true));
    } else if (po.status === "ordered") {
      const receiveAllBtn = el("button", "btn btn-primary btn-sm", "Receive all");
      receiveAllBtn.addEventListener("click", async () => {
        receiveAllBtn.disabled = true;
        try {
          const ok = await transition("received", null, "Receiving all lines will restock inventory. Continue?");
          if (ok) ctx.toast("Purchase order received", "ok");
          else receiveAllBtn.disabled = false;
        } catch (err) {
          ctx.toast("Receive failed: " + err.message, "danger");
          receiveAllBtn.disabled = false;
        }
      });
      actions.appendChild(receiveAllBtn);
    }

    // Cancel available except on terminal states.
    if (!["received", "cancelled", "rejected"].includes(po.status)) {
      const cancelBtn = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancelBtn.addEventListener("click", async () => {
        cancelBtn.disabled = true;
        try {
          const ok = await transition("cancelled", null, "Cancel this purchase order?");
          if (ok) ctx.toast("Purchase order cancelled", "ok");
          else cancelBtn.disabled = false;
        } catch (err) {
          ctx.toast("Cancel failed: " + err.message, "danger");
          cancelBtn.disabled = false;
        }
      });
      actions.appendChild(cancelBtn);
    }

    container.appendChild(headerCard);

    // ---- lines table ----
    const linesCard = el("div", "card");
    linesCard.style.padding = "0";
    linesCard.style.marginBottom = "20px";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `<thead><tr>
      <th>Item</th><th class="right">Qty</th><th class="right">Unit cost</th>
      <th class="right">Received qty</th><th class="right">Line total</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");
    const lines = po.lines || [];
    if (!lines.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No lines on this purchase order.");
      td.colSpan = 5;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      for (const line of lines) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, line.item_name || ("Item #" + line.item_id)));
        tr.appendChild(el("td", "right mono", String(line.quantity)));
        tr.appendChild(el("td", "right mono", ctx.fmt.money(line.unit_cost)));
        tr.appendChild(el("td", "right mono", String(line.received_qty != null ? line.received_qty : 0)));
        tr.appendChild(el("td", "right mono", ctx.fmt.money((line.quantity || 0) * (line.unit_cost || 0))));
        tbody.appendChild(tr);
      }
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    linesCard.appendChild(scroll);

    const totalRow = el("div", "right");
    totalRow.style.padding = "10px 14px";
    totalRow.style.borderTop = "1px solid var(--border, #ccc)";
    const totalLabel = el("strong", null, "Total: " + ctx.fmt.money(po.total_cost || 0));
    totalRow.appendChild(totalLabel);
    linesCard.appendChild(totalRow);

    container.appendChild(linesCard);

    // ---- receiving panel (status = ordered) ----
    if (po.status === "ordered" && lines.length) {
      container.appendChild(buildReceivingPanel(po));
    }

    // ---- documents ----
    container.appendChild(buildDocumentsPanel(po));
  }

  // ---- receiving panel ------------------------------------------------------
  function buildReceivingPanel(po) {
    const card = el("div", "card");
    card.style.marginBottom = "20px";
    card.appendChild(el("div", "card-title", "Receive shipment"));
    card.appendChild(el("p", "muted", "Enter the quantity received for each line. Receiving restocks inventory."));

    const rows = [];
    const wrap = el("div");
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.gap = "8px";
    wrap.style.margin = "10px 0";

    for (const line of (po.lines || [])) {
      const outstanding = (line.quantity || 0) - (line.received_qty != null ? line.received_qty : 0);
      if (outstanding <= 0) continue;
      const row = el("div");
      row.style.display = "flex";
      row.style.gap = "10px";
      row.style.alignItems = "center";
      row.style.flexWrap = "wrap";

      const nameEl = el("div", null, line.item_name || ("Item #" + line.item_id));
      nameEl.style.flex = "1 1 220px";
      const outEl = el("span", "muted", "outstanding " + outstanding);

      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "0";
      qtyInput.max = String(outstanding);
      qtyInput.value = String(outstanding);
      qtyInput.className = "chip";
      qtyInput.style.width = "84px";

      row.append(nameEl, outEl, qtyInput);
      wrap.appendChild(row);
      rows.push({ line_id: line.id, input: qtyInput, outstanding });
    }

    if (!rows.length) {
      card.appendChild(el("div", "empty-state", "All lines already fully received."));
      return card;
    }

    card.appendChild(wrap);

    const receiveBtn = el("button", "btn btn-primary btn-sm", "Receive entered quantities");
    receiveBtn.addEventListener("click", async () => {
      const receipts = [];
      for (const r of rows) {
        const q = parseInt(r.input.value, 10);
        if (!q || q <= 0) continue;
        if (q > r.outstanding) {
          ctx.toast("Quantity exceeds outstanding for a line", "warn");
          return;
        }
        receipts.push({ line_id: r.line_id, qty: q });
      }
      if (!receipts.length) {
        ctx.toast("Enter a quantity for at least one line", "warn");
        return;
      }
      if (!window.confirm("Receiving will restock inventory for the entered quantities. Continue?")) return;
      receiveBtn.disabled = true;
      try {
        await ctx.api.post("/api/purchase-orders/" + po.id + "/receive", { receipts });
        ctx.toast("Shipment received", "ok");
        try { await loadOrders(); } catch (_) { /* best effort */ }
        showDetail(po.id);
      } catch (err) {
        ctx.toast("Receive failed: " + err.message, "danger");
        receiveBtn.disabled = false;
      }
    });
    card.appendChild(receiveBtn);

    return card;
  }

  // ---- documents panel ------------------------------------------------------
  function buildDocumentsPanel(po) {
    const card = el("div", "card");
    card.style.marginBottom = "20px";
    card.appendChild(el("div", "card-title", "Documents"));

    const docs = po.documents || [];
    const listWrap = el("div");
    listWrap.style.margin = "8px 0 14px";
    if (!docs.length) {
      listWrap.appendChild(el("div", "muted", "No documents attached."));
    } else {
      for (const doc of docs) {
        const row = el("div");
        row.style.display = "flex";
        row.style.gap = "10px";
        row.style.alignItems = "center";
        row.style.flexWrap = "wrap";
        row.style.padding = "4px 0";

        const kindTag = el("span", "badge", statusLabel(doc.kind || "other"));
        const link = el("a", "card-link", doc.label || doc.filename || doc.url || ("Document #" + doc.id));
        link.href = doc.href || doc.url || "#";
        link.target = "_blank";
        link.rel = "noopener";
        row.append(kindTag, link);

        if (canManage) {
          const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
          delBtn.addEventListener("click", async () => {
            if (!window.confirm("Delete this document?")) return;
            delBtn.disabled = true;
            try {
              await ctx.api.del("/api/documents/" + doc.id);
              ctx.toast("Document deleted", "ok");
              showDetail(po.id);
            } catch (err) {
              ctx.toast("Delete failed: " + err.message, "danger");
              delBtn.disabled = false;
            }
          });
          row.appendChild(delBtn);
        }
        listWrap.appendChild(row);
      }
    }
    card.appendChild(listWrap);

    // Attach control
    const attach = el("div", "panel");
    attach.style.maxWidth = "560px";
    attach.appendChild(el("div", "muted", "Attach a document"));

    const controls = el("div");
    controls.style.display = "flex";
    controls.style.flexDirection = "column";
    controls.style.gap = "8px";
    controls.style.marginTop = "8px";

    const kindSelect = document.createElement("select");
    kindSelect.className = "chip";
    for (const k of DOC_KINDS) {
      const opt = el("option", null, statusLabel(k));
      opt.value = k;
      kindSelect.appendChild(opt);
    }
    kindSelect.style.maxWidth = "200px";

    const labelInput = document.createElement("input");
    labelInput.type = "text";
    labelInput.className = "chip";
    labelInput.placeholder = "Label (optional)";
    labelInput.style.maxWidth = "320px";

    // Link row
    const linkRow = el("div");
    linkRow.style.display = "flex";
    linkRow.style.gap = "8px";
    linkRow.style.flexWrap = "wrap";
    linkRow.style.alignItems = "center";
    const urlInput = document.createElement("input");
    urlInput.type = "text";
    urlInput.className = "chip";
    urlInput.placeholder = "https://... link URL";
    urlInput.style.flex = "1 1 240px";
    const addLinkBtn = el("button", "btn btn-ghost btn-sm", "Add link");
    addLinkBtn.addEventListener("click", async () => {
      const url = urlInput.value.trim();
      if (!url) { ctx.toast("Enter a link URL", "warn"); return; }
      addLinkBtn.disabled = true;
      try {
        const body = { po_id: po.id, kind: kindSelect.value, url };
        const lbl = labelInput.value.trim();
        if (lbl) body.label = lbl;
        await ctx.api.post("/api/documents", body);
        ctx.toast("Link attached", "ok");
        showDetail(po.id);
      } catch (err) {
        ctx.toast("Attach failed: " + err.message, "danger");
        addLinkBtn.disabled = false;
      }
    });
    linkRow.append(urlInput, addLinkBtn);

    // Upload row
    const uploadRow = el("div");
    uploadRow.style.display = "flex";
    uploadRow.style.gap = "8px";
    uploadRow.style.flexWrap = "wrap";
    uploadRow.style.alignItems = "center";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "chip";
    fileInput.style.flex = "1 1 240px";
    const uploadBtn = el("button", "btn btn-ghost btn-sm", "Upload file");
    uploadBtn.addEventListener("click", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) { ctx.toast("Choose a file to upload", "warn"); return; }
      uploadBtn.disabled = true;
      try {
        const fd = new FormData();
        fd.append("po_id", String(po.id));
        fd.append("kind", kindSelect.value);
        const lbl = labelInput.value.trim();
        if (lbl) fd.append("label", lbl);
        fd.append("file", file);
        const res = await fetch("/api/documents/upload", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
        });
        if (!res.ok) {
          let detail = "Upload failed (" + res.status + ")";
          try {
            const j = await res.json();
            if (j && j.detail) detail = j.detail;
          } catch (_) { /* keep default */ }
          throw new Error(detail);
        }
        ctx.toast("File uploaded", "ok");
        showDetail(po.id);
      } catch (err) {
        ctx.toast("Upload failed: " + err.message, "danger");
        uploadBtn.disabled = false;
      }
    });
    uploadRow.append(fileInput, uploadBtn);

    controls.append(kindSelect, labelInput, linkRow, uploadRow);
    attach.appendChild(controls);
    card.appendChild(attach);

    return card;
  }

  // ---- new PO form -----------------------------------------------------------
  function buildNewPoForm() {
    const card = el("div", "card");
    card.id = "new-po-form";
    card.appendChild(el("div", "card-title", "New requisition / purchase order"));
    if (ctx.user.role === "member") {
      const note = el("p", "muted", "Submitted as a requisition -- needs approval unless it's under the auto-approval threshold.");
      note.style.marginTop = "0";
      card.appendChild(note);
    }

    const lineRows = [];
    const linesWrap = el("div");
    linesWrap.style.display = "flex";
    linesWrap.style.flexDirection = "column";
    linesWrap.style.gap = "8px";
    linesWrap.style.marginBottom = "10px";

    const vendorInput = document.createElement("input");
    vendorInput.type = "text";
    vendorInput.className = "chip";
    vendorInput.placeholder = "Vendor";
    vendorInput.style.marginBottom = "8px";
    vendorInput.style.width = "100%";
    vendorInput.style.maxWidth = "320px";

    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.className = "chip";
    noteInput.placeholder = "Note (optional)";
    noteInput.style.marginBottom = "10px";
    noteInput.style.width = "100%";
    noteInput.style.maxWidth = "480px";

    // Funding source + expected arrival
    const metaRow = el("div");
    metaRow.style.display = "flex";
    metaRow.style.gap = "14px";
    metaRow.style.flexWrap = "wrap";
    metaRow.style.marginBottom = "10px";

    const fundField = el("div");
    fundField.appendChild(el("div", "muted", "Funding source"));
    const fundSelect = buildFundSelect(null);
    fundField.appendChild(fundSelect);

    const etaField = el("div");
    etaField.appendChild(el("div", "muted", "Expected arrival"));
    const etaInput = document.createElement("input");
    etaInput.type = "date";
    etaInput.className = "chip";
    etaField.appendChild(etaInput);

    metaRow.append(fundField, etaField);

    card.appendChild(vendorInput);
    card.appendChild(noteInput);
    card.appendChild(metaRow);
    card.appendChild(linesWrap);

    const addLineBtn = el("button", "btn btn-ghost btn-sm", "+ Add line");
    addLineBtn.style.marginBottom = "10px";
    addLineBtn.addEventListener("click", async () => {
      await loadItems();
      addLineRow();
    });
    card.appendChild(addLineBtn);

    const submitRow = el("div");
    const submitBtn = el("button", "btn btn-primary", "Create purchase order");
    submitRow.appendChild(submitBtn);
    card.appendChild(submitRow);

    // Autocomplete item-picker against the loaded inventory (state.items). Exposes
    // a `.value` getter returning the chosen item_id so the submit logic below is
    // unchanged. Reuses the command-palette result-list styling.
    function makeItemPicker() {
      const wrap = el("div");
      wrap.style.position = "relative";
      wrap.style.flex = "1 1 240px";
      const input = document.createElement("input");
      input.className = "chip";
      input.placeholder = "Search inventory (name, cat #, vendor)...";
      input.style.width = "100%";
      input.autocomplete = "off";
      const results = el("div", "search-results");
      results.style.left = "0";
      results.style.right = "auto";
      results.style.width = "100%";
      results.style.maxWidth = "none";
      results.style.zIndex = "70";
      results.hidden = true;
      let selectedId = "";
      wrap.append(input, results);

      const close = () => { results.hidden = true; results.innerHTML = ""; };
      function draw(q) {
        const needle = q.toLowerCase();
        const matches = state.items.filter((it) =>
          it.item_name.toLowerCase().includes(needle) ||
          String(it.catalog_number || "").toLowerCase().includes(needle) ||
          String(it.vendor || "").toLowerCase().includes(needle)
        ).slice(0, 20);
        results.innerHTML = "";
        if (!matches.length) {
          results.appendChild(el("div", "search-item muted", "No matches"));
        } else {
          for (const it of matches) {
            const r = el("div", "search-item");
            r.appendChild(el("div", null, it.item_name));
            const sub = el("div", "muted",
              [it.catalog_number, it.vendor].filter(Boolean).join(" · "));
            sub.style.fontSize = "12px";
            r.appendChild(sub);
            r.addEventListener("mousedown", (e) => {
              e.preventDefault();
              selectedId = String(it.item_id);
              input.value = it.item_name;
              close();
            });
            results.appendChild(r);
          }
        }
        results.hidden = false;
      }
      input.addEventListener("input", () => {
        selectedId = ""; // typing invalidates a prior pick
        const q = input.value.trim();
        if (!q) { close(); return; }
        draw(q);
      });
      input.addEventListener("focus", () => {
        const q = input.value.trim();
        if (q && !selectedId) draw(q);
      });
      input.addEventListener("blur", () => setTimeout(close, 150));
      return { wrap, input, get value() { return selectedId; } };
    }

    function addLineRow() {
      const row = el("div");
      row.style.display = "flex";
      row.style.gap = "8px";
      row.style.alignItems = "center";
      row.style.flexWrap = "wrap";

      const itemSelect = makeItemPicker();

      const qtyInput = document.createElement("input");
      qtyInput.type = "number";
      qtyInput.min = "1";
      qtyInput.value = "1";
      qtyInput.className = "chip";
      qtyInput.style.width = "84px";

      const costInput = document.createElement("input");
      costInput.type = "number";
      costInput.min = "0";
      costInput.step = "0.01";
      costInput.className = "chip";
      costInput.placeholder = "defaults to current cost";
      costInput.style.width = "170px";

      const removeBtn = el("button", "btn btn-ghost btn-sm", "Remove");
      removeBtn.addEventListener("click", () => {
        linesWrap.removeChild(row);
        const idx = lineRows.indexOf(row);
        if (idx >= 0) lineRows.splice(idx, 1);
      });

      row.append(itemSelect.wrap, qtyInput, costInput, removeBtn);
      row._fields = { itemSelect, qtyInput, costInput };
      linesWrap.appendChild(row);
      lineRows.push(row);
    }

    submitBtn.addEventListener("click", async () => {
      const vendor = vendorInput.value.trim();
      const note = noteInput.value.trim();
      if (!lineRows.length) {
        ctx.toast("Add at least one line", "warn");
        return;
      }
      const lines = [];
      for (const row of lineRows) {
        const { itemSelect, qtyInput, costInput } = row._fields;
        if (!itemSelect.value) { continue; }
        const qty = parseInt(qtyInput.value, 10);
        if (!qty || qty <= 0) {
          ctx.toast("Enter a positive quantity for every line", "warn");
          return;
        }
        const line = { item_id: Number(itemSelect.value), quantity: qty };
        const costVal = costInput.value.trim();
        if (costVal !== "") line.unit_cost = Number(costVal);
        lines.push(line);
      }
      if (!lines.length) {
        ctx.toast("Add at least one valid line", "warn");
        return;
      }

      const body = { lines };
      if (vendor) body.vendor = vendor;
      if (note) body.note = note;
      if (fundSelect.value) body.fund_id = Number(fundSelect.value);
      if (etaInput.value) body.expected_arrival = etaInput.value;

      submitBtn.disabled = true;
      try {
        const created = await ctx.api.post("/api/purchase-orders", body);
        ctx.toast("Purchase order created", "ok");
        vendorInput.value = "";
        noteInput.value = "";
        fundSelect.value = "";
        etaInput.value = "";
        linesWrap.innerHTML = "";
        lineRows.length = 0;
        try { await loadOrders(); } catch (_) { /* best effort */ }
        showDetail(created.id);
      } catch (err) {
        ctx.toast("Could not create purchase order: " + err.message, "danger");
        submitBtn.disabled = false;
      }
    });

    // start with one empty line, loading items lazily
    loadItems().then(() => addLineRow()).catch(() => addLineRow());

    return card;
  }
}
