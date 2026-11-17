/* SVG generators for cabinet space, front baffle, sections, 3D, wiring schematic, and CNC parts. */
import { COL, actions, esc, fmt, state, $$ } from './state.js';

let svgUid = 0;
export function uniq(svg) {
  const uid = `u${++svgUid}-`;
  return svg.replaceAll('url(#', `url(#${uid}`).replace(/ id="/g, ` id="${uid}`);
}

const DEFS = `<defs>
  <radialGradient id="cone" cx="40%" cy="35%"><stop offset="0" stop-color="#6b7280"/><stop offset="1" stop-color="#1f2937"/></radialGradient>
  <radialGradient id="dome" cx="40%" cy="35%"><stop offset="0" stop-color="#e5e7eb"/><stop offset="1" stop-color="#6b7280"/></radialGradient>
  <pattern id="mdf" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#dcc7a3"/><circle cx="2" cy="3" r="0.5" fill="#c7ae86"/></pattern>
  <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#e7d7bb"/><line x1="0" y1="0" x2="0" y2="6" stroke="#b9a07a" stroke-width="1"/></pattern>
</defs>`;
const WOOL = '#fde68a';
const REF_MARK = ['◆', '▲', '■'];

function dimLine(x1, y1, x2, y2, label, off = 0, vertical = false) {
  let textEl = '';
  if (label) {
    if (vertical) {
      const tx = x1 - 6 - off;
      const ty = (y1 + y2) / 2;
      textEl = `<text x="${tx}" y="${ty}" font-size="11" text-anchor="middle" transform="rotate(-90 ${tx} ${ty})" fill="#475569">${label}</text>`;
    } else {
      textEl = `<text x="${(x1 + x2) / 2}" y="${y1 + 14 + off}" font-size="11" text-anchor="middle" fill="#475569">${label}</text>`;
    }
  }
  const lines = vertical
    ? `<line x1="${x1 - off}" y1="${y1}" x2="${x2 - off}" y2="${y2}"/><line x1="${x1 - off - 4}" y1="${y1}" x2="${x1 - off + 4}" y2="${y1}"/><line x1="${x1 - off - 4}" y1="${y2}" x2="${x1 - off + 4}" y2="${y2}"/>`
    : `<line x1="${x1}" y1="${y1 + off}" x2="${x2}" y2="${y2 + off}"/><line x1="${x1}" y1="${y1 + off - 4}" x2="${x1}" y2="${y1 + off + 4}"/><line x1="${x2}" y1="${y1 + off - 4}" x2="${x2}" y2="${y1 + off + 4}"/>`;
  return `<g stroke="#64748b" stroke-width="0.8">${lines}</g>${textEl}`;
}

export function bassScale(P) {
  const W = 520;
  const H = 70;
  const xAt = (freq) => 20 + (Math.log(freq / 15) / Math.log(150 / 15)) * (W - 40);

  let s = `<svg viewBox="0 0 ${W} ${H}"><rect x="20" y="22" width="${W - 40}" height="10" rx="5" fill="#e2e8f0"/>`;
  s += `<rect x="${xAt(P.best.vented_f3)}" y="22" width="${xAt(P.best.sealed_f3) - xAt(P.best.vented_f3)}" height="10" fill="#93c5fd"/>`;
  s += `<rect x="${xAt(P.best.sealed_f3)}" y="22" width="${xAt(150) - xAt(P.best.sealed_f3)}" height="10" fill="#2563eb"/>`;

  [15, 20, 30, 40, 50, 70, 100, 150].forEach((freq) => {
    const x = xAt(freq);
    s += `<line x1="${x}" y1="33" x2="${x}" y2="37" stroke="#94a3b8"/>`;
    s += `<text x="${x}" y="48" font-size="10" text-anchor="middle" fill="#64748b">${freq}${freq === 150 ? ' Hz' : ''}</text>`;
  });
  P.references.forEach((r, i) => {
    s += `<text x="${xAt(r.hz)}" y="18" font-size="11" text-anchor="middle" fill="#334155">${REF_MARK[i % 3]}</text>`;
  });
  const legend = P.references
    .map((r, i) => `<span>${REF_MARK[i % 3]} ${esc(r.label.replace('typical ', ''))} ≈ ${r.hz} Hz</span>`)
    .join('');

  return `${s}</svg><div class="scale-legend"><span><i style="background:#2563eb"></i>sealed reach</span><span><i style="background:#93c5fd"></i>extra with a port</span>${legend}</div>`;
}

export function highlightDim(key) {
  $$('#space-views [data-dim]').forEach((group) => {
    const on = group.dataset.dim === key;
    group.querySelectorAll('line,rect.dimbox').forEach((el) => el.classList.toggle('dim-hl', on));
    group.querySelectorAll('text').forEach((el) => el.classList.toggle('dim-txt-hl', on));
  });
}

const dimG = (key, inner) => `<g data-dim="${key}">${inner}</g>`;

export function frontDimSVG(r, pxW) {
  const g = r.geometry;
  const t = g.wall_t;
  const W = g.int_w + 2 * t;
  const H = g.int_h + 2 * t;
  const pad = 50;

  let s = `<svg width="${pxW}" viewBox="${-pad} -22 ${W + pad + 30} ${H + pad + 28}">${DEFS}`;
  s += `<rect x="0" y="0" width="${W}" height="${H}" fill="url(#hatch)" stroke="#8b7355"/>`;
  s += `<rect x="${t}" y="${t}" width="${g.int_w}" height="${g.int_h}" fill="#f8fafc" stroke="#8b7355"/>`;
  s += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="15" fill="#94a3b8">front opening</text>`;
  s += dimG('w', dimLine(t, H + 10, t + g.int_w, H + 10, `inside width ${fmt(g.int_w, 0)} mm`));
  s += dimG('h', dimLine(-10, t, -10, t + g.int_h, `inside height ${fmt(g.int_h, 0)} mm`, 8, true));
  s += dimG('wall', `<line x1="${W - t}" y1="${t + 30}" x2="${W}" y2="${t + 30}" stroke="#64748b"/><text x="${W - t / 2}" y="${t + 24}" font-size="11" text-anchor="middle" fill="#475569">${t}</text>`);
  return `${s}<text x="${W / 2}" y="-8" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">Front view</text></svg>`;
}

export function sideDimSVG(r, pxW) {
  const g = r.geometry;
  const c = state.design.cabinet;
  const t = g.wall_t;
  const fit = g.mode === 'fit';
  const D = fit ? c.inner_d : g.int_d;
  const door = fit ? c.door_recess : 0;
  const H = g.int_h + 2 * t;
  const bt = g.baffle_t;
  let back = t;
  if (fit) back = c.back === 'replace_inside' ? 18 : 0;
  const x0 = door + 10;
  const W = x0 + D + 5 + 20;
  const pad = 40;

  let s = `<svg width="${pxW}" viewBox="${-pad} -22 ${W + pad + 20} ${H + pad + 40}">${DEFS}`;
  s += `<rect x="${x0}" y="0" width="${D}" height="${t}" fill="url(#hatch)" stroke="#8b7355"/>`;
  s += `<rect x="${x0}" y="${H - t}" width="${D}" height="${t}" fill="url(#hatch)" stroke="#8b7355"/>`;
  s += `<rect x="${x0}" y="${t}" width="${D}" height="${g.int_h}" fill="#f8fafc"/>`;
  if (fit) s += `<rect x="${x0 + D}" y="0" width="5" height="${H}" fill="#7c5a3a"/>`;
  s += dimG('baffle', `<rect class="dimbox" x="${x0 - bt}" y="0" width="${bt}" height="${H}" fill="url(#mdf)" stroke="#8b7355"/><text x="${x0 - bt / 2}" y="${H / 2}" font-size="11" text-anchor="middle" fill="#475569" transform="rotate(-90 ${x0 - bt / 2} ${H / 2})">new baffle ${bt} mm</text>`);
  if (back) s += dimG('back', `<rect class="dimbox" x="${x0 + D - back}" y="${t}" width="${back}" height="${g.int_h}" fill="url(#mdf)" stroke="#8b7355"/><text x="${x0 + D - back / 2}" y="${H / 2}" font-size="11" text-anchor="middle" fill="#475569" transform="rotate(-90 ${x0 + D - back / 2} ${H / 2})">new back ${back} mm</text>`);
  s += dimG('d', dimLine(x0, H + 10, x0 + D, H + 10, `inside depth ${fmt(D, 0)} mm → ${fmt(g.int_d, 0)} mm usable`));
  if (fit) s += dimG('door', `${dimLine(x0 - door, -6, x0, -6, '')}<text x="${x0 - door / 2}" y="-12" font-size="10" text-anchor="middle" fill="#475569">door ${door}</text>`);
  return `${s}<text x="${x0 + D / 2}" y="-8" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">Side section (front ←)</text></svg>`;
}

function driverGlyph(drv, x, y, role, idx, editable, bolts) {
  const ro = drv.outer_d_mm / 2;
  const rc = drv.cutout_d_mm / 2;
  const rp = Math.sqrt((drv.Sd_cm2 * 100) / Math.PI);
  const isTweeter = role === 'tweeter';
  const isSelected = state.sel && state.sel.role === role && state.sel.idx === idx;
  const cls = `${editable ? 'drag' : ''}${isSelected && editable ? ' sel' : ''}`;

  let s = `<g class="${cls}" data-role="${role}" data-idx="${idx}" transform="translate(${x},${y})" ${editable ? 'tabindex="0"' : ''}>`;
  s += `<circle r="${ro}" fill="#2b2f36" stroke="#111" stroke-width="1"/>`;
  s += `<circle r="${rc}" fill="none" stroke="#9ca3af" stroke-width="0.8" stroke-dasharray="4 3"/>`;
  if (isTweeter) {
    s += `<circle r="${Math.min(rp * 1.6, rc)}" fill="#3f4652"/><circle r="${rp}" fill="url(#dome)"/>`;
  } else {
    s += `<circle r="${Math.min(rp * 1.12, rc)}" fill="#1f2937"/><circle r="${rp}" fill="url(#cone)"/><circle r="${rp * 0.32}" fill="#374151" stroke="#111" stroke-width="0.5"/>`;
  }
  if (bolts) {
    const bc = drv.bolt_circle_eff_mm / 2;
    for (let i = 0; i < drv.bolt_count; i++) {
      const ang = Math.PI / 2 + ((i + 0.5) * 2 * Math.PI) / drv.bolt_count;
      s += `<circle cx="${bc * Math.cos(ang)}" cy="${bc * Math.sin(ang)}" r="2.3" fill="#cbd5e1"/>`;
    }
  }
  return `${s}<circle r="${ro}" fill="none" stroke="${COL[role]}" stroke-width="2.4"/></g>`;
}

export function frontSVG(r, mirror, editable, pxW, opts = {}) {
  const g = r.geometry;
  const d = r.design;
  const pos = d.layout.positions;
  const dr = r.drivers;
  const port = r.port;
  const W = g.baffle_w;
  const H = g.baffle_h;
  const pad = 34;
  const X = (x) => (mirror ? W - x : x);
  const Y = (y) => H - y;

  let s = `<svg width="${pxW}" viewBox="${-pad} -16 ${W + pad + 12} ${H + pad + 16}" data-front="${mirror ? 'R' : 'L'}">${DEFS}`;
  s += `<rect x="0" y="0" width="${W}" height="${H}" fill="url(#mdf)" stroke="#8b7355" stroke-width="1.2" rx="${Math.min(d.sim.edge_radius_mm || 0, 20)}"/>`;
  const openX = mirror ? W - g.open_x - g.open_w : g.open_x;
  s += `<rect x="${openX}" y="${Y(g.open_y + g.open_h)}" width="${g.open_w}" height="${g.open_h}" fill="none" stroke="#8b7355" stroke-dasharray="6 4" stroke-width="0.8"/>`;

  if (port?.shape === 'slot' && port.location === 'front') {
    const sx = g.open_x + (g.open_w - port.slot_w_mm) / 2;
    const drawX = mirror ? W - sx - port.slot_w_mm : sx;
    s += `<rect x="${drawX}" y="${Y(g.open_y + port.slot_h_mm)}" width="${port.slot_w_mm}" height="${port.slot_h_mm}" fill="#111" stroke="${COL.port}" stroke-width="2"/>`;
  }
  if (port?.location === 'front' && port.shape === 'round') {
    (pos.port || []).forEach((p, i) => {
      const rOut = port.outer_d_mm / 2 + (port.flange_mm || 0);
      s += `<g class="${editable ? 'drag' : ''}" data-role="port" data-idx="${i}" transform="translate(${X(p.x)},${Y(p.y)})"><circle r="${rOut}" fill="#3f4652" stroke="${COL.port}" stroke-width="2.4"/><circle r="${port.d_mm / 2}" fill="#050505"/></g>`;
    });
  }
  if (r.chamber && pos.mid) {
    const ch = r.chamber;
    const cx = pos.mid.x + ch.offset_x;
    const cy = pos.mid.y + ch.offset_y;
    s += `<rect x="${X(cx) - ch.ext_w / 2}" y="${Y(cy + ch.ext_h / 2)}" width="${ch.ext_w}" height="${ch.ext_h}" fill="#16a34a" fill-opacity="0.07" stroke="#16a34a" stroke-width="1.4" stroke-dasharray="7 4" pointer-events="none"/>`;
    s += `<text x="${X(cx) - ch.ext_w / 2 + 4}" y="${Y(cy - ch.ext_h / 2) - 4}" font-size="10" fill="#15803d" pointer-events="none">mid chamber</text>`;
  }

  (pos.woofer || []).forEach((p, i) => { s += driverGlyph(dr.woofer, X(p.x), Y(p.y), 'woofer', i, editable, opts.bolts); });
  if (dr.mid && pos.mid) s += driverGlyph(dr.mid, X(pos.mid.x), Y(pos.mid.y), 'mid', 0, editable, opts.bolts);
  if (dr.tweeter) s += driverGlyph(dr.tweeter, X(pos.tweeter.x), Y(pos.tweeter.y), 'tweeter', 0, editable, opts.bolts);

  if (opts.clear) {
    (r.clearances || []).filter((c) => c.web_mm < 40).forEach((c) => {
      const dx = c.bx - c.ax;
      const dy = c.by - c.ay;
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;
      const x1 = X(c.ax + ux * c.ar);
      const y1 = Y(c.ay + uy * c.ar);
      const x2 = X(c.bx - ux * c.br);
      const y2 = Y(c.by - uy * c.br);
      const min = d.layout.min_web_mm ?? 10;
      let col = '#15803d';
      if (c.web_mm < 0) col = '#dc2626';
      else if (c.web_mm < min - 0.05) col = '#d97706';
      const label = c.web_mm < 0 ? 'overlap' : `${fmt(c.web_mm, 0)} mm`;
      s += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${col}" stroke-width="2.5"/>`;
      s += `<g pointer-events="none"><rect x="${(x1 + x2) / 2 - 17}" y="${(y1 + y2) / 2 - 8}" width="34" height="14" rx="3" fill="${col}"/><text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 + 3}" font-size="10" fill="#fff" text-anchor="middle" font-weight="700">${label}</text></g>`;
    });
  }

  s += dimLine(0, H + 4, W, H + 4, `${fmt(W, 0)} mm`);
  s += dimLine(-4, 0, -4, H, `${fmt(H, 0)} mm`, 8, true);

  let title;
  if (r.system === 'sub') title = `Subwoofer – front${editable ? ' · drag to move' : ''}`;
  else if (mirror) title = 'RIGHT speaker (mirrored)';
  else title = `LEFT speaker – front${editable ? ' · drag to move' : ''}`;

  return `${s}<text x="${W / 2}" y="-4" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">${title}</text></svg>`;
}

function dampSide(r, D, Y) {
  const dm = r.damping;
  const g = r.geometry;
  if (!dm) return '';
  const L = dm.lining_mm;
  const y0 = g.open_y;
  const y1 = g.open_y + g.int_h;
  const style = `fill="${WOOL}" fill-opacity="0.8" stroke="#ca8a04" stroke-width="0.8" stroke-dasharray="3 2"`;

  let s = dm.fill_pct
    ? `<rect x="${L}" y="${Y(y1 - L)}" width="${D - 2 * L}" height="${g.int_h - 2 * L}" fill="${WOOL}" fill-opacity="0.25"/>`
    : '';
  if (dm.walls.includes('back')) s += `<rect x="${D - L}" y="${Y(y1)}" width="${L}" height="${g.int_h}" ${style}/>`;
  if (dm.walls.includes('top')) s += `<rect x="0" y="${Y(y1)}" width="${D}" height="${L}" ${style}/>`;
  if (dm.walls.includes('bottom')) s += `<rect x="0" y="${Y(y0 + L)}" width="${D}" height="${L}" ${style}/>`;

  const fillTxt = dm.fill_pct ? ` + ${dm.fill_pct} % loose fill` : '';
  return `${s}<text x="${D - L - 4}" y="${Y(y1) + 14}" font-size="9.5" text-anchor="end" fill="#a16207">${L} mm lining${fillTxt}</text>`;
}

function dampTop(r, D, Zs) {
  const dm = r.damping;
  const g = r.geometry;
  if (!dm) return '';
  const L = dm.lining_mm;
  const style = `fill="${WOOL}" fill-opacity="0.8" stroke="#ca8a04" stroke-width="0.8" stroke-dasharray="3 2"`;

  let s = dm.fill_pct
    ? `<rect x="${g.open_x + L}" y="${Zs(D - L)}" width="${g.int_w - 2 * L}" height="${D - 2 * L}" fill="${WOOL}" fill-opacity="0.25"/>`
    : '';
  if (dm.walls.includes('back')) s += `<rect x="${g.open_x}" y="${Zs(D)}" width="${g.int_w}" height="${L}" ${style}/>`;
  if (dm.walls.includes('left')) s += `<rect x="${g.open_x}" y="${Zs(D)}" width="${L}" height="${D}" ${style}/>`;
  if (dm.walls.includes('right')) s += `<rect x="${g.open_x + g.int_w - L}" y="${Zs(D)}" width="${L}" height="${D}" ${style}/>`;
  return s;
}

export function sideSVG(r, pxW) {
  const g = r.geometry;
  const pos = r.design.layout.positions;
  const dr = r.drivers;
  const port = r.port;
  const ch = r.chamber;
  const bt = g.baffle_t;
  const t = g.wall_t;
  const D = g.int_d;
  const bk = g.back_t;
  const hb = g.mode === 'fit' && g.back_mode === 'replace_inside' ? 5 : 0;
  const zmin = -bt - 6;
  const zmax = D + bk + hb + 6;
  const ymin = Math.min(0, g.open_y - t) - 6;
  const ymax = Math.max(g.baffle_h, g.open_y + g.int_h + t) + 6;
  const Y = (y) => ymax - y;

  let s = `<svg width="${pxW}" viewBox="${zmin - 40} -16 ${zmax - zmin + 60} ${ymax - ymin + 36}">${DEFS}`;
  s += `<rect x="0" y="${Y(g.open_y + g.int_h)}" width="${D}" height="${g.int_h}" fill="#f8fafc"/>`;
  s += `<rect x="0" y="${Y(g.open_y)}" width="${D + bk + hb}" height="${t}" fill="url(#hatch)"/>`;
  s += `<rect x="0" y="${Y(g.open_y + g.int_h + t)}" width="${D + bk + hb}" height="${t}" fill="url(#hatch)"/>`;
  s += `<rect x="${-bt}" y="${Y(g.baffle_h)}" width="${bt}" height="${g.baffle_h}" fill="url(#mdf)" stroke="#8b7355"/>`;
  s += `<rect x="${D}" y="${Y(g.open_y + g.int_h)}" width="${bk}" height="${g.int_h}" fill="url(#mdf)" stroke="#8b7355"/>`;
  if (hb) s += `<rect x="${D + bk}" y="${Y(g.open_y + g.int_h)}" width="5" height="${g.int_h}" fill="#7c5a3a"/>`;
  s += dampSide(r, D, Y);

  const driverSide = (drv, y, col) => {
    const rc = drv.cutout_d_mm / 2;
    const ro = drv.outer_d_mm / 2;
    const dep = drv.depth_mm;
    const rm = Math.max(rc * 0.42, 12);
    return `<rect x="${-drv.flange_mm}" y="${Y(y + ro)}" width="${drv.flange_mm}" height="${2 * ro}" fill="#2b2f36"/>`
      + `<path d="M0,${Y(y + rc)} L${dep * 0.62},${Y(y + rm)} L${dep * 0.62},${Y(y - rm)} L0,${Y(y - rc)} Z" fill="#4b5563" stroke="${col}" stroke-width="1.4"/>`
      + `<rect x="${dep * 0.62}" y="${Y(y + rm * 1.1)}" width="${dep * 0.38}" height="${rm * 2.2}" fill="#111827" stroke="${col}" stroke-width="1.4"/>`;
  };

  if (ch && pos.mid) {
    const cy = pos.mid.y + ch.offset_y;
    s += `<rect x="0" y="${Y(cy + ch.ext_h / 2)}" width="${ch.ext_depth}" height="${ch.ext_h}" fill="#dcfce7" fill-opacity="0.6" stroke="${COL.mid}" stroke-width="1.2" stroke-dasharray="5 3"/>`;
    s += `<text x="${ch.ext_depth + 4}" y="${Y(cy)}" font-size="10" fill="${COL.mid}">mid chamber ${fmt(ch.Vb_L, 1)} L</text>`;
  }

  (pos.woofer || []).forEach((p) => { s += driverSide(dr.woofer, p.y, COL.woofer); });
  if (dr.mid && pos.mid) s += driverSide(dr.mid, pos.mid.y, COL.mid);
  if (dr.tweeter) s += driverSide(dr.tweeter, pos.tweeter.y, COL.tweeter);

  if (port) {
    const pStyle = `fill="#ede9fe" fill-opacity="0.8" stroke="${COL.port}" stroke-width="1.4"`;
    if (port.shape === 'slot') {
      s += `<rect x="${-bt}" y="${Y(g.open_y + port.slot_h_mm + 18)}" width="${port.length_mm}" height="18" fill="url(#mdf)" stroke="${COL.port}"/>`;
    } else if (port.location === 'front') {
      (pos.port || []).forEach((p) => { s += `<rect x="${-bt}" y="${Y(p.y + port.outer_d_mm / 2)}" width="${port.length_mm}" height="${port.outer_d_mm}" ${pStyle}/>`; });
    } else if (port.location === 'rear') {
      (pos.port || []).forEach((p) => { s += `<rect x="${D + bk - port.length_mm}" y="${Y(p.y + port.outer_d_mm / 2)}" width="${port.length_mm}" height="${port.outer_d_mm}" ${pStyle}/>`; });
    } else {
      (pos.port || []).forEach((p) => { s += `<rect x="${p.z - port.outer_d_mm / 2}" y="${Y(g.open_y - t + port.length_mm)}" width="${port.outer_d_mm}" height="${port.length_mm}" ${pStyle}/>`; });
    }
  }

  s += dimLine(0, ymax - ymin + 2, D, ymax - ymin + 2, `${fmt(D, 0)} mm inside`);
  return `${s}<text x="${(zmax + zmin) / 2}" y="-4" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">Side section (front ←)</text></svg>`;
}

export function topSVG(r, pxW) {
  const g = r.geometry;
  const pos = r.design.layout.positions;
  const dr = r.drivers;
  const port = r.port;
  const ch = r.chamber;
  const bt = g.baffle_t;
  const t = g.wall_t;
  const D = g.int_d;
  const bk = g.back_t;
  const W = g.baffle_w;
  const Zs = (z) => D + bk - z;
  const xmin = Math.min(0, g.open_x - t) - 6;
  const xmax = Math.max(W, g.open_x + g.int_w + t) + 6;

  let s = `<svg width="${pxW}" viewBox="${xmin - 10} -16 ${xmax - xmin + 20} ${D + bk + bt + 40}">${DEFS}`;
  s += `<rect x="${g.open_x}" y="${Zs(D)}" width="${g.int_w}" height="${D}" fill="#f8fafc"/>`;
  s += `<rect x="${g.open_x - t}" y="0" width="${t}" height="${D + bk}" fill="url(#hatch)"/>`;
  s += `<rect x="${g.open_x + g.int_w}" y="0" width="${t}" height="${D + bk}" fill="url(#hatch)"/>`;
  s += `<rect x="0" y="${Zs(0)}" width="${W}" height="${bt}" fill="url(#mdf)" stroke="#8b7355"/>`;
  s += `<rect x="${g.open_x}" y="0" width="${g.int_w}" height="${bk}" fill="url(#mdf)" stroke="#8b7355"/>`;
  s += dampTop(r, D, Zs);

  const driverTop = (drv, x, col) => {
    const rc = drv.cutout_d_mm / 2;
    const dep = drv.depth_mm;
    const rm = Math.max(rc * 0.42, 12);
    return `<path d="M${x - rc},${Zs(0)} L${x - rm},${Zs(dep * 0.62)} L${x + rm},${Zs(dep * 0.62)} L${x + rc},${Zs(0)} Z" fill="#4b5563" stroke="${col}" stroke-width="1.4"/>`
      + `<rect x="${x - rm * 1.1}" y="${Zs(dep)}" width="${rm * 2.2}" height="${dep * 0.38}" fill="#111827" stroke="${col}" stroke-width="1.4"/>`;
  };

  if (ch && pos.mid) {
    const cx = pos.mid.x + ch.offset_x;
    s += `<rect x="${cx - ch.ext_w / 2}" y="${Zs(ch.ext_depth)}" width="${ch.ext_w}" height="${ch.ext_depth}" fill="#dcfce7" fill-opacity="0.6" stroke="${COL.mid}" stroke-dasharray="5 3"/>`;
  }
  (pos.woofer || []).forEach((p) => { s += driverTop(dr.woofer, p.x, COL.woofer); });
  if (dr.mid && pos.mid) s += driverTop(dr.mid, pos.mid.x, COL.mid);
  if (dr.tweeter) s += driverTop(dr.tweeter, pos.tweeter.x, COL.tweeter);

  if (port) {
    const pStyle = `fill="#ede9fe" fill-opacity="0.8" stroke="${COL.port}" stroke-width="1.4"`;
    if (port.location === 'bottom') (pos.port || []).forEach((p) => { s += `<circle cx="${g.open_x + p.x}" cy="${Zs(p.z)}" r="${port.outer_d_mm / 2}" ${pStyle}/>`; });
    else if (port.shape === 'slot') s += `<rect x="${g.open_x + (g.open_w - port.slot_w_mm) / 2}" y="${Zs(port.length_mm - bt)}" width="${port.slot_w_mm}" height="${port.length_mm}" ${pStyle}/>`;
    else if (port.location === 'front') (pos.port || []).forEach((p) => { s += `<rect x="${p.x - port.outer_d_mm / 2}" y="${Zs(port.length_mm - bt)}" width="${port.outer_d_mm}" height="${port.length_mm}" ${pStyle}/>`; });
    else (pos.port || []).forEach((p) => { s += `<rect x="${p.x - port.outer_d_mm / 2}" y="0" width="${port.outer_d_mm}" height="${port.length_mm}" ${pStyle}/>`; });
  }
  return `${s}<text x="${W / 2}" y="-4" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">Top section, left speaker (front ↓)</text></svg>`;
}

export function isoSVG(r, pxW) {
  const g = r.geometry;
  const pos = r.design.layout.positions;
  const dr = r.drivers;
  const port = r.port;
  const W = g.baffle_w;
  const H = g.baffle_h;
  const Dp = g.int_d + g.back_t + g.baffle_t;
  const k = 0.5;
  const ang = Math.PI / 6;
  const dx = Dp * k * Math.cos(ang);
  const dy = Dp * k * Math.sin(ang);
  const Y = (y) => H - y + dy;

  let s = `<svg width="${pxW}" viewBox="-10 -18 ${W + dx + 20} ${H + dy + 28}">${DEFS}`;
  s += `<polygon points="0,${Y(H)} ${dx},${Y(H) - dy} ${W + dx},${Y(H) - dy} ${W},${Y(H)}" fill="#cdb48c" stroke="#8b7355"/>`;
  s += `<polygon points="${W},${Y(H)} ${W + dx},${Y(H) - dy} ${W + dx},${Y(0) - dy} ${W},${Y(0)}" fill="#b89d73" stroke="#8b7355"/>`;
  s += `<rect x="0" y="${Y(H)}" width="${W}" height="${H}" fill="url(#mdf)" stroke="#8b7355"/>`;

  if (r.damping) {
    const L = r.damping.lining_mm * k;
    const insetPoly = (x0, y0, x1, y1, x2, y2, x3, y3) => (
      `<polygon points="${x0},${y0} ${x1},${y1} ${x2},${y2} ${x3},${y3}" fill="${WOOL}" fill-opacity="0.55" stroke="#ca8a04" stroke-dasharray="3 2"/>`
    );
    s += insetPoly(W + L * 0.5, Y(H) + L, W + dx - L * 0.5, Y(H) - dy + L, W + dx - L * 0.5, Y(0) - dy - L, W + L * 0.5, Y(0) - L);
    if (r.damping.walls.includes('top')) {
      s += insetPoly(L, Y(H) - L * 0.4, dx + L, Y(H) - dy + L * 0.4, W + dx - L, Y(H) - dy + L * 0.4, W - L, Y(H) - L * 0.4);
    }
    s += `<text x="${W + dx / 2}" y="${Y(H / 2) - dy / 2}" font-size="10" text-anchor="middle" fill="#a16207" transform="rotate(-90 ${W + dx / 2} ${Y(H / 2) - dy / 2})">${r.damping.lining_mm} mm lining</text>`;
  }

  const circle = (x, y, rr, fill, stroke) => `<circle cx="${x}" cy="${Y(y)}" r="${rr}" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>`;
  const rp = (d) => Math.sqrt((d.Sd_cm2 * 100) / Math.PI);
  (pos.woofer || []).forEach((p) => { s += circle(p.x, p.y, dr.woofer.outer_d_mm / 2, '#2b2f36', COL.woofer) + circle(p.x, p.y, rp(dr.woofer), 'url(#cone)', '#111'); });
  if (dr.mid && pos.mid) s += circle(pos.mid.x, pos.mid.y, dr.mid.outer_d_mm / 2, '#2b2f36', COL.mid) + circle(pos.mid.x, pos.mid.y, rp(dr.mid), 'url(#cone)', '#111');
  if (dr.tweeter) s += circle(pos.tweeter.x, pos.tweeter.y, dr.tweeter.outer_d_mm / 2, '#2b2f36', COL.tweeter) + circle(pos.tweeter.x, pos.tweeter.y, rp(dr.tweeter), 'url(#dome)', '#111');
  if (port?.location === 'front' && port.shape === 'round') {
    (pos.port || []).forEach((p) => { s += circle(p.x, p.y, port.d_mm / 2, '#050505', COL.port); });
  }
  return `${s}<text x="${W / 2}" y="-5" font-size="12" text-anchor="middle" fill="#334155" font-weight="600">3D · ${fmt(W, 0)} × ${fmt(H, 0)} × ${fmt(Dp, 0)} mm</text></svg>`;
}

export function enableDrag(svg, r) {
  if (!svg) return;
  const H = r.geometry.baffle_h;
  svg.querySelectorAll('g.drag').forEach((gEl) => {
    gEl.addEventListener('pointerdown', (ev) => {
      ev.preventDefault();
      gEl.setPointerCapture(ev.pointerId);
      const role = gEl.dataset.role;
      const idx = +gEl.dataset.idx;
      state.sel = { role, idx };
      svg.querySelectorAll('g.drag').forEach((x) => x.classList.toggle('sel', x === gEl));

      const ctm = svg.getScreenCTM().inverse();
      const toSvg = (e) => {
        const pt = svg.createSVGPoint();
        pt.x = e.clientX;
        pt.y = e.clientY;
        return pt.matrixTransform(ctm);
      };
      const start = toSvg(ev);
      let moved = false;

      const onMove = (e) => {
        const pt = toSvg(e);
        if (Math.hypot(pt.x - start.x, pt.y - start.y) > 1) moved = true;
        gEl.setAttribute('transform', `translate(${pt.x},${pt.y})`);
      };
      const onUp = (e) => {
        gEl.removeEventListener('pointermove', onMove);
        gEl.removeEventListener('pointerup', onUp);
        if (!moved) return;
        const pt = toSvg(e);
        const nextPt = { x: Math.round(pt.x * 2) / 2, y: Math.round((H - pt.y) * 2) / 2 };
        actions.placeChecked(role, idx, nextPt, `moved ${role}`);
      };
      gEl.addEventListener('pointermove', onMove);
      gEl.addEventListener('pointerup', onUp);
    });
  });
}

function componentSym(kind, cx, cy, vertical) {
  const rot = vertical ? `rotate(90 ${cx} ${cy})` : '';
  if (kind === 'C') {
    return `<g transform="${rot}"><line x1="${cx - 30}" y1="${cy}" x2="${cx - 4}" y2="${cy}" stroke="#000"/><line x1="${cx - 4}" y1="${cy - 11}" x2="${cx - 4}" y2="${cy + 11}" stroke="#000" stroke-width="2.5"/><line x1="${cx + 4}" y1="${cy - 11}" x2="${cx + 4}" y2="${cy + 11}" stroke="#000" stroke-width="2.5"/><line x1="${cx + 4}" y1="${cy}" x2="${cx + 30}" y2="${cy}" stroke="#000"/></g>`;
  }
  if (kind === 'L') {
    return `<g transform="${rot}"><path d="M${cx - 30},${cy} H${cx - 20} a5,5 0 0,1 10,0 a5,5 0 0,1 10,0 a5,5 0 0,1 10,0 a5,5 0 0,1 10,0 H${cx + 30}" fill="none" stroke="#000" stroke-width="1.6"/></g>`;
  }
  if (kind === 'R') {
    return `<g transform="${rot}"><line x1="${cx - 30}" y1="${cy}" x2="${cx - 14}" y2="${cy}" stroke="#000"/><rect x="${cx - 14}" y="${cy - 6}" width="28" height="12" fill="#fff" stroke="#000" stroke-width="1.6"/><line x1="${cx + 14}" y1="${cy}" x2="${cx + 30}" y2="${cy}" stroke="#000"/></g>`;
  }
  return `<g transform="${rot}"><line x1="${cx - 30}" y1="${cy}" x2="${cx - 22}" y2="${cy}" stroke="#000"/><rect x="${cx - 22}" y="${cy - 5}" width="16" height="10" fill="#fff" stroke="#000" stroke-width="1.4"/><line x1="${cx - 6}" y1="${cy}" x2="${cx + 4}" y2="${cy}" stroke="#000"/><line x1="${cx + 4}" y1="${cy - 9}" x2="${cx + 4}" y2="${cy + 9}" stroke="#000" stroke-width="2.4"/><line x1="${cx + 10}" y1="${cy - 9}" x2="${cx + 10}" y2="${cy + 9}" stroke="#000" stroke-width="2.4"/><line x1="${cx + 10}" y1="${cy}" x2="${cx + 30}" y2="${cy}" stroke="#000"/></g>`;
}

function schematicInner(way, branch, drv, labels) {
  const els = (branch.schematic || []).map((e) => ({
    ...e,
    label: e.label.replace(/ \(unwind[^)]*\)/, '').replace(' in parallel', ''),
  }));
  const step = 118;
  const top = 34;
  const bot = 128;
  const x0 = 26;
  const W = x0 + (els.length + 1) * step + 140;
  let s = labels ? `<text x="4" y="${top + 4}" font-weight="700">+</text><text x="4" y="${bot + 4}" font-weight="700">−</text>` : '';
  let x = x0;

  els.forEach((e) => {
    const [ref, ...rest] = e.label.split(' ');
    const valStr = rest.join(' ');
    if (e.pos === 'series') {
      s += `<line x1="${x}" y1="${top}" x2="${x + step / 2 - 30}" y2="${top}" stroke="#000"/>`;
      s += componentSym(e.kind, x + step / 2, top, false);
      s += `<line x1="${x + step / 2 + 30}" y1="${top}" x2="${x + step}" y2="${top}" stroke="#000"/>`;
      s += `<text x="${x + step / 2}" y="${top - 16}" text-anchor="middle" font-weight="700">${ref}</text>`;
      s += `<text x="${x + step / 2}" y="${top + 24}" text-anchor="middle" fill="#475569">${esc(valStr)}</text>`;
    } else {
      const midY = (top + bot) / 2;
      const clipped = valStr.slice(0, e.kind === 'RC' ? 28 : 20);
      s += `<line x1="${x}" y1="${top}" x2="${x + step}" y2="${top}" stroke="#000"/><circle cx="${x + step / 2}" cy="${top}" r="2.5"/>`;
      s += `<line x1="${x + step / 2}" y1="${top}" x2="${x + step / 2}" y2="${midY - 30}" stroke="#000"/>`;
      s += componentSym(e.kind, x + step / 2, midY, true);
      s += `<line x1="${x + step / 2}" y1="${midY + 30}" x2="${x + step / 2}" y2="${bot}" stroke="#000"/><circle cx="${x + step / 2}" cy="${bot}" r="2.5"/>`;
      s += `<text x="${x + step / 2 + 14}" y="${midY - 4}" font-weight="700">${ref}</text>`;
      s += `<text x="${x + step / 2 + 14}" y="${midY + 10}" fill="#475569">${esc(clipped)}</text>`;
      if (e.note) s += `<text x="${x + step / 2 + 14}" y="${midY + 23}" fill="#9333ea">${e.note}</text>`;
    }
    x += step;
  });

  const inv = (branch.polarity ?? 1) < 0;
  const midY = (top + bot) / 2;
  s += `<line x1="${x}" y1="${top}" x2="${x + 40}" y2="${top}" stroke="#000"/><line x1="${x0}" y1="${bot}" x2="${x + 40}" y2="${bot}" stroke="#000"/>`;
  s += `<rect x="${x + 30}" y="${midY - 16}" width="16" height="32" fill="#fff" stroke="${COL[way]}" stroke-width="2"/>`;
  s += `<path d="M${x + 46},${midY - 16} L${x + 66},${midY - 34} L${x + 66},${midY + 34} L${x + 46},${midY + 16} Z" fill="#fff" stroke="${COL[way]}" stroke-width="2"/>`;
  s += `<line x1="${x + 38}" y1="${top}" x2="${x + 38}" y2="${midY - 16}" stroke="#000"/><line x1="${x + 38}" y1="${bot}" x2="${x + 38}" y2="${midY + 16}" stroke="#000"/>`;
  s += `<text x="${x + 44}" y="${top - 4}" font-size="11">${inv ? '−' : '+'} terminal</text><text x="${x + 44}" y="${bot + 14}" font-size="11">${inv ? '+' : '−'} terminal</text>`;
  s += `<text x="${x + 72}" y="${midY + 4}" font-weight="700" fill="${COL[way]}">${esc(drv.model)}</text>`;
  if (inv) s += `<text x="${x + 72}" y="${midY + 18}" fill="#b45309">INVERTED</text>`;
  return { inner: s, W };
}

export function wiringSVG(r) {
  const x = r.design.crossover;
  const active = x.mode === 'active';
  const ways = Object.keys(x.levels || {});
  const BH = 182;
  const top = 44;
  const bot = 138;
  const head = 28;
  let W = 0;
  let body = '';

  ways.forEach((w, i) => {
    const branch = r.crossover_parts[w] || { schematic: [], polarity: x.polarity?.[w] ?? 1 };
    branch.polarity = x.polarity?.[w] ?? branch.polarity ?? 1;
    const { inner, W: branchW } = schematicInner(w, branch, r.drivers[w], false);
    W = Math.max(W, branchW + 40);
    const y = head + i * BH;
    body += `<g transform="translate(40,${y + 10})">${inner}</g>`;
    if (active) {
      body += `<text x="2" y="${y + top - 8}" font-size="10.5" font-weight="700" fill="${COL[w]}">amp ${i + 1}</text>`;
      body += `<rect x="22" y="${y + top - 5}" width="10" height="10" fill="#dc2626"/><rect x="22" y="${y + bot - 5}" width="10" height="10" fill="#111"/>`;
      body += `<line x1="32" y1="${y + top}" x2="66" y2="${y + top}" stroke="#000"/><line x1="32" y1="${y + bot}" x2="66" y2="${y + bot}" stroke="#000"/>`;
      body += `<text x="44" y="${y + 6}" font-size="11.5" font-weight="700" fill="${COL[w]}">${w.toUpperCase()}</text>`;
    } else {
      body += `<text x="44" y="${y + 6}" font-size="11.5" font-weight="700" fill="${COL[w]}">${w.toUpperCase()} BRANCH</text>`;
      body += `<line x1="14" y1="${y + top}" x2="66" y2="${y + top}" stroke="#dc2626" stroke-width="1.6"/><circle cx="14" cy="${y + top}" r="3" fill="#dc2626"/>`;
      body += `<line x1="26" y1="${y + bot}" x2="66" y2="${y + bot}" stroke="#111" stroke-width="1.6"/><circle cx="26" cy="${y + bot}" r="3" fill="#111"/>`;
    }
  });

  const H = head + ways.length * BH;
  const headerSvg = active
    ? '<text x="2" y="14" font-size="11" font-weight="700">One amplifier channel per driver (from the DSP)</text>'
    : `<text x="2" y="14" font-size="11" font-weight="700">Input terminals</text><rect x="9" y="18" width="10" height="10" fill="#dc2626"/><text x="22" y="27" font-size="10">+</text><rect x="21" y="18" width="10" height="10" fill="#111" transform="translate(12,0)"/>
       <line x1="14" y1="28" x2="14" y2="${head + (ways.length - 1) * BH + top}" stroke="#dc2626" stroke-width="2"/><line x1="26" y1="28" x2="26" y2="${head + (ways.length - 1) * BH + bot}" stroke="#111" stroke-width="2"/>`;
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-size="11">${headerSvg}${body}</svg>`;
}

export function partSVG(p, maxPx = 380) {
  const sc = maxPx / Math.max(p.w, p.h);
  const W = p.w;
  const H = p.h;
  const col = { through: '#dc2626', pocket: '#2563eb', drill: '#16a34a', chamfer_rear: '#9333ea', center: '#94a3b8', rect: '#dc2626' };

  let s = `<svg width="${W * sc + 20}" height="${H * sc + 20}" viewBox="-10 -10 ${W + 20 / sc} ${H + 20 / sc}"><rect width="${W}" height="${H}" fill="#f3e9d8" stroke="#000" stroke-width="${1 / sc}"/>`;
  p.features.forEach((f) => {
    const c = col[f.op];
    const sw = 1.2 / sc;
    const dash = f.op === 'pocket' || f.op === 'chamfer_rear' ? ` stroke-dasharray="${4 / sc} ${3 / sc}"` : '';
    if (f.op === 'rect') s += `<rect x="${f.x}" y="${H - f.y - f.h}" width="${f.w}" height="${f.h}" fill="none" stroke="${c}" stroke-width="${sw}"/>`;
    else if (f.op === 'center') s += `<path d="M${f.x - 5},${H - f.y}H${f.x + 5}M${f.x},${H - f.y - 5}V${H - f.y + 5}" stroke="${c}" stroke-width="${sw}"/>`;
    else s += `<circle cx="${f.x}" cy="${H - f.y}" r="${f.d / 2}" fill="none" stroke="${c}" stroke-width="${sw}"${dash}/>`;
  });
  return `${s}</svg>`;
}
