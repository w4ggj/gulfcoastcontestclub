'use strict';

const API = '';   // same-origin; relative URLs

// ── Auth ────────────────────────────────────────────────────────────────────
let _token = sessionStorage.getItem('gccc_admin_token') || '';

function showLogin() {
  el('login-overlay').classList.remove('hidden');
}
function hideLogin() {
  el('login-overlay').classList.add('hidden');
}

window.handleLogin = async function(e) {
  e.preventDefault();
  const pw = el('login-pw').value;
  const errEl = el('login-error');
  errEl.style.display = 'none';
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Login failed');
    }
    const data = await res.json();
    _token = data.token;
    sessionStorage.setItem('gccc_admin_token', _token);
    hideLogin();
    await loadContests();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = 'block';
  }
};

window.handleLogout = async function() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + _token },
    });
  } catch (_) {}
  _token = '';
  sessionStorage.removeItem('gccc_admin_token');
  showLogin();
};

// ── Boot ────────────────────────────────────────────────────────────────────
(async function init() {
  // Check if we have a valid stored token
  if (_token) {
    try {
      const res = await fetch('/api/auth/check', {
        headers: { 'Authorization': 'Bearer ' + _token },
      });
      if (res.ok) {
        hideLogin();
        await loadContests();
        return;
      }
    } catch (_) {}
  }
  // No valid token — clear stale one and show login
  _token = '';
  sessionStorage.removeItem('gccc_admin_token');
  showLogin();
})();

// ── Contest list ────────────────────────────────────────────────────────────
async function loadContests() {
  let contests;
  try {
    contests = await api('/api/contests');
  } catch (e) {
    el('contest-list').innerHTML = `<p class="muted">Could not load contests: ${e.message}</p>`;
    return;
  }

  // Populate station-setup contest selector
  const sel = el('st-contest');
  sel.innerHTML = '<option value="">— select —</option>' +
    contests.map(c => `<option value="${c.id}">${esc(c.name)} (${c.year})</option>`).join('');

  // Live banner
  const live = contests.find(c => c.status === 'live');
  if (live) {
    el('live-banner').classList.remove('hidden');
    el('live-banner-text').textContent = `Live: ${live.name}`;
    window._liveContestId = live.id;
  }

  // Contest list
  if (!contests.length) {
    el('contest-list').innerHTML = '<p class="muted">No contests yet. Create one above.</p>';
    return;
  }

  el('contest-list').innerHTML = contests.map(c => {
    const actions = [];
    actions.push(`<button class="btn btn-outline btn-sm" onclick="editContest(${c.id})">Edit</button>`);
    if (c.status === 'draft') {
      actions.push(`<button class="btn btn-success btn-sm" onclick="startContest(${c.id})">Start</button>`);
    }
    if (c.status === 'live') {
      actions.push(`<button class="btn btn-danger btn-sm" onclick="completeContest(${c.id})">Complete</button>`);
    }
    if (c.status !== 'live') {
      actions.push(`<button class="btn btn-danger btn-sm" onclick="deleteContest(${c.id}, '${esc(c.name).replace(/'/g, "\\'")}')">Delete</button>`);
    }
    // Format start/end times for display
    let timeLine = '';
    if (c.start_utc) {
      const s = new Date(c.start_utc.endsWith('Z') ? c.start_utc : c.start_utc + 'Z');
      const fmt = d => d.toLocaleDateString('en-US', {month:'short', day:'numeric'}) + ' ' +
                        d.toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
      timeLine = fmt(s);
      if (c.end_utc) {
        const e = new Date(c.end_utc.endsWith('Z') ? c.end_utc : c.end_utc + 'Z');
        timeLine += ' – ' + fmt(e);
      }
    }
    return `<div class="contest-item">
      <div class="contest-item-info">
        <span class="contest-item-name">${esc(c.name)}</span>
        <span class="contest-item-meta">${c.year} · ${esc(c.location || '')} · ${esc(c.station_callsign || '')} · ${esc(c.category || '')}${timeLine ? ' · ' + timeLine : ''}</span>
      </div>
      <div class="contest-item-actions">
        <span class="status-badge status-${c.status}">${c.status}</span>
        ${actions.join('')}
      </div>
    </div>`;
  }).join('');
}

// ── Create contest ───────────────────────────────────────────────────────────
window.createContest = async function() {
  const body = {
    name:             val('f-name'),
    contest_type:     val('f-type'),
    year:             parseInt(val('f-year'), 10),
    location:         val('f-location') || undefined,
    station_callsign: val('f-callsign') || undefined,
    category:         val('f-category') || undefined,
    start_utc:        val('f-start')    || undefined,
    end_utc:          val('f-end')      || undefined,
    notes:            val('f-notes')    || undefined,
  };
  if (!body.name || !body.contest_type || !body.year) {
    toast('Name, Contest Type, and Year are required.', 'err'); return;
  }
  try {
    const r = await api('/api/contests', { method: 'POST', body });
    toast(`Contest created (id=${r.id})`, 'ok');
    await loadContests();
  } catch (e) {
    toast(e.message, 'err');
  }
};

// ── Lifecycle ────────────────────────────────────────────────────────────────
window.startContest = async function(id) {
  try {
    await api(`/api/contests/${id}/start`, { method: 'POST' });
    toast('Contest is now LIVE. Packets will be captured.', 'ok');
    await loadContests();
  } catch (e) {
    toast(e.message, 'err');
  }
};

window.completeContest = async function(id) {
  const cid = id ?? window._liveContestId;
  if (!cid) { toast('No live contest to complete.', 'err'); return; }
  if (!confirm('Mark this contest as complete? This closes capture and syncs to Supabase.')) return;
  try {
    const r = await api(`/api/contests/${cid}/complete`, { method: 'POST' });
    const rec = r.reconciliation;
    const msg = rec?.status === 'synced'
      ? `Complete ✓ — synced ${rec.local_qsos}/${rec.remote_qsos} QSOs to Supabase.`
      : rec?.status === 'no_mirror'
      ? 'Complete ✓ — no Supabase mirror configured.'
      : `Complete — reconciliation: ${JSON.stringify(rec)}`;
    toast(msg, 'ok');
    el('live-banner').classList.add('hidden');
    await loadContests();
  } catch (e) {
    toast(e.message, 'err');
  }
};

// ── Station setup ────────────────────────────────────────────────────────────
window.addStation = async function() {
  const contestId = val('st-contest');
  if (!contestId) { toast('Select a contest first.', 'err'); return; }
  const body = {
    station_name:   val('st-name'),
    position_label: val('st-label'),
    rig:            val('st-rig')   || undefined,
    antenna:        val('st-ant')   || undefined,
    bands:          val('st-bands') || undefined,
    note:           val('st-note')  || undefined,
  };
  if (!body.station_name || !body.position_label) {
    toast('Station Name and Position Label are required.', 'err'); return;
  }
  try {
    await api(`/api/contests/${contestId}/stations`, { method: 'POST', body });
    toast('Station saved.', 'ok');
  } catch (e) {
    toast(e.message, 'err');
  }
};

// ── Edit contest ────────────────────────────────────────────────────────────
window.editContest = async function(id) {
  let data;
  try {
    data = await api(`/api/contests/${id}`);
  } catch (e) {
    toast(e.message, 'err'); return;
  }
  const c = data.contest;
  // Populate edit modal fields
  el('edit-id').value        = c.id;
  el('e-name').value         = c.name || '';
  el('e-type').value         = c.contest_type || '';
  el('e-year').value         = c.year || '';
  el('e-location').value     = c.location || '';
  el('e-callsign').value     = c.station_callsign || '';
  el('e-category').value     = c.category || '';
  el('e-start').value        = (c.start_utc || '').replace('Z','').slice(0,16);
  el('e-end').value          = (c.end_utc || '').replace('Z','').slice(0,16);
  el('e-notes').value        = c.notes || '';
  el('edit-modal').classList.remove('hidden');
};

window.saveContest = async function() {
  const id = el('edit-id').value;
  const body = {};
  const f = (fld, id_) => { const v = val(id_); if (v) body[fld] = v; };
  f('name', 'e-name');
  f('contest_type', 'e-type');
  const yr = val('e-year');
  if (yr) body.year = parseInt(yr, 10);
  f('location', 'e-location');
  f('station_callsign', 'e-callsign');
  f('category', 'e-category');
  f('start_utc', 'e-start');
  f('end_utc', 'e-end');
  f('notes', 'e-notes');

  try {
    await api(`/api/contests/${id}`, { method: 'PUT', body });
    toast('Contest updated.', 'ok');
    el('edit-modal').classList.add('hidden');
    await loadContests();
  } catch (e) {
    toast(e.message, 'err');
  }
};

window.closeEditModal = function() {
  el('edit-modal').classList.add('hidden');
};

// ── Delete contest ──────────────────────────────────────────────────────────
window.deleteContest = async function(id, name) {
  if (!confirm(`Delete contest "${name}"? This removes ALL contacts, scores, and station data for this contest. This cannot be undone.`)) return;
  try {
    await api(`/api/contests/${id}`, { method: 'DELETE' });
    toast('Contest deleted.', 'ok');
    await loadContests();
  } catch (e) {
    toast(e.message, 'err');
  }
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
function val(id) { return (el(id)?.value ?? '').trim(); }
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (_token) headers['Authorization'] = 'Bearer ' + _token;
  const options = {
    method: opts.method || 'GET',
    headers,
  };
  if (opts.body) options.body = JSON.stringify(opts.body);
  const res = await fetch(path, options);
  if (res.status === 401) {
    // Token expired or invalid — force re-login
    _token = '';
    sessionStorage.removeItem('gccc_admin_token');
    showLogin();
    throw new Error('Session expired — please log in again');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function toast(msg, type = 'ok') {
  const area = el('toast-area');
  const div  = document.createElement('div');
  div.className = `toast toast-${type}`;
  div.textContent = msg;
  area.appendChild(div);
  setTimeout(() => div.remove(), 4000);
}
