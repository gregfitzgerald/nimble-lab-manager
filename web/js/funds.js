// funds.js -- fund/budget tracking with burn-down bars and charge management.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "funds", label: "Funds", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Spartan burn-down bar: outer bordered box, inner fill width = pct_spent%.
// Fill color: neutral by default, warn > 75%, danger > 90%.
function burnBar(pctSpent, opts) {
  const width = (opts && opts.width) || 160;
  const height = (opts && opts.height) || 12;
  const pct = Math.max(0, Number(pctSpent) || 0);
  const capped = Math.min(pct, 100);

  const outer = el("div");
  outer.style.width = width + "px";
  outer.style.height = height + "px";
  outer.style.border = "1px solid var(--border, #999)";
  outer.style.position = "relative";
  outer.style.boxSizing = "border-box";

  const inner = el("div");
  inner.style.width = capped + "%";
  inner.style.height = "100%";
  let fill = "var(--text)";
  if (pct > 90) fill = "var(--danger)";
  else if (pct > 75) fill = "var(--warn)";
  inner.style.background = fill;

  outer.appendChild(inner);
  outer.title = pct.toFixed(1) + "% spent";
  return outer;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const canManage = ["manager", "admin"].includes(ctx.user.role);

  root.appendChild(el("h1", "view-title", "Funds"));
  root.appendChild(el("p", "view-sub", "Grant/budget tracking with burn-down and charge history."));

  const container = el("div");
  root.appendChild(container);

  const focusId = params && params.fundId;
  if (focusId != null) {
    await showDetail(Number(focusId));
  } else {
    await showList();
  }

  // ---- list view ----------------------------------------------------------
  async function showList() {
    container.innerHTML = "";

    let funds;
    try {
      funds = await ctx.api.get("/api/funds");
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load funds: " + err.message));
      return;
    }

    const toolbar = el("div");
    toolbar.style.display = "flex";
    toolbar.style.justifyContent = "space-between";
    toolbar.style.gap = "10px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "12px";
    const searchInput = document.createElement("input");
    searchInput.className = "chip";
    searchInput.placeholder = "Search funds...";
    searchInput.style.minWidth = "200px";
    searchInput.addEventListener("input", applySearch);
    toolbar.appendChild(searchInput);
    if (canManage) {
      const addBtn = el("button", "btn btn-primary btn-sm", "+ New fund");
      addBtn.addEventListener("click", () => openAddForm());
      toolbar.appendChild(addBtn);
    }
    container.appendChild(toolbar);

    const addFormHost = el("div");
    container.appendChild(addFormHost);

    // Client-side search over the already-loaded funds.
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

    if (!funds.length) {
      container.appendChild(el("div", "empty-state", "No funds set up yet."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Name</th><th>Sponsor</th><th class=\"right\">Budget</th>" +
      "<th class=\"right\">Spent</th><th class=\"right\">Remaining</th><th>Burn-down</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const f of funds) {
      const tr = el("tr", "row-link");
      tr.appendChild(el("td", null, f.name));
      tr.appendChild(el("td", "muted", f.sponsor || "--"));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(f.budget)));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(f.spent)));
      const remainingTd = el("td", "right mono", ctx.fmt.money(f.remaining));
      if (f.remaining < 0 || f.pct_spent > 90) remainingTd.style.color = "var(--danger)";
      tr.appendChild(remainingTd);
      const barTd = document.createElement("td");
      barTd.appendChild(burnBar(f.pct_spent));
      tr.appendChild(barTd);
      tr.addEventListener("click", () => showDetail(f.id));
      tr._haystack = [f.name, f.sponsor].filter(Boolean).join(" ").toLowerCase();
      dataRows.push(tr);
      tbody.appendChild(tr);
    }
    tbody.appendChild(noMatchRow);
    table.appendChild(tbody);
    scroll.appendChild(table);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);

    await showSpendByPerson();

    function openAddForm() {
      if (addFormHost.firstChild) { addFormHost.innerHTML = ""; return; }
      const card = el("div", "card");
      card.style.marginBottom = "16px";
      card.appendChild(el("div", "card-title", "New fund"));

      function field(labelText, inputEl) {
        const w = el("div");
        w.style.display = "flex";
        w.style.flexDirection = "column";
        w.style.gap = "3px";
        w.appendChild(el("label", "muted", labelText));
        w.appendChild(inputEl);
        return w;
      }

      const gridForm = el("div", "grid");
      gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(200px, 1fr))";
      gridForm.style.gap = "10px";

      const nameInput = document.createElement("input");
      nameInput.type = "text"; nameInput.className = "chip"; nameInput.placeholder = "Fund name";
      const sponsorInput = document.createElement("input");
      sponsorInput.type = "text"; sponsorInput.className = "chip"; sponsorInput.placeholder = "Sponsor";
      const budgetInput = document.createElement("input");
      budgetInput.type = "number"; budgetInput.step = "0.01"; budgetInput.className = "chip"; budgetInput.value = "0";
      const startInput = document.createElement("input");
      startInput.type = "date"; startInput.className = "chip";
      const endInput = document.createElement("input");
      endInput.type = "date"; endInput.className = "chip";

      gridForm.append(
        field("Name *", nameInput),
        field("Sponsor", sponsorInput),
        field("Budget *", budgetInput),
        field("Start date", startInput),
        field("End date", endInput),
      );
      card.appendChild(gridForm);

      const noteInput = document.createElement("textarea");
      noteInput.className = "chip";
      noteInput.rows = 2;
      noteInput.placeholder = "Note";
      noteInput.style.width = "100%";
      noteInput.style.marginTop = "10px";
      const noteWrap = el("div");
      noteWrap.style.display = "flex";
      noteWrap.style.flexDirection = "column";
      noteWrap.style.gap = "3px";
      noteWrap.appendChild(el("label", "muted", "Note"));
      noteWrap.appendChild(noteInput);
      card.appendChild(noteWrap);

      const btnRow = el("div");
      btnRow.style.display = "flex";
      btnRow.style.gap = "8px";
      btnRow.style.marginTop = "10px";
      const submit = el("button", "btn btn-primary btn-sm", "Create fund");
      const cancel = el("button", "btn btn-ghost btn-sm", "Cancel");
      cancel.addEventListener("click", () => { addFormHost.innerHTML = ""; });
      submit.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        const budget = Number(budgetInput.value);
        if (!name) { ctx.toast("Fund name is required", "warn"); nameInput.focus(); return; }
        if (!budget || budget <= 0) { ctx.toast("Enter a positive budget", "warn"); budgetInput.focus(); return; }
        const body = {
          name,
          sponsor: sponsorInput.value.trim() || null,
          budget,
          start_date: startInput.value || null,
          end_date: endInput.value || null,
          note: noteInput.value.trim() || null,
        };
        submit.disabled = true;
        try {
          await ctx.api.post("/api/funds", body);
          ctx.toast("Fund created", "ok");
          addFormHost.innerHTML = "";
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
  }

  // ---- detail view --------------------------------------------------------
  async function showDetail(fundId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to funds");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/funds/" + fundId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load fund: " + err.message));
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
      editBtn.addEventListener("click", () => { editForm.hidden = !editForm.hidden; });
      titleRow.appendChild(editBtn);
      const delBtn = el("button", "btn btn-ghost btn-sm", "Delete fund");
      delBtn.addEventListener("click", async () => {
        if (!confirm("Delete fund \"" + data.name + "\"? This removes all its charges.")) return;
        delBtn.disabled = true;
        try {
          await ctx.api.del("/api/funds/" + fundId);
          ctx.toast("Fund deleted", "ok");
          showList();
        } catch (err) {
          ctx.toast("Delete failed: " + err.message, "danger");
          delBtn.disabled = false;
        }
      });
      titleRow.appendChild(delBtn);
    }
    summary.appendChild(titleRow);
    summary.appendChild(el("div", "muted", data.sponsor || "No sponsor"));

    // manager edit form
    const editForm = el("div");
    editForm.hidden = true;
    if (canManage) {
      editForm.style.display = "flex";
      editForm.style.flexWrap = "wrap";
      editForm.style.gap = "8px";
      editForm.style.alignItems = "center";
      editForm.style.margin = "10px 0";

      const nameInput = document.createElement("input");
      nameInput.type = "text"; nameInput.className = "chip"; nameInput.value = data.name || "";
      const sponsorInput = document.createElement("input");
      sponsorInput.type = "text"; sponsorInput.className = "chip"; sponsorInput.value = data.sponsor || "";
      const budgetInput = document.createElement("input");
      budgetInput.type = "number"; budgetInput.step = "0.01"; budgetInput.className = "chip";
      budgetInput.value = data.budget != null ? String(data.budget) : "0";
      const startInput = document.createElement("input");
      startInput.type = "date"; startInput.className = "chip"; startInput.value = data.start_date || "";
      const endInput = document.createElement("input");
      endInput.type = "date"; endInput.className = "chip"; endInput.value = data.end_date || "";

      const saveBtn = el("button", "btn btn-primary btn-sm", "Save");
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        try {
          await ctx.api.patch("/api/funds/" + fundId, {
            name: nameInput.value.trim(),
            sponsor: sponsorInput.value.trim() || null,
            budget: Number(budgetInput.value) || 0,
            start_date: startInput.value || null,
            end_date: endInput.value || null,
          });
          ctx.toast("Fund updated", "ok");
          showDetail(fundId);
        } catch (err) {
          ctx.toast("Update failed: " + err.message, "danger");
          saveBtn.disabled = false;
        }
      });
      editForm.append(nameInput, sponsorInput, budgetInput, startInput, endInput, saveBtn);
      summary.appendChild(editForm);
    }

    const stats = el("div", "grid");
    stats.style.gridTemplateColumns = "repeat(3, 1fr)";
    stats.style.gap = "10px";
    stats.style.margin = "14px 0";
    const budgetStat = el("div", "stat");
    budgetStat.append(el("div", "stat-value", ctx.fmt.money(data.budget)), el("div", "stat-label", "Budget"));
    const spentStat = el("div", "stat");
    spentStat.append(el("div", "stat-value", ctx.fmt.money(data.spent)), el("div", "stat-label", "Spent"));
    const remainingStat = el("div", "stat");
    const remainingVal = el("div", "stat-value", ctx.fmt.money(data.remaining));
    if (data.remaining < 0 || data.pct_spent > 90) remainingVal.style.color = "var(--danger)";
    remainingStat.append(remainingVal, el("div", "stat-label", "Remaining"));
    stats.append(budgetStat, spentStat, remainingStat);
    summary.appendChild(stats);

    const barWrap = el("div");
    barWrap.style.marginBottom = "10px";
    barWrap.appendChild(burnBar(data.pct_spent, { width: 280, height: 20 }));
    summary.appendChild(barWrap);

    if (data.note) {
      summary.appendChild(el("div", "muted", data.note));
    }
    grid.appendChild(summary);

    // charge panel (managers/admins only)
    if (canManage) {
      const chargeCard = el("div", "card");
      chargeCard.appendChild(el("div", "card-title", "Charge to fund"));

      const modeRow = el("div");
      modeRow.style.display = "flex";
      modeRow.style.gap = "8px";
      modeRow.style.marginBottom = "10px";
      const manualBtn = el("button", "btn btn-sm btn-primary", "Manual");
      const poBtn = el("button", "btn btn-sm btn-ghost", "From purchase order");
      modeRow.append(manualBtn, poBtn);
      chargeCard.appendChild(modeRow);

      const manualPanel = el("div");
      manualPanel.style.display = "flex";
      manualPanel.style.flexDirection = "column";
      manualPanel.style.gap = "8px";
      const amountInput = document.createElement("input");
      amountInput.type = "number"; amountInput.step = "0.01"; amountInput.className = "chip";
      amountInput.placeholder = "Amount";
      const descInput = document.createElement("input");
      descInput.type = "text"; descInput.className = "chip";
      descInput.placeholder = "Description";
      const manualSubmit = el("button", "btn btn-primary btn-sm", "Add charge");
      manualSubmit.addEventListener("click", async () => {
        const amount = Number(amountInput.value);
        if (!amount || amount <= 0) { ctx.toast("Enter a positive amount", "warn"); amountInput.focus(); return; }
        manualSubmit.disabled = true;
        try {
          await ctx.api.post("/api/funds/" + fundId + "/charges", {
            amount,
            description: descInput.value.trim() || null,
            source_type: "manual",
          });
          ctx.toast("Charge added", "ok");
          showDetail(fundId);
        } catch (err) {
          ctx.toast("Charge failed: " + err.message, "danger");
          manualSubmit.disabled = false;
        }
      });
      manualPanel.append(amountInput, descInput, manualSubmit);
      chargeCard.appendChild(manualPanel);

      const poPanel = el("div");
      poPanel.style.display = "none";
      poPanel.style.flexDirection = "column";
      poPanel.style.gap = "8px";
      const poSelect = document.createElement("select");
      poSelect.className = "chip";
      const poSubmit = el("button", "btn btn-primary btn-sm", "Charge PO to fund");
      poSubmit.disabled = true;
      poPanel.append(poSelect, poSubmit);
      chargeCard.appendChild(poPanel);

      let posLoaded = false;
      async function loadReceivedPOs() {
        if (posLoaded) return;
        poSelect.innerHTML = "";
        try {
          const pos = await ctx.api.get("/api/purchase-orders");
          const received = (pos || []).filter((p) => p.status === "received");
          if (!received.length) {
            poSelect.appendChild(el("option", null, "No received purchase orders"));
            poSubmit.disabled = true;
          } else {
            for (const po of received) {
              const opt = el("option", null, `PO #${po.id} ${po.vendor || "--"} -- ${ctx.fmt.money(po.total_cost)}`);
              opt.value = String(po.id);
              poSelect.appendChild(opt);
            }
            poSubmit.disabled = false;
          }
          posLoaded = true;
        } catch (err) {
          poSelect.appendChild(el("option", null, "Could not load purchase orders"));
          ctx.toast("Could not load purchase orders: " + err.message, "danger");
        }
      }

      manualBtn.addEventListener("click", () => {
        manualBtn.className = "btn btn-sm btn-primary";
        poBtn.className = "btn btn-sm btn-ghost";
        manualPanel.style.display = "flex";
        poPanel.style.display = "none";
      });
      poBtn.addEventListener("click", async () => {
        poBtn.className = "btn btn-sm btn-primary";
        manualBtn.className = "btn btn-sm btn-ghost";
        poPanel.style.display = "flex";
        manualPanel.style.display = "none";
        await loadReceivedPOs();
      });
      poSubmit.addEventListener("click", async () => {
        const poId = poSelect.value;
        if (!poId) return;
        poSubmit.disabled = true;
        try {
          await ctx.api.post("/api/funds/" + fundId + "/charges", {
            source_type: "purchase_order",
            source_id: Number(poId),
          });
          ctx.toast("PO charged to fund", "ok");
          showDetail(fundId);
        } catch (err) {
          ctx.toast("Charge failed: " + err.message, "danger");
          poSubmit.disabled = false;
        }
      });

      grid.appendChild(chargeCard);
    }

    // charges table
    const chargesCard = el("div", "card");
    chargesCard.style.gridColumn = "1 / -1";
    chargesCard.style.padding = "0";
    chargesCard.appendChild((() => {
      const t = el("div", "card-title", "Charges");
      t.style.margin = "16px 16px 0";
      return t;
    })());
    const charges = data.charges || [];
    if (!charges.length) {
      const empty = el("div", "muted", "No charges recorded.");
      empty.style.padding = "16px";
      chargesCard.appendChild(empty);
    } else {
      const scroll = el("div", "table-scroll");
      const table = document.createElement("table");
      table.className = "table";
      const thead = document.createElement("thead");
      const headRow = "<tr><th>Date</th><th class=\"right\">Amount</th><th>Source</th><th>Description</th><th>By</th>" +
        (canManage ? "<th></th>" : "") + "</tr>";
      thead.innerHTML = headRow;
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const c of charges) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", "muted", c.charged_at ? ctx.fmt.date(c.charged_at) : "--"));
        tr.appendChild(el("td", "right mono", ctx.fmt.money(c.amount)));
        tr.appendChild(el("td", null, c.source_type || "--"));
        tr.appendChild(el("td", null, c.description || "--"));
        tr.appendChild(el("td", "muted", c.charged_by_username || "--"));
        if (canManage) {
          const actionTd = document.createElement("td");
          const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
          delBtn.addEventListener("click", async () => {
            if (!confirm("Delete this charge?")) return;
            delBtn.disabled = true;
            try {
              await ctx.api.del("/api/funds/" + fundId + "/charges/" + c.id);
              ctx.toast("Charge deleted", "ok");
              showDetail(fundId);
            } catch (err) {
              ctx.toast("Delete failed: " + err.message, "danger");
              delBtn.disabled = false;
            }
          });
          actionTd.appendChild(delBtn);
          tr.appendChild(actionTd);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      scroll.appendChild(table);
      chargesCard.appendChild(scroll);
    }
    grid.appendChild(chargesCard);
  }

  // ---- spend-by-person section (appended below the fund list) -------------
  async function showSpendByPerson() {
    const card = el("div", "card");
    card.style.marginTop = "16px";
    card.style.padding = "0";
    const title = el("div", "card-title", "Spend by person");
    title.style.margin = "16px 16px 0";
    card.appendChild(title);

    let data;
    try {
      data = await ctx.api.get("/api/funds/spend-by-person");
    } catch (err) {
      const e = el("div", "muted", "Could not load spend by person: " + err.message);
      e.style.padding = "16px";
      card.appendChild(e);
      container.appendChild(card);
      return;
    }

    const people = (data && data.people) || [];
    if (!people.length) {
      const empty = el("div", "muted", "No charges recorded yet.");
      empty.style.padding = "16px";
      card.appendChild(empty);
      container.appendChild(card);
      return;
    }

    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Person</th><th class=\"right\">Charges</th>" +
      "<th class=\"right\">Total charged</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const p of people) {
      const tr = document.createElement("tr");
      const who = (p.full_name && p.full_name.trim()) || p.username || "--";
      const nameTd = el("td", null, who);
      if (p.role) nameTd.appendChild(el("span", "muted", " (" + p.role + ")"));
      tr.appendChild(nameTd);
      tr.appendChild(el("td", "right mono", String(p.charge_count != null ? p.charge_count : 0)));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(p.total_charged)));
      tbody.appendChild(tr);

      const funds = p.funds || [];
      if (funds.length) {
        const breakTr = document.createElement("tr");
        const breakTd = document.createElement("td");
        breakTd.colSpan = 3;
        breakTd.style.paddingTop = "0";
        for (const fb of funds) {
          const line = el("div", "muted");
          line.style.fontSize = "12px";
          line.textContent = (fb.fund_name || "--") + " -- " + ctx.fmt.money(fb.amount);
          breakTd.appendChild(line);
        }
        breakTr.appendChild(breakTd);
        tbody.appendChild(breakTr);
      }
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    card.appendChild(scroll);
    container.appendChild(card);
  }
}
