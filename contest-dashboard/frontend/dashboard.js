/**
 * GCCC Contest Dashboard — live display logic.
 *
 * Data-source abstraction:
 *   ?source=local  (default) → WebSocket to the Pi's local API
 *   ?source=supabase          → Supabase realtime (for Render deployment)
 *   SUPABASE_URL + SUPABASE_ANON_KEY injected via meta tags when deployed on Render
 *
 * Auto-rotates between war-room view and leaderboard view.
 */

'use strict';

// ── Config ─────────────────────────────────────────────────────────────────
const params        = new URLSearchParams(location.search);
const DATA_SOURCE   = params.get('source') || 'local';
let   rotationMs    = 30_000;   // updated from /api/config
let   rotationTimer = null;
let   currentView   = 'warroom';

// State
let state = {
  contest:   null,
  stats:     null,
  score:     null,
};

// ── Entry point ─────────────────────────────────────────────────────────────
(async function init() {
  try {
    const cfg = await fetch('/api/config').then(r => r.json()).catch(() => ({}));
    if (cfg.rotation_seconds) rotationMs = cfg.rotation_seconds * 1000;
  } catch (_) {}

  if (DATA_SOURCE === 'supabase') {
    initSupabase();
  } else {
    initLocal();
  }

  // Clock
  updateClock();
  setInterval(updateClock, 1000);
})();

// ── Local WebSocket mode ────────────────────────────────────────────────────
function initLocal() {
  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl   = `${wsProto}//${location.host}/ws`;

  function connect() {
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setStatus('Live', 'ok');

    ws.onmessage = ({ data }) => {
      const msg = JSON.parse(data);
      handleMessage(msg);
    };

    ws.onclose = () => {
      setStatus('Reconnecting…', 'err');
      setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  }

  connect();
}

// ── Supabase realtime mode (Render deployment) ──────────────────────────────
function initSupabase() {
  // Expects <meta name="supabase-url"> and <meta name="supabase-anon-key"> in HTML
  const url = document.querySelector('meta[name="supabase-url"]')?.content;
  const key = document.querySelector('meta[name="supabase-anon-key"]')?.content;
  if (!url || !key) {
    setStatus('Supabase not configured', 'err');
    return;
  }
  // Load the Supabase JS client dynamically
  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js';
  script.onload = () => {
    const sb = window.supabase.createClient(url, key);
    loadFromSupabase(sb);
  };
  document.head.appendChild(script);
}

async function loadFromSupabase(sb) {
  // Fetch live contest
  let { data: contests } = await sb.from('contests').select('*').eq('status', 'live').limit(1);
  if (!contests?.length) {
    const { data: recent } = await sb.from('contests').select('*').eq('status', 'complete').order('end_utc', { ascending: false }).limit(1);
    if (!recent?.length) { showIdle(); return; }
    contests = recent;
  }
  const contest = contests[0];

  const [contacts, snapshots] = await Promise.all([
    sb.from('contacts').select('*').eq('contest_id', contest.id).eq('deleted', false),
    sb.from('score_snapshots').select('*').eq('contest_id', contest.id).order('snapshot_utc', { ascending: false }).limit(1),
  ]);

  const stats = computeStatsFromContacts(contacts.data || []);
  handleMessage({ type: 'snapshot', contest, stats, score: snapshots.data?.[0] || null });

  // Subscribe to realtime changes
  sb.channel('contacts').on('postgres_changes', { event: '*', schema: 'public', table: 'contacts',
    filter: `contest_id=eq.${contest.id}` }, async () => {
      const { data } = await sb.from('contacts').select('*').eq('contest_id', contest.id).eq('deleted', false);
      const stats = computeStatsFromContacts(data || []);
      handleMessage({ type: 'stats_update', stats });
  }).subscribe();

  sb.channel('scores').on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'score_snapshots',
    filter: `contest_id=eq.${contest.id}` }, ({ new: row }) => {
      handleMessage({ type: 'score_update', score: row });
  }).subscribe();

  setStatus('Live (remote)', 'ok');
}

function computeStatsFromContacts(contacts) {
  const byBand = {}, byOp = {}, byStation = {};
  let total = 0;
  const cutoff = new Date(Date.now() - 3600_000).toISOString();

  for (const c of contacts) {
    total++;
    const band = c.band || '?';
    if (!byBand[band]) byBand[band] = { band, qsos: 0, pts: 0 };
    byBand[band].qsos++;
    byBand[band].pts += c.points || 0;

    const op = c.operator || '?';
    if (!byOp[op]) byOp[op] = { operator: op, qsos: 0, bands_active: new Set() };
    byOp[op].qsos++;
    byOp[op].bands_active.add(band);

    const key = `${c.station_name}:${c.radio_nr}`;
    if (!byStation[key]) byStation[key] = { station_name: c.station_name, radio_nr: c.radio_nr,
                                              qsos: 0, last_band: band, last_mode: c.mode };
    byStation[key].qsos++;
    byStation[key].last_band = band;
    byStation[key].last_mode = c.mode;
  }

  const rate_1h = contacts.filter(c => c.qso_utc >= cutoff).length;

  return {
    total_qsos: total,
    rate_1h,
    bands:     Object.values(byBand).sort((a,b) => a.band.localeCompare(b.band)),
    operators: Object.values(byOp).map(o => ({ ...o, bands_active: [...o.bands_active].join(',') }))
                     .sort((a,b) => b.qsos - a.qsos),
    stations:  Object.values(byStation),
    op_band:   [],
  };
}

// ── Message handler ─────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {
    case 'snapshot':
      state.contest = msg.contest;
      state.stats   = msg.stats;
      state.score   = msg.score;
      if (state.contest) { showDashboard(); renderAll(); startRotation(); }
      else                { showIdle(); }
      break;

    case 'stats_update':
      state.stats = msg.stats;
      renderStats();
      break;

    case 'score_update':
      state.score = msg.score;
      renderScore();
      break;

    case 'no_live_contest':
      showIdle();
      break;

    case 'contest_started':
    case 'contest_completed':
      // Reload to pick up new contest state
      setTimeout(() => location.reload(), 1500);
      break;
  }
}

// ── View switching ──────────────────────────────────────────────────────────
function showIdle() {
  document.getElementById('screen-idle').classList.remove('hidden');
  document.getElementById('screen-dashboard').classList.add('hidden');
  stopRotation();
}

function showDashboard() {
  document.getElementById('screen-idle').classList.add('hidden');
  document.getElementById('screen-dashboard').classList.remove('hidden');
}

function setView(name) {
  currentView = name;
  document.querySelectorAll('.dash-view').forEach(el => {
    el.classList.toggle('active', el.id === `view-${name}`);
    el.classList.toggle('hidden', el.id !== `view-${name}`);
  });
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === name);
  });
  resetRotationTimer();
}

window.setView = setView;  // expose for onclick

function startRotation() {
  stopRotation();
  rotationTimer = setInterval(() => {
    setView(currentView === 'warroom' ? 'leaderboard' : 'warroom');
  }, rotationMs);
}

function stopRotation() {
  if (rotationTimer) { clearInterval(rotationTimer); rotationTimer = null; }
}

function resetRotationTimer() {
  // When user manually switches, restart the rotation clock
  if (rotationTimer) startRotation();
}

// ── Render functions ────────────────────────────────────────────────────────
function renderAll() {
  renderHeader();
  renderStats();
  renderScore();
}

function renderHeader() {
  const c = state.contest;
  if (!c) return;
  document.getElementById('hdr-contest-name').textContent = c.name || '—';
  document.getElementById('hdr-callsign').textContent     = c.station_callsign || '';
}

function renderStats() {
  const s = state.stats;
  if (!s) return;

  const total = s.total_qsos ?? 0;
  const rate  = s.rate_1h ?? 0;

  document.getElementById('hdr-total-qsos').textContent = fmt(total);
  document.getElementById('hdr-rate').textContent       = fmt(rate);
  document.getElementById('sr-qsos').textContent        = fmt(total);
  document.getElementById('sr-rate').textContent        = fmt(rate);

  renderStations(s.stations || []);
  renderLeaderboard(s.operators || [], s.op_band || []);
  renderTicker(s.recent || []);
  renderDonut('donut-bands', s.bands  || [], 'band', 'qsos');
  renderDonut('donut-modes', s.modes  || [], 'mode', 'qsos');
}

function renderScore() {
  const sc = state.score;
  const score  = sc?.score       ?? sc?.total_qsos ? (sc.total_points * sc.total_mults) : null;
  const mults  = sc?.total_mults ?? sc?.mults  ?? null;
  const pts    = sc?.total_points ?? sc?.points ?? null;
  const qsos   = sc?.total_qsos  ?? sc?.qsos   ?? null;

  setText('hdr-score',  score  != null ? fmt(score)  : '—');
  setText('sr-score',   score  != null ? fmt(score)  : '—');
  setText('sr-mults',   mults  != null ? fmt(mults)  : '—');
  setText('sr-points',  pts    != null ? fmt(pts)    : '—');
  if (qsos != null) setText('sr-qsos', fmt(qsos));
}

function renderBands(bands) {
  const grid = document.getElementById('band-grid');
  if (!bands.length) { grid.innerHTML = '<p style="color:var(--dash-text-sub);font-size:0.85rem">No QSOs yet</p>'; return; }

  const maxQsos = Math.max(...bands.map(b => b.qsos), 1);
  grid.innerHTML = bands.map(b => {
    const pct = Math.round((b.qsos / maxQsos) * 100);
    return `<div class="band-row">
      <span class="band-label">${esc(b.band)}</span>
      <div class="band-bar-wrap"><div class="band-bar" style="width:${pct}%"></div></div>
      <span class="band-count">${fmt(b.qsos)}</span>
    </div>`;
  }).join('');
}

function renderStations(stations) {
  const list = document.getElementById('station-list');
  if (!stations.length) { list.innerHTML = '<p style="color:var(--dash-text-sub);font-size:0.85rem">No stations yet</p>'; return; }

  list.innerHTML = stations.map(st => {
    const label = st.station_name ? `${st.station_name}${st.radio_nr > 1 ? ` R${st.radio_nr}` : ''}` : '?';
    const band  = st.last_band || '—';
    const mode  = st.last_mode || '—';
    return `<div class="station-card active-run">
      <div>
        <div class="station-name">${esc(label)}</div>
        <div class="station-mode-band">${esc(band)} · ${esc(mode)}</div>
      </div>
      <div>
        <div class="station-qsos">${fmt(st.qsos)}</div>
        <div class="station-rate">QSOs</div>
      </div>
    </div>`;
  }).join('');
}

function renderLeaderboard(operators, opBand) {
  const tbody = document.getElementById('lb-body');
  const total = state.stats?.total_qsos ?? 0;
  document.getElementById('lb-subtitle').textContent =
    `${fmt(total)} total QSOs · ${operators.length} operator${operators.length !== 1 ? 's' : ''}`;

  // Build per-op per-band lookup
  const obMap = {};
  for (const row of opBand) {
    if (!obMap[row.operator]) obMap[row.operator] = {};
    obMap[row.operator][row.band] = row.qsos;
  }

  renderDonut('donut-operators', operators, 'operator', 'qsos');

  tbody.innerHTML = operators.map((op, i) => {
    const rank = i + 1;
    const rankClass = rank <= 3 ? `rank-${rank}` : '';
    const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : rank;
    const bands = (op.bands_active || '').split(',').filter(Boolean);
    const bb = bands.map(b => {
      const n = obMap[op.operator]?.[b] ?? op.qsos;
      return `<span>${esc(b)} <span class="bb-val">${n}</span></span>`;
    }).join('');

    return `<tr class="${rankClass}">
      <td class="lb-rank">${medal}</td>
      <td class="lb-op">${esc(op.operator || '?')}</td>
      <td class="lb-qsos">${fmt(op.qsos)}</td>
    </tr>`;
  }).join('');
}

// ── Chart palette ───────────────────────────────────────────────────────────
const CHART_COLORS = [
  '#2d8a58','#4ab87a','#e8c040','#4a9edd','#e05050',
  '#9b59b6','#e67e22','#1abc9c','#c0392b','#2980b9',
];

function renderDonut(containerId, data, labelKey, valueKey) {
  const wrap = document.getElementById(containerId);
  if (!wrap) return;
  if (!data.length) { wrap.innerHTML = '<span style="color:var(--dash-text-sub);font-size:0.8rem">No data</span>'; return; }

  const total = data.reduce((s, d) => s + (d[valueKey] || 0), 0);
  if (!total) { wrap.innerHTML = '<span style="color:var(--dash-text-sub);font-size:0.8rem">No data</span>'; return; }

  // Fixed logical coordinate space; CSS scales the SVG via donut-circle-wrap
  const V = 200, cx = 100, cy = 100, r = 76, inner = 44;
  let angle = -Math.PI / 2;
  let paths = '';

  data.forEach((d, i) => {
    const slice = (d[valueKey] / total) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    angle += slice;
    const x2 = cx + r * Math.cos(angle);
    const y2 = cy + r * Math.sin(angle);
    const xi1 = cx + inner * Math.cos(angle - slice);
    const yi1 = cy + inner * Math.sin(angle - slice);
    const xi2 = cx + inner * Math.cos(angle);
    const yi2 = cy + inner * Math.sin(angle);
    const large = slice > Math.PI ? 1 : 0;
    const color = CHART_COLORS[i % CHART_COLORS.length];
    paths += `<path d="M${xi1},${yi1} L${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} L${xi2},${yi2} A${inner},${inner} 0 ${large},0 ${xi1},${yi1} Z" fill="${color}" opacity="0.9"/>`;
  });

  const legend = data.map((d, i) => {
    const color = CHART_COLORS[i % CHART_COLORS.length];
    const pct = Math.round((d[valueKey] / total) * 100);
    return `<div class="donut-legend-item">
      <span class="donut-swatch" style="background:${color}"></span>
      <span class="donut-legend-label">${esc(String(d[labelKey] || '?'))}</span>
      <span class="donut-legend-val">${d[valueKey]} (${pct}%)</span>
    </div>`;
  }).join('');

  wrap.innerHTML = `
    <div class="donut-circle-wrap">
      <svg viewBox="0 0 ${V} ${V}" preserveAspectRatio="xMidYMid meet">${paths}
        <text x="${cx}" y="${cy + 8}" text-anchor="middle" fill="#e8f5ed" font-size="22" font-weight="700" font-family="Barlow Condensed,sans-serif">${total}</text>
      </svg>
    </div>
    <div class="donut-legend">${legend}</div>`;
}


function renderTicker(recent) {
  const track = document.getElementById('ticker-track');
  if (!track) return;
  if (!recent.length) {
    track.innerHTML = '<span class="ticker-item"><span class="ti-op">No contacts yet</span></span>';
    track.style.animation = 'none';
    return;
  }

  // Build items; duplicate for seamless loop
  const items = recent.map(r => {
    const call = esc(r.call || '?');
    const op   = r.operator ? esc(r.operator) : '';
    const band = esc(r.band || '?');
    const mode = esc(r.mode || '?');
    return `<span class="ticker-item">
      <span class="ti-call">${call}</span>
      ${op ? `<span class="ti-sep">·</span><span class="ti-op">${op}</span>` : ''}
      <span class="ti-sep">·</span>
      <span class="ti-band">${band}</span>
      <span class="ti-mode">${mode}</span>
    </span>`;
  }).join('');

  track.innerHTML = items + items;  // duplicate for seamless loop
  track.style.animation = '';
}

// ── Utilities ───────────────────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function fmt(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function setStatus(msg, cls) {
  const el = document.getElementById('footer-status');
  if (!el) return;
  el.textContent = msg;
  el.className = `footer-status ${cls || ''}`;
}

function updateClock() {
  const now = new Date();
  const utc = now.toUTCString().match(/(\d{2}:\d{2})/);
  setText('hdr-time', utc ? utc[1] : '--:--');
}
