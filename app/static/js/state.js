/* Shared state, persistence, API client, formatting helpers, and glossary/help data. */

export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => [...document.querySelectorAll(selector)];

export const COL = {
  woofer: '#2563eb',
  mid: '#16a34a',
  tweeter: '#dc2626',
  sum: '#0f172a',
  port: '#9333ea',
};

export const STEPS = ['space', 'design', 'build'];

export const clone = (obj) => JSON.parse(JSON.stringify(obj));

export function fmt(val, decimals = 1) {
  if (val == null || Number.isNaN(+val)) return '—';
  return (+val).toFixed(decimals);
}

export function eur(val) {
  return val == null ? '—' : `€${(+val).toFixed(0)}`;
}

export function esc(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
  return String(str ?? '').replace(/[&<>"]/g, (ch) => map[ch]);
}

export const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(`sp-${key}`);
      return raw == null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, val) {
    localStorage.setItem(`sp-${key}`, JSON.stringify(val));
  },
};

export const state = {
  defaults: null,
  config: {},
  design: null,
  result: null,
  prev: null,
  undo: null,
  txUntil: 0,
  txLabel: '',
  pendingToast: null,
  drivers: [],
  find: null,
  potential: null,
  chart: 'spl',
  sel: null,
  step: 'space',
  btab: 'bom',
  autoPick: true,
  dsReady: false,
  xoTunedKey: null,
  xoManual: false,
  tuningXo: false,
  checkedStoredLayout: false,
  resetting: false,
  pickSlot: null,
  dbMode: 'browse',
  repTarget: null,
  repData: null,
  dbLimit: 60,
  goals: {
    start: 'fit',
    budget: 700,
    amp: 'active',
    style: 'balanced',
    port: 'front',
    ways: '3',
    tier: 3,
    stock: false,
    dual: true,
  },
};

/* Callback hooks wired by main.js / start.js / design.js to avoid circular imports. */
export const actions = {
  simulate: () => {},
  runSimulate: async () => {},
  syncInputs: () => {},
  syncBodyClasses: () => {},
  syncGoalsUI: () => {},
  showStep: () => {},
  refreshPotential: () => {},
  runFind: () => {},
  renderStep: () => {},
  placeChecked: () => {},
  runBem: () => {},
  openCatalogPicker: () => {},
  openDriverDetail: () => {},
};

export const PRESETS = {
  balanced: { bass: 1, output: 0.7, accuracy: 1, quality: 0.8, value: 0.4 },
  deep: { bass: 1.8, output: 1.3, accuracy: 0.7, quality: 0.5, value: 0.3 },
  accurate: { bass: 0.6, output: 0.4, accuracy: 1.8, quality: 1.3, value: 0.3 },
  value: { bass: 0.8, output: 0.6, accuracy: 0.8, quality: 0.3, value: 1.6 },
};

export const STYLE_NAME = {
  balanced: 'Balanced',
  deep: 'Deep bass',
  accurate: 'Accuracy',
  value: 'Value',
};

export const isSub = () => state.design?.system === 'sub';

export function getPath(obj, path) {
  return path.split('.').reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

export function setPath(obj, path, val) {
  const keys = path.split('.');
  let cur = obj;
  for (const key of keys.slice(0, -1)) {
    if (cur[key] == null || typeof cur[key] !== 'object') cur[key] = {};
    cur = cur[key];
  }
  cur[keys.at(-1)] = val;
}

export function deepMerge(base, override) {
  const out = clone(base);
  for (const [k, v] of Object.entries(override || {})) {
    const bothObjects = v && typeof v === 'object' && !Array.isArray(v)
      && out[k] && typeof out[k] === 'object';
    out[k] = bothObjects ? deepMerge(out[k], v) : clone(v);
  }
  return out;
}

export function setStatus(msg, cls = '') {
  const el = $('#status');
  if (!el) return;
  el.textContent = msg;
  el.className = `status ${cls}`;
}

export async function api(path, body, raw = false, method) {
  setStatus('calculating…', 'busy');
  try {
    const opts = body === undefined
      ? { method: method || 'GET' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail;
      try {
        detail = (await res.json()).detail;
      } catch {
        detail = res.statusText;
      }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    const out = raw ? await res.blob() : await res.json();
    setStatus('✓ up to date');
    return out;
  } catch (err) {
    setStatus(err.message, 'err');
    throw err;
  }
}

export function download(blob, name) {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 2000);
}

export function persist() {
  if (state.resetting) return;
  store.set('design', state.design);
  store.set('goals', state.goals);
  store.set('step', state.step);
  store.set('auto', state.autoPick);
}

export function markChange(label) {
  const now = Date.now();
  if (now > state.txUntil) {
    state.prev = state.result;
    state.undo = clone(state.design);
    state.txLabel = label;
  } else if (label) {
    state.txLabel = label;
  }
  state.txUntil = now + 2500;
}

export function resetXo(design) {
  if (!design.crossover) return;
  Object.assign(design.crossover, {
    f_wm: null,
    f_mt: null,
    levels: null,
    polarity: null,
    kind: null,
  });
}

export function resetAuto(design) {
  design.box.fb = null;
  design.box.port.d_mm = null;
  design.box.port.count = null;
  resetXo(design);
  design.layout.positions = null;
}

/* ---------------- Glossary & Help ---------------- */
export const GLOSS = {
  Fs: ['Resonance frequency (Fs)', 'Frequency where the cone resonates in free air. Lower Fs → the driver can go deeper. Tweeters are crossed at 2.5–3× Fs or higher.'],
  Qts: ['Total Q (Qts)', 'How damped the resonance is. ~0.2–0.4 suits vented boxes, ~0.4–0.7 suits sealed boxes.'],
  Vas: ['Equivalent volume (Vas)', 'Volume of air with the same stiffness as the cone suspension. Big Vas → needs a big box.'],
  Sd: ['Cone area (Sd)', 'Effective radiating area of the cone. Sd × Xmax = how much air it can move = bass output.'],
  Xmax: ['Linear excursion (Xmax)', 'How far (one way) the cone moves before distortion rises sharply. Exceeding it sounds bad and can damage the driver.'],
  EBP: ['Efficiency-bandwidth product', 'Fs / Qes. Below ~50 → sealed box, above ~90 → vented box, in between: either.'],
  fb: ['Port tuning (fb)', 'Frequency where the air in the port resonates with the air in the box. Bass rolls off quickly (24 dB/oct) below it.'],
  F3: ['F3 (−3 dB point)', 'Frequency where the bass is 3 dB down. Anechoic value; in a room near a wall you get several dB more bass.'],
  Qtc: ['Sealed-box Q (Qtc)', '0.5 = very tight and lean, 0.707 = flattest (Butterworth), 1.0+ = boomy.'],
  baffle_step: ['Baffle step', 'At low frequency sound wraps around the cabinet (radiates in all directions) – the speaker loses up to 6 dB below ~115/width[m] Hz. A wider flat front lowers this frequency.'],
  diffraction: ['Baffle diffraction', 'The baffle edges re-radiate sound with a delay, creating ripples of ±1–3 dB. Off-centre drivers and rounded edges smooth it.'],
  fx: ['Crossover frequency', 'Where one driver hands over to the next. Choose it where both drivers are comfortable: below the woofer\'s break-up/beaming and well above the tweeter\'s Fs.'],
  LR4: ['Linkwitz-Riley 24 dB/oct', 'The standard active crossover: both sides −6 dB at the crossover, they sum perfectly flat and in phase.'],
  LR2: ['Linkwitz-Riley 12 dB/oct', 'Common 2nd-order passive crossover; one driver usually wired with inverted polarity.'],
  zobel: ['Zobel network', 'A resistor + capacitor across a woofer/mid that cancels the rising voice-coil impedance so the passive filter behaves as designed.'],
  lpad: ['L-pad', 'Two resistors that reduce a louder driver (usually the tweeter) to match the others without changing the impedance the filter sees.'],
  port_speed: ['Port air speed', 'Air rushing through the port. Above ~17 m/s (25 m/s flared) you hear chuffing. Bigger or flared ports reduce it.'],
  group_delay: ['Group delay', 'How much later the bass arrives than the treble. Below ~1.5 cycles at a given frequency is considered inaudible.'],
  sens: ['Sensitivity', 'Loudness at 1 m with 2.83 V (1 W into 8 Ω). +3 dB means half the amplifier power for the same loudness.'],
  maxspl: ['Maximum SPL', 'Loudest the woofer can play at each frequency before hitting Xmax, its power rating or port-noise limit.'],
  web: ['MDF web', 'Material left between two flush-mount rebates. Under ~10 mm it can chip or crack during routing.'],
  rebate: ['Flush-mount rebate', 'A shallow pocket (flange thickness deep) so the driver sits flush with the baffle – smoother response and cleaner look.'],
  HT: ['HT/KG pipe', 'European plastic drain pipe (EN 1451), sold in DIY stores in DN40…DN125 – cheap, accurate port tubes.'],
  MKP: ['MKP capacitor', 'Polypropylene film capacitor – the standard for crossovers (low loss, stable). Combine two in parallel to hit odd values.'],
  DCR: ['Coil resistance (DCR)', 'Resistance of an inductor\'s wire. In series with a woofer it costs sensitivity and damping – keep it low.'],
  mid_chamber: ['Mid chamber', 'A small sealed box behind the midrange so the woofer\'s pressure does not push the mid cone.'],
  net_volume: ['Net volume', 'Air volume the woofer actually "sees": gross inside volume minus drivers, mid chamber, port tube and bracing.'],
};

export const term = (key, label) => `<span class="term" data-term="${key}">${label ?? key}</span>`;

export function initGlossary() {
  const tip = $('#tip');
  document.addEventListener('mouseover', (e) => {
    const target = e.target.closest('[data-term],[data-tip]');
    if (!target) {
      tip.hidden = true;
      return;
    }
    const entry = target.dataset.term ? GLOSS[target.dataset.term] : null;
    tip.innerHTML = entry ? `<b>${entry[0]}</b><br>${entry[1]}` : target.dataset.tip;
    tip.hidden = false;
    const rect = target.getBoundingClientRect();
    tip.style.left = `${Math.min(rect.left, innerWidth - 360)}px`;
    const top = rect.bottom + 6 > innerHeight - 120
      ? rect.top - tip.offsetHeight - 6
      : rect.bottom + 6;
    tip.style.top = `${top}px`;
  });

  const renderGlossaryList = () => {
    const q = $('#gl-q').value.toLowerCase();
    $('#gl-list').innerHTML = Object.entries(GLOSS)
      .filter(([k, [title, desc]]) => !q || (k + title + desc).toLowerCase().includes(q))
      .map(([, [title, desc]]) => `<dt>${title}</dt><dd>${desc}</dd>`)
      .join('');
  };
  $('#gl-q').oninput = renderGlossaryList;
  renderGlossaryList();
}

export const HELP = {
  space: `<h3>Start</h3><ul>
    <li>Pick a template (<b>Bookshelf</b>, <b>Floorstander</b>, <b>Built-in space</b>, <b>Subwoofer</b>) or choose <b>From drivers</b>.</li>
    <li>The right card summarizes usable volume, deepest bass reach, and compatible drivers.</li>
  </ul>`,
  design: `<h3>Design workspace</h3><ul>
    <li><b>Top</b>: click any active driver card for full specs, <b>Change</b> to browse all 1,300+ drivers, or <b>Replace</b> for drop-in matches.</li>
    <li><b>Stage</b>: drag drivers on the front panel (or use arrow keys) while watching the sound curve react live.</li>
    <li><b>Tuning</b>: crossover tunes automatically when drivers or box change; <b>Auto-optimize</b> tunes layout + port + crossover together; <b>Verify with BEM</b> runs a full 3D check.</li>
  </ul>`,
  build: `<h3>Build</h3><p>Use the tabs to move through shopping, wiring/DSP settings, CNC panel templates, and your assembly checklist + engine checks.</p>`,
};

/* ---------------- Shared UI helpers ---------------- */
export function kv(rows) {
  const cells = rows.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join('');
  return `<div class="kv">${cells}</div>`;
}

export function metricTile(title, value, sub, cls, tip) {
  const tipAttr = tip ? `data-tip="${esc(tip)}"` : '';
  const subHtml = sub ? `<div class="s">${sub}</div>` : '';
  return `<div class="metric ${cls}" ${tipAttr}><div class="k">${title}</div><div class="v">${value}</div>${subHtml}</div>`;
}

export function minWeb(result) {
  if (!result.clearances?.length) return null;
  return Math.min(...result.clearances.map((c) => c.web_mm));
}

export function grade(key, val, result) {
  if (val == null) return key === 'port' ? 'ok' : '';
  const band = (good, ok, higherBetter = false) => {
    if (higherBetter) return val >= good ? 'ok' : val >= ok ? 'warn' : 'bad';
    return val <= good ? 'ok' : val <= ok ? 'warn' : 'bad';
  };
  const limits = {
    f3: () => band(32, 45),
    dev: () => band(2, 3.5),
    spl40: () => band(100, 94, true),
    sens: () => band(87, 84, true),
    port: () => band(12, result.port?.vel_limit_ms ?? 17),
    zmin: () => band(3.5, 3.0, true),
    web: () => band(result.design.layout.min_web_mm ?? 10, 3, true),
    peak: () => band(1, 2),
  };
  return limits[key] ? limits[key]() : '';
}

export function deltaBadge(key, now, dir, decimals) {
  const prev = state.prev?.metrics?.[key];
  if (prev == null || now == null) return '';
  const diff = now - prev;
  if (Math.abs(diff) < Math.pow(10, -decimals) * 0.5) return '';
  const cls = diff * dir > 0 ? 'better' : 'worse';
  const arrow = diff > 0 ? '▲' : '▼';
  return `<span class="d ${cls}">${arrow}${fmt(Math.abs(diff), decimals)}</span>`;
}

const DELTA = [
  ['woofer_f3_hz', 'bass', -1, 'Hz', 0],
  ['deviation_db', 'flatness ±', -1, 'dB', 1],
  ['sensitivity_db_2v83_1m', 'sensitivity', 1, 'dB', 1],
  ['max_spl_40hz', '40 Hz max', 1, 'dB', 0],
  ['price_drivers_pair_eur', 'drivers', -1, '€', 0],
];

export function changeSummary(result) {
  if (!state.prev) return '';
  return DELTA.map(([key, label, , unit, dp]) => {
    const before = state.prev.metrics[key];
    const after = result.metrics[key];
    if (before == null || after == null) return null;
    if (Math.abs(before - after) < Math.pow(10, -dp) * 0.5) return null;
    const fromTxt = unit === '€' ? `€${fmt(before, 0)}` : fmt(before, dp);
    const toTxt = unit === '€' ? `€${fmt(after, 0)}` : `${fmt(after, dp)} ${unit}`;
    return `${label} ${fromTxt} → <b>${toTxt}</b>`;
  }).filter(Boolean).join(' · ');
}
