// Settings -- admin modularity. Lets an admin rename the lab, and per module
// toggle visibility, rename its nav label, and reorder it; plus edit the
// canonical item-category list. Persists the whole UI config blob to the server
// (app_setting key `ui_config`) via PATCH /api/config, then asks the app shell
// to re-apply it live. dashboard + settings are never hide-able so the admin
// can always return here.

export const view = { id: "settings", label: "Settings", minRole: "admin" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Default item categories, shown as the textarea placeholder when the admin has
// not defined a custom list. Mirrors inventory.js's built-in defaults.
const DEFAULT_CATEGORIES = [
  "reagent", "supply", "chemical", "antibody", "enzyme",
  "media", "animal", "equipment", "other",
];

export async function render(root, ctx) {
  const catalog = (ctx.moduleCatalog && ctx.moduleCatalog()) || [];

  // Working copy of the config the admin is editing. Seeded from the live config
  // so unsaved edits never touch the running app until "Save changes".
  const live = (ctx.getConfig && ctx.getConfig()) || {};
  const work = {
    lab_name: live.lab_name || "",
    modules: {},
    item_categories: Array.isArray(live.item_categories)
      ? live.item_categories.slice() : [],
  };
  // Preserve any other keys the shell may add later.
  for (const k of Object.keys(live)) {
    if (!(k in work)) work[k] = live[k];
  }
  // Normalize a per-module entry for every catalog module, in effective order.
  const lm = live.modules || {};
  catalog.forEach((m, i) => {
    const c = lm[m.id] || {};
    work.modules[m.id] = {
      enabled: c.enabled !== false,
      label: (c.label && String(c.label).trim()) || "",
      order: (typeof c.order === "number") ? c.order : i,
    };
  });
  // Ordered list of module ids the admin can reorder in place.
  let orderIds = catalog.map((m) => m.id).sort(
    (a, b) => work.modules[a].order - work.modules[b].order
  );

  root.innerHTML = "";
  const head = el("div");
  head.appendChild(el("h1", "view-title", "Settings"));
  head.appendChild(el("p", "view-sub",
    "Admin configuration. Tailor this workspace to your lab: rename it, show or "
    + "hide modules, rename and reorder the navigation, and define item categories."));
  root.appendChild(head);

  // ----- Lab identity ------------------------------------------------------
  const idCard = el("div", "card");
  idCard.appendChild(el("div", "card-title", "Lab identity"));
  const nameRow = el("div");
  nameRow.style.display = "flex";
  nameRow.style.flexDirection = "column";
  nameRow.style.gap = "4px";
  nameRow.style.maxWidth = "420px";
  nameRow.appendChild(el("label", "muted", "Lab name (shown in the sidebar brand)"));
  const nameInput = document.createElement("input");
  nameInput.className = "chip";
  nameInput.placeholder = "Nimble Lab Manager";
  nameInput.value = work.lab_name;
  nameInput.addEventListener("input", () => { work.lab_name = nameInput.value; });
  nameRow.appendChild(nameInput);
  idCard.appendChild(nameRow);
  root.appendChild(idCard);

  // ----- Modules -----------------------------------------------------------
  const modCard = el("div", "card");
  modCard.appendChild(el("div", "card-title", "Modules"));
  modCard.appendChild(el("p", "muted",
    "Hide modules your lab doesn't use, rename them, or reorder the sidebar. "
    + "Dashboard and Settings are always visible."));
  const tableHost = el("div", "table-scroll");
  modCard.appendChild(tableHost);
  root.appendChild(modCard);

  function catOf(id) { return catalog.find((m) => m.id === id); }

  function paintModules() {
    tableHost.innerHTML = "";
    const table = el("table", "table");
    const thead = el("thead");
    const htr = el("tr");
    ["Order", "Module", "Visible", "Nav label"].forEach((h) => {
      htr.appendChild(el("th", null, h));
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");

    orderIds.forEach((id, idx) => {
      const meta = catOf(id);
      const cfg = work.modules[id];
      const tr = el("tr");

      // Order: up/down controls.
      const orderTd = el("td");
      const upBtn = el("button", "btn btn-ghost btn-sm", "^");
      upBtn.title = "Move up";
      upBtn.disabled = idx === 0;
      upBtn.addEventListener("click", () => {
        orderIds.splice(idx - 1, 0, orderIds.splice(idx, 1)[0]);
        paintModules();
      });
      const downBtn = el("button", "btn btn-ghost btn-sm", "v");
      downBtn.title = "Move down";
      downBtn.disabled = idx === orderIds.length - 1;
      downBtn.addEventListener("click", () => {
        orderIds.splice(idx + 1, 0, orderIds.splice(idx, 1)[0]);
        paintModules();
      });
      orderTd.appendChild(upBtn);
      orderTd.appendChild(document.createTextNode(" "));
      orderTd.appendChild(downBtn);
      tr.appendChild(orderTd);

      // Module: default label + id/minRole.
      const modTd = el("td");
      modTd.appendChild(el("div", null, meta.defaultLabel));
      const sub = el("div", "muted");
      sub.style.fontSize = "12px";
      sub.textContent = meta.id + (meta.minRole && meta.minRole !== "viewer"
        ? "  (min role: " + meta.minRole + ")" : "");
      modTd.appendChild(sub);
      tr.appendChild(modTd);

      // Visible checkbox (locked-on for fixed modules).
      const visTd = el("td");
      const vis = document.createElement("input");
      vis.type = "checkbox";
      vis.checked = cfg.enabled;
      if (meta.fixed) {
        vis.checked = true;
        vis.disabled = true;
        vis.title = "This module is always visible";
      }
      vis.addEventListener("change", () => { cfg.enabled = vis.checked; });
      visTd.appendChild(vis);
      tr.appendChild(visTd);

      // Nav label override.
      const lblTd = el("td");
      const lbl = document.createElement("input");
      lbl.className = "chip";
      lbl.placeholder = meta.defaultLabel;
      lbl.value = cfg.label;
      lbl.addEventListener("input", () => { cfg.label = lbl.value; });
      lblTd.appendChild(lbl);
      tr.appendChild(lblTd);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableHost.appendChild(table);
  }
  paintModules();

  // ----- Item categories ---------------------------------------------------
  const catCard = el("div", "card");
  catCard.appendChild(el("div", "card-title", "Item categories"));
  catCard.appendChild(el("p", "muted",
    "One category per line. These populate the category dropdown when adding or "
    + "editing inventory items. Leave blank to use the built-in defaults."));
  const catArea = document.createElement("textarea");
  catArea.className = "chip";
  catArea.style.width = "100%";
  catArea.style.maxWidth = "420px";
  catArea.style.minHeight = "160px";
  catArea.style.fontFamily = "monospace";
  catArea.placeholder = DEFAULT_CATEGORIES.join("\n");
  catArea.value = work.item_categories.join("\n");
  catCard.appendChild(catArea);
  root.appendChild(catCard);

  // ----- Email alert digest -----------------------------------------------
  const digestCard = el("div", "card");
  digestCard.appendChild(el("div", "card-title", "Email alert digest"));
  digestCard.appendChild(el("p", "muted",
    "A daily email summarizing open alerts -- expiring reagents, low stock, "
    + "equipment service, license and approval deadlines -- so they reach people "
    + "who are not in the app. Configure delivery on the server (NLM_SMTP_HOST, "
    + "NLM_DIGEST_TO, and NLM_SCHEDULER for the daily send); see the README. The "
    + "preview below always works, even without email configured."));
  const digestStatus = el("div", "muted", "Loading preview...");
  digestCard.appendChild(digestStatus);
  const digestBody = el("div");
  digestBody.style.marginTop = "8px";
  digestCard.appendChild(digestBody);
  const sendRow = el("div");
  sendRow.style.marginTop = "10px";
  const sendBtn = el("button", "btn", "Send test digest now");
  const sendMsg = el("span", "muted");
  sendMsg.style.marginLeft = "8px";
  sendRow.appendChild(sendBtn);
  sendRow.appendChild(sendMsg);
  digestCard.appendChild(sendRow);
  root.appendChild(digestCard);

  function renderDigestPreview(d) {
    digestBody.innerHTML = "";
    const summary = el("div", null, d.total
      ? `${d.total} open alert${d.total === 1 ? "" : "s"}`
        + (d.urgent ? ` (${d.urgent} urgent)` : "")
      : "No open alerts right now.");
    summary.style.fontWeight = "600";
    digestBody.appendChild(summary);
    for (const g of (d.groups || [])) {
      const gt = el("div", null, `${g.label} (${g.items.length})`);
      gt.style.marginTop = "6px";
      gt.style.fontWeight = "600";
      digestBody.appendChild(gt);
      const ul = el("ul");
      ul.style.margin = "2px 0 0 18px";
      for (const it of g.items) {
        const li = el("li", null, it.message);
        if (it.severity === "danger") li.style.color = "var(--danger, #b00020)";
        ul.appendChild(li);
      }
      digestBody.appendChild(ul);
    }
  }

  (async () => {
    try {
      const d = await ctx.api.get("/api/notifications/digest/preview");
      digestStatus.textContent = d.email_configured
        ? "Email delivery: configured. Recipients: "
          + ((d.recipients || []).join(", ") || "(none -- set NLM_DIGEST_TO)") + "."
        : "Email delivery: not configured on the server -- preview only.";
      renderDigestPreview(d);
    } catch (err) {
      digestStatus.textContent = "Could not load digest preview: "
        + (err && err.message ? err.message : err);
    }
  })();

  sendBtn.addEventListener("click", async () => {
    sendBtn.disabled = true;
    sendMsg.textContent = "Sending...";
    try {
      const r = await ctx.api.post("/api/notifications/digest/send", {});
      if (r.sent) {
        sendMsg.textContent = "Sent to " + r.recipients.join(", ") + ".";
        ctx.toast("Digest sent", "ok");
      } else {
        const why = {
          "no-recipients": "No recipients configured (set NLM_DIGEST_TO).",
          "smtp-not-configured": "Email is not configured on the server.",
          "no-open-alerts": "No open alerts to send.",
        }[r.reason] || r.reason;
        sendMsg.textContent = why;
        ctx.toast("Not sent: " + why, "warn");
      }
    } catch (err) {
      sendMsg.textContent = "";
      ctx.toast("Send failed: "
        + (err && err.message ? err.message : err), "danger");
    } finally {
      sendBtn.disabled = false;
    }
  });

  // ----- Save / reset ------------------------------------------------------
  const actions = el("div", "card");
  const btnRow = el("div");
  btnRow.style.display = "flex";
  btnRow.style.gap = "8px";
  btnRow.style.alignItems = "center";
  const saveBtn = el("button", "btn btn-primary", "Save changes");
  const resetBtn = el("button", "btn btn-ghost", "Reset");
  const status = el("span", "muted");
  status.style.marginLeft = "8px";
  btnRow.appendChild(saveBtn);
  btnRow.appendChild(resetBtn);
  btnRow.appendChild(status);
  actions.appendChild(btnRow);
  root.appendChild(actions);

  resetBtn.addEventListener("click", () => { render(root, ctx); });

  saveBtn.addEventListener("click", async () => {
    // Fold the reordered list + textarea into the config blob.
    orderIds.forEach((id, i) => { work.modules[id].order = i; });
    work.lab_name = nameInput.value.trim();
    work.item_categories = catArea.value.split("\n")
      .map((s) => s.trim()).filter(Boolean);
    // Drop empty label overrides so the default label is used.
    for (const id of Object.keys(work.modules)) {
      if (!work.modules[id].label) delete work.modules[id].label;
    }
    saveBtn.disabled = true;
    status.textContent = "Saving...";
    try {
      await ctx.api.patch("/api/config", work);
      if (ctx.reloadConfig) await ctx.reloadConfig();
      status.textContent = "Saved.";
      ctx.toast("Settings saved", "ok");
    } catch (err) {
      status.textContent = "";
      ctx.toast("Could not save settings: "
        + (err && err.message ? err.message : err), "danger");
    } finally {
      saveBtn.disabled = false;
    }
  });
}
