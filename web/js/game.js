// Lab Tycoon -- a resource-management mini-sim that drives the REAL API.
//
// Teaching goal: this is not a toy separate from the app. Every shift, NPC
// researchers generate DEMAND and we persist it as real POST
// /api/items/{id}/consume calls, so the SQLite database actually changes. The
// player manages SUPPLY under a GRANT BUDGET: reorder before a reorder point
// triggers a stockout, size each order so reagents get used before they EXPIRE
// (paid-for stock that spoils is money wasted), and account for supplier LEAD
// TIMES and BACKORDERS. Random events (freezer failure, price spike, rush
// deadline) and a rising difficulty curve mirror the chaos of a real lab. You
// play one grant period and are graded win/lose at the end.
//
// Contract: exports view = {id,label} and render(root, ctx, params).
// Uses ONLY ctx (api, navigate, toast, fmt) and the shared design system.

export const view = { id: 'game', label: 'Tutorial' };

// ---------------------------------------------------------------------------
// Tuning constants (the game's "rules"). Kept together so they read as a spec.
// ---------------------------------------------------------------------------
const TICK_MS = 1000;          // one simulated "shift" = 1s of real time at 1x
const MAX_DELTA_MS = 1000;     // clamp frame delta so a backgrounded tab can't
                               // dump hundreds of ticks at once (spiral of death)
const MAX_CATCHUP_TICKS = 4;   // hard cap on ticks processed per rAF frame
const SPEEDS = [1, 2, 4];

const GRANT_PERIOD = 36;       // shifts in one grant cycle -> win/lose at the end
const ROUND_LEN = 9;           // shifts per "round"; difficulty steps each round
const START_BUDGET = 600;      // opening grant funds to spend on reorders
const INSTALLMENT = 300;       // grant installment paid at the end of each round
const WIN_SCORE = 120;         // final score needed to "keep the grant"

const PRODUCTIVITY_PER_UNIT = 2;   // score per satisfied demand unit
const STOCKOUT_PENALTY = 4;        // score lost per unit of unfilled demand
const WASTE_PENALTY = 3;           // score lost per unit spoiled/expired
const BASE_UNIT_COST = 8;          // fallback purchase price when item has none

const ORDER_SIZES = [              // reorder decisions: little-and-often vs bulk
  { label: '+6', qty: 6 },
  { label: 'Bulk +18', qty: 18 },
];
const SHELF_LIFE = 16;         // shifts a fresh lot stays usable before spoiling
const BASE_LEAD_TIME = 2;      // shifts before a normal order arrives
const BACKORDER_CHANCE = 0.2;  // chance any single order is back-ordered (slower)

const DIFFICULTY_STEP = 0.22;  // demand growth per round (the difficulty curve)
const EVENT_BASE_CHANCE = 0.06;// per-shift random-event probability floor
const EVENT_MAX_CHANCE = 0.17; // ...and its ceiling as the period wears on
const RUSH_MULT = 1.8;         // demand multiplier during a rush-deadline event
const LOG_LIMIT = 40;

// NPC roster. Each researcher has a consumption PROFILE: keyword-matched
// preferred items + a per-shift rate. Rates are fractional and accumulate, so a
// rate of 0.4 means "roughly 2 units every 5 shifts". staffHint maps onto a real
// staff row (best-effort) so persisted usage_events carry a plausible staff_id.
const NPC_PROFILES = [
  { key: 'rivera', name: 'Dr. Rivera',  role: 'Surgery',     staffHint: 'Rivera',
    keywords: ['isoflurane', 'ketamine', 'anesth'], rate: 0.55 },
  { key: 'okafor', name: 'Dr. Okafor',  role: 'Histology',   staffHint: 'Okafor',
    keywords: ['paraform', 'pfa', 'slide', 'formalin', 'stain'], rate: 0.45 },
  { key: 'chen',   name: 'Dr. Chen',    role: 'Immuno',      staffHint: 'Chen',
    keywords: ['antibody', 'anti-', 'igg', 'serum'], rate: 0.25 },
  { key: 'patel',  name: 'S. Patel',    role: 'Bench tech',  staffHint: 'Patel',
    keywords: ['tip', 'pipette', 'tube', 'plate', 'consumable'], rate: 0.7 },
  { key: 'nguyen', name: 'L. Nguyen',   role: 'Undergrad',   staffHint: 'Nguyen',
    keywords: ['media', 'buffer', 'pbs', 'enzyme', 'agar', 'dmem'], rate: 0.4 },
];

// ---------------------------------------------------------------------------
// Module-level loop control. render() bumps `generation`; any in-flight rAF loop
// from a previous mount sees the mismatch (or a detached root) and self-cancels.
// ---------------------------------------------------------------------------
let generation = 0;
let rafId = null;

function stopLoop() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
}

// ---------------------------------------------------------------------------
// render
// ---------------------------------------------------------------------------
export async function render(root, ctx, params) {
  generation += 1;
  const myGen = generation;
  stopLoop();

  root.innerHTML = shell();

  // Fetch the REAL inventory + staff so the sim is seeded from the database.
  let items = [];
  let staff = [];
  try {
    items = await ctx.api.get('/api/items');
  } catch (err) {
    root.querySelector('#lt-supply').innerHTML =
      `<div class="card"><div class="card-title">Could not load inventory</div>
       <div style="color:var(--text-muted)">${escapeHtml(String(err))}</div></div>`;
    return;
  }
  try { staff = await ctx.api.get('/api/staff'); } catch (_) { staff = []; }

  // If a newer render started while we awaited, abandon this mount.
  if (myGen !== generation) return;

  const state = buildState(items, staff);

  // Wire controls + first paint.
  bindControls(root, ctx, state, myGen);
  paintDynamic(root, state, ctx);

  startLoop(root, ctx, state, myGen);
}

// ---------------------------------------------------------------------------
// State construction -- map real items onto supplies and assign NPCs.
// ---------------------------------------------------------------------------
function buildState(items, staff) {
  const supplies = items.map((it) => {
    const flag = it.expiry_flag || 'none';
    // Seed shelf life from the item's real expiry flag so already-old stock
    // starts closer to spoiling (teaches you to rotate the oldest lots first).
    const fresh = flag === 'expired' ? 2 : flag === 'expiring' ? 5 : SHELF_LIFE;
    return {
      id: it.item_id,
      name: it.item_name,
      unit: it.unit || 'unit',
      onHand: Number(it.quantity_on_hand) || 0,
      reorder: Number(it.reorder_threshold) || 0,
      unitCost: Number(it.unit_cost) || 0,
      expiryFlag: flag,        // ok | expiring | expired | none
      freshShifts: fresh,      // shifts until the current stock spoils
      pendingConsume: 0,       // batched units to persist on the next flush
    };
  });

  const byId = new Map(supplies.map((s) => [s.id, s]));

  // Assign each NPC a preferred supply by keyword; fall back round-robin so
  // every researcher always has something to consume even on odd seed data.
  const used = new Set();
  const npcs = NPC_PROFILES.map((p, idx) => {
    let target = supplies.find(
      (s) => !used.has(s.id) && p.keywords.some((k) => s.name.toLowerCase().includes(k))
    );
    if (!target) target = supplies.find((s) => !used.has(s.id));
    if (!target) target = supplies[idx % Math.max(supplies.length, 1)];
    if (target) used.add(target.id);

    const staffRow = staff.find((s) =>
      (s.full_name || '').toLowerCase().includes(p.staffHint.toLowerCase()));

    return {
      key: p.key,
      name: p.name,
      role: p.role,
      rate: p.rate,
      itemId: target ? target.id : null,
      itemName: target ? target.name : '(no item)',
      staffId: staffRow ? staffRow.staff_id : null,
      accrual: 0,      // fractional demand carried between shifts
      blocked: false,  // last shift ended in a stockout for this NPC
    };
  }).filter((n) => n.itemId !== null);

  return {
    supplies,
    byId,
    npcs,
    running: false,
    speed: 1,
    accumulator: 0,
    lastTs: 0,
    shift: 0,          // completed sim shifts
    score: 0,
    productivity: 0,
    stockouts: 0,
    waste: 0,
    // Economy / logistics.
    budget: START_BUDGET,
    spent: 0,
    wastedCash: 0,     // dollars of paid-for stock that spoiled
    pendingOrders: [], // {itemId,name,qty,cost,arriveShift,backordered}
    // Active event modifiers (0 = inactive).
    priceMult: 1, priceUntil: 0,
    rushUntil: 0,
    leadPenalty: 0, leadUntil: 0,
    // End state.
    gameOver: false,
    outcome: null,     // 'win' | 'lose'
    log: [],
  };
}

// ---------------------------------------------------------------------------
// Fixed-timestep loop: rAF + accumulator. Real time drives simulated shifts.
// ---------------------------------------------------------------------------
function startLoop(root, ctx, state, myGen) {
  state.lastTs = performance.now();

  const frame = (ts) => {
    // Self-cancel if superseded or detached from the DOM.
    if (myGen !== generation || !root.isConnected) {
      stopLoop();
      return;
    }

    const raw = ts - state.lastTs;
    state.lastTs = ts;

    if (state.running && !state.gameOver) {
      const delta = Math.min(Math.max(raw, 0), MAX_DELTA_MS);
      state.accumulator += delta * state.speed;

      let processed = 0;
      let dirty = false;
      while (state.accumulator >= TICK_MS && processed < MAX_CATCHUP_TICKS
             && !state.gameOver) {
        state.accumulator -= TICK_MS;
        processed += 1;
        const result = computeTick(state);
        applyTick(state, result);
        flushPersistence(ctx, state, result);
        dirty = true;
      }
      // Drop any leftover backlog beyond the catch-up cap.
      if (state.accumulator >= TICK_MS) state.accumulator = 0;
      if (dirty) paintDynamic(root, state, ctx);
    }

    rafId = requestAnimationFrame(frame);
  };

  rafId = requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// Difficulty curve: demand ramps up each round.
// ---------------------------------------------------------------------------
function roundOf(shift) { return Math.floor(shift / ROUND_LEN) + 1; }
function difficultyMult(shift) { return 1 + (roundOf(shift) - 1) * DIFFICULTY_STEP; }

// ---------------------------------------------------------------------------
// computeTick: reads current state and produces the demands, arrivals, spoilage,
// event, and score deltas for ONE simulated shift. It does NOT mutate state or
// call the API -- applyTick / flushPersistence do that.
// ---------------------------------------------------------------------------
function computeTick(state) {
  const nextShift = state.shift + 1;
  const demandMult = difficultyMult(state.shift)
                     * (state.rushUntil > state.shift ? RUSH_MULT : 1);

  // Snapshot available stock so multiple NPCs share the same shift's supply.
  const avail = new Map(state.supplies.map((s) => [s.id, s.onHand]));
  const consumeByItem = new Map();   // itemId -> units actually taken this shift
  const npcAccrual = new Map();      // npc.key -> new fractional accrual
  const blocked = new Map();         // npc.key -> bool
  const events = [];
  let dProd = 0, dStock = 0, dWaste = 0;

  for (const npc of state.npcs) {
    const want = npc.accrual + npc.rate * demandMult;
    const demand = Math.floor(want);
    npcAccrual.set(npc.key, want - demand);
    if (demand <= 0) { blocked.set(npc.key, false); continue; }

    const supply = state.byId.get(npc.itemId);
    const have = avail.get(npc.itemId) || 0;
    const taken = Math.min(demand, have);
    const short = demand - taken;

    if (taken > 0) {
      avail.set(npc.itemId, have - taken);
      consumeByItem.set(npc.itemId, (consumeByItem.get(npc.itemId) || 0) + taken);
      dProd += taken * PRODUCTIVITY_PER_UNIT;
      events.push({ kind: 'ok', text: `${npc.name} consumed ${taken} ${supply.name}` });
    }
    if (short > 0) {
      dStock += short * STOCKOUT_PENALTY;
      events.push({ kind: 'danger',
        text: `STOCKOUT: ${supply.name} -> ${npc.name} loses ${short} unit(s) of work` });
    }
    blocked.set(npc.key, short > 0);
  }

  // Orders that land at the end of this shift (usable next shift).
  const arrivals = state.pendingOrders.filter((o) => o.arriveShift <= nextShift);
  const arrivalIds = new Set(arrivals.map((o) => o.itemId));

  // Shelf-life aging: stock whose freshness runs out this shift spoils. This is
  // the expiry lesson -- reagents you bought but did not use become pure waste.
  const spoilage = [];
  for (const s of state.supplies) {
    if (arrivalIds.has(s.id)) continue;         // a fresh lot arrives; skip aging
    const newFresh = s.freshShifts - 1;
    const left = avail.get(s.id) || 0;
    if (newFresh <= 0 && left > 0) {
      spoilage.push({ itemId: s.id, qty: left, name: s.name, unitCost: s.unitCost });
      dWaste += left * WASTE_PENALTY;
      events.push({ kind: 'warn',
        text: `EXPIRED & DISCARDED: ${left} ${s.name} passed shelf life` });
    }
  }

  // Roll one random event (probability climbs across the grant period).
  const event = rollEvent(state);

  return { nextShift, consumeByItem, npcAccrual, blocked, arrivals, arrivalIds,
           spoilage, event, events, dProd, dStock, dWaste };
}

function rollEvent(state) {
  const chance = Math.min(EVENT_BASE_CHANCE + state.shift * 0.004, EVENT_MAX_CHANCE);
  if (Math.random() > chance) return null;
  const types = ['freezer', 'price', 'rush', 'windfall', 'backorder'];
  return { type: types[Math.floor(Math.random() * types.length)] };
}

// Mutate state from a computed tick (the only place tick results land).
function applyTick(state, r) {
  state.shift += 1;

  // 1. Consumption.
  for (const [itemId, qty] of r.consumeByItem) {
    const s = state.byId.get(itemId);
    if (s) { s.onHand = Math.max(0, s.onHand - qty); s.pendingConsume += qty; }
  }

  // 2. Spoilage removes stock (waste already counted in r.dWaste).
  for (const sp of r.spoilage) {
    const s = state.byId.get(sp.itemId);
    if (s) {
      s.onHand = Math.max(0, s.onHand - sp.qty);
      state.wastedCash += Math.round(sp.qty * (sp.unitCost > 0 ? sp.unitCost : BASE_UNIT_COST));
    }
  }

  // 3. Arrivals add fresh stock and reset the shelf-life clock.
  for (const o of r.arrivals) {
    const s = state.byId.get(o.itemId);
    if (s) {
      s.onHand += o.qty;
      s.freshShifts = SHELF_LIFE;
      s.expiryFlag = 'none';
      const badge = o.backordered ? ' (was back-ordered)' : '';
      state.log.unshift({ kind: 'ok', shift: state.shift,
        text: `RECEIVED ${o.qty} ${s.name}${badge}` });
    }
  }
  state.pendingOrders = state.pendingOrders.filter((o) => o.arriveShift > state.shift);

  // 4. Age everything that did not just receive a lot; refresh expiry flags.
  for (const s of state.supplies) {
    if (r.arrivalIds.has(s.id)) continue;
    s.freshShifts = Math.max(0, s.freshShifts - 1);
    if (s.onHand <= 0) s.expiryFlag = 'none';
    else if (s.freshShifts <= 0) s.expiryFlag = 'expired';
    else if (s.freshShifts <= 3) s.expiryFlag = 'expiring';
    else s.expiryFlag = 'none';
  }

  // 5. Random event effects (may add waste / cash / modifiers).
  if (r.event) {
    for (const ev of applyEvent(state, r.event, r)) {
      state.log.unshift({ ...ev, shift: state.shift });
    }
  }

  // 6. NPC accrual / blocked status.
  for (const npc of state.npcs) {
    if (r.npcAccrual.has(npc.key)) npc.accrual = r.npcAccrual.get(npc.key);
    if (r.blocked.has(npc.key)) npc.blocked = r.blocked.get(npc.key);
  }

  // 7. Score.
  state.score += r.dProd - r.dStock - r.dWaste;
  state.productivity += r.dProd;
  state.stockouts += r.dStock;
  state.waste += r.dWaste;

  // 8. Grant installment at each round boundary (funding cycle).
  if (state.shift > 0 && state.shift % ROUND_LEN === 0 && state.shift < GRANT_PERIOD) {
    state.budget += INSTALLMENT;
    state.log.unshift({ kind: 'ok', shift: state.shift,
      text: `GRANT INSTALLMENT received: +$${INSTALLMENT}` });
  }

  // 9. Log the shift's activity.
  for (const ev of r.events) state.log.unshift({ ...ev, shift: state.shift });
  if (state.log.length > LOG_LIMIT) state.log.length = LOG_LIMIT;

  // 10. Expire spent modifiers.
  if (state.priceUntil && state.shift >= state.priceUntil) { state.priceMult = 1; state.priceUntil = 0; }
  if (state.rushUntil && state.shift >= state.rushUntil) state.rushUntil = 0;
  if (state.leadUntil && state.shift >= state.leadUntil) { state.leadPenalty = 0; state.leadUntil = 0; }

  // 11. End of the grant period -> grade the player.
  if (state.shift >= GRANT_PERIOD) {
    state.gameOver = true;
    state.running = false;
    state.outcome = state.score >= WIN_SCORE ? 'win' : 'lose';
    state.log.unshift({ kind: state.outcome === 'win' ? 'ok' : 'danger', shift: state.shift,
      text: state.outcome === 'win'
        ? `GRANT PERIOD COMPLETE -- renewed! Final score ${Math.round(state.score)}`
        : `GRANT PERIOD COMPLETE -- not renewed. Final score ${Math.round(state.score)}` });
  }
}

// Random event effects. Returns log entries; mutates state / result.
function applyEvent(state, ev, result) {
  const log = [];
  if (ev.type === 'freezer') {
    const cands = state.supplies.filter((s) => s.onHand > 0);
    if (cands.length) {
      const s = cands[Math.floor(Math.random() * cands.length)];
      const lost = Math.ceil(s.onHand * 0.5);
      s.onHand = Math.max(0, s.onHand - lost);
      const cost = Math.round(lost * (s.unitCost > 0 ? s.unitCost : BASE_UNIT_COST));
      result.dWaste += lost * WASTE_PENALTY;
      state.wastedCash += cost;
      // Persist the loss so the database reflects the destroyed stock.
      result.spoilage.push({ itemId: s.id, qty: lost, name: s.name, unitCost: s.unitCost });
      log.push({ kind: 'danger',
        text: `FREEZER FAILURE: lost ${lost} ${s.name} ($${cost} down the drain)` });
    }
  } else if (ev.type === 'price') {
    state.priceMult = 1.5; state.priceUntil = state.shift + 8;
    log.push({ kind: 'warn', text: `SUPPLIER PRICE SPIKE: reorders cost +50% for a while` });
  } else if (ev.type === 'rush') {
    state.rushUntil = state.shift + 6;
    log.push({ kind: 'warn', text: `RUSH GRANT DEADLINE: demand surges for 6 shifts` });
  } else if (ev.type === 'windfall') {
    const bonus = 150 + Math.floor(Math.random() * 150);
    state.budget += bonus;
    log.push({ kind: 'ok', text: `SUPPLEMENTAL GRANT: +$${bonus} awarded` });
  } else if (ev.type === 'backorder') {
    state.leadPenalty = 2; state.leadUntil = state.shift + 8;
    log.push({ kind: 'warn', text: `SUPPLY CHAIN DELAY: new orders take +2 shifts to arrive` });
  }
  return log;
}

// ---------------------------------------------------------------------------
// Persistence: batch by item, ONE consume call per item per shift. Consumption
// and destroyed (spoiled/freezer) stock both persist as consume events; arrivals
// persist as restock. The in-memory mirror is authoritative for the UI; the API
// call makes the database reflect it. Fire-and-forget with error catch.
// ---------------------------------------------------------------------------
function flushPersistence(ctx, state, r) {
  for (const [itemId, qty] of r.consumeByItem) {
    if (qty <= 0) continue;
    const s = state.byId.get(itemId);
    const npc = state.npcs.find((n) => n.itemId === itemId);
    const body = { quantity: qty, note: `Lab Tycoon: ${npc ? npc.name : 'sim'}` };
    if (npc && npc.staffId) body.staff_id = npc.staffId;
    ctx.api.post(`/api/items/${itemId}/consume`, body).catch(() => {
      state.log.unshift({ kind: 'warn', shift: state.shift,
        text: `Sync note: server had no ${s ? s.name : 'item'} left to record` });
    });
  }
  for (const sp of r.spoilage) {
    if (sp.qty <= 0) continue;
    ctx.api.post(`/api/items/${sp.itemId}/consume`,
      { quantity: sp.qty, note: 'Lab Tycoon: discarded (expired/damaged)' }).catch(() => {});
  }
  for (const o of r.arrivals) {
    ctx.api.post(`/api/items/${o.itemId}/restock`, {
      quantity: o.qty,
      lot_number: `TYC-${o.itemId}-${state.shift}`,
      expiry_date: oneYearOut(),
    }).catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Player action: place a purchase order (costs budget, arrives after a lead time).
// ---------------------------------------------------------------------------
function placeOrder(ctx, state, supply, qty, root) {
  if (state.gameOver) return;
  const unitCost = supply.unitCost > 0 ? supply.unitCost : BASE_UNIT_COST;
  const cost = Math.round(qty * unitCost * (state.priceMult || 1));
  if (cost > state.budget) {
    ctx.toast('Not enough grant funds for that order', 'warn');
    state.log.unshift({ kind: 'danger', shift: state.shift,
      text: `Order refused: ${supply.name} costs $${cost}, only $${Math.round(state.budget)} left` });
    if (state.log.length > LOG_LIMIT) state.log.length = LOG_LIMIT;
    paintDynamic(root, state, ctx);
    return;
  }

  state.budget -= cost;
  state.spent += cost;
  const backordered = Math.random() < BACKORDER_CHANCE;
  const lead = BASE_LEAD_TIME + (backordered ? 2 : 0)
               + (state.leadUntil > state.shift ? state.leadPenalty : 0);
  state.pendingOrders.push({
    itemId: supply.id, name: supply.name, qty, cost,
    arriveShift: state.shift + lead, backordered,
  });
  state.log.unshift({ kind: backordered ? 'warn' : 'ok', shift: state.shift,
    text: `Ordered ${qty} ${supply.name} for $${cost}, arrives in ${lead} shift(s)`
          + (backordered ? ' [BACK-ORDERED]' : '') });
  if (state.log.length > LOG_LIMIT) state.log.length = LOG_LIMIT;
  ctx.toast(`Ordered ${qty} ${supply.name}`, 'ok');
  paintDynamic(root, state, ctx);
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
function bindControls(root, ctx, state, myGen) {
  const q = (sel) => root.querySelector(sel);

  q('#lt-start').addEventListener('click', () => {
    if (state.gameOver) return;
    state.running = !state.running;
    if (state.running) state.lastTs = performance.now();
    paintDynamic(root, state, ctx);
  });

  q('#lt-speed').addEventListener('click', () => {
    const idx = SPEEDS.indexOf(state.speed);
    state.speed = SPEEDS[(idx + 1) % SPEEDS.length];
    paintDynamic(root, state, ctx);
  });

  q('#lt-reset').addEventListener('click', async () => {
    if (!confirm('Reset the demo database and restart Lab Tycoon?')) return;
    state.running = false;
    try {
      await ctx.api.post('/api/reset', {});
      ctx.toast('Demo data reset', 'ok');
    } catch (err) {
      ctx.toast(`Reset failed: ${err}`, 'danger');
      return;
    }
    if (myGen === generation) render(root, ctx, {});
  });

  // Delegated: order buttons (supply table is repainted each shift).
  q('#lt-supply').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-order]');
    if (btn) {
      const supply = state.byId.get(Number(btn.dataset.order));
      if (supply) placeOrder(ctx, state, supply, Number(btn.dataset.qty), root);
      return;
    }
    // Clicking a supply name jumps to its Inventory detail (findability).
    const link = e.target.closest('[data-item]');
    if (link) ctx.navigate('inventory', { itemId: Number(link.dataset.item) });
  });

  // Delegated: "Play again" in the end-of-period banner.
  root.addEventListener('click', (e) => {
    if (e.target.closest('#lt-again') && myGen === generation) render(root, ctx, {});
  });
}

// ---------------------------------------------------------------------------
// Rendering. shell() is static; paintDynamic() re-renders the live regions.
// ---------------------------------------------------------------------------
function shell() {
  return `
  <section class="lt-wrap" style="display:flex;flex-direction:column;gap:16px">
    <div class="card">
      <div class="card-title">Interactive tutorial -- Lab Tycoon</div>
      <p style="color:var(--text-muted);margin:6px 0 10px;max-width:74ch;line-height:1.5">
        New to Nimble Lab Manager? This is the hands-on way to learn it. You
        <strong style="color:var(--text)">run this lab's supply chain</strong> for one
        <strong style="color:var(--text)">grant period</strong>, and it drives the
        <strong style="color:var(--text)">same REST API</strong> as the rest of the app,
        so the database genuinely changes as you play -- every lesson here is a real
        action you'll take for real in Inventory and Procurement. Autonomous researchers
        generate demand and consume reagents; you manage
        <strong style="color:var(--text)">supply on a budget</strong>: reorder before a
        stockout, but size each order so stock is used before it
        <strong style="color:var(--text)">expires</strong> (spoiled reagents are money
        wasted), and plan around <strong style="color:var(--text)">lead times and
        back-orders</strong>. Score ${WIN_SCORE}+ by shift ${GRANT_PERIOD} to keep the
        grant. It teaches the exact planning muscles the tool is built to encourage.
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <button id="lt-start" class="btn btn-primary">Start</button>
        <button id="lt-speed" class="btn btn-ghost">Speed 1x</button>
        <button id="lt-reset" class="btn btn-ghost">Reset demo</button>
        <span id="lt-mods" style="color:var(--text-muted);font-size:13px"></span>
        <span id="lt-clock" class="chip" style="margin-left:auto">Shift 0 / ${GRANT_PERIOD}</span>
      </div>
    </div>

    <div id="lt-banner"></div>

    <div id="lt-scorebar"
         style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px"></div>

    <div class="lt-cols"
         style="display:grid;grid-template-columns:1.4fr 1fr;gap:16px;align-items:start">
      <div style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <div class="card" style="min-width:0">
          <div class="card-title">Supply (live inventory)</div>
          <div style="overflow-x:auto"><div id="lt-supply"></div></div>
        </div>
        <div class="card">
          <div class="card-title">Incoming orders</div>
          <div id="lt-orders" style="font-size:13px"></div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <div class="card">
          <div class="card-title">Researchers</div>
          <div id="lt-npcs" style="display:flex;flex-direction:column;gap:8px"></div>
        </div>
        <div class="card">
          <div class="card-title">Event log</div>
          <div id="lt-log" style="display:flex;flex-direction:column;gap:4px;
               max-height:280px;overflow-y:auto;font-size:13px"></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">How this mirrors real lab management</div>
      <ul style="margin:6px 0 0;padding-left:20px;color:var(--text-muted);
                 line-height:1.6;max-width:80ch">
        <li><strong style="color:var(--text)">Grant budget:</strong> funds are finite and
          arrive in installments. Every reorder spends real money; over-ordering ties up
          cash you cannot get back.</li>
        <li><strong style="color:var(--text)">Reorder points:</strong> let stock fall below
          the threshold and researchers stall (a stockout). This is exactly the low-stock
          signal the Inventory view flags.</li>
        <li><strong style="color:var(--text)">Expiry &amp; waste:</strong> reagents have a
          shelf life. Buy more than you can use in time and it spoils -- lost science AND
          lost dollars. Little-and-often beats hoarding.</li>
        <li><strong style="color:var(--text)">Lead times &amp; back-orders:</strong> orders
          do not arrive instantly, and suppliers slip. You must reorder early, before you
          are empty.</li>
        <li><strong style="color:var(--text)">Random events:</strong> freezer failures,
          price spikes and rush deadlines are the real disruptions a lab manager buffers
          against with slack stock and a cash reserve.</li>
      </ul>
    </div>
  </section>`;
}

// Repaint everything that changes during play.
function paintDynamic(root, state, ctx) {
  const clock = root.querySelector('#lt-clock');
  if (clock) clock.textContent = `Shift ${state.shift} / ${GRANT_PERIOD} - Round ${roundOf(state.shift)}`;

  const mods = root.querySelector('#lt-mods');
  if (mods) mods.textContent = activeModsText(state);

  const start = root.querySelector('#lt-start');
  if (start) {
    start.disabled = state.gameOver;
    start.textContent = state.gameOver ? 'Finished' : (state.running ? 'Pause' : 'Start');
    start.classList.toggle('btn-primary', !state.running && !state.gameOver);
    start.classList.toggle('btn-ghost', state.running || state.gameOver);
  }
  const speed = root.querySelector('#lt-speed');
  if (speed) speed.textContent = `Speed ${state.speed}x`;

  paintBanner(root, state);
  paintScore(root, state, ctx);
  paintSupply(root, state, ctx);
  paintOrders(root, state);
  paintNpcs(root, state);
  paintLog(root, state);
}

function activeModsText(state) {
  const on = [];
  if (state.rushUntil > state.shift) on.push('RUSH');
  if (state.priceUntil > state.shift) on.push('PRICE +50%');
  if (state.leadUntil > state.shift) on.push('SLOW SHIPPING');
  return on.length ? 'Active: ' + on.join(' - ') : '';
}

function paintBanner(root, state) {
  const el = root.querySelector('#lt-banner');
  if (!el) return;
  if (!state.gameOver) { el.innerHTML = ''; return; }
  const win = state.outcome === 'win';
  const color = win ? 'var(--ok)' : 'var(--danger)';
  el.innerHTML = `<div class="card" style="border-left:4px solid ${color}">
    <div class="card-title" style="color:${color}">
      ${win ? 'Grant renewed -- you win' : 'Grant not renewed -- you lose'}</div>
    <div style="margin:6px 0;line-height:1.6">
      Final score <strong>${Math.round(state.score)}</strong>
      (needed ${WIN_SCORE}). Budget left <strong>$${Math.round(state.budget)}</strong>,
      spent $${Math.round(state.spent)}, of which
      <strong style="color:var(--warn)">$${Math.round(state.wastedCash)}</strong>
      spoiled or was destroyed.
      Stockout loss ${Math.round(state.stockouts)}, expiry waste ${Math.round(state.waste)}.
    </div>
    <div style="color:var(--text-muted);margin-bottom:10px">
      ${win
        ? 'You kept researchers supplied without drowning the lab in soon-to-expire stock.'
        : 'Tighten it up: reorder earlier so you never stock out, but order smaller lots so less expires.'}
    </div>
    <button id="lt-again" class="btn btn-primary">Play again</button>
  </div>`;
}

function paintScore(root, state, ctx) {
  const el = root.querySelector('#lt-scorebar');
  if (!el) return;
  const n = ctx.fmt && ctx.fmt.num ? ctx.fmt.num : (x) => String(x);
  const money = ctx.fmt && ctx.fmt.money ? ctx.fmt.money : (x) => '$' + Math.round(x);
  const scoreColor = state.score >= WIN_SCORE ? 'var(--ok)'
                   : state.score >= 0 ? 'var(--text)' : 'var(--danger)';
  const budgetColor = state.budget <= 0 ? 'var(--danger)'
                    : state.budget < 120 ? 'var(--warn)' : 'var(--text)';
  const total = state.supplies.length || 1;
  const healthy = state.supplies.filter((s) => s.onHand > s.reorder).length;
  const healthPct = Math.round((healthy / total) * 100);
  const healthColor = healthPct >= 66 ? 'var(--ok)'
                    : healthPct >= 33 ? 'var(--warn)' : 'var(--danger)';
  el.innerHTML = [
    stat('Score', n(Math.round(state.score)), scoreColor),
    stat('Budget', money(Math.round(state.budget)), budgetColor),
    stat('Stock health', healthPct + '%', healthColor),
    stat('Productivity', '+' + n(Math.round(state.productivity)), 'var(--ok)'),
    stat('Stockout loss', state.stockouts > 0 ? '-' + n(Math.round(state.stockouts)) : '0', state.stockouts > 0 ? 'var(--danger)' : 'var(--text)'),
    stat('Expiry waste', state.waste > 0 ? '-' + n(Math.round(state.waste)) : '0', state.waste > 0 ? 'var(--warn)' : 'var(--text)'),
  ].join('');
}

function stat(label, value, color) {
  return `<div class="card stat" style="text-align:left">
      <div style="font-size:24px;font-weight:700;color:${color}">${value}</div>
      <div style="color:var(--text-muted);font-size:12px;text-transform:uppercase;
           letter-spacing:.04em">${label}</div>
    </div>`;
}

function paintSupply(root, state, ctx) {
  const el = root.querySelector('#lt-supply');
  if (!el) return;
  const pm = state.priceMult || 1;
  const rows = state.supplies.map((s) => {
    const low = s.onHand <= s.reorder;
    const out = s.onHand <= 0;
    const stockBadge = out
      ? `<span class="badge badge-danger">out</span>`
      : low ? `<span class="badge badge-warn">low</span>`
            : `<span class="badge badge-ok">ok</span>`;
    const expBadge = expiryBadge(s.expiryFlag);
    const incoming = state.pendingOrders
      .filter((o) => o.itemId === s.id)
      .reduce((a, o) => a + o.qty, 0);
    const incBadge = incoming ? `<span class="badge">+${incoming} inbound</span>` : '';
    const unitCost = s.unitCost > 0 ? s.unitCost : BASE_UNIT_COST;
    const disabled = state.gameOver ? 'disabled' : '';
    const orderBtns = ORDER_SIZES.map((o) => {
      const cost = Math.round(o.qty * unitCost * pm);
      return `<button class="btn btn-ghost btn-sm" data-order="${s.id}" data-qty="${o.qty}"
                title="$${cost}" ${disabled}>${o.label}</button>`;
    }).join(' ');
    return `<tr${low ? ' style="background:var(--accent-soft)"' : ''}>
      <td><a href="#" data-item="${s.id}"
             style="color:var(--accent);text-decoration:none">${escapeHtml(s.name)}</a></td>
      <td style="font-family:var(--mono);text-align:right">${s.onHand}</td>
      <td style="text-align:right;color:var(--text-muted)">${s.reorder}</td>
      <td>${stockBadge} ${expBadge} ${incBadge}</td>
      <td style="text-align:right;white-space:nowrap">${orderBtns}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table class="table" style="width:100%">
    <thead><tr>
      <th style="text-align:left">Item</th>
      <th style="text-align:right">On hand</th>
      <th style="text-align:right">Reorder pt</th>
      <th style="text-align:left">Status</th>
      <th style="text-align:right">Order</th>
    </tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function expiryBadge(flag) {
  if (flag === 'expired') return `<span class="badge badge-danger">expired</span>`;
  if (flag === 'expiring') return `<span class="badge badge-warn">expiring</span>`;
  return '';
}

function paintOrders(root, state) {
  const el = root.querySelector('#lt-orders');
  if (!el) return;
  if (!state.pendingOrders.length) {
    el.innerHTML = `<div style="color:var(--text-muted)">No orders in transit.</div>`;
    return;
  }
  const rows = state.pendingOrders
    .slice()
    .sort((a, b) => a.arriveShift - b.arriveShift)
    .map((o) => {
      const eta = Math.max(0, o.arriveShift - state.shift);
      const back = o.backordered ? ` <span class="badge badge-warn">back-ordered</span>` : '';
      return `<div style="display:flex;justify-content:space-between;gap:8px;
           padding:4px 0;border-bottom:1px solid var(--border)">
        <span>${o.qty} ${escapeHtml(o.name)}${back}</span>
        <span style="font-family:var(--mono);color:var(--text-muted)">ETA ${eta} shift(s)</span>
      </div>`;
    }).join('');
  el.innerHTML = rows;
}

function paintNpcs(root, state) {
  const el = root.querySelector('#lt-npcs');
  if (!el) return;
  const mult = difficultyMult(state.shift) * (state.rushUntil > state.shift ? RUSH_MULT : 1);
  el.innerHTML = state.npcs.map((npc) => {
    const status = state.gameOver
      ? `<span class="badge">done</span>`
      : !state.running
        ? `<span class="badge">idle</span>`
        : npc.blocked ? `<span class="badge badge-danger">blocked</span>`
                      : `<span class="badge badge-ok">working</span>`;
    const eff = (npc.rate * mult).toFixed(2);
    return `<div style="display:flex;justify-content:space-between;align-items:center;
         gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
      <div style="min-width:0">
        <div style="font-weight:600">${escapeHtml(npc.name)}
          <span style="color:var(--text-muted);font-weight:400">-- ${escapeHtml(npc.role)}</span></div>
        <div style="color:var(--text-muted);font-size:12px">
          uses ${escapeHtml(npc.itemName)} (~${eff}/shift)</div>
      </div>
      ${status}
    </div>`;
  }).join('');
}

function paintLog(root, state) {
  const el = root.querySelector('#lt-log');
  if (!el) return;
  if (!state.log.length) {
    el.innerHTML = `<div style="color:var(--text-muted)">Press Start to run the lab.</div>`;
    return;
  }
  const color = { ok: 'var(--ok)', warn: 'var(--warn)', danger: 'var(--danger)' };
  el.innerHTML = state.log.map((e) =>
    `<div style="display:flex;gap:8px">
       <span style="font-family:var(--mono);color:var(--text-muted);flex:0 0 auto">
         ${String(e.shift).padStart(3, '0')}</span>
       <span style="color:${color[e.kind] || 'var(--text)'}">${escapeHtml(e.text)}</span>
     </div>`).join('');
}

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------
function oneYearOut() {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  return d.toISOString().slice(0, 10);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
