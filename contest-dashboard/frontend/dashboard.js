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
      if (currentView === 'map' && state.contest) loadAndRenderDashMap();
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
    const active = el.id === `view-${name}`;
    el.classList.toggle('active', active);
    el.classList.toggle('hidden', !active);
  });
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === name);
  });
  if (name === 'map' && state.contest) loadAndRenderDashMap();
  resetRotationTimer();
}

window.setView = setView;  // expose for onclick

const ROTATION_VIEWS = ['warroom', 'leaderboard', 'map'];

function startRotation() {
  stopRotation();
  rotationTimer = setInterval(() => {
    const idx = ROTATION_VIEWS.indexOf(currentView);
    setView(ROTATION_VIEWS[(idx + 1) % ROTATION_VIEWS.length]);
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
  const qsoScore = sc?.score ?? (sc?.total_points && sc?.total_mults ? sc.total_points * sc.total_mults : null);
  const mults    = sc?.total_mults ?? sc?.mults  ?? null;
  const pts      = sc?.total_points ?? sc?.points ?? null;
  const qsos     = sc?.total_qsos  ?? sc?.qsos   ?? null;
  const bonus    = sc?.bonus_points ?? 0;
  const total    = qsoScore != null ? qsoScore + bonus : null;

  setText('hdr-score',  total    != null ? fmt(total)    : '—');
  setText('sr-total',   total    != null ? fmt(total)    : '—');
  setText('sr-score',   qsoScore != null ? fmt(qsoScore) : '—');
  setText('sr-bonus',   fmt(bonus));
  setText('sr-mults',   mults    != null ? fmt(mults)    : '—');
  setText('sr-points',  pts      != null ? fmt(pts)      : '—');
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

// ── Contact Map ─────────────────────────────────────────────────────────────

const HOME_LAT = 27.81, HOME_LON = -82.71;

const BAND_COLORS = {
  '160m':'#9b59b6','80m':'#e67e22','40m':'#e8c040',
  '20m':'#4ab87a','15m':'#4a9edd','10m':'#e05050',
  '6m':'#1abc9c','2m':'#c0392b',
};
const BAND_ORDER = ['160m','80m','40m','20m','15m','10m','6m','2m'];

const PREFIX_COORDS = {
  'W1':[43.5,-72],'K1':[43.5,-72],'N1':[43.5,-72],
  'W2':[40.7,-74],'K2':[40.7,-74],'N2':[40.7,-74],
  'W3':[39.9,-76],'K3':[39.9,-76],'N3':[39.9,-76],
  'W4':[33,-84],'K4':[33,-84],'N4':[33,-84],
  'W5':[31,-98],'K5':[31,-98],'N5':[31,-98],
  'W6':[37,-120],'K6':[37,-120],'N6':[37,-120],
  'W7':[45,-114],'K7':[45,-114],'N7':[45,-114],
  'W8':[42,-83],'K8':[42,-83],'N8':[42,-83],
  'W9':[41.5,-87.6],'K9':[41.5,-87.6],'N9':[41.5,-87.6],
  'W0':[39,-95],'K0':[39,-95],'N0':[39,-95],
  'KL7':[64,-153],'AL7':[64,-153],'NL7':[64,-153],'WL7':[64,-153],
  'KH6':[20.5,-157],'AH6':[20.5,-157],'NH6':[20.5,-157],'WH6':[20.5,-157],
  'KH2':[13.5,144.8],'KH0':[15.2,145.8],'KH8':[-14.3,-170.7],
  'KP4':[18.2,-66.5],'KP2':[17.7,-64.8],
  'VE1':[45.5,-63],'VA1':[45.5,-63],'VE2':[48,-72],'VA2':[48,-72],
  'VE3':[44,-80],'VA3':[44,-80],'VE4':[50,-97],'VE5':[52,-106],
  'VE6':[53,-114],'VA6':[53,-114],'VE7':[50,-123],'VA7':[50,-123],
  'VE8':[62,-110],'VE9':[46.5,-66.5],'VY1':[63,-136],'VY2':[46.2,-63.1],
  'XE':[23,-102],'TI':[9.9,-84.1],'HP':[9,-80],'TG':[15.5,-90.3],
  'HQ':[15,-86.5],'YS':[13.7,-89.1],
  'CO':[22,-79.5],'CM':[22,-79.5],'HI':[18.8,-70.2],'HH':[18.9,-72.3],
  'VP9':[32.3,-64.8],'ZF':[19.3,-81.4],'8P':[13.2,-59.6],
  'J3':[12,-61.7],'J7':[15.3,-61.4],'J8':[13.2,-61.2],'J6':[13.9,-61],
  'PY':[-15,-53],'PP':[-10,-53],'PQ':[-15,-53],'PR':[-15,-53],'PS':[-15,-53],'PT':[-15,-53],'PU':[-15,-53],'PV':[-15,-53],'PW':[-15,-53],'PX':[-15,-53],
  'LU':[-34,-64],'CE':[-33,-71],'OA':[-12,-77],'HC':[-2,-78],
  'HK':[4,-74],'YV':[8,-66],'ZP':[-23,-58],'CX':[-34,-56],'CP':[-17,-65],
  'G':[52,-1],'M':[52,-1],'GX':[52,-1],'2E':[52,-1],
  'GI':[54.6,-6.3],'MI':[54.6,-6.3],'GW':[52.1,-3.7],'MW':[52.1,-3.7],
  'GM':[57,-4],'MM':[57,-4],
  'EI':[53.1,-8],
  'DL':[51,10],'DM':[51,10],'DN':[51,10],'DP':[51,10],'DQ':[51,10],'DR':[51,10],
  'F':[46.6,2.3],
  'I':[42.8,12.6],
  'EA':[40.4,-3.7],
  'PA':[52.1,5.3],'PD':[52.1,5.3],'PE':[52.1,5.3],'PH':[52.1,5.3],
  'SM':[60,15],'SA':[60,15],'SB':[60,15],'SC':[60,15],'SD':[60,15],'SE':[60,15],
  'OH':[64,25],'OG':[64,25],
  'LA':[60,9],'LB':[60,9],'LC':[60,9],
  'OZ':[56,10],'OV':[56,10],'OW':[56,10],
  'OX':[71.7,-42.6],
  'SP':[52,20],'SN':[52,20],'SO':[52,20],'SQ':[52,20],'SR':[52,20],
  'OK':[50.1,14.4],'OL':[50.1,14.4],
  'OM':[48.7,19.7],
  'HA':[47,19],'HG':[47,19],
  'YO':[45.9,24.9],'YP':[45.9,24.9],'YQ':[45.9,24.9],'YR':[45.9,24.9],
  'LZ':[42.7,25.5],
  'SV':[37.9,23.7],'SX':[37.9,23.7],'J4':[37.9,23.7],
  'SV5':[36.4,28.2],'SV9':[35.3,25.1],
  'OE':[48.2,16.4],
  'HB9':[47,8.3],'HB0':[47.1,9.5],
  'ON':[50.5,4.5],'OO':[50.5,4.5],'OP':[50.5,4.5],'OR':[50.5,4.5],'OS':[50.5,4.5],
  'LX':[49.8,6.1],
  'TK':[42,9],'IS':[40,9],
  'IT9':[37.5,14],
  'YU':[44.8,20.5],'YT':[44.8,20.5],
  'S5':[46,15],'E7':[43.8,17.5],'9A':[45.1,15.2],
  'Z3':[41.6,21.7],'ZA':[41.3,19.8],'4O':[42.4,19.3],'Z6':[42.7,21.2],
  'YL':[56.9,24.1],'LY':[54.7,25.3],'ES':[59.4,24.8],
  'TA':[39,35],'TC':[39,35],
  'OD':[33.9,35.5],'4X':[31.8,34.8],'4Z':[31.8,34.8],
  '5B':[35,33.2],
  'UR':[49,31],'US':[49,31],'UT':[49,31],'UU':[49,31],'UV':[49,31],
  'UW':[49,31],'UX':[49,31],'UY':[49,31],'UZ':[49,31],
  'EM':[49,31],'EN':[49,31],'EO':[49,31],
  'EW':[53.9,27.6],'EU':[54,28],
  'UA9':[56,60],'UA0':[55,95],
  'UA':[55.8,37.6],'RA':[55.8,37.6],'RK':[55.8,37.6],'RM':[55.8,37.6],
  'RN':[55.8,37.6],'RO':[55.8,37.6],'RU':[55.8,37.6],'RV':[55.8,37.6],
  'RW':[55.8,37.6],'RX':[55.8,37.6],'RY':[55.8,37.6],'RZ':[55.8,37.6],
  '4L':[41.7,44.8],'EK':[40.2,44.5],'4J':[40.4,49.9],'4K':[40.4,49.9],
  'EP':[32.5,54],'EQ':[32.5,54],
  'A4':[23.6,58.6],'A7':[25.3,51.2],'A6':[24.5,54.4],
  '9K':[29.4,47.6],'YI':[33.3,44.4],'HZ':[24,45],'7Z':[24,45],
  'JY':[31.9,35.9],'YK':[34.8,38.9],
  'UN':[48,67],'UK':[41,65],'EY':[39,71],
  'ZS':[-29,25],'ZR':[-29,25],'ZT':[-29,25],'ZU':[-29,25],
  'EA8':[28.1,-15.4],'CT3':[32.7,-16.9],
  'SU':[26.8,30.8],'CN':[33.8,-7],'7X':[28.2,2.6],
  'TS':[33.9,9.6],'5A':[32.9,13.2],
  'ST':[15.5,32.5],'SS':[15.5,32.5],
  '5Z':[-1.3,36.8],'9L':[8.5,-13.2],'9G':[7.9,-1.2],'5N':[9.1,8.7],
  'EL':[6.4,-9.4],'TU':[5.4,-4],
  'ZD8':[-7.9,-14.4],'ZD7':[-15.9,-5.7],
  'D2':[-11.2,17.9],'9J':[-13.1,27.9],'Z2':[-20,30],
  'V5':[-22.6,17.1],'A2':[-22,24.7],'C9':[-18.7,35.5],
  '5R':[-18.9,47.5],'VQ9':[-7.3,72.4],
  'JA':[36,138],'JD':[24,141],
  'HL':[37.6,127],'DS':[37.6,127],'DT':[37.6,127],
  'BY':[35,105],'BA':[35,105],'BD':[35,105],'BG':[35,105],'BH':[35,105],
  'BI':[35,105],'BJ':[35,105],'BL':[35,105],'BT':[35,105],
  'BV':[25,121],'BU':[25,121],'BW':[25,121],'BX':[25,121],
  'VU':[20.5,78.9],'AT':[20.5,78.9],'AU':[20.5,78.9],
  'AP':[30.4,69.3],'4S':[7.9,80.7],
  'S2':[23.7,90.4],'S3':[23.7,90.4],
  '9N':[28,84.1],'A5':[27.5,90.4],
  'XV':[16,108],'XU':[11.6,104.9],'XW':[17.9,102.6],
  'HS':[15.9,100.6],'XZ':[20,96],
  '9M2':[3.1,101.7],'9M6':[5.4,115.2],'9W':[3,113],
  'YB':[-6,106.8],'YC':[-6,106.8],'YD':[-6,106.8],
  'DU':[12.9,121.7],'DV':[12.9,121.7],'DW':[12.9,121.7],'DX':[12.9,121.7],
  '9V':[1.4,103.8],'VR':[22.3,114.2],
  'VK':[-25,133],'ZL':[-41.3,174.8],
  'YJ':[-17.7,168.3],'FO':[-17.5,-149.6],
  'T8':[7,134],'V6':[6.9,158.2],
  'CU':[38.5,-28.6],'EA9':[35.9,-5.4],
  'VP8':[-51.7,-57.9],
  '9H':[35.9,14.5],
};

function lookupCallsign(call) {
  if (!call) return null;
  call = call.toUpperCase().replace(/\/\S+$/, '').trim();
  for (let l = Math.min(4, call.length); l >= 1; l--) {
    const c = PREFIX_COORDS[call.slice(0, l)];
    if (c) return c;
  }
  // US callsigns with 2-letter prefixes (KA-KZ, WA-WZ, NA-NZ, AA-AZ):
  // extract the district digit and map to the corresponding call area
  if (/^[KWNA][A-Z]/.test(call)) {
    const m = call.match(/^[A-Z]+(\d)/);
    if (m) return PREFIX_COORDS['W' + m[1]] || null;
  }
  return null;
}

let _worldCache = null;
async function getWorld() {
  if (_worldCache) return _worldCache;
  _worldCache = await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json').then(r => r.json());
  return _worldCache;
}

async function loadAndRenderDashMap() {
  const contestId = state.contest?.id;
  if (!contestId) return;

  let contacts;
  try {
    contacts = await fetch(`/api/contests/${contestId}/contacts`).then(r => r.json());
  } catch(e) {
    return;
  }

  const total = contacts.length;
  const sub = document.getElementById('map-view-sub');
  if (sub) sub.textContent = `${total.toLocaleString()} QSO${total !== 1 ? 's' : ''}`;

  const container = document.getElementById('dash-map-wrap');
  const legendEl  = document.getElementById('dash-map-legend');
  await renderDashMap(container, contacts, legendEl);
}

async function renderDashMap(container, contacts, legendEl) {
  if (!container) return;
  container.innerHTML = '<div style="padding:2rem;text-align:center;color:var(--dash-text-sub);font-size:0.9rem;">Loading map…</div>';

  let world;
  try { world = await getWorld(); }
  catch(e) {
    container.innerHTML = '<div style="padding:2rem;text-align:center;color:var(--dash-text-sub);">Map unavailable (no network)</div>';
    return;
  }

  container.innerHTML = '';
  const W = container.clientWidth  || 900;
  const H = container.clientHeight || Math.round(W * 0.5);

  const svg = d3.select(container).append('svg')
    .attr('viewBox', `0 0 ${W} ${H}`)
    .attr('width', '100%').attr('height', '100%');

  const proj = d3.geoNaturalEarth1().scale(W / 6.3).translate([W / 2, H / 2]);
  const path = d3.geoPath().projection(proj);

  // Dark ocean background
  svg.append('rect').attr('width', W).attr('height', H).attr('fill', '#071620');

  // Land (dark forest green)
  const land = topojson.feature(world, world.objects.countries);
  svg.append('g').selectAll('path').data(land.features).join('path')
    .attr('d', path).attr('fill', '#1a3825').attr('stroke', '#2a5535').attr('stroke-width', 0.4);

  // Graticule
  svg.append('path').datum(d3.geoGraticule()())
    .attr('d', path).attr('fill', 'none')
    .attr('stroke', 'rgba(255,255,255,0.07)').attr('stroke-width', 0.3);

  // Build unique entity map
  const entities = {};
  contacts.forEach(c => {
    if (!c.call) return;
    const coords = lookupCallsign(c.call);
    if (!coords) return;
    const band = c.band || '20m';
    const key  = c.call.slice(0, 4) + '|' + band;
    if (!entities[key]) entities[key] = { call: c.call, coords, band, count: 0 };
    entities[key].count++;
  });

  const gLines = svg.append('g');
  const gDots  = svg.append('g');
  const bandsUsed = new Set();

  Object.values(entities).forEach(({ call, coords, band, count }) => {
    const [lat, lon] = coords;
    const destPt = proj([lon, lat]);
    if (!destPt) return;
    const color = BAND_COLORS[band] || '#2d8a58';
    bandsUsed.add(band);

    gLines.append('path')
      .datum({ type: 'Feature', geometry: { type: 'LineString',
        coordinates: [[HOME_LON, HOME_LAT], [lon, lat]] }})
      .attr('d', path).attr('fill', 'none')
      .attr('stroke', color).attr('stroke-width', 1.2).attr('stroke-opacity', 0.5);

    gDots.append('circle')
      .attr('cx', destPt[0]).attr('cy', destPt[1]).attr('r', 4)
      .attr('fill', color).attr('stroke', 'rgba(0,0,0,0.6)').attr('stroke-width', 0.8)
      .append('title').text(`${call} · ${band} · ${count} QSO${count > 1 ? 's' : ''}`);
  });

  // Home station marker
  const homePt = proj([HOME_LON, HOME_LAT]);
  if (homePt) {
    svg.append('circle').attr('cx', homePt[0]).attr('cy', homePt[1]).attr('r', 7)
      .attr('fill', '#c0392b').attr('stroke', '#fff').attr('stroke-width', 1.5);
    svg.append('circle').attr('cx', homePt[0]).attr('cy', homePt[1]).attr('r', 3)
      .attr('fill', '#fff');
  }

  if (legendEl) {
    legendEl.innerHTML = BAND_ORDER
      .filter(b => bandsUsed.has(b))
      .map(b => `<span class="dash-map-legend-item"><span class="dash-map-legend-dot" style="background:${BAND_COLORS[b]}"></span>${b}</span>`)
      .join('') +
      `<span class="dash-map-legend-item" style="margin-left:auto;">
        <span class="dash-map-legend-dot" style="background:#c0392b;border:1.5px solid #fff;box-sizing:border-box;"></span>Home (W4GGJ)
      </span>`;
  }
}
