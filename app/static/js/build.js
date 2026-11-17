/* Step 3: tabbed Build & export (Shopping list, Wiring & crossover, CNC & panels, Checklist & summary). */
import { $, $$, COL, actions, api, download, esc, eur, fmt, kv, state, store, term } from './state.js';
import { LOGX, plotBase } from './charts.js';
import { isoSVG, partSVG, uniq, wiringSVG } from './svg.js';

const WIRING_HELP = `
  <details class="adv">
    <summary>How to read the diagram</summary>
    <p class="hint">
      red = + wire, black = − wire. Parts drawn <b>on</b> the + wire are in <b>series</b>
      (the signal passes through them); parts drawn <b>between</b> + and − are <b>shunts</b>
      (one leg to +, one leg to −). Order matters: build each branch from the input towards
      the driver exactly as shown. “a + b µF” = two capacitors connected in parallel and used
      as one part. A dot = joint; crossing lines without a dot are not connected.
    </p>
  </details>`;

export function setBuildTab(tab) {
  state.btab = tab;
  $$('#build-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.btab === tab));
  $$('.btab').forEach((p) => p.classList.toggle('active', p.id === `btab-${tab}`));
  if (tab === 'check' && document.getElementById('ov-chart')?.data) {
    Plotly.Plots.resize('ov-chart');
  }
}

export function initBuild() {
  $$('[data-dl]').forEach((btn) => { btn.onclick = () => exportFile(btn.dataset.dl); });
  $$('#build-tabs button').forEach((btn) => { btn.onclick = () => setBuildTab(btn.dataset.btab); });
  setBuildTab(state.btab || 'bom');
}

async function exportFile(kind, part) {
  const filenames = {
    zip: 'speaker_project.zip',
    dxf: `${part || 'panels'}.dxf`,
    cutlist: 'cutlist.csv',
    build: 'BUILD.md',
    svg: `${part || 'template'}.svg`,
  };
  const qs = part ? `?part=${encodeURIComponent(part)}` : '';
  const blob = await api(`/api/export/${kind}${qs}`, state.design, true);
  download(blob, filenames[kind].replace(/[\/ ]/g, '_'));
}

function volumeTable(r) {
  const rows = r.volumes.items
    .map((item) => `<tr><td>${esc(item.label)}</td><td class="num">${fmt(item.L, 2)}</td></tr>`)
    .join('');
  const chamberNote = r.chamber
    ? `<p class="hint">${term('mid_chamber', 'Mid chamber')}: inside ${fmt(r.chamber.inner_w, 0)} × ${fmt(r.chamber.inner_h, 0)} × ${fmt(r.chamber.inner_depth, 0)} mm (12 mm MDF) = ${fmt(r.chamber.Vb_L, 2)} L, resonance ${fmt(r.metrics.mid_chamber_fc_hz, 0)} Hz.</p>`
    : '';
  return `
    <div class="tablewrap">
      <table>
        <tr><th>Item</th><th class="num">Litres</th></tr>
        ${rows}
        <tr class="total"><td>Net volume</td><td class="num">${fmt(r.volumes.net_L, 2)}</td></tr>
        <tr><td>Acts like (with damping)</td><td class="num">${fmt(r.volumes.effective_L, 2)}</td></tr>
      </table>
    </div>
    ${chamberNote}`;
}

export async function renderBuild(r) {
  let parts = [];
  try {
    parts = await api('/api/export/parts', state.design);
  } catch (err) {
    $('#b-parts').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  }
  renderBom(r, parts);
  renderXoBuild(r);
  renderChecklist(r);
  renderParts(parts);
  renderOverview(r);
  setBuildTab(state.btab || 'bom');
}

function crossoverBuyList(r) {
  const merged = new Map();
  const put = (key, item, unit, qty) => {
    const entry = merged.get(key) || { item, unit, qty: 0 };
    entry.qty += qty;
    merged.set(key, entry);
  };

  Object.values(r.crossover_parts).forEach((branch) => {
    branch.parts.forEach((p) => {
      if (p.type === 'capacitor') {
        p.build.split('+')
          .map((v) => parseFloat(v))
          .filter((v) => !Number.isNaN(v))
          .forEach((v) => put(`C${v}`, `Capacitor ${v} µF – MKP film, ≥ 100 V`, 1.2 + 0.11 * v, 2));
      } else if (p.type === 'inductor') {
        put(`L${p.use_value}${p.spec}`, `Coil ${p.use_value} mH – ${p.spec}`, p.est_eur, 2);
      } else {
        put(`R${p.use_value}`, `Resistor ${p.use_value} Ω – 10 W`, p.est_eur, 2);
      }
    });
  });

  const order = { C: 0, L: 1, R: 2 };
  return [...merged.entries()]
    .sort((a, b) => order[a[0][0]] - order[b[0][0]] || parseFloat(a[0].slice(1)) - parseFloat(b[0].slice(1)))
    .map(([, v]) => v);
}

function renderBom(r, parts) {
  const d = r.design;
  const dr = r.drivers;
  const n = d.drivers.woofer.count || 1;
  const rows = [];
  const add = (cat, item, qty, unit, note = '', link = '') => rows.push({ cat, item, qty, unit, note, link });

  add('Drivers', `${dr.woofer.brand} ${dr.woofer.model} woofer`, 2 * n, dr.woofer.price_eur, dr.woofer.in_stock ? '' : 'out of stock', dr.woofer.shop?.url);
  if (dr.mid) add('Drivers', `${dr.mid.brand} ${dr.mid.model} midrange`, 2, dr.mid.price_eur, dr.mid.in_stock ? '' : 'out of stock', dr.mid.shop?.url);
  add('Drivers', `${dr.tweeter.brand} ${dr.tweeter.model} tweeter`, 2, dr.tweeter.price_eur, dr.tweeter.in_stock ? '' : 'out of stock', dr.tweeter.shop?.url);

  crossoverBuyList(r).forEach((x) => add('Crossover', x.item, x.qty, x.unit, 'estimate'));
  if (d.crossover.mode === 'passive') {
    add('Crossover', 'Crossover board, wire 1.5 mm² + 0.75 mm², heat-shrink', 2, 6, 'estimate');
  }
  if (r.port?.shape === 'round') {
    add('Cabinet', `${r.port.tube_name || 'Port tube'} – cut ${2 * r.port.count}× ${fmt(r.port.length_mm, 0)} mm`, 1, 6, 'DIY store, 1 m length');
  }

  const m2 = parts
    .filter((p) => p.t >= 12 && !p.template && !/Port tube/.test(p.name))
    .reduce((sum, p) => sum + (p.w * p.h * p.qty) / 1e6, 0);
  add('Cabinet', `MDF 18 mm (and 12 mm) panels, ~${fmt(m2 * 1.25, 1)} m² incl. 25 % waste`, 1, Math.round(m2 * 1.25 * 14), 'cut list in ZIP');
  add('Cabinet', 'Acoustic damping (polyester wadding / felt), ~1 m² per speaker', 2, 12, 'estimate');
  add('Cabinet', `Terminals: ${d.crossover.mode === 'active' ? '3 pairs (one per way)' : '1 pair'} per speaker`, 2, d.crossover.mode === 'active' ? 15 : 8, 'estimate');
  add('Cabinet', 'Foam gasket tape, screws, wood glue, acrylic sealant', 1, 25, 'estimate');
  if (d.crossover.mode === 'active') {
    add('Electronics', 'DSP with 6 outputs + 6 amplifier channels (e.g. miniDSP 2x4 HD + 3 stereo amps, or a 6-channel DSP amp)', 1, null, 'not included in total');
  }

  const total = rows.reduce((sum, x) => sum + (x.unit || 0) * x.qty, 0);
  let lastCat = '';
  const bodyRows = rows.map((x) => {
    const catRow = x.cat !== lastCat ? `<tr><td colspan="5"><b>${(lastCat = x.cat)}</b></td></tr>` : '';
    const itemHtml = x.link ? `<a href="${x.link}" target="_blank" rel="noopener">${esc(x.item)}</a>` : esc(x.item);
    const eachTxt = x.unit == null ? '—' : `€${fmt(x.unit, 2)}`;
    const totTxt = x.unit == null ? '—' : `€${fmt(x.unit * x.qty, 2)}`;
    const noteCls = /out of stock/.test(x.note) ? 'warn' : '';
    const noteHtml = x.note ? `<span class="tag ${noteCls}">${esc(x.note)}</span>` : '';
    return `${catRow}<tr><td>${itemHtml}</td><td class="num">${x.qty}</td><td class="num">${eachTxt}</td><td class="num">${totTxt}</td><td>${noteHtml}</td></tr>`;
  }).join('');

  $('#b-bom').innerHTML = `
    <div class="tablewrap">
      <table>
        <tr><th>Item</th><th class="num">Qty</th><th class="num">Each</th><th class="num">Total</th><th>Note</th></tr>
        ${bodyRows}
        <tr class="total"><td>Total (approx., both speakers)</td><td></td><td></td><td class="num">€${fmt(total, 0)}</td><td></td></tr>
      </table>
    </div>
    <p class="hint">Driver prices: SoundImports (NL, ships EU-wide), incl. VAT. Crossover parts are available from the same shop or Intertechnik/Mundorf/Jantzen dealers; HT pipe from any DIY store.</p>`;
}

function renderXoBuild(r) {
  const x = r.design.crossover;
  const sol = r.soldering;
  const solderMsg = sol.required
    ? `<b>Soldering required</b>: ${sol.components_incl_parallel} components, about ${sol.solder_joints_est} solder joints per speaker.`
    : '✓ No soldering needed apart from wiring the drivers.';

  let html = `<h3>Complete wiring</h3><div class="schem">${wiringSVG(r)}</div>${WIRING_HELP}
    <div class="alert ${sol.required ? 'warn' : 'ok'}">${solderMsg}</div>`;

  if (x.mode === 'active') {
    const dspRows = Object.keys(x.levels).map((w) => {
      const subNote = r.metrics.fb_hz ? ` ≥ ${fmt(0.8 * r.metrics.fb_hz, 0)} Hz` : '';
      const hp = w === 'woofer'
        ? `20 Hz BW2 (subsonic)${subNote}`
        : `${fmt(w === 'mid' ? x.f_wm : x.f_mt, 0)} Hz ${x.kind}`;
      const lpFreq = w === 'woofer' ? (x.f_wm || x.f_mt) : x.f_mt;
      const lp = w === 'tweeter' ? '—' : `${fmt(lpFreq, 0)} Hz ${x.kind}`;
      const pol = x.polarity[w] < 0 ? 'inverted' : 'normal';
      return `<tr><td style="color:${COL[w]};font-weight:600">${w}</td><td>${hp}</td><td>${lp}</td><td class="num">−${fmt(x.levels[w])} dB</td><td>${pol}</td></tr>`;
    }).join('');
    html += `<h3>DSP settings (per speaker)</h3>
      <div class="tablewrap"><table><tr><th>Output</th><th>High-pass</th><th>Low-pass</th><th class="num">Gain</th><th>Polarity</th></tr>${dspRows}</table></div>
      <p class="hint">Start with these, then measure with REW and a calibrated microphone and add EQ. Keep the subsonic high-pass on a vented woofer.</p>`;
  }

  const partsList = Object.entries(r.crossover_parts).flatMap(([w, b]) => b.parts.map((p) => ({ w, p })));
  if (partsList.length) {
    const partRows = partsList.map(({ w, p }) => {
      const detailsHtml = (p.details || []).map((t) => `<div class="spec">• ${esc(t)}</div>`).join('');
      return `<tr>
        <td style="color:${COL[w]};font-weight:600">${w}</td>
        <td><b>${p.ref}</b></td>
        <td>${p.type}</td>
        <td>${esc(p.position)}</td>
        <td class="num">${fmt(p.value, 2)} ${p.unit}</td>
        <td><b>${esc(p.build)}</b>${detailsHtml}</td>
      </tr>`;
    }).join('');

    const notes = Object.entries(r.crossover_parts).map(([w, b]) => {
      if (b.purpose) return `${w}: ${esc(b.purpose)}`;
      if (b.R_design_ohm) return `${w} filter designed for ${b.R_design_ohm} Ω`;
      return '';
    }).filter(Boolean).join(' · ');

    html += `<h3>Where each part goes</h3>
      <div class="tablewrap"><table><tr><th>Branch</th><th>Ref</th><th>Part</th><th>Position (see diagram)</th><th class="num">Calculated</th><th>Use</th></tr>${partRows}</table></div>
      <p class="hint">${notes}.</p>`;
  }

  if (x.mode === 'passive') {
    html += '<div class="row-btns"><button id="b-spice">Cross-check the crossover with ngspice</button></div><div id="b-spice-out"></div>';
  }
  if (sol.required) {
    html += `<h3>How to build it</h3><ol>${sol.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol><p class="hint">Tools: ${sol.tools.map(esc).join(', ')}.</p>`;
  }

  $('#b-xo').innerHTML = html;
  const spiceBtn = $('#b-spice');
  if (spiceBtn) {
    spiceBtn.onclick = async () => {
      spiceBtn.disabled = true;
      spiceBtn.textContent = 'Running ngspice…';
      try {
        const q = await api('/api/spice', state.design);
        if (!q.available) {
          $('#b-spice-out').innerHTML = `<div class="alert warn">${esc(q.reason)}</div>`;
        } else {
          const branchDevs = Object.entries(q.branches).map(([w, b]) => `${w} ${fmt(b.max_dev_db, 3)} dB`).join(', ');
          $('#b-spice-out').innerHTML = `
            <div class="alert ${q.max_dev_db < 0.1 ? 'ok' : 'warn'}">ngspice AC analysis agrees with the internal network solver within <b>${fmt(q.max_dev_db, 3)} dB</b> (${branchDevs}).</div>
            <button id="b-spice-dl">Download SPICE netlist (.cir, works in LTspice too)</button>`;
          const dl = $('#b-spice-dl');
          if (dl) dl.onclick = () => download(new Blob([q.netlist], { type: 'text/plain' }), 'crossover.cir');
        }
      } catch (err) {
        $('#b-spice-out').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
      } finally {
        spiceBtn.disabled = false;
        spiceBtn.textContent = 'Cross-check the crossover with ngspice';
      }
    };
  }
}

function renderChecklist(r) {
  const fit = r.geometry.mode === 'fit';
  const passive = r.design.crossover.mode === 'passive';
  const port = r.port;
  const ticks = store.get('checks', {});

  let backStep = 'Fit the new 18 mm back panel';
  if (r.geometry.back_mode === 'replace_inside') backStep = 'Glue + screw the new 18 mm back panel inside against the old back; seal its edge';
  else if (r.geometry.back_mode === 'solid') backStep = 'Seal the existing back airtight';

  let portStep = null;
  if (port?.location === 'bottom') portStep = 'Drill the bottom at the template position and glue the port tube vertically';
  else if (port) portStep = 'Glue the port tube into the baffle hole';

  const phases = [
    ['Order', [
      'Order drivers (check stock badges)',
      passive ? 'Order crossover parts from the list above' : 'Get the DSP and 6 amplifier channels',
      `Buy 18 mm MDF (and 12 mm for the mid chamber), glue, screws, gasket tape, damping${port?.shape === 'round' ? `, ${port.tube_name}` : ''}`,
    ]],
    ['Verify', [
      'When drivers arrive: measure flange Ø, cut-out and depth with a caliper and update the driver if needed',
      'Check that all drivers are the same model/impedance as designed',
    ]],
    ['Cabinet', fit
      ? ['Remove doors/fronts and hinges; fill holes airtight', 'Seal all inside corners with acrylic sealant', backStep, 'Glue in the baffle-to-back braces where they do not hit drivers']
      : ['Cut panels from the cut list', 'Glue the box (sides, top, bottom, back) and seal inside joints']],
    ['Baffle', [
      'CNC/rout the baffles from the DXF (left and right are mirrored)',
      'Rout the 45° chamfer behind woofer and mid cut-outs',
      'Round over front edges ≥ 10 mm (unless flush with furniture)',
      'Dry-fit every driver in its rebate',
    ]],
    ['Inside', [
      r.chamber ? 'Build and glue the mid chamber behind the mid; fill it loosely with wadding' : null,
      portStep,
      `Line the walls with damping${port ? ' – keep the port mouth free' : ''}`,
      passive ? 'Solder the crossovers (step-by-step above) and mount them on the back panel' : 'Solder the tweeter protection capacitor; run one cable pair per way to the terminals',
    ].filter(Boolean)],
    ['Close & test', [
      'Wire drivers observing the polarity shown',
      'Mount the baffle on the foam gasket, screws every ~100 mm',
      'Play a sine sweep: listen for buzzes, air leaks or port noise',
      'Measure with REW + mic and fine-tune levels/EQ',
    ]],
  ];

  $('#b-steps').innerHTML = phases.map(([phase, items]) => {
    const listItems = items.map((t) => (
      `<li class="${ticks[t] ? 'done' : ''}"><input type="checkbox" data-check="${esc(t)}" ${ticks[t] ? 'checked' : ''}><span>${esc(t)}</span></li>`
    )).join('');
    return `<h4>${phase}</h4><ul class="checklist">${listItems}</ul>`;
  }).join('');

  $$('[data-check]').forEach((cb) => {
    cb.onchange = () => {
      const saved = store.get('checks', {});
      saved[cb.dataset.check] = cb.checked;
      store.set('checks', saved);
      cb.parentElement.classList.toggle('done', cb.checked);
    };
  });
}

function renderParts(parts) {
  const legend = '<div class="vlegend" style="width:100%"><span><i style="background:#dc2626"></i>cut through</span><span><i style="background:#2563eb"></i>flush rebate</span><span><i style="background:#16a34a"></i>pilot hole</span><span><i style="background:#9333ea"></i>rear chamfer</span></div>';

  const partCards = parts.map((p) => {
    const ops = p.features.filter((f) => !['center', 'drill'].includes(f.op));
    const flat = p.t > 0;
    const opsRows = ops.map((f) => {
      const sizeStr = f.op === 'rect' ? `${fmt(f.w, 0)}×${fmt(f.h, 0)}` : fmt(f.d);
      return `<tr><td>${f.op.replace('_', ' ')}</td><td class="num">${fmt(f.x)}</td><td class="num">${fmt(f.y)}</td><td class="num">${sizeStr}</td><td class="num">${f.depth ?? ''}</td><td>${esc(f.label)}</td></tr>`;
    }).join('');
    const tbl = ops.length
      ? `<div class="tablewrap"><table><tr><th>Operation</th><th class="num">X</th><th class="num">Y</th><th class="num">Ø / size</th><th class="num">Depth</th><th>Note</th></tr>${opsRows}</table></div>`
      : '';
    const dlBtns = flat
      ? `<div class="row-btns"><button data-part="${esc(p.name)}" data-f="dxf">DXF</button><button data-part="${esc(p.name)}" data-f="svg">SVG 1:1</button></div>`
      : '';

    return `
      <div class="part">
        <div class="cap"><b>${esc(p.name)}</b><span>${p.qty}× ${fmt(p.w)} × ${fmt(p.h)} × ${p.t} mm · ${esc(p.material)}</span></div>
        ${flat ? partSVG(p) : ''}
        ${tbl}
        <p class="hint">${esc(p.notes || '')} ${ops.length ? 'X/Y from the bottom-left corner, seen from the front.' : ''}</p>
        ${dlBtns}
      </div>`;
  }).join('');

  $('#b-parts').innerHTML = legend + partCards;
  $$('#b-parts [data-part]').forEach((btn) => { btn.onclick = () => exportFile(btn.dataset.f, btn.dataset.part); });
}

function renderOverview(r) {
  const m = r.metrics;
  const d = r.drivers;
  const x = r.design.crossover;
  const g = r.geometry;
  const p = r.port;
  const wooferCount = r.design.drivers.woofer.count > 1 ? `${r.design.drivers.woofer.count}× ` : '';

  let dampingDesc = '—';
  if (r.damping) {
    const fillNote = r.damping.fill_pct ? `, ${r.damping.fill_pct} % loose fill` : '';
    const midNote = r.damping.mid_chamber ? `; mid chamber: ${esc(r.damping.mid_chamber)}` : '';
    dampingDesc = `${r.damping.lining_mm} mm on ${r.damping.walls.join(', ')}${fillNote}; ${esc(r.damping.material)}${midNote}`;
  }

  let solderDesc = 'none';
  if (r.soldering.required) {
    solderDesc = x.mode === 'active' ? '1 protection capacitor' : `~${r.soldering.solder_joints_est} joints per speaker`;
  }

  $('#ov').innerHTML = `<div class="ov-grid">
    <div class="card"><h2>The speakers</h2><div class="view">${uniq(isoSVG(r, 420))}</div></div>
    <div class="card"><h2>Drivers</h2>${kv([
      ['Woofer', `${wooferCount}${esc(d.woofer.brand)} ${esc(d.woofer.model)}`],
      ['Midrange', d.mid ? `${esc(d.mid.brand)} ${esc(d.mid.model)}` : '— (2-way)'],
      ['Tweeter', `${esc(d.tweeter.brand)} ${esc(d.tweeter.model)}`],
      ['Drivers per pair', eur(m.price_drivers_pair_eur)],
    ])}</div>
    <div class="card"><h2>Cabinet</h2>${kv([
      ['Type', g.mode === 'fit' ? 'built into an existing space' : 'free-standing cabinet'],
      ['Baffle', `${fmt(g.baffle_w, 0)} × ${fmt(g.baffle_h, 0)} × ${g.baffle_t} mm`],
      ['Inside', `${fmt(g.int_w, 0)} × ${fmt(g.int_h, 0)} × ${fmt(g.int_d, 0)} mm`],
      ['Net volume', `${fmt(m.net_volume_L)} L`],
      ['Box', m.fb_hz ? `vented, fb ${fmt(m.fb_hz)} Hz` : `sealed, Qtc ${fmt(m.qtc, 2)}`],
      ['Port', p ? `${p.count}× ${esc(p.tube_name || '')} Ø${fmt(p.d_mm, 0)} × ${fmt(p.length_mm, 0)} mm (${p.location})` : '—'],
      ['Damping', dampingDesc],
    ])}</div>
    <div class="card"><h2>Performance</h2>${kv([
      ['Bass −3 / −10 dB', `${fmt(m.woofer_f3_hz, 0)} / ${fmt(m.woofer_f10_hz, 0)} Hz`],
      ['Response', `±${fmt(m.deviation_db)} dB (150 Hz–10 kHz)`],
      ['Sensitivity', `${fmt(m.sensitivity_db_2v83_1m)} dB 2.83 V/1 m`],
      ['Max SPL 40 / 100 Hz', `${fmt(m.max_spl_40hz, 0)} / ${fmt(m.max_spl_100hz, 0)} dB`],
      ['Min impedance', m.z_min_ohm ? `${fmt(m.z_min_ohm, 1)} Ω` : 'per amp channel'],
    ])}<div id="ov-chart" class="chart small"></div></div>
    <div class="card"><h2>Crossover</h2>${kv([
      ['Type', x.mode === 'active' ? 'active DSP' : 'passive'],
      ['Filters', `${x.kind} at ${x.f_wm ? `${fmt(x.f_wm, 0)} / ` : ''}${fmt(x.f_mt, 0)} Hz`],
      ['Soldering', solderDesc],
      ['Crossover parts', `≈ ${eur(2 * m.crossover_parts_eur_each)} per pair`],
    ])}</div>
    <div class="card"><h2>Where the volume goes</h2>${volumeTable(r)}</div>
    <div class="card"><h2>Verification with independent engines</h2>
      <p class="hint">Check crossover circuits with ngspice and 3D diffraction with bempp-cl.</p>
      <div class="row-btns">
        ${x.mode === 'passive' ? '<button id="ov-spice">Crossover vs ngspice</button>' : ''}
        <button id="ov-bem">${r.bem?.used ? 'BEM: verified ✓ (run again)' : 'Baffle with BEM (2–4 min)'}</button>
      </div>
      <div id="ov-verify"></div>
    </div>
    <div class="card"><h2>Status</h2>${r.warnings.length ? r.warnings.map((w) => `<div class="alert warn">⚠ ${esc(w)}</div>`).join('') : '<div class="alert ok">✓ No problems found</div>'}</div>
  </div>`;

  const spiceBtn = $('#ov-spice');
  if (spiceBtn) {
    spiceBtn.onclick = async () => {
      try {
        const q = await api('/api/spice', state.design);
        $('#ov-verify').innerHTML += q.available
          ? `<div class="alert ${q.max_dev_db < 0.1 ? 'ok' : 'warn'}">ngspice AC analysis vs internal crossover solver: max difference <b>${fmt(q.max_dev_db, 3)} dB</b>.</div>`
          : `<div class="alert warn">${esc(q.reason)}</div>`;
      } catch (err) {
        $('#ov-verify').innerHTML += `<div class="alert bad">${esc(err.message)}</div>`;
      }
    };
  }

  $('#ov-bem').onclick = () => {
    actions.showStep('design');
    actions.runBem();
  };

  Plotly.react(
    'ov-chart',
    [{ x: r.curves.f, y: r.curves.sum_smoothed, mode: 'lines', line: { color: COL.sum, width: 2.4 }, name: 'response' }],
    { ...plotBase('dB'), showlegend: false, xaxis: { ...LOGX, range: [Math.log10(15), Math.log10(20000)] } },
    { responsive: true, displaylogo: false },
  );
}

export async function renderSubBuild(r) {
  let parts = [];
  try {
    parts = await api('/api/export/parts', state.design);
  } catch (err) {
    $('#b-parts').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  }

  const m = r.metrics;
  const d = r.design;
  const w = r.drivers.woofer;
  const n = d.drivers.woofer.count || 1;
  const p = r.port;
  const zPar = w.Z_nom / n;
  const zSer = w.Z_nom * n;
  const m2 = parts
    .filter((q) => q.t >= 12 && !q.template && !/Port tube/.test(q.name))
    .reduce((sum, q) => sum + (q.w * q.h * q.qty) / 1e6, 0);

  const rows = [
    [`${w.brand} ${w.model}`, n, w.price_eur, w.in_stock ? '' : 'out of stock'],
    [`Plate amplifier or DSP amp, ≥ ${fmt(m.amp_w, 0)} W into ${fmt(n > 1 ? zPar : w.Z_nom, 1)} Ω, with low-pass + subsonic`, 1, Math.max(120, 0.8 * m.amp_w), 'estimate'],
    p?.shape === 'round' ? [`${p.tube_name || 'Port tube'} – cut ${p.count}× ${fmt(p.length_mm, 0)} mm`, 1, 6, 'DIY store'] : null,
    [`MDF ${d.cabinet.wall_t} mm, ~${fmt(m2 * 1.25, 1)} m² incl. 25 % waste`, 1, Math.round(m2 * 1.25 * 14), 'cut list in ZIP'],
    ['Damping: polyester wadding / felt', 1, 15, 'estimate'],
    ['Gasket tape, screws, glue, sealant', 1, 15, 'estimate'],
  ].filter(Boolean);

  const total = rows.reduce((sum, x) => sum + x[1] * x[2], 0);
  const bomRows = rows.map((x) => (
    `<tr><td>${esc(x[0])}</td><td class="num">${x[1]}</td><td class="num">${eur(x[2])}</td><td class="num">${eur(x[1] * x[2])}</td><td>${x[3] ? `<span class="tag">${esc(x[3])}</span>` : ''}</td></tr>`
  )).join('');

  $('#b-bom').innerHTML = `
    <div class="tablewrap">
      <table>
        <tr><th>Item</th><th class="num">Qty</th><th class="num">Each</th><th class="num">Total</th><th>Note</th></tr>
        ${bomRows}
        <tr class="total"><td>Total</td><td></td><td></td><td class="num">${eur(total)}</td><td></td></tr>
      </table>
    </div>`;

  const subsonicText = m.subsonic_hz
    ? `${fmt(m.subsonic_hz, 0)} Hz, ${m.box_type === 'vented' ? '24 dB/oct (protects the cone below the port tuning)' : '12 dB/oct'}`
    : 'off';
  const portLimitTxt = m.port_power_w ? ` · port limit ${m.port_power_w} W` : '';
  const multiWiring = n > 1
    ? `<h3 class="mt">Wiring ${n} drivers</h3><p>Parallel: ${fmt(zPar, 1)} Ω (check the amp is stable at this load) · series: ${fmt(zSer, 1)} Ω (less power from most amps). Keep every driver in phase: + to +.</p>`
    : '';

  $('#b-xo').innerHTML = `
    <h3>Amplifier / DSP settings</h3>
    <div class="kv">
      <span>Low-pass</span><span>${fmt(m.lp_hz, 0)} Hz, ${esc(d.sub.lp_kind)}</span>
      <span>Subsonic high-pass</span><span>${subsonicText}</span>
      <span>Power</span><span>up to ${fmt(m.amp_w, 0)} W (rated ${m.rated_power_w} W · Xmax at ${m.xmax_power_w} W${portLimitTxt})</span>
      <span>Phase</span><span>start at 0°; at your seat, flip/adjust until the bass around ${fmt(m.lp_hz, 0)} Hz is loudest</span>
    </div>
    ${multiWiring}
    <h3 class="mt">Placement</h3>
    <p class="hint">Corners give the most bass but also the strongest room modes. Try the "sub crawl": put the sub at your seat, play bass, and crawl along the walls – where it sounds most even is the spot.</p>`;

  let portStep = 'No port: make sure the box is fully airtight';
  if (p) {
    const loc = p.location === 'rear' ? 'Fit the port in the back panel' : 'Fit the port';
    portStep = `${loc} – ${p.shape === 'slot' ? 'slot' : 'tube'} ${fmt(p.length_mm, 0)} mm, keep its inner opening clear`;
  }
  const subSteps = [
    'Order the driver(s) and plate amplifier; check stock',
    'When the driver arrives, measure its frame, cut-out and depth and correct them if needed',
    'Cut the panels from the cut list; CNC/rout the baffle from the DXF (45° chamfer behind the cut-out)',
    'Glue the box; add the brace(s); seal every inside joint',
    portStep,
    `Damping: ${r.damping?.lining_mm || 25} mm lining on the walls${r.damping?.fill_pct ? `, plus ${r.damping.fill_pct} % loose fill` : ''}`,
    'Mount the amplifier plate (cut-out in the back panel), wire + to +, mount the driver on gasket tape',
    'Set the amplifier as above; measure at your seat and adjust phase / low-pass',
  ];
  $('#b-steps').innerHTML = `<ol>${subSteps.map((t) => `<li>${esc(t)}</li>`).join('')}</ol>`;

  renderParts(parts);
  renderSubOverview(r);
  setBuildTab(state.btab || 'bom');
}

function renderSubOverview(r) {
  const m = r.metrics;
  const g = r.geometry;
  const p = r.port;
  const w = r.drivers.woofer;
  const portDesc = p
    ? `${p.shape === 'slot' ? `slot ${fmt(p.slot_w_mm, 0)} × ${fmt(p.slot_h_mm, 0)}` : `${p.count}× Ø${fmt(p.d_mm, 0)}`} × ${fmt(p.length_mm, 0)} mm, ${p.location}`
    : '—';
  const dampDesc = r.damping
    ? `${r.damping.lining_mm} mm lining${r.damping.fill_pct ? `, ${r.damping.fill_pct} % fill` : ''}`
    : '—';

  $('#ov').innerHTML = `<div class="ov-grid">
    <div class="card"><h2>The subwoofer</h2><div class="view">${uniq(isoSVG(r, 420))}</div></div>
    <div class="card"><h2>Specs</h2>${kv([
      ['Driver', `${r.design.drivers.woofer.count || 1}× ${esc(w.brand)} ${esc(w.model)}`],
      ['Box', `${m.box_type}, ${fmt(m.net_volume_L, 1)} L net${m.fb_hz ? `, tuned to ${fmt(m.fb_hz, 1)} Hz` : ''}`],
      ['Outer size', `${fmt(g.outer_w, 0)} × ${fmt(g.outer_h, 0)} × ${fmt(g.outer_d, 0)} mm`],
      ['Port', portDesc],
      ['Bass −3 / −10 dB', `${fmt(m.woofer_f3_hz, 0)} / ${fmt(m.woofer_f10_hz, 0)} Hz`],
      ['Output @ 40 Hz', `${fmt(m.out_at_amp_40hz, 0)} dB at ${fmt(m.amp_w, 0)} W`],
      ['Filters', `low-pass ${fmt(m.lp_hz, 0)} Hz${m.subsonic_hz ? ` · subsonic ${fmt(m.subsonic_hz, 0)} Hz` : ''}`],
      ['Damping', dampDesc],
    ])}</div>
    <div class="card"><h2>Where the volume goes</h2>${volumeTable(r)}</div>
    <div class="card"><h2>Status</h2>${r.warnings.length ? r.warnings.map((x) => `<div class="alert warn">⚠ ${esc(x)}</div>`).join('') : '<div class="alert ok">✓ No problems found</div>'}</div>
  </div>`;
}
