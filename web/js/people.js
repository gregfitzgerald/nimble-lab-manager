// people.js -- admin-only user management: list, create, activate/deactivate,
// change role, reset password, delete. Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export function render(root, ctx, params).

export const view = { id: "people", label: "People", minRole: "admin" };

const ROLES = ["viewer", "member", "manager", "admin"];

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function statusBadge(isActive) {
  return isActive
    ? el("span", "badge badge-ok", "Active")
    : el("span", "badge badge-danger", "Inactive");
}
function isSelf(ctx, row) {
  if (!ctx.user) return false;
  if (ctx.user.id != null && row.id != null) return ctx.user.id === row.id;
  return ctx.user.username === row.username;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  const state = { users: [] };

  root.appendChild(el("h1", "view-title", "People"));
  root.appendChild(el("p", "view-sub", "Manage lab accounts: roles, access, and passwords."));

  const addFormHost = el("div");
  root.appendChild(addFormHost);

  const container = el("div");
  root.appendChild(container);

  async function loadUsers() {
    state.users = await ctx.api.get("/api/users");
  }

  try {
    await loadUsers();
  } catch (err) {
    container.appendChild(el("div", "empty-state", "Could not load people: " + err.message));
    return;
  }

  buildAddForm();
  drawTable();

  // ---- add-person form ------------------------------------------------
  function buildAddForm() {
    addFormHost.innerHTML = "";
    const card = el("div", "card");
    card.style.marginBottom = "16px";
    card.appendChild(el("div", "card-title", "Add person"));

    const gridForm = el("div", "grid");
    gridForm.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
    gridForm.style.gap = "10px";

    function field(labelText, inputEl) {
      const w = el("div");
      w.style.display = "flex";
      w.style.flexDirection = "column";
      w.style.gap = "3px";
      w.appendChild(el("label", "muted", labelText));
      w.appendChild(inputEl);
      return w;
    }

    const usernameInput = document.createElement("input");
    usernameInput.type = "text";
    usernameInput.className = "chip";
    usernameInput.placeholder = "username";

    const fullNameInput = document.createElement("input");
    fullNameInput.type = "text";
    fullNameInput.className = "chip";
    fullNameInput.placeholder = "Full name";

    const roleSel = document.createElement("select");
    roleSel.className = "chip";
    for (const r of ROLES) {
      const opt = el("option", null, r);
      opt.value = r;
      roleSel.appendChild(opt);
    }
    roleSel.value = "member";

    const passwordInput = document.createElement("input");
    passwordInput.type = "password";
    passwordInput.className = "chip";
    passwordInput.placeholder = "Password";

    gridForm.append(
      field("Username *", usernameInput),
      field("Full name *", fullNameInput),
      field("Role", roleSel),
      field("Password *", passwordInput),
    );
    card.appendChild(gridForm);

    const btnRow = el("div");
    btnRow.style.marginTop = "10px";
    const submit = el("button", "btn btn-primary btn-sm", "Add person");
    submit.addEventListener("click", async () => {
      const username = usernameInput.value.trim();
      const fullName = fullNameInput.value.trim();
      const password = passwordInput.value;
      if (!username || !fullName || !password) {
        ctx.toast("Username, full name, and password are required", "warn");
        return;
      }
      submit.disabled = true;
      try {
        await ctx.api.post("/api/users", {
          username, full_name: fullName, role: roleSel.value, password,
        });
        ctx.toast("Person added", "ok");
        usernameInput.value = "";
        fullNameInput.value = "";
        passwordInput.value = "";
        roleSel.value = "member";
        try { await loadUsers(); } catch (_) { /* best-effort refresh */ }
        drawTable();
      } catch (err) {
        ctx.toast("Add failed: " + err.message, "danger");
      }
      submit.disabled = false;
    });
    btnRow.appendChild(submit);
    card.appendChild(btnRow);

    addFormHost.appendChild(card);
  }

  // ---- table ------------------------------------------------------------
  function drawTable() {
    container.innerHTML = "";

    if (!state.users.length) {
      container.appendChild(el("div", "empty-state", "No people found."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const t = document.createElement("table");
    t.className = "table";
    t.innerHTML = "<thead><tr><th>Full name</th><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>";
    const tbody = document.createElement("tbody");

    for (const row of state.users) {
      const tr = document.createElement("tr");
      tr.appendChild(el("td", null, row.full_name || "--"));
      tr.appendChild(el("td", "mono", row.username));

      const self = isSelf(ctx, row);

      const roleTd = document.createElement("td");
      const roleSel = document.createElement("select");
      roleSel.className = "chip";
      for (const r of ROLES) {
        const opt = el("option", null, r);
        opt.value = r;
        roleSel.appendChild(opt);
      }
      roleSel.value = row.role;
      roleSel.disabled = self;
      roleSel.addEventListener("change", async () => {
        roleSel.disabled = true;
        try {
          await ctx.api.patch("/api/users/" + row.id, { role: roleSel.value });
          ctx.toast("Role updated", "ok");
          try { await loadUsers(); } catch (_) { /* best-effort */ }
          drawTable();
        } catch (err) {
          ctx.toast("Role change failed: " + err.message, "danger");
          roleSel.value = row.role;
          roleSel.disabled = self;
        }
      });
      roleTd.appendChild(roleSel);
      tr.appendChild(roleTd);

      tr.appendChild(el("td", null)).appendChild(statusBadge(!!row.is_active));

      // A <td> must stay a table cell -- flexing it drops it out of the table's
      // column layout. The buttons go in a .row-actions wrapper instead.
      const actionsCell = document.createElement("td");
      const actionsTd = el("div", "row-actions");

      if (self) {
        actionsTd.appendChild(el("span", "muted", "(your account)"));
      } else {
        const toggleBtn = el("button", "btn btn-ghost btn-sm", row.is_active ? "Deactivate" : "Activate");
        toggleBtn.addEventListener("click", async () => {
          toggleBtn.disabled = true;
          try {
            await ctx.api.patch("/api/users/" + row.id, { is_active: !row.is_active });
            ctx.toast(row.is_active ? "Person deactivated" : "Person activated", "ok");
            try { await loadUsers(); } catch (_) { /* best-effort */ }
            drawTable();
          } catch (err) {
            ctx.toast("Update failed: " + err.message, "danger");
            toggleBtn.disabled = false;
          }
        });
        actionsTd.appendChild(toggleBtn);

        const resetBtn = el("button", "btn btn-ghost btn-sm", "Reset password");
        resetBtn.addEventListener("click", async () => {
          const pw = prompt("New password for " + row.username + ":");
          if (!pw) return;
          resetBtn.disabled = true;
          try {
            await ctx.api.post("/api/users/" + row.id + "/password", { password: pw });
            ctx.toast("Password reset", "ok");
          } catch (err) {
            ctx.toast("Reset failed: " + err.message, "danger");
          }
          resetBtn.disabled = false;
        });
        actionsTd.appendChild(resetBtn);

        const delBtn = el("button", "btn btn-ghost btn-sm", "Delete");
        delBtn.addEventListener("click", async () => {
          if (!confirm("Delete \"" + row.username + "\"? This cannot be undone.")) return;
          delBtn.disabled = true;
          try {
            await ctx.api.del("/api/users/" + row.id);
            ctx.toast("Person deleted", "ok");
            try { await loadUsers(); } catch (_) { /* best-effort */ }
            drawTable();
          } catch (err) {
            ctx.toast("Delete failed: " + err.message, "danger");
            delBtn.disabled = false;
          }
        });
        actionsTd.appendChild(delBtn);
      }

      actionsCell.appendChild(actionsTd);
      tr.appendChild(actionsCell);
      tbody.appendChild(tr);
    }

    t.appendChild(tbody);
    scroll.appendChild(t);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }
}
