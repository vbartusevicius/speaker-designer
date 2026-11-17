/* Step 1: quick presets, driver-first box synthesis, and cabinet potential summary. */
import { $, $$, actions, api, clone, deepMerge, esc, fmt, isSub, markChange, persist, state } from './state.js';
import { fillDriverSelect } from './catalog.js';
import { bassScale, frontDimSVG, sideDimSVG, uniq } from './svg.js';

const DS_SETS = {
  1: { sub: true },
  2: { w: 1, mid: false },
  3: { w: 1, mid: true },
  '3b': { w: 2, mid: false },
  4: { w: 2, mid: true },
  5: { w: 3, mid: true },
};

export function applyStartPreset(preset) {
  state.goals.start = preset;
  persist();
  if (preset === 'sub' || preset === 'drivers') {
    state.dsReady = false;
    if (preset === 'sub') {
      state.goals.dsN = '1';
    } else if (state.goals.dsN === '1' || !state.goals.dsN) {
      state.goals.dsN = '3';
    }
    initDriverStart();
    actions.syncBodyClasses();
    return;
  }

  markChange(`preset → ${preset}`);
  const design = clone(state.defaults.design);
  if (preset === 'bookshelf') {
    Object.assign(design.cabinet, {
      mode: 'free', outer_w: 240, outer_h: 390, outer_d: 300, wall_t: 18, baffle_t: 18,
    });
    design.drivers = {
      woofer: { id: 'dayton-rs150-8', count: 1 },
      mid: null,
      tweeter: { id: 'sb-sb26adc-c000-4' },
    };
    Object.assign(state.goals, { ways: '2', budget: 450, dual: false });
  } else if (preset === 'tower') {
    Object.assign(design.cabinet, {
      mode: 'free', outer_w: 280, outer_h: 900, outer_d: 340, wall_t: 18, baffle_t: 18,
    });
    Object.assign(state.goals, { ways: '3', budget: 800, dual: true });
  } else {
    Object.assign(design.cabinet, {
      mode: 'fit', inner_w: 500, inner_h: 400, inner_d: 350, wall_t: 18, baffle_t: 18,
    });
    Object.assign(state.goals, { ways: '3', budget: 700, dual: true });
  }

  state.design = design;
  delete state.design.system;
  state.autoPick = true;
  state.xoManual = false;
  state.xoTunedKey = null;

  const cab = state.design.cabinet;
  if (cab.mode === 'free') {
    cab.outer_w ??= cab.inner_w + 2 * cab.wall_t;
    cab.outer_h ??= cab.inner_h + 2 * cab.wall_t;
    cab.outer_d ??= cab.inner_d + 2 * cab.wall_t;
  }

  actions.syncGoalsUI?.();
  actions.syncInputs();
  actions.simulate(0);
  refreshPotential();
  actions.runFind(true, preset);
}

function defaultDriverSetKey() {
  const drivers = state.design.drivers;
  if (isSub()) return '1';
  if (drivers.mid) return drivers.woofer.count > 1 ? '4' : '3';
  return drivers.woofer.count > 1 ? '3b' : '2';
}

export function initDriverStart() {
  const drivers = state.design.drivers;
  if (!state.goals.dsN) state.goals.dsN = defaultDriverSetKey();

  $('#ds-woofer').value = drivers.woofer.id;
  if (drivers.tweeter) $('#ds-tweeter').value = drivers.tweeter.id;
  if (drivers.mid) $('#ds-mid').value = drivers.mid.id;
  $('#ds-open').hidden = !state.dsReady;

  const updateSetUI = () => {
    const set = DS_SETS[state.goals.dsN];
    $$('#drv-count button').forEach((btn) => {
      btn.classList.toggle('on', btn.dataset.n === String(state.goals.dsN));
    });
    $('.ds-mid').hidden = !set.mid;
    document.body.classList.toggle('ds-one', !!set.sub);

    const wooferSelect = $('#ds-woofer');
    const roles = set.sub ? 'subwoofer,woofer' : 'woofer,midwoofer';
    if (wooferSelect.dataset.roles !== roles) {
      wooferSelect.dataset.roles = roles;
      fillDriverSelect(wooferSelect);
      const hasDaytonSub = [...wooferSelect.options].some((o) => o.value === 'dayton-rss265hf-4');
      if (set.sub && hasDaytonSub) wooferSelect.value = 'dayton-rss265hf-4';
    }
    $('.ds-wlabel').textContent = set.sub ? 'Subwoofer driver' : 'Woofer';
  };

  $$('#drv-count button').forEach((btn) => {
    btn.onclick = () => {
      state.goals.dsN = btn.dataset.n;
      persist();
      updateSetUI();
    };
  });
  updateSetUI();

  $('#ds-go').onclick = async () => {
    const set = DS_SETS[state.goals.dsN];
    const fixed = {};
    if (+$('#ds-w').value) fixed.outer_w = +$('#ds-w').value;
    if (+$('#ds-h').value) fixed.outer_h = +$('#ds-h').value;
    $('#ds-out').textContent = 'Designing…';

    if (set.sub) {
      try {
        const res = await api('/api/sub/reverse', {
          woofer: $('#ds-woofer').value,
          woofer_count: +$('#ds-subn').value,
          alignment: $('#ds-align').value,
          fixed,
        });
        markChange('subwoofer from driver');
        state.design = res.result.design;
        state.dsReady = true;
        $('#ds-open').hidden = false;
        const cab = res.result.design.cabinet;
        const m = res.result.metrics;
        $('#ds-out').textContent = `${m.box_type}, ${fmt(m.net_volume_L, 0)} L → ${fmt(cab.outer_w, 0)} × ${fmt(cab.outer_h, 0)} × ${fmt(cab.outer_d, 0)} mm, −3 dB at ${fmt(m.woofer_f3_hz, 0)} Hz.`;
        actions.syncInputs();
        actions.simulate(0);
        refreshPotential();
      } catch (err) {
        $('#ds-out').textContent = err.message;
      }
      return;
    }

    try {
      const res = await api('/api/reverse', {
        woofer: $('#ds-woofer').value,
        woofer_count: set.w,
        mid: set.mid ? $('#ds-mid').value : null,
        tweeter: $('#ds-tweeter').value,
        alignment: $('#ds-align').value,
        fixed,
        crossover_mode: state.goals.amp,
        port_location: state.goals.port === 'sealed' ? 'front' : state.goals.port,
        layout_style: 'auto',
      });
      markChange('enclosure from drivers');
      state.design = deepMerge(state.defaults.design, res.result.design);
      delete state.design.system;
      state.autoPick = false;
      if ($('#g-auto')) $('#g-auto').checked = false;
      state.xoManual = false;
      state.xoTunedKey = null;
      state.dsReady = true;
      $('#ds-open').hidden = false;

      const cab = res.result.design.cabinet;
      $('#ds-out').textContent = `${res.alignment.type}, ${fmt(res.result.metrics.net_volume_L, 0)} L net → ${fmt(cab.outer_w, 0)} × ${fmt(cab.outer_h, 0)} × ${fmt(cab.outer_d, 0)} mm.`;
      actions.syncInputs();
      actions.simulate(0);
      refreshPotential();
      actions.runFind(false);
    } catch (err) {
      $('#ds-out').textContent = err.message;
    }
  };
}

let potTimer;
export function refreshPotential() {
  clearTimeout(potTimer);
  potTimer = setTimeout(async () => {
    try {
      state.potential = await api('/api/potential', {
        cabinet: state.design.cabinet,
        three_way: state.goals.ways !== '2',
      });
      if (state.step === 'space' && state.result) renderSpace(state.result);
    } catch {}
  }, 250);
}

function describeBassReach(f3) {
  if (f3 <= 25) return 'Subwoofer-deep bass';
  if (f3 <= 35) return 'Deeper than most floorstanders';
  if (f3 <= 45) return 'Like a solid floorstander';
  if (f3 <= 60) return 'Like a large bookshelf';
  return 'Compact bookshelf bass';
}

export function renderSpace(result) {
  const hostW = $('#space-views').clientWidth || 520;
  const viewW = Math.max(210, Math.min(270, Math.floor((hostW - 28) / 2)));
  $('#space-views').innerHTML = [frontDimSVG(result, viewW), sideDimSVG(result, viewW)]
    .map((svg) => `<div class="view">${uniq(svg)}</div>`)
    .join('');

  const P = state.potential;
  if (!P) return;
  const vols = result.volumes;
  const best = P.best;
  const sizes = P.fit.sizes_mm;
  const sizeRange = sizes.length ? `${sizes[0] / 10}–${sizes.at(-1) / 10} cm` : '—';
  const notesHtml = P.notes.map((n) => {
    const ok = best.vented_f3 && best.vented_f3 <= n.hz;
    const suffix = ok ? '' : ' <span class="muted">(rolled off)</span>';
    return `<li class="${ok ? 'y' : 'n'}">${ok ? '✓' : '–'} ${fmt(n.hz, 1)} Hz – ${esc(n.label)}${suffix}</li>`;
  }).join('');

  const wooferRows = P.woofers.map((w) => {
    const stockBadge = w.in_stock ? '' : ' <span class="tag warn">out of stock</span>';
    const maxSpl = Math.max(w.max_spl_40_vented, w.max_spl_40_sealed);
    return `<tr>
      <td>${esc(w.name)}${stockBadge}</td>
      <td class="num">${fmt(w.nominal_mm / 10, 0)} cm</td>
      <td class="num">${fmt(w.vented_f3, 0)} Hz</td>
      <td class="num">${fmt(w.sealed_f3, 0)} Hz</td>
      <td class="num">${fmt(maxSpl, 0)} dB</td>
      <td class="num">${fmt(w.price_eur, 0)}</td>
    </tr>`;
  }).join('');

  $('#space-meaning').innerHTML = `
    <div class="space-kpis">
      <div class="space-kpi"><b>~${fmt(vols.net_L, 0)} L</b><span>usable air (${fmt(vols.items[0].L, 0)} L gross)</span></div>
      <div class="space-kpi"><b>~${fmt(best.vented_f3, 0)} Hz</b><span>deepest ported (~${fmt(best.sealed_f3, 0)} sealed)</span></div>
      <div class="space-kpi"><b>~${fmt(best.max_spl_40, 0)} dB</b><span>max output @ 40 Hz</span></div>
    </div>
    <p class="hint"><b>${describeBassReach(best.vented_f3)}</b> · drivers up to ${sizeRange} (depth ≤ ${fmt(P.fit.max_driver_depth_mm, 0)} mm).</p>
    <div class="scale">${bassScale(P)}</div>
    <details class="adv mt">
      <summary>Musical notes &amp; compatible woofers (${P.woofers.length})</summary>
      <ul class="notes-list">${notesHtml}</ul>
      <div class="tablewrap mt">
        <table>
          <tr><th>Woofer</th><th class="num">Size</th><th class="num">Vented −3 dB</th><th class="num">Sealed −3 dB</th><th class="num">Max @40 Hz</th><th class="num">€</th></tr>
          ${wooferRows}
        </table>
      </div>
    </details>`;
}
