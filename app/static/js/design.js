/* Step 2: driver goals & rankings, active driver cards, auto crossover tuning, optimize/BEM, baffle layout, and port UI. */
import {
  $, $$, COL, PRESETS, STYLE_NAME, actions, api, changeSummary, clone, deepMerge, deltaBadge,
  esc, eur, fmt, grade, isSub, markChange, metricTile, minWeb, persist, resetAuto, resetXo, state, term,
} from './state.js';
import { driverSpecLine, sizeLabel } from './catalog.js';
import { renderChart } from './charts.js';
import { enableDrag, frontSVG, isoSVG, sideSVG, topSVG, uniq } from './svg.js';
import { refreshPotential } from './start.js';

export function toast(html) {
  $('#t-toast').innerHTML = `<div class="toast"><span>${html}</span><button id="t-undo">Undo</button></div>`;
  $('#t-undo').onclick = () => $('#t-undo2').click();
}

export function syncGoalsUI() {
  const g = state.goals;
  $('#g-budget').value = g.budget;
  $('#g-budget-r').value = g.budget;
  $$('[data-goal]').forEach((row) => {
    const key = row.dataset.goal;
    row.querySelectorAll('.choice').forEach((btn) => {
      btn.classList.toggle('on', g[key] === btn.dataset.val);
    });
  });

  const setControl = (selector, key) => {
    const el = $(selector);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!g[key];
    else el.value = g[key];
  };
  setControl('#g-ways', 'ways');
  setControl('#g-tier', 'tier');
  setControl('#g-stock', 'stock');
  setControl('#g-dual', 'dual');
  $('#g-auto').checked = state.autoPick;
}

export function initGoals() {
  const g = state.goals;
  actions.syncGoalsUI = syncGoalsUI;
  actions.runFind = runFind;
  syncGoalsUI();

  const onBudget = (val) => {
    g.budget = +val;
    $('#g-budget').value = g.budget;
    $('#g-budget-r').value = g.budget;
    persist();
    runFind(true, `budget €${g.budget}`);
  };
  $('#g-budget').onchange = (e) => onBudget(e.target.value);
  $('#g-budget-r').oninput = (e) => { $('#g-budget').value = e.target.value; };
  $('#g-budget-r').onchange = (e) => onBudget(e.target.value);

  $$('[data-goal]').forEach((row) => {
    const key = row.dataset.goal;
    row.querySelectorAll('.choice').forEach((btn) => {
      btn.onclick = () => {
        if (g[key] === btn.dataset.val) return;
        g[key] = btn.dataset.val;
        row.querySelectorAll('.choice').forEach((x) => x.classList.toggle('on', x === btn));

        const goalNames = { amp: 'amplifier', style: 'priority', port: 'bass port' };
        const label = `${goalNames[key]} → ${btn.querySelector('b').textContent}`;
        markChange(label);

        if (key === 'amp' && state.design.crossover) {
          state.design.crossover.mode = g.amp;
          resetXo(state.design);
          state.xoManual = false;
          state.xoTunedKey = null;
        }
        if (key === 'port') {
          if (g.port === 'sealed') {
            state.design.box.type = 'sealed';
          } else {
            state.design.box.type = 'auto';
            state.design.box.port.location = g.port;
          }
          state.design.box.fb = null;
          state.design.box.port.d_mm = null;
          state.design.box.port.count = null;
          if (state.design.layout.positions) delete state.design.layout.positions.port;
          state.xoTunedKey = null;
        }

        actions.syncInputs();
        persist();
        if (key !== 'style') actions.simulate(0);
        runFind(true, label);
      };
    });
  });

  const bindGoalSelect = (selector, key, convert = (v) => v) => {
    const el = $(selector);
    if (!el) return;
    el.onchange = () => {
      const raw = el.type === 'checkbox' ? el.checked : el.value;
      g[key] = convert(raw);
      persist();
      refreshPotential();
      runFind(true, key);
    };
  };
  bindGoalSelect('#g-ways', 'ways');
  bindGoalSelect('#g-tier', 'tier', Number);
  bindGoalSelect('#g-stock', 'stock');
  bindGoalSelect('#g-dual', 'dual');

  $('#g-auto').onchange = (e) => {
    state.autoPick = e.target.checked;
    persist();
    if (state.autoPick) runFind(true, 'auto-pick on');
  };
}

let findSeq = 0;
let findTimer;
export function runFind(mayApply = true, label = '') {
  clearTimeout(findTimer);
  findTimer = setTimeout(() => doFind(mayApply, label), 350);
}

async function doFind(mayApply, label) {
  if (isSub()) return;
  const seq = ++findSeq;
  const g = state.goals;
  $('#rank-status').textContent = '· ranking…';

  const req = {
    cabinet: state.design.cabinet,
    sim: state.design.sim,
    budget_eur_pair: g.budget,
    ways: g.ways,
    crossover_mode: g.amp,
    box: g.port === 'sealed' ? 'sealed' : 'auto',
    port_location: g.port === 'sealed' ? 'front' : g.port,
    min_tier: g.tier,
    allow_dual_woofers: g.dual,
    priorities: PRESETS[g.style],
    in_stock_only: g.stock,
    top_n: 6,
  };

  try {
    const found = await api('/api/optimize', req);
    if (seq !== findSeq) return;
    state.find = found;
    $('#rank-status').textContent = `(${found.evaluated})`;
    const rc = $('#rank-count');
    if (rc) rc.textContent = `· ${found.evaluated} sets fit`;

    const top = found.results[0];
    if (mayApply && state.autoPick && top && !isCurrent(top)) {
      const prefix = label ? `${label} · ` : '';
      applyDesign(top.design, `${prefix}best set for “${STYLE_NAME[g.style]}”: ${shortSet(top)}`);
    } else if (mayApply && label && top && isCurrent(top)) {
      const summary = changeSummary(state.result);
      const suffix = summary ? `: ${summary}` : '';
      toast(`<b>${esc(label)}</b>${suffix} · best set for “${STYLE_NAME[g.style]}” is still your current one.`);
    }
    renderRanks();
  } catch (err) {
    $('#rank-list').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
    $('#rank-status').textContent = '';
  }
}

function isCurrent(item) {
  const c = state.design.drivers;
  const d = item.design.drivers;
  return (
    c.woofer.id === d.woofer.id
    && (c.woofer.count || 1) === (d.woofer.count || 1)
    && (c.mid?.id || null) === (d.mid?.id || null)
    && c.tweeter.id === d.tweeter.id
  );
}

function shortSet(item) {
  return [item.drivers.woofer, item.drivers.mid, item.drivers.tweeter]
    .filter(Boolean)
    .map((d) => d.model.split(' ')[0])
    .join(' + ');
}

function applyDesign(resolved, why) {
  markChange(why);
  const d = clone(resolved);
  resetAuto(d);
  const keep = {
    cabinet: state.design.cabinet,
    sim: state.design.sim,
    layout: { min_web_mm: state.design.layout.min_web_mm },
  };
  state.design = deepMerge(state.defaults.design, deepMerge(d, keep));
  state.design.layout.positions = null;
  state.xoManual = false;
  state.xoTunedKey = null;
  if (why) state.pendingToast = why;
  actions.syncInputs();
  actions.simulate(0);
  renderRanks();
}

export function renderRanks() {
  const found = state.find;
  if (!found) return;
  if (!found.results.length) {
    $('#rank-list').innerHTML = `<div class="alert warn">No driver set fits (${found.rejected.budget} over budget, ${found.rejected.fit} don't fit). Raise budget or adjust filters.</div>`;
    return;
  }

  $('#rank-list').innerHTML = found.results.map((item, idx) => {
    const m = item.metrics;
    const cur = isCurrent(item);
    const d = item.drivers;
    const badge = idx === 0 ? '★ ' : `#${idx + 1} `;
    const midPart = d.mid ? ` · ${esc(d.mid.brand)} ${fmt(d.mid.nominal_mm / 10, 0)} cm` : '';
    const outOfStock = [d.woofer, d.mid, d.tweeter].some((z) => z && !z.in_stock);
    const stockNote = outOfStock ? ' · <span class="tag warn">stock</span>' : '';
    const proNote = item.pros[0] ? `<div class="why">+ ${esc(item.pros[0])}</div>` : '';

    return `
      <button class="rank ${cur ? 'cur' : ''}" data-rank="${idx}">
        <div class="r1"><span>${badge}${esc(shortSet(item))}</span><span>${eur(m.price_drivers_pair_eur)}</span></div>
        <div class="r2">${esc(d.woofer.brand)} ${fmt(d.woofer.nominal_mm / 10, 0)} cm${midPart} · ${esc(d.tweeter.brand)}${stockNote}</div>
        <div class="r3"><span>${fmt(m.woofer_f3_hz, 0)} Hz</span><span>±${fmt(m.deviation_db)} dB</span><span>${fmt(m.max_spl_40hz, 0)} dB</span>${cur ? '<span>✓ in use</span>' : ''}</div>
        ${proNote}
      </button>`;
  }).join('');

  $$('[data-rank]').forEach((btn) => {
    btn.onclick = () => {
      const item = state.find.results[+btn.dataset.rank];
      if (!isCurrent(item)) applyDesign(item.design, `Driver set → ${shortSet(item)}`);
      const dlg = $('#drv-picker-dialog');
      if (dlg?.open) dlg.close();
    };
  });
}

export function xoSig(design = state.design) {
  if (!design) return '';
  return JSON.stringify([
    design.drivers,
    design.box?.type,
    design.box?.port?.location,
    design.crossover?.mode,
    design.layout?.positions,
  ]);
}

export async function ensureCrossoverTuned(silent = true) {
  if (isSub() || state.xoManual || state.tuningXo || !state.design) return;
  const sig = xoSig();
  if (state.xoTunedKey === sig) return;

  state.tuningXo = true;
  const pill = $('#t-xo-pill');
  if (pill) {
    pill.className = 'pill';
    pill.textContent = 'Tuning crossover…';
  }
  try {
    const res = await api('/api/tune', state.design);
    if (xoSig() !== sig) return;
    const pos = state.design.layout.positions;
    state.design = deepMerge(state.defaults.design, res.design);
    if (pos) state.design.layout.positions = pos;
    state.xoTunedKey = xoSig();
    actions.syncInputs();
    if (!silent) {
      state.pendingToast = `Crossover auto-tuned: ±${fmt(res.before.deviation_db)} → ±${fmt(res.after.deviation_db)} dB`;
    }
    await actions.runSimulate();
  } catch {} finally {
    state.tuningXo = false;
  }
}

const OPT = {
  tune: { url: '/api/tune', label: 'Crossover only', busy: 'Tuning crossover…', keepPos: true },
  maximize: { url: '/api/maximize', label: 'Auto-optimize', busy: 'Optimizing… (~5 s)', keepPos: false },
};

async function optimizeDesign(kind = 'tune') {
  const opt = OPT[kind];
  const btns = $$('[data-opt]');
  btns.forEach((b) => {
    b.disabled = true;
    if (b.dataset.opt === kind) b.textContent = opt.busy;
  });

  try {
    const before = clone(state.design);
    const res = await api(opt.url, state.design);
    markChange(opt.label);
    state.undo = before;

    const d = res.design;
    if (opt.keepPos) d.layout.positions = state.design.layout.positions;
    state.design = deepMerge(state.defaults.design, d);
    state.xoManual = false;
    state.xoTunedKey = xoSig();
    actions.syncInputs();
    actions.simulate(0);

    const summary = `response ±${fmt(res.before.deviation_db)} → ±${fmt(res.after.deviation_db)} dB, sensitivity ${fmt(res.before.sensitivity)} → ${fmt(res.after.sensitivity)} dB`;
    const changesHtml = res.changes.map((c) => `<li>${esc(c)}</li>`).join('');
    $('#t-optres').innerHTML = `<div class="optres"><b>${opt.label}: ${summary}</b> <span class="muted">(${res.evals} simulations)</span><ul>${changesHtml}</ul><button id="t-opt-undo">↶ Undo</button></div>`;
    state.pendingToast = `${opt.label}: ${summary} – ${res.changes.join(', ')}`;
    $('#t-opt-undo').onclick = () => {
      markChange(`undo ${kind}`);
      state.design = before;
      actions.syncInputs();
      actions.simulate(0);
      $('#t-optres').innerHTML = '';
    };
  } catch (err) {
    $('#t-optres').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  } finally {
    btns.forEach((b) => {
      b.disabled = false;
      b.textContent = b.dataset.text;
    });
  }
}

export async function runBem() {
  const btn = $('#t-bem');
  btn.disabled = true;
  try {
    const design = clone(state.design);
    delete design.sim.bem;
    const job = await api('/api/bem/start', design);
    for (;;) {
      await new Promise((r) => setTimeout(r, 3000));
      const st = await api(`/api/bem/${job.id}`);
      btn.textContent = `BEM ${st.done || 0}/${st.total} frequencies…`;
      if (st.status === 'error') throw new Error(st.error);
      if (st.status === 'done') {
        markChange('BEM verification');
        state.design.sim.bem = { ...st.result, positions_key: job.positions_key };
        state.pendingToast = 'Baffle diffraction replaced by full 3D BEM (80–1200 Hz).';
        actions.simulate(0);
        break;
      }
    }
  } catch (err) {
    $('#t-alerts').innerHTML = `<div class="alert bad">BEM: ${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Verify with BEM';
  }
}

export function initWorkspace() {
  actions.placeChecked = placeChecked;
  actions.runBem = runBem;

  $('#t-relayout').onclick = () => {
    markChange('auto-layout');
    state.design.layout.positions = null;
    state.sel = null;
    state.xoTunedKey = null;
    actions.simulate(0);
  };

  $('#t-xo-auto').onclick = () => {
    markChange('crossover → automatic');
    state.xoManual = false;
    state.xoTunedKey = null;
    resetXo(state.design);
    actions.syncInputs();
    actions.simulate(0);
  };

  ['#v-clear', '#v-bolts'].forEach((sel) => {
    $(sel).onchange = () => renderViews(state.result);
  });
  $('#t-sections-card').addEventListener('toggle', () => renderSections(state.result));

  $$('#charttabs button').forEach((btn) => {
    btn.onclick = () => {
      state.chart = btn.dataset.chart;
      $$('#charttabs button').forEach((x) => x.classList.toggle('active', x === btn));
      renderChart();
    };
  });

  $('#t-bem').onclick = runBem;
  $('#sub-back').onclick = () => {
    markChange('back to speakers');
    state.design = clone(state.defaults.design);
    state.goals.start = 'fit';
    syncGoalsUI();
    actions.syncInputs();
    actions.simulate(0);
    refreshPotential();
    runFind(false);
  };

  $('#t-port-best').onclick = bestPort;
  $('#t-build-pill').onclick = () => $('#t-alerts')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  $$('[data-opt]').forEach((btn) => {
    btn.dataset.text = btn.textContent;
    btn.onclick = () => optimizeDesign(btn.dataset.opt);
  });

  $('#t-relayout2').onclick = () => $('#t-relayout').click();
  $('#t-undo2').onclick = () => {
    if (!state.undo) return;
    const prevDesign = state.undo;
    state.undo = null;
    state.prev = state.result;
    state.autoPick = false;
    $('#g-auto').checked = false;
    state.design = prevDesign;
    actions.syncInputs();
    actions.simulate(0);
    $('#t-toast').innerHTML = '';
    renderRanks();
  };

  document.addEventListener('keydown', (e) => {
    const moveKeys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape'];
    const editingInput = /INPUT|SELECT/.test(document.activeElement?.tagName);
    if (state.step !== 'design' || !state.sel || !moveKeys.includes(e.key) || editingInput) return;

    e.preventDefault();
    if (e.key === 'Escape') {
      state.sel = null;
      renderViews(state.result);
      return;
    }

    const stepMm = e.shiftKey ? 10 : 1;
    const pos = state.design.layout.positions;
    const { role, idx } = state.sel;
    const current = Array.isArray(pos[role]) ? pos[role][idx] : pos[role];
    const nextPt = { ...current };
    if (e.key === 'ArrowUp') nextPt.y += stepMm;
    if (e.key === 'ArrowDown') nextPt.y -= stepMm;
    if (e.key === 'ArrowLeft') nextPt.x -= stepMm;
    if (e.key === 'ArrowRight') nextPt.x += stepMm;
    placeChecked(role, idx, nextPt, `moved ${role}`);
  });
}

let placing = false;
export async function placeChecked(role, idx, target, label) {
  if (isSub()) {
    markChange(label);
    const pos = state.design.layout.positions;
    if (Array.isArray(pos[role])) pos[role][idx] = { ...pos[role][idx], ...target };
    actions.simulate(0);
    return;
  }
  if (placing) return;
  placing = true;

  try {
    const pos = state.design.layout.positions;
    const getPt = (p) => (Array.isArray(p[role]) ? p[role][idx] : p[role]);
    const from = { ...getPt(pos) };
    const withPt = (pt) => {
      const next = clone(pos);
      if (Array.isArray(next[role])) next[role][idx] = { ...getPt(next), ...pt };
      else next[role] = { ...getPt(next), ...pt };
      return next;
    };
    const checkPt = (pt) => api('/api/layout/check', {
      design: { ...state.design, layout: { ...state.design.layout, positions: withPt(pt) } },
      port: state.result?.port,
    });

    const startCheck = await checkPt(from);
    const targetCheck = await checkPt(target);
    let finalPt = target;
    let reason = null;

    if (!startCheck.ok && targetCheck.errors.length <= startCheck.errors.length) {
      markChange(label);
      state.design.layout.positions = withPt(target);
      actions.simulate(0);
      return;
    }

    if (!targetCheck.ok) {
      reason = targetCheck.errors[0];
      let lo = 0;
      let hi = 1;
      for (let i = 0; i < 7; i++) {
        const t = (lo + hi) / 2;
        const midPt = { x: from.x + (target.x - from.x) * t, y: from.y + (target.y - from.y) * t };
        if ((await checkPt(midPt)).ok) lo = t;
        else hi = t;
      }
      finalPt = from;
      for (const t of [lo, lo * 0.97, lo * 0.9]) {
        const snapped = {
          x: Math.round((from.x + (target.x - from.x) * t) * 2) / 2,
          y: Math.round((from.y + (target.y - from.y) * t) * 2) / 2,
        };
        if (t > 0.02 && (await checkPt(snapped)).ok) {
          finalPt = snapped;
          break;
        }
      }
    }

    if (finalPt.x === from.x && finalPt.y === from.y) {
      renderViews(state.result);
      toast(`<b>Not allowed:</b> ${esc(reason)}`);
      return;
    }
    markChange(label);
    state.design.layout.positions = withPt(finalPt);
    if (reason) state.pendingToast = `Stopped at the closest allowed position – ${reason}`;
    actions.simulate(0);
  } finally {
    placing = false;
  }
}

function buildPill(result, web) {
  const pill = $('#t-build-pill');
  if (!pill) return;
  const p = result.port;
  const m = result.metrics;
  const minW = result.design.layout.min_web_mm ?? 10;
  const portInfo = p ? ` · ${fmt(p.vel_peak_ms, 0)} m/s` : '';
  const boxTxt = `${m.box_type} ${fmt(m.net_volume_L, 0)} L${portInfo}`;
  const webFail = web != null && web < minW - 0.05;
  const hasErr = result.warnings.length || webFail;

  let pillCls = 'ok';
  if (result.warnings.length) pillCls = 'warn';
  else if (webFail) pillCls = 'bad';

  pill.className = `pill ${pillCls}`;
  pill.textContent = hasErr ? `⚠ ${result.warnings.length || 1} check(s) · ${boxTxt}` : `✓ Ready to build · ${boxTxt}`;
  pill.title = result.warnings.length ? result.warnings.join(' | ') : 'All clearances, port speed and dimensions look good.';
}

export function renderDesign(r) {
  const m = r.metrics;
  const x = r.design.crossover;
  const web = minWeb(r);
  const tile = (k, v, sub, cls, tip, dk, dir, dp) => (
    metricTile(k, v + (dk ? deltaBadge(dk, m[dk], dir, dp) : ''), sub, cls, tip)
  );

  $('#t-metrics').innerHTML = [
    tile(term('F3', 'Bass depth'), `${fmt(m.woofer_f3_hz, 0)} Hz`, `−10 dB at ${fmt(m.woofer_f10_hz, 0)} Hz`, grade('f3', m.woofer_f3_hz, r), 'Lowest strong bass note (−3 dB, anechoic). Green ≤ 32 Hz.', 'woofer_f3_hz', -1, 0),
    tile(term('diffraction', 'Sound balance'), `±${fmt(m.deviation_db)} dB`, 'smoothness 150 Hz–10 kHz', grade('dev', m.deviation_db, r), 'How flat the response is. Green ≤ ±2 dB.', 'deviation_db', -1, 1),
    tile(term('sens', 'Loudness'), `${fmt(m.sensitivity_db_2v83_1m)} dB`, `max ${fmt(m.max_spl_40hz, 0)} dB @ 40 Hz`, grade('sens', m.sensitivity_db_2v83_1m, r), 'Sensitivity at 2.83 V / 1 m, and max bass SPL.', 'sensitivity_db_2v83_1m', 1, 1),
    tile('Drivers', eur(m.price_drivers_pair_eur), x.mode === 'passive' ? `+ ≈${eur(2 * m.crossover_parts_eur_each)} crossover` : 'active (DSP)', 'ok', 'Driver pair incl. VAT.', 'price_drivers_pair_eur', -1, 0),
  ].join('');

  buildPill(r, web);

  const xp = $('#t-xo-pill');
  if (xp) {
    const tuned = state.xoTunedKey === xoSig();
    xp.className = `pill ${!state.xoManual && tuned ? 'ok' : ''}`;
    if (state.xoManual) xp.textContent = 'Manual crossover';
    else if (tuned) xp.textContent = '✓ Crossover tuned';
    else xp.textContent = 'Crossover: pending tune';
  }

  const sum = changeSummary(r);
  if (state.pendingToast || (sum && Date.now() < state.txUntil + 4000)) {
    const head = state.pendingToast ? esc(state.pendingToast) : `<b>${esc(state.txLabel || 'change')}</b>`;
    toast(`${head}${sum ? `: ${sum}` : ''}`);
    state.pendingToast = null;
  }

  const alerts = [
    ...r.warnings.map((w) => `<div class="alert warn">⚠ ${esc(w)}</div>`),
    ...(r.notes || []).map((n) => `<div class="alert info">ℹ ${esc(n)}</div>`),
  ];
  if (r.bem?.used) {
    alerts.push(`<div class="alert ok">Baffle response verified with BEM up to ${fmt(r.bem.f_max, 0)} Hz (edge model above).</div>`);
  } else if (r.bem?.stale) {
    alerts.push('<div class="alert info">The BEM result is out of date after layout changes – run “Verify with BEM” again.</div>');
  }
  Object.entries(r.measured || {}).forEach(([role, used]) => {
    const note = role === 'woofer' ? ' (box model below the merge point)' : '';
    alerts.push(`<div class="alert ok">Using measured ${used.join(' + ')} for the ${role}${note}.</div>`);
  });
  ['woofer', 'mid', 'tweeter'].forEach((role) => {
    const drv = r.drivers[role];
    if (!drv) return;
    if (!drv.in_stock) {
      alerts.push(`<div class="alert warn">${esc(drv.brand)} ${esc(drv.model)} (${role}) is out of stock. <button class="mini" data-rep-btn="${drv.id}" data-rep-slot="${role}">Find replacement</button></div>`);
    }
    if (!drv.dims_verified) {
      alerts.push(`<div class="alert info">${esc(drv.brand)} ${esc(drv.model)}: frame dimensions are estimates – check the drawing before cutting.</div>`);
    }
  });
  $('#t-alerts').innerHTML = alerts.join('');

  $$('[data-rep-btn]').forEach((btn) => {
    btn.onclick = () => actions.openCatalogPicker(btn.dataset.repSlot || null, 'replace', btn.dataset.repBtn);
  });

  renderViews(r);
  renderSections(r);
  renderChart();
  renderRanks();
  renderPort(r);
  renderActiveDrivers(r);
}

function renderActiveDrivers(r) {
  const host = $('#active-drivers');
  if (!host || !r.drivers) return;

  const slots = [
    ['woofer', 'w', 'Woofer', r.drivers.woofer],
    ['mid', 'm', 'Midrange', r.drivers.mid],
    ['tweeter', 't', 'Tweeter', r.drivers.tweeter],
  ];

  host.innerHTML = slots.map(([slot, cls, label, drv]) => {
    if (!drv) {
      return `
        <div class="ad-card ${cls}" data-pick-slot="${slot}">
          <div class="ad-info">
            <div class="ad-role">${label}</div>
            <div class="ad-name muted">None (2-way)</div>
            <div class="ad-specs">Click + Add to pick a midrange</div>
          </div>
          <div class="ad-btns"><button class="mini" data-pick-slot="${slot}">+ Add</button></div>
        </div>`;
    }
    let priceTxt = 'no price';
    if (drv.price_eur > 0) priceTxt = `€${fmt(drv.price_eur, 0)}`;
    else if (drv.shop?.url) priceTxt = 'EU shop';
    const stockTag = drv.in_stock === false ? '<span class="tag warn">out</span>' : '<span class="tag ok">in stock</span>';

    return `
      <div class="ad-card ${cls}" data-detail-id="${drv.id}" title="Click for full datasheet specifications">
        <div class="ad-info">
          <div class="ad-role">${label} · ${sizeLabel(drv)} · ${priceTxt} ${stockTag}</div>
          <div class="ad-name">${esc(drv.brand)} ${esc(drv.model)}</div>
          <div class="ad-specs">${driverSpecLine(drv)}</div>
        </div>
        <div class="ad-btns">
          <button class="mini" data-pick-slot="${slot}">Change</button>
          <button class="mini" data-rep-slot="${slot}" data-rep-id="${drv.id}">Replace</button>
        </div>
      </div>`;
  }).join('');

  $$('#active-drivers [data-detail-id]').forEach((card) => {
    card.onclick = (e) => { if (!e.target.closest('button')) actions.openDriverDetail(card.dataset.detailId); };
  });
  $$('#active-drivers [data-pick-slot]').forEach((btn) => {
    btn.onclick = (e) => { e.stopPropagation(); actions.openCatalogPicker(btn.dataset.pickSlot, 'browse'); };
  });
  $$('#active-drivers [data-rep-id]').forEach((btn) => {
    btn.onclick = (e) => { e.stopPropagation(); actions.openCatalogPicker(btn.dataset.repSlot, 'replace', btn.dataset.repId); };
  });
}

export function renderSubDesign(r) {
  const m = r.metrics;
  let limitReason = 'cone travel limit';
  if (m.amp_w >= m.rated_power_w) limitReason = 'driver rating';
  else if (m.port_power_w && m.amp_w >= m.port_power_w - 1) limitReason = 'port noise limit';

  $('#t-metrics').innerHTML = [
    metricTile(term('F3', 'Bass depth'), `${fmt(m.woofer_f3_hz, 0)} Hz${deltaBadge('woofer_f3_hz', m.woofer_f3_hz, -1, 0)}`, `−10 dB at ${fmt(m.woofer_f10_hz, 0)} Hz`, m.woofer_f3_hz <= 25 ? 'ok' : m.woofer_f3_hz <= 35 ? 'warn' : 'bad', 'Before room gain.'),
    metricTile('Output @ 40 Hz', `${fmt(m.out_at_amp_40hz, 0)} dB`, `at ${fmt(m.amp_w, 0)} W (${limitReason})`, m.out_at_amp_40hz >= 105 ? 'ok' : m.out_at_amp_40hz >= 98 ? 'warn' : 'bad', `Max 20/30 Hz: ${fmt(m.max_spl_20hz, 0)}/${fmt(m.max_spl_30hz, 0)} dB.`),
    metricTile('Box', `${m.box_type} ${fmt(m.net_volume_L, 0)} L`, m.fb_hz ? `fb ${fmt(m.fb_hz, 1)} Hz` : `Qtc ${fmt(m.qtc, 2)}`, 'ok', `Cone travel: ${fmt(m.xmax_use_pct, 0)} % of Xmax.`),
    metricTile('Driver(s)', eur(m.price_drivers_eur), `${r.design.drivers.woofer.count || 1}× ${esc(r.drivers.woofer.model)}`, 'ok', 'Incl. VAT.'),
  ].join('');

  buildPill(r, null);
  const sum = changeSummary(r);
  if (state.pendingToast || (sum && Date.now() < state.txUntil + 4000)) {
    const head = state.pendingToast ? esc(state.pendingToast) : `<b>${esc(state.txLabel || 'change')}</b>`;
    toast(`${head}${sum ? `: ${sum}` : ''}`);
    state.pendingToast = null;
  }

  const dimWarn = r.drivers.woofer.dims_verified
    ? ''
    : `<div class="alert info">${esc(r.drivers.woofer.model)}: frame dimensions partly estimated – check the drawing before cutting.</div>`;
  $('#t-alerts').innerHTML = r.warnings.map((w) => `<div class="alert warn">⚠ ${esc(w)}</div>`).join('') + dimWarn;

  renderViews(r);
  renderSections(r);
  renderChart();
  renderPort(r);
}

function renderPort(r) {
  const p = r.port;
  const el = $('#t-port');
  const shortEl = $('#t-port-short');
  if (!el) return;

  $('#t-port-best').hidden = !p;
  if (shortEl) {
    if (!p) {
      shortEl.textContent = 'sealed (no port)';
    } else {
      const sizeStr = p.shape === 'slot'
        ? `${fmt(p.slot_w_mm, 0)}×${fmt(p.slot_h_mm, 0)} slot`
        : `Ø${fmt(p.d_mm, 0)}`;
      shortEl.textContent = `${p.count}× ${sizeStr} × ${fmt(p.length_mm, 0)} mm · ${fmt(p.vel_peak_ms, 1)} m/s`;
    }
  }
  if (!p) {
    el.innerHTML = '<p class="muted">Sealed box – no port.</p>';
    return;
  }

  const posText = (r.design.layout.positions.port || []).map((q) => (
    q.plan
      ? `x ${fmt(q.x, 0)} / depth ${fmt(q.z, 0)} mm (bottom panel, from left inner wall / baffle)`
      : `x ${fmt(q.x, 0)} / y ${fmt(q.y, 0)} mm on the baffle`
  )).join('; ');

  const typeDesc = p.shape === 'slot'
    ? `slot ${fmt(p.slot_w_mm, 0)} × ${fmt(p.slot_h_mm, 0)} mm (floor = one wall, 18 mm MDF shelf above)`
    : `${p.count}× ${esc(p.tube_name || 'tube')} – inner Ø ${fmt(p.d_mm, 1)} mm, outer Ø ${fmt(p.outer_d_mm, 0)} mm${p.flared ? ', flared ends' : ''}`;

  const rows = [
    ['Type', typeDesc],
    ['Cut length', `${fmt(p.length_mm, 0)} mm each (acoustic length ${fmt(p.leff_mm, 0)} mm incl. end correction) – max that fits ${fmt(p.max_len_mm, 0)} mm`],
    ['Where', `${p.location} · ${posText || '—'}`],
    ['Tuning', `${fmt(r.metrics.fb_hz, 1)} Hz · area ${fmt(p.area_cm2, 1)} cm² · first pipe resonance ${fmt(p.pipe_resonance_hz, 0)} Hz`],
    ['Air speed', `<b>${fmt(p.vel_peak_ms, 1)} m/s</b> peak at ${r.curves.design_power_w ?? r.curves.amp_w} W (quiet < 12, limit ${p.vel_limit_ms} m/s${p.flared ? ' flared' : ''})`],
  ];
  el.innerHTML = `<div class="kv">${rows.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join('')}</div><div id="t-port-opts"></div>`;
}

async function bestPort() {
  const box = $('#t-port-opts');
  box.innerHTML = '<p class="muted">Checking every pipe, flared kit and slot…</p>';
  try {
    const opts = await api('/api/port/options', state.design);
    const portLabel = (p) => (
      p.shape === 'slot'
        ? `slot ${fmt(p.slot_w_mm, 0)} × ${fmt(p.slot_h_mm, 0)} mm`
        : `${p.count}× ${p.tube_name}`
    );
    const rowsHtml = opts.map((p, i) => `
      <tr>
        <td>${esc(portLabel(p))}</td>
        <td class="num">${fmt(p.length_mm, 0)} mm</td>
        <td class="num">${fmt(p.vel_peak_ms, 1)} / ${p.vel_limit_ms} m/s</td>
        <td><button class="mini" data-pi="${i}">Use</button></td>
      </tr>`).join('');

    box.innerHTML = `
      <h3 class="mt">Ports that fit, quietest first</h3>
      <div class="tablewrap"><table><tr><th>Port</th><th class="num">Length</th><th class="num">Air speed</th><th></th></tr>${rowsHtml}</table></div>
      <p class="hint">Same tuning for all; bigger area = quieter but longer. Slots use the cabinet floor as one wall.</p>`;

    $$('[data-pi]').forEach((btn) => {
      btn.onclick = () => {
        const p = opts[+btn.dataset.pi];
        markChange(`port → ${portLabel(p)}`);
        Object.assign(state.design.box.port, {
          shape: p.shape,
          flared: p.flared,
          d_mm: p.shape === 'slot' ? null : p.d_mm,
          count: p.count,
          slot_w_mm: p.slot_w_mm,
        });
        if (state.design.layout.positions) delete state.design.layout.positions.port;
        state.xoTunedKey = null;
        actions.syncInputs();
        actions.simulate(0);
      };
    });
  } catch (err) {
    box.innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  }
}

function renderViews(r) {
  const host = $('#t-views');
  if (!host || !r) return;
  const sideBySide = (host.clientWidth || 500) > 420;
  const baseW = sideBySide ? (host.clientWidth - 28) * 0.58 : (host.clientWidth || 360) - 16;
  const pxW = Math.max(210, Math.min(460, baseW));
  const opts = { clear: $('#v-clear').checked, bolts: $('#v-bolts').checked };

  const svgs = r.system === 'sub'
    ? [frontSVG(r, false, true, Math.min(340, pxW * 1.2), opts)]
    : [frontSVG(r, false, true, pxW, opts), frontSVG(r, true, false, pxW * 0.62, opts)];

  host.innerHTML = svgs.map((s) => `<div class="view">${uniq(s)}</div>`).join('')
    + `<div class="vlegend"><span><i style="background:${COL.woofer}"></i>woofer</span><span><i style="background:${COL.mid}"></i>mid</span><span><i style="background:${COL.tweeter}"></i>tweeter</span><span><i style="background:${COL.port}"></i>port</span></div>`;
  enableDrag(host.querySelector('svg[data-front="L"]'), r);
}

function renderSections(r) {
  if (!r || !$('#t-sections-card').open) return;
  const w = Math.min(420, ($('#t-sections').clientWidth || 900) / 3 - 14);
  $('#t-sections').innerHTML = [sideSVG(r, w), topSVG(r, w), isoSVG(r, w)]
    .map((s) => `<div class="view">${uniq(s)}</div>`)
    .join('');
}
