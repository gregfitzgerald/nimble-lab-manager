// history.js -- audit trail of all actions by all users (manager+).
// Vanilla DOM, design-system classes only. Contract: export const view = {id,label,minRole};
// export function render(root, ctx, params).

export const view = { id: "history", label: "History", minRole: "manager" };

const LIMIT = 100;

// Actions that flag something destructive/negative -- shown with a danger badge.
const NEGATIVE_HINTS = ["deprecate", "delete", "consume"];

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

function isNegativeAction(action) {
  const a = (action || "").toLowerCase();
  return NEGATIVE_HINTS.some((h) => a.includes(h));
}

function actionCell(action) {
  const td = document.createElement("td");
  if (isNegativeAction(action)) {
    td.appendChild(el("span", "badge badge-danger", action));
  } else {
    td.textContent = action;
  }
  return td;
}

function entityCell(entry) {
  const parts = [entry.entity_type || "--"];
  if (entry.entity_id != null) parts.push("#" + entry.entity_id);
  return el("td", "mono muted", parts.join(" "));
}

function whenText(ctx, occurredAt) {
  if (!occurredAt) return "--";
  const [datePart, timePart] = occurredAt.split(" ");
  const date = ctx.fmt.date(datePart);
  return timePart ? `${date} ${timePart}` : date;
}

export async function render(root, ctx, params) {
  const state = { action: "", username: "", offset: 0, total: 0, actions: [] };

  root.appendChild(el("h1", "view-title", "History"));
  root.appendChild(el("p", "view-sub", "Audit trail of actions taken across the lab by all users."));

  const toolbar = el("div", "card");
  toolbar.style.display = "flex";
  toolbar.style.flexWrap = "wrap";
  toolbar.style.gap = "10px";
  toolbar.style.alignItems = "center";
  toolbar.style.marginBottom = "16px";
  root.appendChild(toolbar);

  const actionSelect = document.createElement("select");
  actionSelect.className = "chip";
  toolbar.appendChild(actionSelect);

  const usernameInput = document.createElement("input");
  usernameInput.type = "text";
  usernameInput.className = "chip";
  usernameInput.placeholder = "Filter by username";
  toolbar.appendChild(usernameInput);

  const applyBtn = el("button", "btn btn-ghost btn-sm", "Filter");
  toolbar.appendChild(applyBtn);

  const spacer = el("div", "spacer");
  toolbar.appendChild(spacer);

  const pageInfo = el("span", "muted", "");
  const prevBtn = el("button", "btn btn-ghost btn-sm", "Prev");
  const nextBtn = el("button", "btn btn-ghost btn-sm", "Next");
  toolbar.append(pageInfo, prevBtn, nextBtn);

  const tableWrap = el("div", "card");
  tableWrap.style.padding = "0";
  const scroll = el("div", "table-scroll");
  tableWrap.appendChild(scroll);
  root.appendChild(tableWrap);

  function buildTable() {
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = `<thead><tr>
      <th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Detail</th>
    </tr></thead><tbody></tbody>`;
    return t;
  }

  function populateActionSelect() {
    actionSelect.innerHTML = "";
    const allOpt = el("option", null, "All actions");
    allOpt.value = "";
    actionSelect.appendChild(allOpt);
    for (const a of state.actions) {
      const opt = el("option", null, a);
      opt.value = a;
      actionSelect.appendChild(opt);
    }
    actionSelect.value = state.action;
  }

  function drawRows(entries) {
    scroll.innerHTML = "";
    const table = buildTable();
    scroll.appendChild(table);
    const tbody = table.querySelector("tbody");
    if (!entries.length) {
      const tr = document.createElement("tr");
      const td = el("td", "muted", "No activity recorded yet.");
      td.colSpan = 5;
      td.style.textAlign = "center";
      td.style.padding = "28px";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const entry of entries) {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", "muted", whenText(ctx, entry.occurred_at)));
      tr.appendChild(el("td", null, entry.username || "--"));
      tr.appendChild(actionCell(entry.action));
      tr.appendChild(entityCell(entry));
      tr.appendChild(el("td", "muted", entry.detail || "--"));
      tbody.appendChild(tr);
    }
  }

  function updatePager() {
    const shownFrom = state.total === 0 ? 0 : state.offset + 1;
    const shownTo = Math.min(state.offset + LIMIT, state.total);
    pageInfo.textContent = `showing ${shownFrom}-${shownTo} of ${state.total}`;
    prevBtn.disabled = state.offset <= 0;
    nextBtn.disabled = state.offset + LIMIT >= state.total;
  }

  async function load() {
    scroll.innerHTML = "";
    scroll.appendChild(el("div", "muted", "Loading..."));
    scroll.firstChild.style.padding = "20px";
    try {
      const qs = new URLSearchParams();
      qs.set("limit", String(LIMIT));
      qs.set("offset", String(state.offset));
      if (state.action) qs.set("action", state.action);
      if (state.username) qs.set("username", state.username);
      const data = await ctx.api.get("/api/audit?" + qs.toString());
      state.total = data.total || 0;
      state.actions = data.actions || [];
      populateActionSelect();
      drawRows(data.entries || []);
      updatePager();
    } catch (err) {
      scroll.innerHTML = "";
      scroll.appendChild(el("div", "empty-state", "Could not load history: " + err.message));
      pageInfo.textContent = "";
    }
  }

  applyBtn.addEventListener("click", () => {
    state.action = actionSelect.value;
    state.username = usernameInput.value.trim();
    state.offset = 0;
    load();
  });
  actionSelect.addEventListener("change", () => {
    state.action = actionSelect.value;
    state.offset = 0;
    load();
  });
  usernameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") applyBtn.click();
  });
  prevBtn.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - LIMIT);
    load();
  });
  nextBtn.addEventListener("click", () => {
    if (state.offset + LIMIT < state.total) {
      state.offset += LIMIT;
      load();
    }
  });

  await load();
}
