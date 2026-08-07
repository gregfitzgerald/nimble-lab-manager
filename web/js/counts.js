// counts.js -- cycle count / stocktake sessions: list, start, scan, and close.
// Vanilla DOM, design-system classes only. Contract: export const view = {id,label,minRole};
// export async function render(root, ctx, params).

import { openScanner } from "./scanner.js";

export const view = { id: "stocktake", label: "Stocktake", minRole: "member" };

// ---- tiny helpers ---------------------------------------------------------
function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function pct(n) {
  return Math.round((n || 0) * 100) + "%";
}
function accuracyEl(accuracy) {
  const value = pct(accuracy);
  const span = el("span", null, value);
  if (accuracy < 0.9) span.style.color = "var(--danger)";
  else if (accuracy >= 1) span.style.color = "var(--ok)";
  return span;
}
function statusBadge(status) {
  if (status === "open") return el("span", "badge badge-warn", "open");
  if (status === "closed") return el("span", "badge badge-ok", "closed");
  return el("span", "badge", status);
}
function lineStatusBadge(status) {
  if (status === "found") return el("span", "badge badge-ok", "found");
  if (status === "missing") return el("span", "badge badge-danger", "missing");
  if (status === "extra") return el("span", "badge badge-warn", "extra");
  return el("span", "badge", status || "pending");
}
function boxCellText(line) {
  if (!line.box_name) return "--";
  if (line.row != null && line.col != null) {
    return `${line.box_name} ${String.fromCharCode(64 + line.row)}${line.col}`;
  }
  return line.box_name;
}

// ---- render ---------------------------------------------------------------
export async function render(root, ctx, params) {
  root.appendChild(el("h1", "view-title", "Stocktake"));
  root.appendChild(el("p", "view-sub", "Cycle counts: reconcile physical inventory against what the system expects."));

  const container = el("div");
  root.appendChild(container);

  // Deep link straight to a session detail.
  const focusId = params && params.sessionId;
  if (focusId != null) {
    await showDetail(Number(focusId));
    return;
  }
  await showList();

  // ---- list view ------------------------------------------------------
  async function showList() {
    container.innerHTML = "";

    const startCard = el("div", "card");
    startCard.style.marginBottom = "16px";
    startCard.appendChild(el("div", "card-title", "Start a count"));

    const row = el("div");
    row.style.display = "flex";
    row.style.flexWrap = "wrap";
    row.style.gap = "8px";
    row.style.alignItems = "center";

    const locSelect = document.createElement("select");
    locSelect.className = "chip";
    const wholeOpt = el("option", null, "Whole lab");
    wholeOpt.value = "";
    locSelect.appendChild(wholeOpt);
    try {
      const locs = await ctx.api.get("/api/locations");
      for (const loc of locs) {
        const opt = el("option", null, `${loc.name} -- ${loc.kind}`);
        opt.value = String(loc.id);
        locSelect.appendChild(opt);
      }
    } catch (err) {
      ctx.toast("Could not load locations: " + err.message, "danger");
    }

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "chip";
    nameInput.placeholder = "Name (optional)";
    nameInput.style.flex = "1 1 160px";

    const startBtn = el("button", "btn btn-primary btn-sm", "Start count");
    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      try {
        const body = {};
        if (locSelect.value) body.location_id = Number(locSelect.value);
        if (nameInput.value.trim()) body.name = nameInput.value.trim();
        const session = await ctx.api.post("/api/counts", body);
        ctx.toast("Count started", "ok");
        await showDetail(session.id);
      } catch (err) {
        ctx.toast("Could not start count: " + err.message, "danger");
        startBtn.disabled = false;
      }
    });

    row.append(locSelect, nameInput, startBtn);
    startCard.appendChild(row);
    container.appendChild(startCard);

    let sessions;
    try {
      sessions = await ctx.api.get("/api/counts");
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load count sessions: " + err.message));
      return;
    }

    if (!sessions.length) {
      container.appendChild(el("div", "empty-state", "No count sessions yet. Start one above."));
      return;
    }

    const tableWrap = el("div", "card");
    tableWrap.style.padding = "0";
    const scroll = el("div", "table-scroll");
    const table = document.createElement("table");
    table.className = "table";
    table.innerHTML = "<thead><tr><th>Name / location</th><th>Status</th><th>Started by</th><th>Started at</th><th class=\"right\">Accuracy</th></tr></thead>";
    const tbody = document.createElement("tbody");
    for (const s of sessions) {
      const tr = el("tr", "row-link");
      const nameTd = document.createElement("td");
      nameTd.appendChild(document.createTextNode(s.name || s.location_name || "Whole lab"));
      if (s.name && s.location_name) {
        nameTd.appendChild(el("span", "muted", " (" + s.location_name + ")"));
      }
      tr.appendChild(nameTd);
      const statusTd = document.createElement("td");
      statusTd.appendChild(statusBadge(s.status));
      tr.appendChild(statusTd);
      tr.appendChild(el("td", "muted", s.started_by_username || "--"));
      tr.appendChild(el("td", "muted", s.started_at ? ctx.fmt.date(s.started_at) : "--"));
      const accTd = el("td", "right mono");
      if (s.status === "closed") accTd.appendChild(accuracyEl(s.accuracy));
      else accTd.appendChild(el("span", "muted", "--"));
      tr.appendChild(accTd);
      tr.addEventListener("click", () => showDetail(s.id));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    scroll.appendChild(table);
    tableWrap.appendChild(scroll);
    container.appendChild(tableWrap);
  }

  // ---- detail view ------------------------------------------------------
  async function showDetail(sessionId) {
    container.innerHTML = "";
    const back = el("button", "btn btn-ghost btn-sm", "← Back to sessions");
    back.style.marginBottom = "14px";
    back.addEventListener("click", showList);
    container.appendChild(back);

    let data;
    try {
      data = await ctx.api.get("/api/counts/" + sessionId);
    } catch (err) {
      container.appendChild(el("div", "empty-state", "Could not load count session: " + err.message));
      return;
    }

    const isOpen = data.status === "open";

    const headCard = el("div", "card");
    const titleRow = el("div");
    titleRow.style.display = "flex";
    titleRow.style.alignItems = "center";
    titleRow.style.gap = "10px";
    titleRow.style.flexWrap = "wrap";
    const title = el("div", "card-title", data.name || data.location_name || "Whole lab");
    title.style.marginBottom = "0";
    titleRow.appendChild(title);
    titleRow.appendChild(statusBadge(data.status));
    headCard.appendChild(titleRow);
    const meta = el("div", "muted");
    meta.style.marginTop = "4px";
    meta.textContent = `${data.location_name || "Whole lab"} · started by ${data.started_by_username || "--"} · ${data.started_at ? ctx.fmt.date(data.started_at) : "--"}`;
    headCard.appendChild(meta);

    // summary strip
    const summary = el("div", "grid");
    summary.style.gridTemplateColumns = "repeat(5, 1fr)";
    summary.style.gap = "10px";
    summary.style.marginTop = "14px";
    const s = data.summary || {};
    const stat = (label, value, colorEl) => {
      const d = el("div", "stat");
      const v = el("div", "stat-value", value);
      if (colorEl) v.style.color = colorEl;
      d.append(v, el("div", "stat-label", label));
      return d;
    };
    summary.append(
      stat("Expected", String(s.expected != null ? s.expected : 0)),
      stat("Found", String(s.found != null ? s.found : 0)),
      stat("Missing", String(s.missing != null ? s.missing : 0), s.missing ? "var(--danger)" : null),
      stat("Extra", String(s.extra != null ? s.extra : 0), s.extra ? "var(--warn)" : null),
    );
    const accStat = el("div", "stat");
    const accVal = el("div", "stat-value", pct(s.accuracy));
    if (s.accuracy != null) {
      if (s.accuracy < 0.9) accVal.style.color = "var(--danger)";
      else if (s.accuracy >= 1) accVal.style.color = "var(--ok)";
    }
    accStat.append(accVal, el("div", "stat-label", "Accuracy"));
    summary.appendChild(accStat);
    headCard.appendChild(summary);
    container.appendChild(headCard);

    // Reconciliation panel: what the count could not find, per item. Stock is
    // never adjusted automatically -- containers are not necessarily one unit
    // each -- so each row offers an explicit "set actual quantity".
    const discrepancies = data.discrepancies || [];
    if (!isOpen && discrepancies.length) {
      const recCard = el("div", "card");
      recCard.style.marginTop = "16px";
      recCard.appendChild(el("div", "card-title", "Reconcile"));
      recCard.appendChild(el("p", "muted",
        "These items had containers the count could not find. Quantities were "
        + "not changed automatically -- set the counted amount to bring the "
        + "record in line."));
      const scroll = el("div", "table-scroll");
      const table = el("table", "table");
      const thead = el("thead");
      const hr = el("tr");
      ["Item", "Recorded", "Missing containers", ""].forEach(
        (h) => hr.appendChild(el("th", null, h)));
      thead.appendChild(hr);
      table.appendChild(thead);
      const tb = el("tbody");
      for (const d of discrepancies) {
        const tr = el("tr");
        tr.appendChild(el("td", null, d.item_name));
        tr.appendChild(el("td", null,
          d.quantity_on_hand + " " + (d.unit || "")));
        tr.appendChild(el("td", null, String(d.missing_containers)));
        const actionTd = el("td");
        const btn = el("button", "btn btn-sm", "Set actual quantity");
        btn.addEventListener("click", async () => {
          const raw = window.prompt(
            "Counted quantity for " + d.item_name
            + " (record says " + d.quantity_on_hand + "):",
            String(d.quantity_on_hand),
          );
          if (raw == null) return;
          const qty = parseInt(raw, 10);
          if (!Number.isFinite(qty) || qty < 0) {
            ctx.toast("Enter a quantity of zero or more", "warn");
            return;
          }
          btn.disabled = true;
          try {
            const res = await ctx.api.post(
              "/api/items/" + d.item_id + "/set-quantity",
              { quantity: qty, reason: "stocktake #" + sessionId },
            );
            ctx.toast(d.item_name + " set to " + res.quantity_on_hand, "ok");
            await showDetail(sessionId);
          } catch (err) {
            ctx.toast("Could not set quantity: "
              + (err && err.message ? err.message : err), "danger");
            btn.disabled = false;
          }
        });
        actionTd.appendChild(btn);
        tr.appendChild(actionTd);
        tb.appendChild(tr);
      }
      table.appendChild(tb);
      scroll.appendChild(table);
      recCard.appendChild(scroll);
      container.appendChild(recCard);
    }

    // scan box (open sessions only)
    if (isOpen) {
      const scanCard = el("div", "card");
      scanCard.style.marginTop = "16px";
      scanCard.appendChild(el("div", "card-title", "Scan or type an item code / QR URL"));
      const scanRow = el("div");
      scanRow.style.display = "flex";
      scanRow.style.gap = "8px";
      scanRow.style.marginTop = "6px";
      const scanInput = document.createElement("input");
      scanInput.type = "text";
      scanInput.className = "chip";
      scanInput.style.flex = "1 1 auto";
      scanInput.placeholder = "Item code, id, or scanned QR URL";
      const scanBtn = el("button", "btn btn-primary btn-sm", "Scan");

      // refresh=false while the camera is open: re-rendering the view would
      // tear down the modal holding the live camera stream.
      const submitCode = async (code, refresh) => {
        const result = await ctx.api.post(`/api/counts/${sessionId}/scan`, { code });
        if (result.matched) {
          ctx.toast("Found: " + ((result.line && result.line.item_name) || "item"), "ok");
        } else {
          ctx.toast("Not expected here -- logged as extra", "warn");
        }
        if (refresh) await showDetail(sessionId);
        return result;
      };

      const doScan = async () => {
        const code = scanInput.value.trim();
        if (!code) { ctx.toast("Enter a code to scan", "warn"); return; }
        scanBtn.disabled = true;
        try {
          scanInput.value = "";
          await submitCode(code, true);
        } catch (err) {
          ctx.toast("Scan failed: " + err.message, "danger");
          scanBtn.disabled = false;
        }
      };
      scanBtn.addEventListener("click", doScan);
      scanInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") doScan(); });
      scanRow.append(scanInput, scanBtn);

      // Camera scanning: the point of a stocktake is walking the shelf with a
      // phone, so keep the scanner open and count tube after tube.
      const camBtn = el("button", "btn btn-sm", "Scan with camera");
      camBtn.addEventListener("click", () => {
        let scanned = 0;
        openScanner(ctx, {
          title: "Scan to count",
          hint: "Scan each item's QR label. The count updates as you go; press "
            + "Done when finished.",
          continuous: true,
          onCode: async (code) => {
            await submitCode(code, false);
            scanned += 1;
            return true;  // keep the camera running
          },
          // Pull the freshly-counted lines in once the camera is dismissed.
          onClose: () => { if (scanned) showDetail(sessionId); },
        });
      });
      scanRow.appendChild(camBtn);
      scanCard.appendChild(scanRow);
      container.appendChild(scanCard);
    }

    // lines table
    const linesCard = el("div", "card");
    linesCard.style.marginTop = "16px";
    linesCard.style.padding = "0";
    const lines = data.lines || [];
    if (!lines.length) {
      const empty = el("div", "empty-state", "No lines recorded for this session.");
      empty.style.padding = "24px";
      linesCard.appendChild(empty);
    } else {
      const scroll = el("div", "table-scroll");
      const table = document.createElement("table");
      table.className = "table";
      const headerCells = "<th>Item</th><th>Box / row-col</th><th class=\"right\">Expected</th><th class=\"right\">Counted</th><th>Status</th>" + (isOpen ? "<th></th>" : "");
      table.innerHTML = "<thead><tr>" + headerCells + "</tr></thead>";
      const tbody = document.createElement("tbody");
      for (const line of lines) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", null, line.item_name || "(unknown item)"));
        tr.appendChild(el("td", "muted mono", boxCellText(line)));
        tr.appendChild(el("td", "right mono", String(line.expected != null ? line.expected : 0)));
        tr.appendChild(el("td", "right mono", String(line.counted != null ? line.counted : 0)));
        const statusTd = document.createElement("td");
        statusTd.appendChild(lineStatusBadge(line.status));
        tr.appendChild(statusTd);
        if (isOpen) {
          const actionsTd = document.createElement("td");
          actionsTd.style.display = "flex";
          actionsTd.style.gap = "6px";
          const foundBtn = el("button", "btn btn-ghost btn-sm", "Found");
          foundBtn.addEventListener("click", () => setLineStatus(line.id, "found", foundBtn, missingBtn));
          const missingBtn = el("button", "btn btn-ghost btn-sm", "Missing");
          missingBtn.addEventListener("click", () => setLineStatus(line.id, "missing", foundBtn, missingBtn));
          actionsTd.append(foundBtn, missingBtn);
          tr.appendChild(actionsTd);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      scroll.appendChild(table);
      linesCard.appendChild(scroll);
    }
    container.appendChild(linesCard);

    async function setLineStatus(lineId, status, foundBtn, missingBtn) {
      foundBtn.disabled = true;
      missingBtn.disabled = true;
      try {
        await ctx.api.patch(`/api/counts/${sessionId}/lines/${lineId}`, { status });
        ctx.toast("Line marked " + status, "ok");
        await showDetail(sessionId);
      } catch (err) {
        ctx.toast("Update failed: " + err.message, "danger");
        foundBtn.disabled = false;
        missingBtn.disabled = false;
      }
    }

    // close control (open sessions only)
    if (isOpen) {
      const closeCard = el("div", "card");
      closeCard.style.marginTop = "16px";
      const closeBtn = el("button", "btn btn-primary btn-sm", "Close count");
      closeBtn.addEventListener("click", async () => {
        if (!confirm("Close this count? Remaining pending lines will be marked missing.")) return;
        closeBtn.disabled = true;
        try {
          await ctx.api.post(`/api/counts/${sessionId}/close`, {});
          ctx.toast("Count closed", "ok");
          await showDetail(sessionId);
        } catch (err) {
          ctx.toast("Close failed: " + err.message, "danger");
          closeBtn.disabled = false;
        }
      });
      closeCard.appendChild(closeBtn);
      container.appendChild(closeCard);
    } else {
      // closed: show final accuracy + missing list
      const closedCard = el("div", "card");
      closedCard.style.marginTop = "16px";
      closedCard.appendChild(el("div", "card-title", "Final result"));
      const finalRow = el("div");
      finalRow.appendChild(document.createTextNode("Accuracy: "));
      finalRow.appendChild(accuracyEl(s.accuracy));
      closedCard.appendChild(finalRow);
      const missingLines = lines.filter((l) => l.status === "missing");
      if (missingLines.length) {
        const missingList = el("ul");
        missingList.style.marginTop = "8px";
        for (const l of missingLines) {
          const li = el("li", null, `${l.item_name || "(unknown item)"} -- ${boxCellText(l)}`);
          missingList.appendChild(li);
        }
        closedCard.appendChild(missingList);
      } else {
        closedCard.appendChild(el("div", "muted", "No missing items."));
      }
      container.appendChild(closedCard);
    }
  }
}
