/* App entrypoint: initialization, step routing, input binding, simulation loop, and resize handling. */
import {
  $, $$, HELP, STEPS, actions, api, deepMerge, download, esc, getPath, initGlossary, isSub,
  markChange, persist, resetXo, setPath, state, store,
} from './state.js';
import { initDb, loadDrivers } from './catalog.js';
import { resizeCharts } from './charts.js';
import { highlightDim } from './svg.js';
import { applyStartPreset, initDriverStart, refreshPotential, renderSpace } from './start.js';
import {
  ensureCrossoverTuned, initGoals, initWorkspace, renderDesign, renderRanks, renderSubDesign,
  runFind, syncGoalsUI, xoSig,
} from './design.js';
import { initBuild, renderBuild, renderSubBuild } from './build.js';

function labelFor(el) {
  const lbl = el.closest('label');
  if (!lbl) return el.dataset.path;
  return lbl.childNodes[0].textContent.trim() || lbl.textContent.trim().split('\n')[0];
}

function setInput(el, val) {
  if (el.type === 'checkbox') {
    el.checked = !!val;
  } else {
    el.value = val == null ? '' : val;
  }
}

export function syncBodyClasses() {
  const free = state.design.cabinet.mode === 'free';
  const drvStart = state.goals.start === 'drivers' || state.goals.start === 'sub';
  const fallbackPreset = free ? 'bookshelf' : 'fit';
  const activePreset = state.goals.start || fallbackPreset;

  document.body.classList.toggle('mode-fit', !free);
  document.body.classList.toggle('mode-free', free);
  document.body.classList.toggle('mode-drivers', drvStart);
  document.body.classList.toggle('ds-ready', !!state.dsReady);
  document.body.classList.toggle('sys-sub', isSub());
  document.body.classList.toggle('xo-active', state.design.crossover?.mode === 'active');

  $$('#mode-choice .choice').forEach((btn) => {
    btn.classList.toggle('on', btn.dataset.preset === activePreset);
  });
}

export function syncInputs() {
  $$('[data-path]').forEach((el) => {
    const path = el.dataset.path;
    const val = path === 'drivers.mid.id'
      ? (state.design.drivers.mid || {}).id
      : getPath(state.design, path);
    setInput(el, val);
  });
  syncBodyClasses();
}

function onModeChange() {
  const cab = state.design.cabinet;
  if (cab.mode === 'free') {
    cab.outer_w ??= cab.inner_w + 2 * cab.wall_t;
    cab.outer_h ??= cab.inner_h + 2 * cab.wall_t;
    cab.outer_d ??= cab.inner_d + 2 * cab.wall_t;
  }
  syncInputs();
}

function bindInputs() {
  $$('[data-path]').forEach((el) => {
    el.addEventListener('change', () => {
      const path = el.dataset.path;
      let val = el.type === 'checkbox' ? el.checked : el.value;
      if (el.type === 'number') val = val === '' ? null : Number(val);
      if (el.tagName === 'SELECT' && val === '') val = null;

      markChange(labelFor(el));
      if (path === 'drivers.mid.id') {
        state.design.drivers.mid = val ? { id: val } : null;
      } else {
        setPath(state.design, path, val);
      }

      if (path.startsWith('drivers.') || path.startsWith('cabinet.') || path === 'layout.style' || path === 'layout.min_web_mm') {
        state.design.layout.positions = null;
      }
      if (path.startsWith('box.') && state.design.layout.positions) {
        delete state.design.layout.positions.port;
      }
      if (path.startsWith('drivers.')) {
        state.autoPick = false;
        $('#g-auto').checked = false;
        resetXo(state.design);
        state.xoManual = false;
        state.xoTunedKey = null;
      }
      if (path.startsWith('crossover.') && path !== 'crossover.mode') {
        state.xoManual = true;
      }
      if (path === 'crossover.mode' || path.startsWith('box.') || path.startsWith('cabinet.')) {
        state.xoTunedKey = null;
      }
      if (path === 'cabinet.mode') {
        onModeChange();
      }

      $$(`[data-path="${path}"]`).forEach((other) => {
        if (other !== el) setInput(other, getPath(state.design, path));
      });

      syncBodyClasses();
      simulate();
      if (path.startsWith('cabinet.')) {
        refreshPotential();
        runFind(false);
      }
    });
  });

  $$('[data-dim]').forEach((el) => {
    el.addEventListener('focus', () => highlightDim(el.dataset.dim));
    el.addEventListener('blur', () => highlightDim(null));
  });

  $$('#mode-choice .choice').forEach((btn) => {
    btn.onclick = () => applyStartPreset(btn.dataset.preset);
  });
}

let simTimer = null;
let simSeq = 0;
let xoAutoTimer = null;

export function simulate(delay = 150) {
  clearTimeout(simTimer);
  simTimer = setTimeout(runSimulate, delay);
}

export async function runSimulate() {
  const seq = ++simSeq;
  try {
    const endpoint = isSub() ? '/api/sub/simulate' : '/api/simulate';
    const result = await api(endpoint, state.design);
    if (seq !== simSeq) return;

    if (!state.checkedStoredLayout) {
      state.checkedStoredLayout = true;
      const errors = (result.layout_issues || []).filter((i) => i.level === 'error');
      if (errors.length && state.design.layout.positions) {
        state.design.layout.positions = null;
        state.pendingToast = `Your saved layout broke the current layout rules (${errors[0].msg}) – it was re-laid out automatically.`;
        simulate(0);
        return;
      }
    }

    state.result = result;
    state.design.layout.positions = result.design.layout.positions;
    persist();

    $$('[data-auto]').forEach((el) => {
      const val = getPath(result, el.dataset.auto);
      el.placeholder = val == null ? 'auto' : `auto (${val})`;
    });

    renderStep();

    const needsAutoTune = !isSub() && !state.xoManual && !state.tuningXo
      && state.xoTunedKey !== xoSig() && state.step === 'design';
    if (needsAutoTune) {
      clearTimeout(xoAutoTimer);
      xoAutoTimer = setTimeout(() => ensureCrossoverTuned(true), 350);
    }
  } catch (err) {
    const box = `<div class="alert bad">⚠ ${esc(err.message)}</div>`;
    $('#t-alerts').innerHTML = box;
    $('#space-meaning').innerHTML = box;
  }
}

export function renderStep() {
  const result = state.result;
  if (!result) return;
  const fullRange = { space: renderSpace, design: renderDesign, build: renderBuild };
  const sub = { space: renderSpace, design: renderSubDesign, build: renderSubBuild };
  const handler = (isSub() ? sub : fullRange)[state.step];
  if (handler) handler(result);
}

export async function showStep(stepName) {
  let step = STEPS.includes(stepName) ? stepName : 'space';
  if (step === 'build' && !isSub() && !state.xoManual && state.xoTunedKey !== xoSig()) {
    await ensureCrossoverTuned(true);
  }
  state.step = step;
  $$('.step').forEach((el) => el.classList.toggle('active', el.id === `step-${step}`));
  $$('#stepper li').forEach((li) => {
    li.classList.toggle('active', li.dataset.step === step);
    li.classList.toggle('done', STEPS.indexOf(li.dataset.step) < STEPS.indexOf(step));
  });
  $('#help').innerHTML = HELP[step];
  $('#stage').scrollTop = 0;
  document.scrollingElement.scrollTop = 0;
  persist();
  if (state.result) renderStep();
  if (step === 'design' && !isSub() && !state.xoManual && state.xoTunedKey !== xoSig()) {
    ensureCrossoverTuned(true);
  }
}

async function init() {
  Object.assign(actions, {
    simulate,
    runSimulate,
    syncInputs,
    syncBodyClasses,
    showStep,
    refreshPotential,
    renderStep,
  });

  initGlossary();
  new ResizeObserver(([entry]) => {
    document.documentElement.style.setProperty('--top', `${entry.target.offsetHeight}px`);
  }).observe($('header.top'));

  state.defaults = await api('/api/defaults');
  state.config = await api('/api/config').catch(() => ({}));
  document.body.classList.toggle('read-only', !!state.config.read_only);

  state.design = deepMerge(state.defaults.design, store.get('design', {}));
  state.goals = { ...state.goals, ...store.get('goals', {}) };
  state.autoPick = store.get('auto', true);

  await loadDrivers();
  bindInputs();
  syncInputs();
  initGoals();
  initWorkspace();
  initBuild();
  initDb();

  $$('#stepper li').forEach((li) => { li.onclick = () => showStep(li.dataset.step); });
  $$('[data-goto]').forEach((btn) => { btn.onclick = () => showStep(btn.dataset.goto); });
  $('#btn-help').onclick = () => { $('#drawer').hidden = !$('#drawer').hidden; };
  $('#drawer-close').onclick = () => { $('#drawer').hidden = true; };

  $('#btn-save').onclick = () => {
    const blob = new Blob([JSON.stringify({ design: state.design, goals: state.goals }, null, 1)], { type: 'application/json' });
    download(blob, `${state.design.name || 'speaker-project'}.json`);
  };

  $('#btn-load').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const saved = JSON.parse(await file.text());
    state.design = deepMerge(state.defaults.design, saved.design || saved);
    if (saved.goals) state.goals = { ...state.goals, ...saved.goals };
    if (state.goals.start === 'drivers' || state.goals.start === 'sub') {
      state.dsReady = true;
      initDriverStart();
    }
    state.xoTunedKey = null;
    syncGoalsUI();
    syncInputs();
    state.find = null;
    simulate();
    refreshPotential();
  };

  $('#btn-reset').onclick = () => {
    if (!confirm('Start over? Your current project and checklist will be cleared.')) return;
    state.resetting = true;
    Object.keys(localStorage)
      .filter((k) => k.startsWith('sp-'))
      .forEach((k) => localStorage.removeItem(k));
    location.reload();
  };

  const pickBtn = $('#btn-pick-drivers');
  const picker = $('#drv-picker-dialog');
  if (pickBtn && picker) {
    pickBtn.onclick = () => { renderRanks(); picker.showModal(); };
    $('#drv-picker-close').onclick = () => picker.close();
    picker.onclick = (e) => { if (e.target === picker) picker.close(); };
  }

  if (state.goals.start === 'drivers' || state.goals.start === 'sub') {
    initDriverStart();
  }

  let startStep = store.get('step', 'space');
  if (startStep === 'overview') {
    startStep = 'build';
    state.btab = 'check';
  }
  showStep(startStep);
  simulate(0);
  refreshPotential();
  runFind(false);

  window.__appState = state;
}

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.result) renderStep();
    resizeCharts();
  }, 150);
});

init();
