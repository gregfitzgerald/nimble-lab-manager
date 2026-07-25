// usage.js -- per-member usage reporting (tickets, quantity, cost, by-purpose).
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "usage", label: "Usage", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const isAdmin = !!(ctx.user && ctx.user.role === "admin");

  const head = el("div");
  head.appendChild(el("h1", "view-title", "Usage"));
  head.appendChild(el("p", "view-sub", "Per-member consumption: tickets, quantity, and cost, broken down by purpose."));
  root.appendChild(head);

  const toggleHost = el("div");
  root.appendChild(toggleHost);

  const container = el("div");
  root.appendChild(container);

  await load();

  async function load() {
    container.innerHTML = "";
    toggleHost.innerHTML = "";
    let data;
    try {
      data = await ctx.api.get("/api/usage/by-member");
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load usage: " + err.message));
      return;
    }

    if (isAdmin) toggleHost.appendChild(buildAdminToggle(data.visibility));

    if (!data.can_see_all) {
      const note = el("p", "muted", "You can see only your own usage. Ask an admin to enable shared visibility.");
      container.appendChild(note);
    }

    const members = data.members || [];
    if (!members.length) {
      container.appendChild(el("div", "empty-state", "No usage recorded yet."));
      return;
    }

    // Group by_purpose rows by user_id for the sub-breakdown.
    const purposeByUser = new Map();
    for (const p of data.by_purpose || []) {
      if (!purposeByUser.has(p.user_id)) purposeByUser.set(p.user_id, []);
      purposeByUser.get(p.user_id).push(p);
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = `<thead><tr>
      <th>Member</th><th>Role</th><th class="right">Tickets</th>
      <th class="right">Total qty</th><th class="right">Total cost</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");

    for (const m of members) {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.appendChild(document.createTextNode(m.full_name || m.username));
      nameTd.appendChild(el("span", "muted", " (" + m.username + ")"));
      tr.appendChild(nameTd);
      tr.appendChild(el("td", "muted", m.role));
      tr.appendChild(el("td", "right mono", String(m.tickets)));
      tr.appendChild(el("td", "right mono", String(m.total_qty)));
      tr.appendChild(el("td", "right mono", ctx.fmt.money(m.total_cost)));
      tbody.appendChild(tr);

      const purposes = purposeByUser.get(m.user_id);
      const purTr = document.createElement("tr");
      const purTd = document.createElement("td");
      purTd.colSpan = 5;
      purTd.style.paddingTop = "0";
      if (purposes && purposes.length) {
        const line = el("div", "muted");
        line.style.fontSize = "0.9em";
        purposes.forEach((p, i) => {
          if (i > 0) line.appendChild(document.createTextNode(", "));
          line.appendChild(document.createTextNode((p.purpose || "(no purpose)") + ": " + p.qty));
        });
        purTd.appendChild(line);
      } else {
        purTd.appendChild(el("span", "muted", "No purpose breakdown."));
      }
      purTr.appendChild(purTd);
      tbody.appendChild(purTr);
    }

    table.appendChild(tbody);
    scroll.appendChild(table);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  function buildAdminToggle(visibility) {
    const card = el("div", "card");
    card.style.marginBottom = "16px";
    const row = el("label");
    row.style.display = "flex";
    row.style.gap = "8px";
    row.style.alignItems = "center";
    row.style.cursor = "pointer";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = visibility === "all";
    row.append(check, document.createTextNode("Let members see each other's usage"));
    card.appendChild(row);
    card.appendChild(el("p", "muted", "When on, all members can see this usage table for everyone; when off, members see only their own usage."));

    check.addEventListener("change", async () => {
      check.disabled = true;
      const next = check.checked ? "all" : "admin_only";
      try {
        await ctx.api.patch("/api/settings", { usage_visibility: next });
        ctx.toast("Usage visibility updated", "ok");
      } catch (err) {
        ctx.toast("Could not update visibility: " + err.message, "danger");
        check.checked = !check.checked;
      }
      check.disabled = false;
      await load();
    });

    return card;
  }
}
