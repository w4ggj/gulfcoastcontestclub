'use strict';

const API = '';   // same-origin; relative URLs

// ── Boot ────────────────────────────────────────────────────────────────────
(async function init() {
  await loadContests();
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
    if (c.status === 'draft') {
      actions.push(`<button class="btn btn-success btn-sm" onclick="startContest(${c.id})">Start</button>`);
    }
    if (c.status === 'live') {
      actions.push(`<button class="btn btn-danger btn-sm" onclick="completeContest(${c.id})">Complete</button>`);
    }
    return `<div class="contest-item">
      <div class="contest-item-info">
        <span class="contest-item-name">${esc(c.name)}</span>
        <span class="contest-item-meta">${c.year} · ${esc(c.location || '')} · ${esc(c.station_callsign || '')} · ${esc(c.category || '')}</span>
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

// ── Helpers ──────────────────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
function val(id) { return (el(id)?.value ?? '').trim(); }
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function api(path, opts = {}) {
  const options = {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
  };
  if (opts.body) options.body = JSON.stringify(opts.body);
  const res = await fetch(path, options);
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
