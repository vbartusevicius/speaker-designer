/* Plotly chart rendering for full-range speakers and subwoofers. */
import { $, COL, esc, fmt, state } from './state.js';

export const LOGX = {
  type: 'log',
  title: { text: 'Frequency (Hz)', standoff: 6 },
  range: [1, Math.log10(20000)],
  tickvals: [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000],
  ticktext: ['10', '20', '50', '100', '200', '500', '1k', '2k', '5k', '10k', '20k'],
  gridcolor: '#eef0f3',
};

export const plotBase = (yTitle) => ({
  margin: { l: 50, r: 22, t: 22, b: 86 },
  xaxis: LOGX,
  yaxis: { title: { text: yTitle }, gridcolor: '#eef0f3' },
  legend: { orientation: 'h', y: -0.25, yanchor: 'top', x: 0, font: { size: 10.5 } },
  hovermode: 'x unified',
  font: { size: 11 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: '#fff',
});

const vline = (x, label, color = '#94a3b8') => ({
  x,
  shape: { type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color, dash: 'dot', width: 1 } },
  ann: { x: Math.log10(x), yref: 'paper', y: 1, text: label, showarrow: false, font: { size: 10, color }, yanchor: 'bottom' },
});

function placeMarks(marks) {
  const sorted = [...marks].sort((a, b) => a.x - b.x);
  let lastLx = -99;
  let row = 0;
  return sorted.map((m) => {
    const lx = Math.log10(m.x);
    row = (lx - lastLx < 0.14) ? (row + 1) % 2 : 0;
    lastLx = lx;
    const ann = row === 0
      ? m.ann
      : { ...m.ann, y: 0.94, yanchor: 'top', bgcolor: 'rgba(255,255,255,0.88)' };
    return { ...m, ann };
  });
}

const EXPLAIN = {
  spl: ['How to read it', 'The black line is what you hear on the tweeter axis at your listening distance; the green band is the target to aim for (flat ±2 dB with an ideal bass roll-off for this box). Aim within ±2–3 dB; bass is stronger in-room than shown.',
    'p_total(f) = Σ p_driver(f) · H_xo(f) · D_baffle(f) · e^(−jk·Δpath)'],
  box: ['How to read it', 'The woofer alone in its box in half-space. Look at F3 and whether there is a hump (>1 dB means boomy). Vented boxes fall at 24 dB/oct below fb, sealed at 12 dB/oct.',
    'Sealed: Qtc = Qts·√(1+Vas/Vb)\nVented: fb = c/2π · √(Sp / (Vb·Leff))'],
  imp: ['How to read it', 'The electrical load seen by the amplifier – keep minimum impedance above ~3.2 Ω for 4 Ω-stable amps.', 'Z_in = Re + K·(jω)^0.7 + Bl² / (Z_mech + Sd²·Z_box)'],
  exc: ['How to read it', 'Cone excursion at your loud-listening power. Stay under the dotted Xmax line in the passband.', 'x = |v / jω| · √2'],
  port: ['How to read it', 'Peak air speed in the port. Under 17 m/s (25 m/s flared) it stays quiet.', 'v_port = |U_port| / Sp · √2'],
  maxspl: ['How to read it', 'Loudest the woofer can play at 1 m before hitting Xmax (blue), rated power (orange), or port noise (purple).', 'SPL_max = SPL(V) + 20·log10(V_max/V)'],
  gd: ['How to read it', 'Delay of each frequency relative to treble; up to ~1.5 cycles is generally inaudible.', 'τ(f) = −dφ/dω'],
  diff: ['How to read it', 'Baffle-edge effect relative to an infinite wall (6 dB baffle step at low frequency plus edge ripples).', 'f_step ≈ 115 / baffle width [m]'],
};

function targetTraces(r) {
  const f = r.curves.f;
  const sum = r.curves.sum;
  const m = r.metrics;
  const midband = f
    .map((freq, idx) => [freq, sum[idx]])
    .filter(([freq]) => freq >= 300 && freq <= 3000)
    .map(([, db]) => db)
    .sort((a, b) => a - b);
  const ref = midband[Math.floor(midband.length / 2)];
  const order = m.box_type === 'vented' ? 4 : 2;
  const f3 = Math.max(15, Math.min(m.woofer_f3_hz, 80));
  const tgt = f.map((freq) => {
    const ratio = Math.pow(freq / f3, 2 * order);
    return ref + 10 * Math.log10(ratio / (1 + ratio));
  });

  return [
    { x: f, y: tgt.map((v) => v + 2), mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { x: f, y: tgt.map((v) => v - 2), mode: 'lines', line: { width: 0 }, fill: 'tonexty', fillcolor: 'rgba(34,197,94,0.13)', showlegend: false, hoverinfo: 'skip' },
    { x: f, y: tgt, mode: 'lines', line: { color: '#16a34a', width: 1.5, dash: 'dot' }, name: `target ±2 dB (${fmt(f3, 0)} Hz)` },
  ];
}

export function resizeCharts() {
  ['chart', 'ov-chart'].forEach((id) => {
    const el = document.getElementById(id);
    if (el?.data) Plotly.Plots.resize(el);
  });
}

function makeLayout(extra = {}, marks = []) {
  const placed = placeMarks(marks);
  const base = plotBase(extra.yt || 'dB');
  const rest = { ...extra };
  delete rest.yt;
  return {
    ...base,
    ...rest,
    shapes: placed.map((v) => v.shape),
    annotations: placed.map((v) => v.ann),
  };
}

export function renderChart() {
  const r = state.result;
  if (!r || state.step !== 'design') return;
  if (r.system === 'sub') {
    renderSubChart(r);
    return;
  }

  const c = r.curves;
  const f = c.f;
  const m = r.metrics;
  const ways = Object.keys(c.spl);
  const x = r.design.crossover;
  const line = (y, name, color, extra = {}) => ({ x: f, y, name, mode: 'lines', line: { color, width: 1.7 }, ...extra });
  const xoMarks = [
    x.f_wm && vline(x.f_wm, `${fmt(x.f_wm, 0)} Hz`),
    x.f_mt && vline(x.f_mt, `${fmt(x.f_mt, 0)} Hz`),
  ].filter(Boolean);

  let traces = [];
  let layout;

  switch (state.chart) {
    case 'spl': {
      traces = [
        ...targetTraces(r),
        line(c.sum, 'System', COL.sum, { line: { color: COL.sum, width: 2.8 } }),
        ...ways.map((w) => line(c.spl[w], w, COL[w])),
      ];
      if (state.prev?.curves) {
        traces.splice(4, 0, {
          x: state.prev.curves.f,
          y: state.prev.curves.sum,
          name: 'before last change',
          mode: 'lines',
          line: { color: '#94a3b8', width: 2, dash: 'dash' },
        });
      }
      const peak = Math.max(...c.sum);
      layout = makeLayout({
        yt: `SPL dB @ ${r.design.sim.distance_mm / 1000} m`,
        yaxis: { title: { text: `SPL dB @ ${r.design.sim.distance_mm / 1000} m` }, range: [peak - 45, peak + 6], gridcolor: '#eef0f3' },
      }, xoMarks);
      break;
    }
    case 'box': {
      const peak = Math.max(...c.box_spl_halfspace);
      traces = [line(c.box_spl_halfspace, `Woofer in its ${m.box_type} box`, COL.woofer, { line: { color: COL.woofer, width: 2.4 } })];
      if (state.prev?.curves) {
        traces.push({
          x: state.prev.curves.f,
          y: state.prev.curves.box_spl_halfspace,
          name: 'before last change',
          mode: 'lines',
          line: { color: '#94a3b8', width: 2, dash: 'dash' },
        });
      }
      const boxMarks = [
        vline(m.woofer_f3_hz, `F3 ${fmt(m.woofer_f3_hz, 0)} Hz`, COL.woofer),
        ...(m.fb_hz ? [vline(m.fb_hz, `fb ${fmt(m.fb_hz, 0)} Hz`, COL.port)] : []),
      ];
      layout = makeLayout({
        yt: 'SPL dB',
        yaxis: { range: [peak - 40, peak + 6], title: { text: 'SPL dB (1 m, half-space)' } },
        xaxis: { ...LOGX, range: [1, Math.log10(2000)] },
      }, boxMarks);
      break;
    }
    case 'imp': {
      if (c.impedance_system) {
        traces.push(
          line(c.impedance_system, 'What the amplifier sees', COL.sum, { line: { width: 2.6, color: COL.sum } }),
          line(c.impedance_system_phase, 'phase', '#94a3b8', { yaxis: 'y2', line: { dash: 'dot', color: '#94a3b8' } }),
        );
      }
      ways.forEach((w) => {
        traces.push(line(c.impedance[w], `${w} driver alone`, COL[w], c.impedance_system ? { visible: 'legendonly' } : {}));
      });
      layout = makeLayout({
        yt: 'Ω',
        yaxis: { title: { text: 'Impedance Ω' }, rangemode: 'tozero', gridcolor: '#eef0f3' },
        yaxis2: { title: { text: 'phase °' }, overlaying: 'y', side: 'right', range: [-90, 90] },
      }, xoMarks);
      break;
    }
    case 'exc': {
      traces = [
        line(c.excursion_filtered_mm, `Woofer through crossover @ ${c.design_power_w} W`, COL.woofer, { line: { color: COL.woofer, width: 2.4 } }),
        line(c.excursion_mm, 'Woofer without crossover', COL.woofer, { line: { dash: 'dash', color: COL.woofer } }),
        line(f.map(() => c.xmax_mm), `Woofer Xmax ${c.xmax_mm} mm`, '#ef4444', { line: { dash: 'dot', color: '#ef4444' } }),
      ];
      if (c.mid_excursion_mm) {
        traces.push(
          line(c.mid_excursion_mm, 'Mid through crossover', COL.mid),
          line(f.map(() => r.drivers.mid.Xmax_mm), `Mid Xmax ${r.drivers.mid.Xmax_mm} mm`, COL.mid, { line: { dash: 'dot', color: COL.mid } }),
        );
      }
      layout = makeLayout({
        yt: 'mm',
        yaxis: { title: { text: 'Peak excursion mm' }, rangemode: 'tozero' },
        xaxis: { ...LOGX, range: [1, Math.log10(3000)] },
      }, xoMarks);
      break;
    }
    case 'port': {
      if (!c.port_velocity_ms) {
        layout = makeLayout({
          yt: 'm/s',
          annotations: [{ text: 'Sealed box – no port', showarrow: false, xref: 'paper', yref: 'paper', x: 0.5, y: 0.5, font: { size: 16 } }],
        });
        break;
      }
      traces = [
        line(c.port_velocity_ms, `Peak air speed @ ${c.design_power_w} W`, COL.port, { line: { color: COL.port, width: 2.4 } }),
        line(f.map(() => r.port.vel_limit_ms), 'Audible chuffing above', '#ef4444', { line: { dash: 'dot', color: '#ef4444' } }),
      ];
      layout = makeLayout({
        yt: 'm/s',
        yaxis: { title: { text: 'm/s' }, rangemode: 'tozero' },
        xaxis: { ...LOGX, range: [1, Math.log10(500)] },
      }, [vline(m.fb_hz, `fb ${fmt(m.fb_hz, 0)} Hz`, COL.port)]);
      break;
    }
    case 'maxspl': {
      const limitInfo = {
        xmax: ['limited by cone travel (Xmax)', COL.woofer],
        thermal: ['limited by power rating', '#f59e0b'],
        port: ['limited by port noise', COL.port],
      };
      traces = ['xmax', 'thermal', 'port'].map((key) => ({
        x: f,
        y: c.max_spl.map((v, i) => (c.max_spl_limit[i] === key ? v : null)),
        name: limitInfo[key][0],
        mode: 'lines',
        line: { width: 2.6, color: limitInfo[key][1] },
      }));
      layout = makeLayout({
        yt: 'dB',
        yaxis: { title: { text: 'Max SPL dB (1 m)' } },
        xaxis: { ...LOGX, range: [1, Math.log10(1000)] },
      });
      break;
    }
    case 'gd': {
      traces = [
        line(c.group_delay_sum_ms, 'Whole speaker', COL.sum),
        line(c.group_delay_box_ms, 'Woofer box only', COL.woofer),
      ];
      layout = makeLayout({ yt: 'ms', yaxis: { title: { text: 'Group delay ms' }, range: [-2, 40] } }, xoMarks);
      break;
    }
    case 'diff': {
      traces = ways.map((w) => {
        const suffix = r.bem?.used ? ` (BEM ≤ ${fmt(r.bem.f_max, 0)} Hz, edge model above)` : ' (edge model)';
        return line(c.diffraction_db[w], w + suffix, COL[w]);
      });
      if (r.bem?.used) {
        Object.entries(r.bem.polar).forEach(([name, vals]) => {
          const role = name.replace(/\d+$/, '');
          traces.push({
            x: r.bem.freqs,
            y: vals.re.map((re, i) => 20 * Math.log10(Math.hypot(re, vals.im[i]))),
            name: `${name} BEM points`,
            mode: 'markers',
            marker: { color: COL[role], size: 8, symbol: 'diamond' },
          });
          ['30', '60'].forEach((ang) => {
            traces.push({
              x: r.bem.freqs,
              y: vals.polar_db[ang],
              name: `${name} ${ang}° off-axis (BEM)`,
              mode: 'lines+markers',
              line: { color: COL[role], width: 1, dash: ang === '30' ? 'dash' : 'dot' },
              visible: 'legendonly',
            });
          });
        });
      }
      layout = makeLayout({
        yt: 'dB',
        yaxis: { range: [-9, 6], title: { text: 'dB vs. infinite wall' } },
      }, [vline(m.baffle_step_f3_hz, `baffle step ≈ ${m.baffle_step_f3_hz} Hz`)]);
      break;
    }
  }

  Plotly.react('chart', traces, layout, { responsive: true, displaylogo: false });
  const [title, desc, math] = EXPLAIN[state.chart] || ['', '', ''];
  $('#chart-explain').innerHTML = `<b>${title}:</b> ${desc}<details><summary>Show the math</summary><pre>${esc(math)}</pre></details>`;
}

function renderSubChart(r) {
  const c = r.curves;
  const f = c.f;
  const m = r.metrics;
  const line = (y, name, color, extra = {}) => ({ x: f, y, name, mode: 'lines', line: { color, width: 1.8 }, ...extra });
  const marks = [
    vline(m.lp_hz, `low-pass ${fmt(m.lp_hz, 0)} Hz`, '#94a3b8'),
    m.subsonic_hz && vline(m.subsonic_hz, `subsonic ${fmt(m.subsonic_hz, 0)} Hz`, '#94a3b8'),
    m.fb_hz && vline(m.fb_hz, `fb ${fmt(m.fb_hz, 0)}`, COL.port),
  ].filter(Boolean);
  const subLayout = (extra = {}, subMarks = marks) => makeLayout(
    { ...extra, xaxis: { ...LOGX, range: [1, Math.log10(400)] } },
    subMarks,
  );

  let traces = [];
  let layout;
  switch (state.chart) {
    case 'imp':
      traces = [line(c.impedance, 'Impedance', COL.sum, { line: { width: 2.4, color: COL.sum } })];
      layout = subLayout({ yt: 'Ω', yaxis: { title: { text: 'Impedance Ω' }, rangemode: 'tozero' } });
      break;
    case 'exc':
      traces = [
        line(c.excursion_mm, `Cone travel @ ${fmt(m.amp_w, 0)} W (filtered)`, COL.woofer, { line: { width: 2.4, color: COL.woofer } }),
        line(f.map(() => c.xmax_mm), `Xmax ${c.xmax_mm} mm`, '#ef4444', { line: { dash: 'dot', color: '#ef4444' } }),
      ];
      layout = subLayout({ yt: 'mm', yaxis: { title: { text: 'Peak excursion mm' }, rangemode: 'tozero' } });
      break;
    case 'port':
      if (!c.port_velocity_ms) {
        layout = subLayout({
          yt: 'm/s',
          annotations: [{ text: 'Sealed box – no port', showarrow: false, xref: 'paper', yref: 'paper', x: 0.5, y: 0.5, font: { size: 16 } }],
        }, []);
        break;
      }
      traces = [
        line(c.port_velocity_ms, `Air speed @ ${fmt(m.amp_w, 0)} W`, COL.port, { line: { width: 2.4, color: COL.port } }),
        line(f.map(() => r.port.vel_limit_ms), 'Audible chuffing above', '#ef4444', { line: { dash: 'dot', color: '#ef4444' } }),
      ];
      layout = subLayout({ yt: 'm/s', yaxis: { title: { text: 'm/s' }, rangemode: 'tozero' } });
      break;
    case 'maxspl': {
      const limitInfo = {
        xmax: ['limited by cone travel', COL.woofer],
        thermal: ['limited by power rating', '#f59e0b'],
        port: ['limited by port noise', COL.port],
      };
      traces = ['xmax', 'thermal', 'port'].map((key) => line(
        c.max_spl.map((v, i) => (c.max_spl_limit[i] === key ? v : null)),
        limitInfo[key][0],
        limitInfo[key][1],
        { line: { width: 2.6, color: limitInfo[key][1] } },
      ));
      layout = subLayout({ yt: 'dB', yaxis: { title: { text: 'Max SPL dB (1 m)' } } });
      break;
    }
    case 'gd':
      traces = [line(c.group_delay_ms, 'Group delay', COL.sum)];
      layout = subLayout({ yt: 'ms', yaxis: { title: { text: 'ms' }, range: [-2, 60] } });
      break;
    default:
      traces = [
        line(c.spl_out, `Output @ ${fmt(m.amp_w, 0)} W through the filters`, COL.sum, { line: { width: 2.8, color: COL.sum } }),
        line(c.spl_box, 'Box alone, 2.83 V', COL.woofer, { line: { width: 1.6, color: COL.woofer, dash: 'dash' } }),
      ];
      if (state.prev?.curves?.spl_out) {
        traces.push({
          x: state.prev.curves.f,
          y: state.prev.curves.spl_out,
          name: 'before last change',
          mode: 'lines',
          line: { color: '#94a3b8', width: 2, dash: 'dash' },
        });
      }
      layout = subLayout({ yt: 'dB', yaxis: { title: { text: 'SPL dB (1 m, half space)' } } });
  }

  $('#chart-explain').innerHTML = '';
  Plotly.react('chart', traces, layout, { responsive: true, displaylogo: false });
}
