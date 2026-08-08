// labels.js -- printable QR label sheet for inventory items.
// Vanilla DOM, design-system classes only.
// Contract: export const view = {id,label,minRole}; export async function render(root, ctx, params).

export const view = { id: "labels", label: "Labels", minRole: "member" };

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

// Fields the CUSTOM template can show, in render order. Each `render(it)` returns
// a DOM node (or null when the item lacks that data). `qr` and `name` are handled
// specially in customCard.
const DEFAULT_FIELDS = ["qr", "name", "catalog", "pack", "storage", "location", "hazard"];

export async function render(root, ctx, params) {
  // Remembered custom field selection (persisted so a lab keeps its label style).
  let savedFields = null;
  try { savedFields = JSON.parse(localStorage.getItem("nlm-label-fields") || "null"); } catch (_) { savedFields = null; }
  const state = {
    items: [], filter: "all", template: "compact",
    fields: new Set(Array.isArray(savedFields) && savedFields.length ? savedFields : DEFAULT_FIELDS),
  };

  root.appendChild(el("h1", "view-title", "Labels"));
  root.appendChild(el("p", "view-sub", "Printable labels -- QR to open the item in the app, plus whatever detail you choose. Pick a template, or build a custom label."));

  // Print-only styling: hide app chrome so just the label grid prints.
  // Compact = 3 columns of small cards; detailed = 2 columns of larger cards.
  const style = document.createElement("style");
  style.textContent = `
    @media print {
      header.topbar, .toast-host, .labels-toolbar,
      .sidebar, .rail-toggle, .nav-backdrop, .hub-tabs,
      .view-title, .view-sub { display: none !important; }
      /* The shell is a sidebar+content grid on screen; printing the content
         column alone would otherwise keep the empty 190px sidebar gutter. */
      .app-shell { display: block !important; }
      .content { padding: 0 !important; }
      .label-grid { display: grid !important; gap: 8px !important; }
      .label-grid.compact { grid-template-columns: repeat(3, 1fr) !important; }
      .label-grid.detailed { grid-template-columns: repeat(2, 1fr) !important; }
      .label-card { break-inside: avoid; page-break-inside: avoid; }
    }
  `;
  root.appendChild(style);

  const toolbar = el("div", "card labels-toolbar");
  toolbar.style.display = "flex";
  toolbar.style.flexWrap = "wrap";
  toolbar.style.gap = "10px";
  toolbar.style.alignItems = "center";
  toolbar.style.marginBottom = "16px";

  const templateSelect = document.createElement("select");
  templateSelect.className = "chip";
  templateSelect.title = "Label template";
  for (const [value, label] of [["compact", "Compact labels"], ["detailed", "Detailed labels"], ["custom", "Custom label..."]]) {
    const opt = el("option", null, label);
    opt.value = value;
    templateSelect.appendChild(opt);
  }
  templateSelect.value = state.template;
  templateSelect.addEventListener("change", () => {
    state.template = templateSelect.value;
    fieldPicker.hidden = state.template !== "custom";
    drawGrid();
  });
  toolbar.appendChild(templateSelect);

  const filterSelect = document.createElement("select");
  filterSelect.className = "chip";
  filterSelect.title = "Which items";
  const filterOptions = [
    ["all", "All items"],
    ["controlled", "Controlled only"],
    ["low", "Low stock"],
  ];
  for (const [value, label] of filterOptions) {
    const opt = el("option", null, label);
    opt.value = value;
    filterSelect.appendChild(opt);
  }
  filterSelect.value = state.filter;
  filterSelect.addEventListener("change", () => {
    state.filter = filterSelect.value;
    drawGrid();
  });
  toolbar.appendChild(filterSelect);

  const spacer = el("div", "spacer");
  toolbar.appendChild(spacer);

  const printBtn = el("button", "btn btn-primary btn-sm", "Print");
  printBtn.addEventListener("click", () => window.print());
  toolbar.appendChild(printBtn);

  root.appendChild(toolbar);

  // Custom-label field picker: checkboxes for each optional field. Hidden unless
  // the "Custom label..." template is chosen. Selection persists to localStorage.
  const FIELD_META = [
    ["qr", "QR code"], ["name", "Name + flags"], ["catalog", "Catalog # / vendor"],
    ["pack", "Pack size / unit"], ["amount", "On-hand amount"], ["cas", "CAS number"],
    ["storage", "Storage temp"], ["light", "Light-sensitive"], ["location", "Location"],
    ["expiry", "Nearest expiry"], ["hazard", "Hazard chips"],
  ];
  const fieldPicker = el("div", "card labels-toolbar");
  fieldPicker.hidden = state.template !== "custom";
  fieldPicker.style.marginBottom = "16px";
  fieldPicker.appendChild(el("div", "card-title", "Custom label fields"));
  const pickRow = el("div");
  pickRow.style.display = "flex";
  pickRow.style.flexWrap = "wrap";
  pickRow.style.gap = "12px";
  for (const [key, label] of FIELD_META) {
    const wrap = el("label", "muted");
    wrap.style.display = "flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "5px";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.fields.has(key);
    cb.addEventListener("change", () => {
      if (cb.checked) state.fields.add(key); else state.fields.delete(key);
      try { localStorage.setItem("nlm-label-fields", JSON.stringify([...state.fields])); } catch (_) { /* ignore */ }
      drawGrid();
    });
    wrap.append(cb, document.createTextNode(label));
    pickRow.appendChild(wrap);
  }
  fieldPicker.appendChild(pickRow);
  root.appendChild(fieldPicker);

  const gridHost = el("div");
  root.appendChild(gridHost);

  try {
    state.items = await ctx.api.get("/api/items");
  } catch (err) {
    gridHost.appendChild(el("div", "empty-state", "Could not load items: " + err.message));
    return;
  }

  drawGrid();

  function filtered() {
    return state.items.filter((it) => {
      if (state.filter === "controlled") return it.is_controlled;
      if (state.filter === "low") return it.is_low_stock;
      return true;
    });
  }

  // A QR image sized for the given template.
  function qrImg(it, size) {
    const img = document.createElement("img");
    img.src = "/api/items/" + encodeURIComponent(it.item_id) + "/qr.svg";
    img.width = size;
    img.height = size;
    img.alt = "QR for " + it.item_name;
    return img;
  }

  // Controlled / expiry badges shared by both templates.
  function controlledBadge(it) {
    const label = it.controlled_schedule ? "controlled " + it.controlled_schedule : "controlled";
    return el("span", "badge badge-warn", label);
  }
  function expiryBadge(it) {
    if (it.expiry_flag === "expired") return el("span", "badge badge-danger", "expired");
    if (it.expiry_flag === "expiring") return el("span", "badge badge-warn", "expiring");
    return null;
  }

  function drawGrid() {
    gridHost.innerHTML = "";
    const rows = filtered();
    if (!rows.length) {
      gridHost.appendChild(el("div", "empty-state", "No items to label."));
      return;
    }

    const tpl = state.template;
    const wide = tpl === "detailed" || tpl === "custom";
    const grid = el("div", "grid grid-cards label-grid " + (wide ? "detailed" : "compact"));
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = wide
      ? "repeat(auto-fill, minmax(280px, 1fr))"
      : "repeat(auto-fill, minmax(180px, 1fr))";
    grid.style.gap = "12px";

    for (const it of rows) {
      grid.appendChild(
        tpl === "compact" ? compactCard(it)
          : tpl === "detailed" ? detailedCard(it)
            : customCard(it));
    }

    gridHost.appendChild(grid);
  }

  // Custom card: QR (optional) + only the fields the user checked, in a fixed order.
  function customCard(it) {
    const card = el("div", "card label-card");
    card.style.display = "flex";
    card.style.gap = "12px";
    card.style.alignItems = "flex-start";
    card.style.textAlign = "left";

    if (state.fields.has("qr")) {
      const qrCol = el("div");
      qrCol.style.flex = "0 0 auto";
      qrCol.appendChild(qrImg(it, 100));
      card.appendChild(qrCol);
    }

    const info = el("div");
    info.style.flex = "1 1 auto";
    info.style.minWidth = "0";
    info.style.display = "flex";
    info.style.flexDirection = "column";
    info.style.gap = "3px";
    for (const key of ["name", "catalog", "pack", "amount", "cas", "storage", "light", "location", "expiry", "hazard"]) {
      if (!state.fields.has(key)) continue;
      const node = renderField(key, it);
      if (node) info.appendChild(node);
    }
    // A label with no QR and no fields would be blank -- show the name as a floor.
    if (!info.childNodes.length && !state.fields.has("qr")) info.appendChild(el("strong", null, it.item_name));
    card.appendChild(info);
    return card;
  }

  // Render one optional field to a DOM node, or null when the item lacks it.
  function renderField(key, it) {
    if (key === "name") {
      const nameRow = el("div");
      nameRow.style.display = "flex";
      nameRow.style.gap = "6px";
      nameRow.style.alignItems = "center";
      nameRow.style.flexWrap = "wrap";
      const name = el("strong", null, it.item_name);
      name.style.fontSize = "1.05em";
      nameRow.appendChild(name);
      if (it.is_controlled) nameRow.appendChild(controlledBadge(it));
      const exp = expiryBadge(it);
      if (exp) nameRow.appendChild(exp);
      return nameRow;
    }
    if (key === "catalog") {
      const parts = [];
      if (it.catalog_number) parts.push("Cat# " + it.catalog_number);
      if (it.vendor) parts.push(it.vendor);
      return parts.length ? el("div", "muted", parts.join(" - ")) : null;
    }
    if (key === "pack") {
      const parts = [];
      if (it.size) parts.push(String(it.size));
      if (it.unit) parts.push(it.unit);
      return parts.length ? labelLine("Pack", parts.join(" ")) : null;
    }
    if (key === "amount") {
      const v = (it.amount != null && it.amount !== "") ? String(it.amount)
        : (it.quantity_on_hand != null ? String(it.quantity_on_hand) : null);
      return v ? labelLine("On hand", v) : null;
    }
    if (key === "cas") return it.cas_number ? labelLine("CAS", it.cas_number) : null;
    if (key === "storage") {
      return (it.storage_temp != null && String(it.storage_temp) !== "")
        ? labelLine("Store", String(it.storage_temp)) : null;
    }
    if (key === "light") return it.light_sensitive ? labelLine("Light", "store in dark") : null;
    if (key === "location") return it.location ? labelLine("Loc", it.location) : null;
    if (key === "expiry") return it.nearest_expiry ? labelLine("Expiry", ctx.fmt.date(it.nearest_expiry)) : null;
    if (key === "hazard") {
      if (!it.hazard_class) return null;
      const hazards = String(it.hazard_class).split(",").map((h) => h.trim()).filter(Boolean);
      if (!hazards.length) return null;
      const row = el("div");
      row.style.display = "flex";
      row.style.gap = "4px";
      row.style.flexWrap = "wrap";
      row.style.marginTop = "2px";
      for (const h of hazards) row.appendChild(el("span", "badge badge-warn", h));
      return row;
    }
    return null;
  }

  // Compact card: QR + name + vendor / category / unit + controlled badge.
  function compactCard(it) {
    const card = el("div", "card label-card");
    card.style.textAlign = "center";
    card.style.display = "flex";
    card.style.flexDirection = "column";
    card.style.alignItems = "center";
    card.style.gap = "4px";

    card.appendChild(qrImg(it, 96));

    const nameRow = el("div");
    nameRow.style.display = "flex";
    nameRow.style.gap = "6px";
    nameRow.style.alignItems = "center";
    nameRow.style.justifyContent = "center";
    nameRow.style.flexWrap = "wrap";
    nameRow.appendChild(el("strong", null, it.item_name));
    if (it.is_controlled) nameRow.appendChild(controlledBadge(it));
    card.appendChild(nameRow);

    card.appendChild(el("div", "muted", it.vendor || "--"));
    card.appendChild(el("div", "muted", it.category || "uncategorized"));
    card.appendChild(el("div", "muted", it.unit || ""));

    return card;
  }

  // Detailed card: QR on the left, information-rich column on the right.
  function detailedCard(it) {
    const card = el("div", "card label-card");
    card.style.display = "flex";
    card.style.gap = "12px";
    card.style.alignItems = "flex-start";
    card.style.textAlign = "left";

    const qrCol = el("div");
    qrCol.style.flex = "0 0 auto";
    qrCol.appendChild(qrImg(it, 100));
    card.appendChild(qrCol);

    const info = el("div");
    info.style.flex = "1 1 auto";
    info.style.minWidth = "0";
    info.style.display = "flex";
    info.style.flexDirection = "column";
    info.style.gap = "3px";

    // Name + flag badges.
    const nameRow = el("div");
    nameRow.style.display = "flex";
    nameRow.style.gap = "6px";
    nameRow.style.alignItems = "center";
    nameRow.style.flexWrap = "wrap";
    const name = el("strong", null, it.item_name);
    name.style.fontSize = "1.05em";
    nameRow.appendChild(name);
    if (it.is_controlled) nameRow.appendChild(controlledBadge(it));
    const exp = expiryBadge(it);
    if (exp) nameRow.appendChild(exp);
    info.appendChild(nameRow);

    // Catalog # and vendor.
    const idParts = [];
    if (it.catalog_number) idParts.push("Cat# " + it.catalog_number);
    if (it.vendor) idParts.push(it.vendor);
    if (idParts.length) info.appendChild(el("div", "muted", idParts.join(" - ")));

    // Pack size / unit.
    const packParts = [];
    if (it.size) packParts.push(String(it.size));
    if (it.unit) packParts.push(it.unit);
    if (packParts.length) info.appendChild(labelLine("Pack", packParts.join(" ")));

    // CAS number.
    if (it.cas_number) info.appendChild(labelLine("CAS", it.cas_number));

    // Storage temperature.
    if (it.storage_temp != null && String(it.storage_temp) !== "") {
      info.appendChild(labelLine("Store", String(it.storage_temp)));
    }

    // Location.
    if (it.location) info.appendChild(labelLine("Loc", it.location));

    // Hazard chips.
    if (it.hazard_class) {
      const hazards = String(it.hazard_class)
        .split(",")
        .map((h) => h.trim())
        .filter(Boolean);
      if (hazards.length) {
        const hazRow = el("div");
        hazRow.style.display = "flex";
        hazRow.style.gap = "4px";
        hazRow.style.flexWrap = "wrap";
        hazRow.style.marginTop = "2px";
        for (const h of hazards) hazRow.appendChild(el("span", "badge badge-warn", h));
        info.appendChild(hazRow);
      }
    }

    card.appendChild(info);
    return card;
  }

  // A "Label: value" line -- muted label prefix, default-black value.
  function labelLine(label, value) {
    const line = el("div");
    line.style.fontSize = "0.9em";
    const tag = el("span", "muted", label + ": ");
    line.appendChild(tag);
    line.appendChild(document.createTextNode(value));
    return line;
  }
}
