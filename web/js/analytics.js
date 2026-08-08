// analytics.js -- SVG charts dashboard for Nimble Lab Manager.
// Hand-rolled inline SVG (no libraries). Theme-aware: colors reference CSS
// design tokens via var() in inline styles so they re-resolve on theme toggle.
// Exposes: export const view = { id, label }; export function render(root, ctx, params).

export const view = { id: "analytics", label: "Analytics" };

const SVGNS = "http://www.w3.org/2000/svg";

// ---- tiny DOM/SVG helpers -------------------------------------------------

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  applyAttrs(node, attrs);
  append(node, children);
  return node;
}

function svg(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVGNS, tag);
  applyAttrs(node, attrs, true);
  append(node, children);
  return node;
}

function applyAttrs(node, attrs, isSvg = false) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "class") node.setAttribute("class", v);
    else if (k === "style" && !isSvg) node.style.cssText = v;
    else if (k === "on" && typeof v === "object") {
      for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
    } else node.setAttribute(k, v);
  }
}

function append(node, children) {
  const list = Array.isArray(children) ? children : [children];
  for (const c of list) {
    if (c == null || c === false) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
}

// A chart card: title, optional controls row, and a horizontally scrollable
// plot area so wide charts scroll inside their own container (no body scroll).
function chartCard(title, { controls, subtitle } = {}) {
  const plot = el("div", { class: "chart-scroll", style: "overflow-x:auto;overflow-y:hidden;width:100%;" });
  const head = el("div", { class: "chart-head", style: "display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;" }, [
    el("div", {}, [
      el("div", { class: "card-title", text: title }),
      subtitle ? el("div", { class: "chart-sub", style: "color:var(--text-muted);font-size:12px;margin-top:2px;", text: subtitle }) : null,
    ]),
    controls || null,
  ]);
  const card = el("div", { class: "card" }, [head, plot]);
  return { card, plot, head };
}

// Legend built from DOM (theme-aware via var()).
function legend(items) {
  const wrap = el("div", { class: "chart-legend", style: "display:flex;gap:16px;flex-wrap:wrap;margin:4px 0 10px;font-size:12px;color:var(--text-muted);" });
  for (const it of items) {
    wrap.appendChild(el("span", { style: "display:inline-flex;align-items:center;gap:6px;" }, [
      it.line
        ? el("span", { style: `width:16px;height:0;border-top:2px ${it.dashed ? "dashed" : "solid"} ${it.color};display:inline-block;` })
        : el("span", { style: `width:11px;height:11px;border-radius:3px;background:${it.color};display:inline-block;` }),
      document.createTextNode(it.label),
    ]));
  }
  return wrap;
}

function emptyState(msg) {
  return el("div", { class: "chart-empty", style: "padding:32px;text-align:center;color:var(--text-muted);font-size:13px;", text: msg });
}

// ---- scales / axis helpers ------------------------------------------------

// "nice" upper bound + tick step for a max value.
function niceTicks(max, count = 5) {
  if (!isFinite(max) || max <= 0) return { top: 1, step: 1, ticks: [0, 1] };
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  let step;
  if (norm < 1.5) step = 1;
  else if (norm < 3) step = 2;
  else if (norm < 7) step = 5;
  else step = 10;
  step *= mag;
  const top = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(Number(v.toFixed(6)));
  return { top, step, ticks };
}

// Standard plot geometry.
function frame(width, height, m) {
  const iw = width - m.l - m.r;
  const ih = height - m.t - m.b;
  return { width, height, m, iw, ih, x0: m.l, y0: m.t, x1: m.l + iw, y1: m.t + ih };
}

// gridlines + y axis labels for a value axis on the left.
function yAxis(F, ticks, top, fmt) {
  const g = svg("g", {});
  for (const t of ticks) {
    const y = F.y1 - (t / top) * F.ih;
    g.appendChild(svg("line", {
      x1: F.x0, y1: y, x2: F.x1, y2: y,
      style: "stroke:var(--border);stroke-width:1;opacity:.7;",
    }));
    g.appendChild(svg("text", {
      x: F.x0 - 8, y: y + 3, "text-anchor": "end",
      style: "fill:var(--text-muted);font-size:11px;",
      text: fmt ? fmt(t) : String(t),
    }));
  }
  return g;
}

function axisLine(F) {
  return svg("g", {}, [
    svg("line", { x1: F.x0, y1: F.y1, x2: F.x1, y2: F.y1, style: "stroke:var(--text-muted);stroke-width:1;" }),
    svg("line", { x1: F.x0, y1: F.y0, x2: F.x0, y2: F.y1, style: "stroke:var(--text-muted);stroke-width:1;" }),
  ]);
}

function axisTitle(F, text, side) {
  if (side === "left") {
    return svg("text", {
      transform: `translate(${14},${F.y0 + F.ih / 2}) rotate(-90)`,
      "text-anchor": "middle", style: "fill:var(--text-muted);font-size:11px;font-weight:600;", text,
    });
  }
  if (side === "right") {
    return svg("text", {
      transform: `translate(${F.width - 12},${F.y0 + F.ih / 2}) rotate(90)`,
      "text-anchor": "middle", style: "fill:var(--text-muted);font-size:11px;font-weight:600;", text,
    });
  }
  return svg("text", {
    x: F.x0 + F.iw / 2, y: F.height - 4, "text-anchor": "middle",
    style: "fill:var(--text-muted);font-size:11px;font-weight:600;", text,
  });
}

function makeSvg(F, minWidth) {
  return svg("svg", {
    viewBox: `0 0 ${F.width} ${F.height}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "img",
    style: `width:100%;min-width:${minWidth}px;height:auto;display:block;font-family:var(--font,system-ui);`,
  });
}

// ---- Chart 1: Monthly reagent spend (bars + cumulative line) --------------

function renderSpend(plot, ctx, rows) {
  plot.innerHTML = "";
  if (!rows || !rows.length) { plot.appendChild(emptyState("No spend data yet.")); return; }

  const n = rows.length;
  const barSlot = 64;
  const width = Math.max(560, n * barSlot + 120);
  const height = 300;
  const F = frame(width, height, { l: 64, r: 60, t: 16, b: 44 });

  const maxMonthly = Math.max(...rows.map(r => r.monthly_spend || 0), 1);
  const maxCum = Math.max(...rows.map(r => r.cumulative_spend || 0), 1);
  const my = niceTicks(maxMonthly);
  const cy = niceTicks(maxCum);

  const s = makeSvg(F, 560);
  s.appendChild(yAxis(F, my.ticks, my.top, v => ctx.fmt.money(v)));
  s.appendChild(axisLine(F));
  s.appendChild(axisTitle(F, "Monthly spend", "left"));
  s.appendChild(axisTitle(F, "Cumulative", "right"));

  // right axis ticks (cumulative)
  for (const t of cy.ticks) {
    const y = F.y1 - (t / cy.top) * F.ih;
    s.appendChild(svg("text", {
      x: F.x1 + 8, y: y + 3, "text-anchor": "start",
      style: "fill:var(--text-muted);font-size:11px;",
      text: ctx.fmt.money(t),
    }));
  }

  const bw = Math.min(40, F.iw / n * 0.62);
  rows.forEach((r, i) => {
    const cx = F.x0 + (i + 0.5) * (F.iw / n);
    const h = ((r.monthly_spend || 0) / my.top) * F.ih;
    const rect = svg("rect", {
      x: cx - bw / 2, y: F.y1 - h, width: bw, height: Math.max(0, h),
      rx: 4, style: "fill:var(--accent);",
    });
    rect.appendChild(svg("title", { text: `${r.month}: ${ctx.fmt.money(r.monthly_spend || 0)}` }));
    s.appendChild(rect);
    s.appendChild(svg("text", {
      x: cx, y: F.y1 + 16, "text-anchor": "middle",
      style: "fill:var(--text-muted);font-size:10.5px;",
      text: shortMonth(r.month),
    }));
  });

  // cumulative line on right axis
  const pts = rows.map((r, i) => {
    const cx = F.x0 + (i + 0.5) * (F.iw / n);
    const y = F.y1 - ((r.cumulative_spend || 0) / cy.top) * F.ih;
    return [cx, y];
  });
  s.appendChild(svg("path", {
    d: linePath(pts),
    style: "fill:none;stroke:var(--warn);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round;",
  }));
  pts.forEach(([x, y], i) => {
    const dot = svg("circle", { cx: x, cy: y, r: 3.5, style: "fill:var(--warn);stroke:var(--bg-elev);stroke-width:1.5;" });
    dot.appendChild(svg("title", { text: `${rows[i].month} cumulative: ${ctx.fmt.money(rows[i].cumulative_spend || 0)}` }));
    s.appendChild(dot);
  });

  plot.appendChild(s);
}

// ---- Chart 2: Rate-of-use (daily consumption area) ------------------------

function renderUsage(plot, ctx, data, days) {
  plot.innerHTML = "";
  const series = (data && data.series) || [];
  if (!series.length) { plot.appendChild(emptyState("No consumption recorded in this window.")); return; }

  const n = series.length;
  const width = Math.max(600, Math.min(1400, n * 12 + 120));
  const height = 300;
  const F = frame(width, height, { l: 56, r: 20, t: 16, b: 46 });

  const maxQ = Math.max(...series.map(d => d.quantity || 0), 1);
  const qy = niceTicks(maxQ);

  const s = makeSvg(F, 600);

  // gradient for the area fill (theme-aware via var() stop colors)
  const gid = "usageGrad";
  const defs = svg("defs", {}, [
    svg("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
      svg("stop", { offset: "0%", style: "stop-color:var(--accent);stop-opacity:.35;" }),
      svg("stop", { offset: "100%", style: "stop-color:var(--accent);stop-opacity:0;" }),
    ]),
  ]);
  s.appendChild(defs);
  s.appendChild(yAxis(F, qy.ticks, qy.top, v => ctx.fmt.num(v)));
  s.appendChild(axisLine(F));
  s.appendChild(axisTitle(F, "Units consumed / day", "left"));

  const xAt = i => F.x0 + (n === 1 ? F.iw / 2 : (i / (n - 1)) * F.iw);
  const yAt = q => F.y1 - ((q || 0) / qy.top) * F.ih;
  const pts = series.map((d, i) => [xAt(i), yAt(d.quantity)]);

  // area
  const area = `M ${pts[0][0]} ${F.y1} ` + pts.map(p => `L ${p[0]} ${p[1]}`).join(" ") + ` L ${pts[n - 1][0]} ${F.y1} Z`;
  s.appendChild(svg("path", { d: area, style: `fill:url(#${gid});` }));
  // line
  s.appendChild(svg("path", { d: linePath(pts), style: "fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round;" }));

  // x labels: ~6 evenly spaced dates
  const labelEvery = Math.max(1, Math.ceil(n / 6));
  series.forEach((d, i) => {
    if (i % labelEvery !== 0 && i !== n - 1) return;
    s.appendChild(svg("text", {
      x: xAt(i), y: F.y1 + 16, "text-anchor": "middle",
      style: "fill:var(--text-muted);font-size:10.5px;",
      text: shortDate(d.date),
    }));
  });

  // hover markers (transparent hit-dots with titles)
  series.forEach((d, i) => {
    const c = svg("circle", { cx: pts[i][0], cy: pts[i][1], r: 6, style: "fill:transparent;" });
    c.appendChild(svg("title", { text: `${ctx.fmt.date(d.date)}: ${ctx.fmt.num(d.quantity || 0)} units` }));
    s.appendChild(c);
  });

  s.appendChild(axisTitle(F, `Last ${days} days`, "bottom"));
  plot.appendChild(s);
}

// ---- Chart 3: Forecast-to-stockout (ranked bars + table) ------------------

function renderForecast(plot, ctx, rows) {
  plot.innerHTML = "";
  const withRate = (rows || []).filter(r => r.days_to_stockout != null && isFinite(r.days_to_stockout));
  const noRate = (rows || []).filter(r => r.days_to_stockout == null || !isFinite(r.days_to_stockout));
  withRate.sort((a, b) => a.days_to_stockout - b.days_to_stockout);

  if (!withRate.length && !noRate.length) { plot.appendChild(emptyState("No inventory to forecast.")); return; }

  const wrap = el("div", { style: "display:grid;gap:18px;grid-template-columns:minmax(0,1fr);" });

  if (withRate.length) {
    const n = withRate.length;
    const rowH = 30;
    const width = 720;
    const height = n * rowH + 56;
    const F = frame(width, height, { l: 170, r: 64, t: 12, b: 34 });
    // Cap the axis at a 90-day horizon so a few long-runway items don't inflate
    // the scale and squash the near-term (actionable) bars into slivers. Items
    // beyond the horizon render as a full bar (healthy) but keep their real label.
    const FORECAST_HORIZON = 90;
    const maxDays = Math.min(Math.max(...withRate.map(r => r.days_to_stockout), 1), FORECAST_HORIZON);
    const dx = niceTicks(maxDays);

    const s = makeSvg(F, 520);
    // vertical gridlines + x labels
    for (const t of dx.ticks) {
      const x = F.x0 + (t / dx.top) * F.iw;
      s.appendChild(svg("line", { x1: x, y1: F.y0, x2: x, y2: F.y1, style: "stroke:var(--border);stroke-width:1;opacity:.7;" }));
      s.appendChild(svg("text", { x, y: F.y1 + 16, "text-anchor": "middle", style: "fill:var(--text-muted);font-size:11px;", text: String(t) }));
    }
    s.appendChild(axisTitle(F, "Days to stockout", "bottom"));
    s.appendChild(axisLine(F));

    withRate.forEach((r, i) => {
      const cy = F.y0 + i * rowH + rowH / 2;
      const bh = 16;
      const w = (Math.min(r.days_to_stockout, dx.top) / dx.top) * F.iw;
      const color = r.days_to_stockout <= 14 ? "var(--danger)" : r.days_to_stockout <= 30 ? "var(--warn)" : "var(--ok)";
      // label
      s.appendChild(svg("text", {
        x: F.x0 - 10, y: cy + 4, "text-anchor": "end",
        style: "fill:var(--text);font-size:11.5px;",
        text: truncate(r.item_name, 22),
      }));
      const rect = svg("rect", { x: F.x0, y: cy - bh / 2, width: Math.max(1, w), height: bh, rx: 3, style: `fill:${color};` });
      rect.appendChild(svg("title", { text: `${r.item_name}: ${Math.round(r.days_to_stockout)} days (on hand ${ctx.fmt.num(r.quantity_on_hand)}, ~${r.avg_daily_use.toFixed(2)}/day)` }));
      s.appendChild(rect);
      s.appendChild(svg("text", {
        x: F.x0 + Math.max(1, w) + 6, y: cy + 4, "text-anchor": "start",
        style: "fill:var(--text-muted);font-size:11px;",
        text: `${Math.round(r.days_to_stockout)}d`,
      }));
    });
    plot.appendChild(legend([
      { color: "var(--danger)", label: "<= 14 days (critical)" },
      { color: "var(--warn)", label: "<= 30 days" },
      { color: "var(--ok)", label: "> 30 days" },
    ]));
    wrap.appendChild(s);
  }

  // ranked table (all items)
  const tbl = el("div", { style: "overflow-x:auto;width:100%;" }, [
    el("table", { class: "table" }, [
      el("thead", {}, el("tr", {}, [
        el("th", { text: "Item" }),
        el("th", { text: "On hand" }),
        el("th", { text: "Avg/day" }),
        el("th", { text: "Days left" }),
        el("th", { text: "Status" }),
      ])),
      el("tbody", {}, [
        ...withRate.map(r => forecastRow(ctx, r)),
        ...noRate.map(r => forecastRow(ctx, r)),
      ]),
    ]),
  ]);
  wrap.appendChild(tbl);
  plot.appendChild(wrap);
}

function forecastRow(ctx, r) {
  const d = r.days_to_stockout;
  let badge, label;
  if (d == null || !isFinite(d)) { badge = "badge"; label = "no usage"; }
  else if (d <= 14) { badge = "badge badge-danger"; label = "critical"; }
  else if (d <= 30) { badge = "badge badge-warn"; label = "reorder soon"; }
  else { badge = "badge badge-ok"; label = "ok"; }
  const clickable = { style: "cursor:pointer;", on: { click: () => ctx.navigate("inventory", { itemId: r.item_id }) } };
  return el("tr", clickable, [
    el("td", { text: r.item_name }),
    el("td", { class: "right mono", text: ctx.fmt.num(r.quantity_on_hand) }),
    el("td", { class: "right mono", text: r.avg_daily_use != null ? Number(r.avg_daily_use).toFixed(2) : "--" }),
    el("td", { class: "right mono", text: d != null && isFinite(d) ? `${Math.round(d)}` : "--" }),
    el("td", {}, el("span", { class: badge, text: label })),
  ]);
}

// ---- Chart 4: Colony census (grouped bars by strain/sex) ------------------

function renderColony(plot, ctx, rows) {
  plot.innerHTML = "";
  if (!rows || !rows.length) { plot.appendChild(emptyState("No live animals recorded.")); return; }

  // group by strain, series = sex
  const strains = [];
  const sexes = [];
  const map = new Map();
  for (const r of rows) {
    const strain = r.strain || "unknown";
    const sex = (r.sex || "?");
    if (!strains.includes(strain)) strains.push(strain);
    if (!sexes.includes(sex)) sexes.push(sex);
    map.set(strain + "|" + sex, r);
  }
  const sexColor = s => {
    const k = String(s).toUpperCase();
    if (k === "M" || k === "MALE") return "var(--accent)";
    if (k === "F" || k === "FEMALE") return "var(--warn)";
    return "var(--text-muted)";
  };

  const nG = strains.length;
  const groupSlot = Math.max(70, sexes.length * 34 + 24);
  const width = Math.max(560, nG * groupSlot + 100);
  const height = 300;
  const F = frame(width, height, { l: 52, r: 20, t: 16, b: 52 });

  const maxN = Math.max(...rows.map(r => r.n_alive || 0), 1);
  const ny = niceTicks(maxN);

  const s = makeSvg(F, 560);
  s.appendChild(yAxis(F, ny.ticks, ny.top, v => ctx.fmt.num(v)));
  s.appendChild(axisLine(F));
  s.appendChild(axisTitle(F, "Animals alive", "left"));

  const gW = F.iw / nG;
  const innerPad = 0.18 * gW;
  const bandW = (gW - 2 * innerPad) / sexes.length;
  const bw = Math.min(30, bandW * 0.82);

  strains.forEach((strain, gi) => {
    const gx = F.x0 + gi * gW;
    sexes.forEach((sex, si) => {
      const rec = map.get(strain + "|" + sex);
      const val = rec ? (rec.n_alive || 0) : 0;
      const h = (val / ny.top) * F.ih;
      const cx = gx + innerPad + si * bandW + bandW / 2;
      if (val > 0) {
        const rect = svg("rect", {
          x: cx - bw / 2, y: F.y1 - h, width: bw, height: Math.max(0, h),
          rx: 3, style: `fill:${sexColor(sex)};`,
        });
        const age = rec && rec.avg_age_weeks != null ? `, avg ${Number(rec.avg_age_weeks).toFixed(1)}w` : "";
        rect.appendChild(svg("title", { text: `${strain} ${sex}: ${val} alive${age}` }));
        s.appendChild(rect);
        s.appendChild(svg("text", {
          x: cx, y: F.y1 - h - 4, "text-anchor": "middle",
          style: "fill:var(--text-muted);font-size:10px;", text: String(val),
        }));
      }
    });
    // strain label (wrapped-ish: truncate)
    s.appendChild(svg("text", {
      x: gx + gW / 2, y: F.y1 + 16, "text-anchor": "middle",
      style: "fill:var(--text);font-size:11px;", text: truncate(strain, 14),
    }));
  });

  plot.appendChild(legend(sexes.map(sx => ({ color: sexColor(sx), label: sexLabel(sx) }))));
  plot.appendChild(s);
}

// ---- small formatting utils ----------------------------------------------

function linePath(pts) {
  return pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(" ");
}

function shortMonth(m) {
  // m like "2026-06" or "2026-06-01"
  if (!m) return "";
  const parts = String(m).split("-");
  const names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  if (parts.length >= 2) {
    const mi = parseInt(parts[1], 10);
    return `${names[mi] || parts[1]} ${String(parts[0]).slice(2)}`;
  }
  return String(m);
}

function shortDate(d) {
  if (!d) return "";
  const parts = String(d).split("-");
  if (parts.length >= 3) return `${parts[1]}/${parts[2]}`;
  return String(d);
}

function truncate(s, n) {
  s = String(s == null ? "" : s);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function sexLabel(s) {
  const k = String(s).toUpperCase();
  if (k === "M") return "Male";
  if (k === "F") return "Female";
  if (k === "MALE" || k === "FEMALE") return k[0] + k.slice(1).toLowerCase();
  return String(s);
}

// ---- Cost per task (tables) ------------------------------------------------

function renderCostByTask(plot, ctx, data) {
  plot.innerHTML = "";
  const byTask = (data && data.by_task) || [];
  const byPurpose = (data && data.by_purpose) || [];

  if (!byTask.length && !byPurpose.length) {
    plot.appendChild(emptyState("No ticket-based usage yet."));
    return;
  }

  const wrap = el("div", { style: "display:grid;gap:18px;" });

  if (byTask.length) {
    wrap.appendChild(el("div", { class: "table-scroll" }, [
      el("table", { class: "table" }, [
        el("thead", {}, el("tr", {}, [
          el("th", { text: "Task" }),
          el("th", { text: "Tickets" }),
          el("th", { text: "Total qty" }),
          el("th", { text: "Total cost" }),
          el("th", { text: "Avg cost/ticket" }),
        ])),
        el("tbody", {}, byTask.map(r => el("tr", {}, [
          el("td", { text: r.task }),
          el("td", { class: "right mono", text: ctx.fmt.num(r.tickets) }),
          el("td", { class: "right mono", text: ctx.fmt.num(r.total_qty) }),
          el("td", { text: ctx.fmt.money(r.total_cost) }),
          el("td", { text: ctx.fmt.money(r.avg_cost) }),
        ]))),
      ]),
    ]));
  } else {
    wrap.appendChild(emptyState("No tasks with recorded cost yet."));
  }

  if (byPurpose.length) {
    wrap.appendChild(el("div", { class: "card-title", style: "margin-top:4px;", text: "Cost by purpose" }));
    wrap.appendChild(el("div", { class: "table-scroll" }, [
      el("table", { class: "table" }, [
        el("thead", {}, el("tr", {}, [
          el("th", { text: "Purpose" }),
          el("th", { text: "Tickets" }),
          el("th", { text: "Total cost" }),
        ])),
        el("tbody", {}, byPurpose.map(r => el("tr", {}, [
          el("td", { text: r.purpose }),
          el("td", { class: "right mono", text: ctx.fmt.num(r.tickets) }),
          el("td", { text: ctx.fmt.money(r.total_cost) }),
        ]))),
      ]),
    ]));
  }

  plot.appendChild(wrap);
}

// ---- Operations (equipment / funds / counts / top consumers) --------------

// Small label/value stat table. rows = [{label, value, danger, warn}]
function statTable(rows) {
  return el("div", { class: "table-scroll" }, [
    el("table", { class: "table" }, [
      el("tbody", {}, rows.map(r => el("tr", {}, [
        el("td", { text: r.label }),
        el("td", {}, el("span", {
          style: r.danger ? "color:var(--danger);font-weight:600;" : r.warn ? "color:var(--warn);font-weight:600;" : "",
          text: r.value,
        })),
      ]))),
    ]),
  ]);
}

function renderEquipment(plot, ctx, eq) {
  plot.innerHTML = "";
  if (!eq) { plot.appendChild(emptyState("No equipment data.")); return; }
  const wrap = el("div", { style: "display:grid;gap:14px;" });
  wrap.appendChild(statTable([
    { label: "Total", value: ctx.fmt.num(eq.total || 0) },
    { label: "Operational", value: ctx.fmt.num(eq.operational || 0) },
    { label: "In maintenance", value: ctx.fmt.num(eq.in_maintenance || 0) },
    { label: "Out of service", value: ctx.fmt.num(eq.out_of_service || 0) },
    { label: "Service overdue", value: ctx.fmt.num(eq.service_overdue || 0), danger: (eq.service_overdue || 0) > 0 },
    { label: "Due soon", value: ctx.fmt.num(eq.service_due_soon || 0), warn: (eq.service_due_soon || 0) > 0 },
    { label: "Upcoming reservations", value: ctx.fmt.num(eq.reservations_upcoming || 0) },
  ]));
  const topBooked = eq.top_booked || [];
  if (topBooked.length) {
    wrap.appendChild(el("div", { class: "card-title", style: "margin-top:2px;font-size:12px;", text: "Most booked" }));
    wrap.appendChild(el("ul", { style: "margin:0;padding-left:18px;font-size:13px;" },
      topBooked.map(b => el("li", { text: `${b.name} -- ${ctx.fmt.num(b.reservations)} reservations` }))));
  }
  plot.appendChild(wrap);
}

function renderFunds(plot, ctx, funds) {
  plot.innerHTML = "";
  if (!funds) { plot.appendChild(emptyState("No fund data.")); return; }
  const wrap = el("div", { style: "display:grid;gap:14px;" });
  wrap.appendChild(statTable([
    { label: "Total budget", value: ctx.fmt.money(funds.total_budget || 0) },
    { label: "Total spent", value: ctx.fmt.money(funds.total_spent || 0) },
    { label: "Remaining", value: ctx.fmt.money(funds.total_remaining || 0) },
  ]));
  const byFund = funds.by_fund || [];
  if (byFund.length) {
    wrap.appendChild(el("div", { class: "table-scroll" }, [
      el("table", { class: "table" }, [
        el("thead", {}, el("tr", {}, [
          el("th", { text: "Fund" }),
          el("th", { text: "Budget" }),
          el("th", { text: "Spent" }),
          el("th", { text: "Remaining" }),
          el("th", { text: "% spent" }),
        ])),
        el("tbody", {}, byFund.map(f => {
          const pct = f.pct_spent || 0;
          const danger = pct > 90;
          const warn = !danger && pct > 75;
          return el("tr", {}, [
            el("td", { text: f.name }),
            el("td", { text: ctx.fmt.money(f.budget || 0) }),
            el("td", { text: ctx.fmt.money(f.spent || 0) }),
            el("td", { text: ctx.fmt.money(f.remaining || 0) }),
            el("td", {}, el("span", {
              style: danger ? "color:var(--danger);font-weight:600;" : warn ? "color:var(--warn);font-weight:600;" : "",
              text: `${Number(pct).toFixed(0)}%`,
            })),
          ]);
        })),
      ]),
    ]));
  } else {
    wrap.appendChild(emptyState("No funds configured."));
  }
  plot.appendChild(wrap);
}

function renderCounts(plot, ctx, counts) {
  plot.innerHTML = "";
  if (!counts) { plot.appendChild(emptyState("No count session data.")); return; }
  const avgPct = (counts.avg_accuracy != null ? counts.avg_accuracy : 1) * 100;
  const wrap = el("div", { style: "display:grid;gap:14px;" });
  wrap.appendChild(statTable([
    { label: "Sessions", value: ctx.fmt.num(counts.sessions || 0) },
    { label: "Closed", value: ctx.fmt.num(counts.closed || 0) },
    { label: "Average accuracy", value: `${avgPct.toFixed(1)}%`, danger: avgPct < 90 },
  ]));
  const recent = counts.recent || [];
  if (recent.length) {
    wrap.appendChild(el("div", { class: "card-title", style: "margin-top:2px;font-size:12px;", text: "Recent counts" }));
    wrap.appendChild(el("ul", { style: "margin:0;padding-left:18px;font-size:13px;" },
      recent.map(r => el("li", { text: `${r.name_or_location} -- ${(Number(r.accuracy || 0) * 100).toFixed(1)}%` }))));
  }
  plot.appendChild(wrap);
}

function renderTopConsumers(plot, ctx, rows) {
  plot.innerHTML = "";
  if (!rows || !rows.length) { plot.appendChild(emptyState("No ticket usage recorded yet.")); return; }
  plot.appendChild(el("div", { class: "table-scroll" }, [
    el("table", { class: "table" }, [
      el("thead", {}, el("tr", {}, [
        el("th", { text: "User" }),
        el("th", { text: "Tickets" }),
        el("th", { text: "Total qty" }),
        el("th", { text: "Total cost" }),
      ])),
      el("tbody", {}, rows.map(r => el("tr", {}, [
        el("td", { text: r.full_name || r.username }),
        el("td", { class: "right mono", text: ctx.fmt.num(r.tickets) }),
        el("td", { class: "right mono", text: ctx.fmt.num(r.total_qty) }),
        el("td", { text: ctx.fmt.money(r.total_cost) }),
      ]))),
    ]),
  ]));
}

// ---- view render ----------------------------------------------------------

export async function render(root, ctx, params) {
  const grid = el("div", { class: "analytics-grid", style: "display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));" });

  // 1. Spend
  const spend = chartCard("Monthly reagent spend", { subtitle: "Bars = monthly cost, line = cumulative" });
  spend.card.insertBefore(legend([
    { color: "var(--accent)", label: "Monthly spend" },
    { color: "var(--warn)", label: "Cumulative", line: true },
  ]), spend.plot);
  spend.plot.appendChild(emptyState("Loading…"));

  // 2. Usage (with item picker)
  const picker = el("select", { class: "chip", style: "max-width:220px;" });
  const usage = chartCard("Rate of use", { subtitle: "Daily consumption", controls: picker });
  usage.plot.appendChild(emptyState("Loading…"));

  // 3. Forecast
  const forecast = chartCard("Forecast to stockout", { subtitle: "Ranked by days remaining; soonest flagged" });
  forecast.plot.appendChild(emptyState("Loading…"));

  // 4. Colony
  const colony = chartCard("Colony census", { subtitle: "Live animals grouped by strain and sex" });
  colony.plot.appendChild(emptyState("Loading…"));

  // 5. Cost per task
  const costByTask = chartCard("Cost per task", { subtitle: "Ticket spend grouped by task, sorted by total cost" });
  costByTask.plot.appendChild(emptyState("Loading…"));

  grid.append(spend.card, usage.card, forecast.card, colony.card, costByTask.card);

  // 6. Operations section (equipment, funds, counts, top consumers)
  const opsGrid = el("div", { class: "analytics-grid", style: "display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));" });
  const equipment = chartCard("Equipment", { subtitle: "Status, service, and booking" });
  equipment.plot.appendChild(emptyState("Loading…"));
  const funds = chartCard("Funds / budget", { subtitle: "Spend against allocated budget" });
  funds.plot.appendChild(emptyState("Loading…"));
  const counts = chartCard("Count accuracy", { subtitle: "Inventory count sessions" });
  counts.plot.appendChild(emptyState("Loading…"));
  const topConsumers = chartCard("Top consumers", { subtitle: "Highest usage by member" });
  topConsumers.plot.appendChild(emptyState("Loading…"));
  opsGrid.append(equipment.card, funds.card, counts.card, topConsumers.card);

  const kitsStat = el("p", { class: "muted", style: "margin:0 0 12px;font-size:13px;" });

  root.appendChild(el("div", { class: "view view-analytics" }, [
    el("h1", { class: "view-title", style: "margin:0 0 4px;", text: "Analytics" }),
    el("p", { class: "view-sub", style: "color:var(--text-muted);margin:0 0 18px;", text: "Spend, consumption, stockout risk, and colony overview." }),
    grid,
    el("h2", { class: "card-title", style: "margin:26px 0 4px;", text: "Operations" }),
    kitsStat,
    opsGrid,
  ]));

  const DAYS = 90;

  // ---- load spend
  ctx.api.get("/api/analytics/spend")
    .then(rows => renderSpend(spend.plot, ctx, rows))
    .catch(err => { spend.plot.innerHTML = ""; spend.plot.appendChild(emptyState("Failed to load spend data.")); console.error(err); });

  // ---- load forecast
  ctx.api.get("/api/analytics/forecast")
    .then(rows => renderForecast(forecast.plot, ctx, rows))
    .catch(err => { forecast.plot.innerHTML = ""; forecast.plot.appendChild(emptyState("Failed to load forecast.")); console.error(err); });

  // ---- load colony
  ctx.api.get("/api/analytics/colony")
    .then(rows => renderColony(colony.plot, ctx, rows))
    .catch(err => { colony.plot.innerHTML = ""; colony.plot.appendChild(emptyState("Failed to load colony census.")); console.error(err); });

  // ---- load cost per task
  ctx.api.get("/api/analytics/cost-by-task")
    .then(data => renderCostByTask(costByTask.plot, ctx, data))
    .catch(err => { costByTask.plot.innerHTML = ""; costByTask.plot.appendChild(emptyState("Failed to load cost-per-task data.")); console.error(err); });

  // ---- load operations dashboard
  ctx.api.get("/api/analytics/operations")
    .then(data => {
      renderEquipment(equipment.plot, ctx, data && data.equipment);
      renderFunds(funds.plot, ctx, data && data.funds);
      renderCounts(counts.plot, ctx, data && data.counts);
      renderTopConsumers(topConsumers.plot, ctx, data && data.top_consumers);
      kitsStat.textContent = `Kits assembled (all-time): ${ctx.fmt.num((data && data.kits_assembled) || 0)}`;
    })
    .catch(err => {
      const msg = "Failed to load operations data.";
      [equipment.plot, funds.plot, counts.plot, topConsumers.plot].forEach(p => {
        p.innerHTML = "";
        p.appendChild(emptyState(msg));
      });
      kitsStat.textContent = "";
      console.error(err);
    });

  // ---- usage: build item picker, then load per-selection
  const loadUsage = (itemId) => {
    usage.plot.innerHTML = "";
    usage.plot.appendChild(emptyState("Loading…"));
    const q = itemId ? `?item_id=${encodeURIComponent(itemId)}&days=${DAYS}` : `?days=${DAYS}`;
    ctx.api.get(`/api/analytics/usage${q}`)
      .then(data => {
        usage.head.querySelector(".chart-sub").textContent = data && data.item_name
          ? `Daily consumption · ${data.item_name}`
          : "Daily consumption · all items";
        renderUsage(usage.plot, ctx, data, DAYS);
      })
      .catch(err => { usage.plot.innerHTML = ""; usage.plot.appendChild(emptyState("Failed to load usage.")); console.error(err); });
  };

  ctx.api.get("/api/items")
    .then(items => {
      picker.appendChild(el("option", { value: "", text: "All items" }));
      (items || []).forEach(it => picker.appendChild(el("option", { value: String(it.item_id), text: it.item_name })));
      const initial = params && params.itemId ? String(params.itemId) : "";
      if (initial && [...picker.options].some(o => o.value === initial)) picker.value = initial;
      picker.addEventListener("change", () => loadUsage(picker.value || null));
      loadUsage(picker.value || null);
    })
    .catch(err => {
      console.error(err);
      picker.disabled = true;
      loadUsage(params && params.itemId ? params.itemId : null);
    });
}
