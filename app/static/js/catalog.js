/* Driver catalog loading, dropdown population, unified Catalog/Replacements modal, and Driver Specs modal. */
import { $, $$, actions, api, esc, fmt, kv, markChange, resetXo, setStatus, state } from './state.js';

const SLOT_ROLES = {
  woofer: ['woofer', 'midwoofer', 'subwoofer'],
  mid: ['mid', 'midwoofer'],
  tweeter: ['tweeter'],
};

const DB_FIELDS = [
  ['id', 'text'], ['brand', 'text'], ['model', 'text'], ['role', 'role'],
  ['nominal_mm', 'number'], ['price_eur', 'number'], ['Re', 'number'], ['Le_mH', 'number'],
  ['Fs', 'number'], ['Qms', 'number'], ['Qes', 'number'], ['Vas_L', 'number'],
  ['Sd_cm2', 'number'], ['Xmax_mm', 'number'], ['Pe_W', 'number'], ['sens_db', 'number'],
  ['Z_nom', 'number'], ['outer_d_mm', 'number'], ['cutout_d_mm', 'number'], ['depth_mm', 'number'],
  ['flange_mm', 'number'], ['bolt_circle_mm', 'number'], ['bolt_count', 'number'],
  ['fmin', 'number'], ['fmax', 'number'], ['tier', 'number'], ['sealed_back', 'checkbox'],
];

const DB_LABEL = {
  nominal_mm: 'Nominal size mm',
  price_eur: 'Price € each',
  Re: 'Re Ω',
  Le_mH: 'Le mH',
  Fs: 'Fs Hz',
  Vas_L: 'Vas L',
  Sd_cm2: 'Sd cm²',
  Xmax_mm: 'Xmax mm',
  Pe_W: 'Pe W',
  sens_db: 'Sens. dB 2.83V',
  Z_nom: 'Z nominal Ω',
  outer_d_mm: 'Outer Ø mm',
  cutout_d_mm: 'Cut-out Ø mm',
  depth_mm: 'Depth mm',
  flange_mm: 'Flange thickness mm',
  bolt_circle_mm: 'Bolt circle Ø mm',
  bolt_count: 'Screw holes',
  fmin: 'Usable from Hz',
  fmax: 'Usable to Hz',
  tier: 'Quality 1–5',
  sealed_back: 'closed back (tweeter)',
};

export const drvById = (id) => state.drivers.find((d) => d.id === id);

export function sizeLabel(driver) {
  if (driver.role === 'tweeter') return `${fmt(driver.nominal_mm, 0)} mm dome`;
  const decimals = driver.nominal_mm % 10 ? 1 : 0;
  return `${fmt(driver.nominal_mm / 10, decimals)} cm`;
}

export function driverSpecLine(driver) {
  const parts = [`Fs ${fmt(driver.Fs, 0)} Hz`];
  if (driver.role !== 'tweeter') {
    parts.push(
      `Qts ${fmt(driver.Qts, 2)}`,
      `Vas ${fmt(driver.Vas_L, 0)} L`,
      `Xmax ${fmt(driver.Xmax_mm, 1)} mm`,
    );
  }
  parts.push(
    `${fmt(driver.sens_db, 1)} dB`,
    `${fmt(driver.Z_nom, 0)} Ω`,
    `cut-out ${fmt(driver.cutout_d_mm, 0)} mm`,
    `depth ${fmt(driver.depth_mm, 0)} mm`,
  );
  return parts.join(' · ');
}

function slotForRole(role) {
  if (role === 'tweeter') return 'tweeter';
  if (role === 'mid') return 'mid';
  return 'woofer';
}

function sortKey(driver) {
  if (driver.price_eur > 0) return 2;
  if (driver.shop?.url) return 1;
  return 0;
}

export async function loadDrivers() {
  state.drivers = await api('/api/drivers');
  state.drivers.sort((a, b) => (
    (sortKey(b) - sortKey(a))
    || (a.brand + a.model).localeCompare(b.brand + b.model)
  ));
  $$('select.drv').forEach(fillDriverSelect);
  actions.syncInputs();
  renderDb();
}

export function fillDriverSelect(selectEl) {
  const roles = selectEl.dataset.roles.split(',');
  const prevVal = selectEl.value;
  const matching = state.drivers.filter((d) => roles.includes(d.role));

  const formatOption = (d) => {
    let priceTag = '';
    if (d.price_eur > 0) priceTag = ` · €${fmt(d.price_eur, 0)}`;
    else if (d.shop?.url) priceTag = ' · EU shop';
    const stockTag = d.in_stock === false ? ' (out)' : '';
    return `<option value="${d.id}">${esc(d.brand)} ${esc(d.model)} · ${sizeLabel(d)}${priceTag}${stockTag}</option>`;
  };

  const priced = matching.filter((d) => d.price_eur > 0);
  const euLinked = matching.filter((d) => d.price_eur <= 0 && d.shop?.url);
  const catalogRest = matching.filter((d) => d.price_eur <= 0 && !d.shop?.url);

  const groups = [];
  if (selectEl.dataset.none) groups.push('<option value="">— none (2-way) —</option>');
  if (priced.length) groups.push(`<optgroup label="★ EU Priced & Ready (${priced.length})">${priced.map(formatOption).join('')}</optgroup>`);
  if (euLinked.length) groups.push(`<optgroup label="EU Shop — SoundImports (${euLinked.length})">${euLinked.map(formatOption).join('')}</optgroup>`);
  if (catalogRest.length) groups.push(`<optgroup label="Full Catalog — driver-base (${catalogRest.length})">${catalogRest.map(formatOption).join('')}</optgroup>`);

  selectEl.innerHTML = groups.join('');
  const stillExists = prevVal && [...selectEl.options].some((opt) => opt.value === prevVal);
  if (stillExists) {
    selectEl.value = prevVal;
  } else if (!selectEl.dataset.none && selectEl.options.length) {
    selectEl.selectedIndex = 0;
  }
}

export function initDb() {
  state.pickSlot = null;
  state.dbMode = 'browse';
  state.repTarget = null;
  state.repData = null;
  state.dbLimit = 60;

  actions.openCatalogPicker = openCatalogPicker;
  actions.openDriverDetail = openDriverDetail;

  $('#btn-db').onclick = () => openCatalogPicker(null, 'browse');
  $('#db-close').onclick = () => $('#db-dialog').close();
  $('#db-dialog').onclick = (e) => { if (e.target === $('#db-dialog')) $('#db-dialog').close(); };
  $('#dd-close').onclick = () => $('#drv-detail-dialog').close();
  $('#drv-detail-dialog').onclick = (e) => { if (e.target === $('#drv-detail-dialog')) $('#drv-detail-dialog').close(); };

  $$('#db-mode-tabs button').forEach((btn) => {
    btn.onclick = () => {
      state.dbMode = btn.dataset.dbmode;
      $$('#db-mode-tabs button').forEach((x) => x.classList.toggle('on', x === btn));
      if (state.dbMode === 'replace' && state.repTarget) {
        loadReplacements(state.repTarget);
      } else {
        renderDb();
      }
    };
  });

  $('#db-form').innerHTML = DB_FIELDS.map(([key, type]) => {
    if (type === 'role') {
      return `<label>Role<select name="${key}"><option>woofer</option><option>midwoofer</option><option>mid</option><option>tweeter</option></select></label>`;
    }
    if (type === 'checkbox') {
      return `<label class="chk"><input type="checkbox" name="${key}"> ${DB_LABEL[key]}</label>`;
    }
    return `<label>${DB_LABEL[key] || key}<input name="${key}" type="${type}" step="any"></label>`;
  }).join('');

  $('#db-role').onchange = () => { state.dbLimit = 60; renderDb(); };
  $('#db-eu').onchange = () => { state.dbLimit = 60; renderDb(); };
  $('#db-search').oninput = () => { state.dbLimit = 60; renderDb(); };
  $('#db-more').onclick = () => { state.dbLimit += 80; renderDb(); };
  $('#db-clear-mid').onclick = () => { assignDriverToSlot('mid', null); $('#db-dialog').close(); };
  $('#db-fetch-prices').onclick = fetchCatalogPrices;

  $('#db-save').onclick = async (e) => {
    e.preventDefault();
    const payload = {};
    DB_FIELDS.forEach(([key, type]) => {
      const el = $(`#db-form [name="${key}"]`);
      const val = type === 'checkbox' ? el.checked : el.value;
      if (val !== '' && val != null) {
        payload[key] = type === 'number' ? +val : val;
      }
    });
    try {
      await api('/api/drivers', payload);
      await loadDrivers();
      state.find = null;
      setStatus('driver saved');
    } catch (err) {
      alert(err.message);
    }
  };
}

export function openCatalogPicker(slot, mode = 'browse', targetId = null) {
  state.pickSlot = slot;
  state.dbMode = mode;
  state.repTarget = targetId;
  state.repData = null;
  state.dbLimit = 60;

  if ($('#db-search')) $('#db-search').value = '';
  if (mode === 'replace') {
    $('#db-title').textContent = 'Driver replacements';
  } else {
    $('#db-title').textContent = slot ? `Pick ${slot}` : 'Drivers catalog';
  }

  $('#db-role').value = slot || '';
  $('#db-clear-mid').hidden = slot !== 'mid';
  $('#db-mode-tabs').hidden = !targetId;
  $$('#db-mode-tabs button').forEach((btn) => btn.classList.toggle('on', btn.dataset.dbmode === mode));
  $('#db-dialog').showModal();

  if (mode === 'replace' && targetId) {
    loadReplacements(targetId);
  } else {
    renderDb();
  }
}

export async function assignDriverToSlot(slot, driverId) {
  if (!slot) return;
  const drv = driverId ? drvById(driverId) : null;
  if (drv && drv.shop?.url && !(drv.price_eur > 0)) {
    try {
      await api(`/api/catalog/price?url=${encodeURIComponent(drv.shop.url)}`);
      await loadDrivers();
    } catch {}
  }

  markChange(`${slot} → ${drv ? drv.model : 'none'}`);
  if (slot === 'mid') {
    state.design.drivers.mid = driverId ? { id: driverId } : null;
  } else {
    state.design.drivers[slot].id = driverId;
  }

  state.autoPick = false;
  if ($('#g-auto')) $('#g-auto').checked = false;
  state.xoManual = false;
  state.xoTunedKey = null;
  resetXo(state.design);
  state.design.layout.positions = null;
  actions.syncInputs();
  actions.simulate(0);
}

async function fetchCatalogPrices() {
  const btn = $('#db-fetch-prices');
  const statusEl = $('#db-price-status');
  btn.disabled = true;
  btn.textContent = 'Fetching EU prices…';
  statusEl.innerHTML = '<div class="alert info">Checking SoundImports / EU shop pages (respecting crawl delay)…</div>';

  try {
    const res = await api('/api/drivers/fetch-prices', { force: true });
    await loadDrivers();
    state.find = null;
    actions.simulate(0);
    actions.runFind(false);
    const failedNote = res.failed.length ? ` (${res.failed.length} skipped/failed)` : '';
    statusEl.innerHTML = `<div class="alert ok">Updated <b>${res.updated.length}</b> EU prices &amp; stock${failedNote}.</div>`;
  } catch (err) {
    statusEl.innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Fetch EU prices';
  }
}

async function loadReplacements(driverId) {
  state.repTarget = driverId;
  $('#db-rep-banner').hidden = false;
  $('#db-rep-banner').innerHTML = '<span class="muted">Searching 1,300+ drivers for mechanical + acoustic drop-in matches…</span>';
  $('#db-cards').innerHTML = '';
  try {
    state.repData = await api(`/api/drivers/${encodeURIComponent(driverId)}/replacements?limit=15`);
    renderDb();
  } catch (err) {
    $('#db-rep-banner').innerHTML = `<div class="alert bad">${esc(err.message)}</div>`;
  }
}

function renderShopStatusHtml(shopUrl, price, inStock, emptyText, checkAttr) {
  const link = shopUrl ? `<a href="${shopUrl}" target="_blank" rel="noopener">EU shop</a> ` : '';
  if (price > 0) {
    const stockBadge = inStock === false
      ? '<span class="tag warn">out</span>'
      : '<span class="tag ok">in stock</span>';
    return `${link}<b>€${fmt(price, 2)}</b> ${stockBadge}`;
  }
  if (shopUrl) {
    return `${link}<button class="mini" ${checkAttr}="${esc(shopUrl)}">Check €</button>`;
  }
  return `<span class="muted">${emptyText}</span>`;
}

export function openDriverDetail(driverId) {
  const d = drvById(driverId);
  if (!d) return;
  const dlg = $('#drv-detail-dialog');
  $('#dd-title').textContent = `${d.brand} ${d.model} (${d.role})`;

  const shopUrl = d.shop?.url;
  const slot = slotForRole(d.role);
  const isUsed = ['woofer', 'mid', 'tweeter'].some((k) => state.design?.drivers?.[k]?.id === d.id);
  const actionBtn = isUsed
    ? '<span class="tag ok">✓ Active in design</span>'
    : `<button class="primary" id="dd-use">Use as ${slot}</button>`;

  const cmsText = d.Cms_mm_per_N != null ? `${fmt(d.Cms_mm_per_N, 2)} mm/N` : 'derived';
  const blText = d.Bl != null ? `${fmt(d.Bl, 2)} Tm` : 'derived';
  const measButtons = ['frd', 'zma'].map((kind) => {
    if ((d.measured || []).includes(kind)) {
      return `<span class="tag ok">${kind.toUpperCase()} loaded ✓</span><button class="mini" data-dd-mdel="${kind}">Remove ${kind.toUpperCase()}</button>`;
    }
    return `<button class="mini" data-dd-mup="${kind}">+ Upload ${kind.toUpperCase()}</button>`;
  }).join(' ');

  $('#dd-body').innerHTML = `
    <div class="row-btns" style="justify-content:space-between;align-items:center">
      <div>${renderShopStatusHtml(shopUrl, d.price_eur, d.in_stock, 'No EU price listed', 'id="dd-chk-url" data-url')}</div>
      <div class="row-btns" style="margin:0">
        ${actionBtn}
        <button id="dd-rep">Find replacement</button>
      </div>
    </div>
    <div class="dd-grid">
      <div class="dd-box">
        <h4>Thiele / Small parameters</h4>
        ${kv([
          ['Fs', `${fmt(d.Fs, 1)} Hz`],
          ['Qts / Qes / Qms', `${fmt(d.Qts, 3)} / ${fmt(d.Qes, 3)} / ${fmt(d.Qms, 2)}`],
          ['Vas', d.Vas_L != null ? `${fmt(d.Vas_L, 2)} L` : '—'],
          ['Sd', `${fmt(d.Sd_cm2, 1)} cm²`],
          ['Re / Z nom', `${fmt(d.Re, 2)} Ω / ${fmt(d.Z_nom, 0)} Ω`],
          ['Le', `${fmt(d.Le_mH, 2)} mH`],
          ['Mms / Cms', `${fmt(d.Mms_g, 1)} g / ${cmsText}`],
          ['Bl / Xmax', `${blText} / ${fmt(d.Xmax_mm, 2)} mm`],
          ['Sensitivity / Power', `${fmt(d.sens_db, 1)} dB · ${fmt(d.Pe_W, 0)} W`],
          ['Usable band', `${fmt(d.fmin, 0)}–${fmt(d.fmax, 0)} Hz`],
        ])}
      </div>
      <div class="dd-box">
        <h4>Physical dimensions &amp; data</h4>
        ${kv([
          ['Nominal size', sizeLabel(d)],
          ['Outer diameter', `${fmt(d.outer_d_mm, 1)} mm`],
          ['Cut-out diameter', `${fmt(d.cutout_d_mm, 1)} mm`],
          ['Mounting depth', `${fmt(d.depth_mm, 1)} mm`],
          ['Flange thickness', `${fmt(d.flange_mm, 1)} mm`],
          ['Bolt circle / holes', `${fmt(d.bolt_circle_mm, 1)} mm (${d.bolt_count}×)`],
          ['T/S source', d.verified ? 'Datasheet' : 'Partly estimated'],
          ['Dimensions', d.dims_verified ? 'Checked vs drawing' : 'Estimated — verify before CNC'],
        ])}
      </div>
    </div>
    ${d.notes ? `<p class="hint mt">${esc(d.notes)}</p>` : ''}
    <div class="dd-box mt rw-only">
      <h4>Measured response / impedance (FRD / ZMA)</h4>
      <div class="row-btns" style="margin:0">${measButtons}</div>
    </div>`;

  const chkBtn = $('#dd-chk-url');
  if (chkBtn) {
    chkBtn.onclick = async () => {
      chkBtn.disabled = true;
      chkBtn.textContent = '…';
      try {
        await api(`/api/catalog/price?url=${encodeURIComponent(shopUrl)}`);
        await loadDrivers();
        openDriverDetail(d.id);
      } catch {
        chkBtn.textContent = 'err';
      }
    };
  }

  const useBtn = $('#dd-use');
  if (useBtn) {
    useBtn.onclick = async () => {
      await assignDriverToSlot(slot, d.id);
      dlg.close();
      if ($('#db-dialog').open) $('#db-dialog').close();
    };
  }

  $('#dd-rep').onclick = () => {
    dlg.close();
    openCatalogPicker(slot, 'replace', d.id);
  };

  $$('#dd-body [data-dd-mup]').forEach((btn) => {
    btn.onclick = () => {
      const kind = btn.dataset.ddMup;
      const inp = document.createElement('input');
      inp.type = 'file';
      inp.accept = '.frd,.zma,.txt,.csv';
      inp.onchange = async () => {
        const file = inp.files[0];
        if (!file) return;
        try {
          await api(`/api/drivers/${encodeURIComponent(d.id)}/measurements/${kind}`, {
            text: await file.text(),
            filename: file.name,
            source: 'upload',
          });
          await loadDrivers();
          actions.simulate(0);
          openDriverDetail(d.id);
        } catch (err) {
          alert(err.message);
        }
      };
      inp.click();
    };
  });

  $$('#dd-body [data-dd-mdel]').forEach((btn) => {
    btn.onclick = async () => {
      const kind = btn.dataset.ddMdel;
      await api(`/api/drivers/${encodeURIComponent(d.id)}/measurements/${kind}`, undefined, false, 'DELETE');
      await loadDrivers();
      actions.simulate(0);
      openDriverDetail(d.id);
    };
  });

  dlg.showModal();
}

function matchesRoleFilter(driver, selectedRole) {
  const slotRoles = SLOT_ROLES[state.pickSlot] || null;
  if (!selectedRole) {
    return !slotRoles || slotRoles.includes(driver.role);
  }
  const pickingMidwooferForSlot = (state.pickSlot === 'woofer' || state.pickSlot === 'mid')
    && selectedRole === state.pickSlot
    && driver.role === 'midwoofer';
  return driver.role === selectedRole || pickingMidwooferForSlot;
}

function renderCatalogCard(driver, extra = {}) {
  const shopUrl = driver.shop?.url || extra.shop_url;
  const price = extra.price_eur || driver.price_eur;
  const stock = extra.in_stock !== undefined ? extra.in_stock : driver.in_stock;
  const slot = state.pickSlot || slotForRole(driver.role);
  const curId = state.design?.drivers?.[slot]?.id;
  const isCur = curId === driver.id;

  const badge = extra.match_pct
    ? `<span class="rep-pct">${extra.match_pct} % match</span>`
    : `<span class="tag">${esc(driver.role)} · ${sizeLabel(driver)}</span>`;
  const summary = extra.notes ? extra.notes.map(esc).join(' · ') : driverSpecLine(driver);
  const priceHtml = renderShopStatusHtml(shopUrl, price, stock, 'no EU price', 'data-chk-url');
  const replaceBtn = state.dbMode === 'browse'
    ? `<button class="mini" data-rep="${driver.id}">Replace</button>`
    : '';
  const selectLabel = state.pickSlot || state.dbMode === 'replace' ? 'Select' : 'Use';
  const selectHtml = isCur
    ? '<span class="tag ok">✓ In use</span>'
    : `<button class="primary mini" data-pick="${driver.id}">${selectLabel}</button>`;

  return `
    <div class="rep-card ${isCur ? 'cur' : ''}" data-card-id="${driver.id}">
      <div class="r1"><span>${esc(driver.brand)} ${esc(driver.model)}</span>${badge}</div>
      <div class="rep-notes">${summary}</div>
      <div class="rep-foot">
        <span>${priceHtml}</span>
        <span>
          <button class="mini" data-det="${driver.id}">Specs</button>
          ${replaceBtn}
          ${selectHtml}
        </span>
      </div>
    </div>`;
}

export function renderDb() {
  const host = $('#db-cards');
  const banner = $('#db-rep-banner');
  if (!host) return;

  const query = ($('#db-search')?.value || '').trim().toLowerCase();
  const tokens = query ? query.split(/[\s,/]+/).filter(Boolean) : [];
  const selectedRole = $('#db-role').value;
  const euOnly = $('#db-eu')?.checked;

  if (state.dbMode === 'replace' && state.repData) {
    const t = state.repData.target;
    banner.hidden = false;
    banner.innerHTML = `<b>Replacing:</b> ${esc(t.brand)} ${esc(t.model)} (${esc(t.role)}) · cut-out ${fmt(t.cutout_d_mm, 0)} mm · Fs ${fmt(t.Fs, 0)} Hz · Qts ${fmt(t.Qts, 2)} · ${fmt(t.sens_db, 1)} dB · ${fmt(t.Z_nom, 0)} Ω`;

    let reps = state.repData.replacements;
    if (euOnly) reps = reps.filter((r) => r.shop_url);
    if (tokens.length) {
      reps = reps.filter((r) => {
        const hay = `${r.brand} ${r.model} ${r.notes.join(' ')}`.toLowerCase();
        return tokens.every((tk) => hay.includes(tk));
      });
    }
    if ($('#db-count')) $('#db-count').textContent = `${reps.length} drop-in replacements found`;
    if ($('#db-more')) $('#db-more').hidden = true;
    host.innerHTML = reps.length
      ? reps.map((r) => renderCatalogCard(r.driver, r)).join('')
      : '<p class="hint">No matching replacements.</p>';
  } else {
    banner.hidden = true;
    const all = state.drivers.filter((d) => {
      if (!matchesRoleFilter(d, selectedRole)) return false;
      if (euOnly && !d.shop?.url) return false;
      if (tokens.length) {
        const hay = `${d.brand} ${d.model} ${d.id} ${d.role} ${Math.round(d.nominal_mm)}mm ${Math.round(d.nominal_mm / 10)}cm`.toLowerCase();
        if (!tokens.every((tk) => hay.includes(tk))) return false;
      }
      return true;
    });
    const limit = state.dbLimit || 60;
    const rows = all.slice(0, limit);
    const euCnt = all.filter((d) => d.shop?.url).length;
    if ($('#db-count')) $('#db-count').textContent = `Showing ${rows.length} of ${all.length} drivers (${euCnt} with EU shop links)`;
    if ($('#db-more')) $('#db-more').hidden = rows.length >= all.length;
    host.innerHTML = rows.length
      ? rows.map((d) => renderCatalogCard(d)).join('')
      : '<p class="hint">No matching drivers.</p>';
  }

  $$('#db-cards [data-card-id]').forEach((card) => {
    card.onclick = (e) => {
      if (!e.target.closest('button,a')) openDriverDetail(card.dataset.cardId);
    };
  });
  $$('#db-cards [data-det]').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      openDriverDetail(btn.dataset.det);
    };
  });
  $$('#db-cards [data-rep]').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      openCatalogPicker(state.pickSlot, 'replace', btn.dataset.rep);
    };
  });
  $$('#db-cards [data-chk-url]').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      btn.textContent = '…';
      try {
        const p = await api(`/api/catalog/price?url=${encodeURIComponent(btn.dataset.chkUrl)}`);
        await loadDrivers();
        const badge = document.createElement('span');
        const stockTag = p.in_stock ? '<span class="tag ok">in stock</span>' : '<span class="tag warn">out</span>';
        badge.innerHTML = `<b>€${fmt(p.price_eur, 2)}</b> ${stockTag}`;
        btn.replaceWith(badge);
      } catch {
        btn.textContent = 'err';
        btn.disabled = false;
      }
    };
  });
  $$('#db-cards [data-pick]').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      btn.textContent = '…';
      const fromRep = state.repData?.replacements.find((x) => x.id === btn.dataset.pick)?.driver;
      const drv = drvById(btn.dataset.pick) || fromRep;
      const slot = state.pickSlot || slotForRole(drv.role);
      await assignDriverToSlot(slot, drv.id);
      $('#db-dialog').close();
      if (!state.pickSlot) actions.showStep('design');
    };
  });
}
