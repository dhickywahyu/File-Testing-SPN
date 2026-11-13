/* Locker Cell Tester — logika UI. Mengambil status dari /api/state tiap 250 ms. */
'use strict';

const POLL_MS = 250;

const ICON = {
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  unlock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
  bulb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/></svg>',
  doorOpen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V3h9"/><path d="M14 3v18l6-2V5z"/><path d="M17 12h.01"/></svg>',
  doorClosed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V3h14v18"/><path d="M15 12h.01"/></svg>',
};

const TEST_BADGE = {
  idle: ['BELUM DITES', ''],
  running: ['SEDANG DITES', 'running'],
  pass: ['LULUS', 'pass'],
  fail: ['GAGAL', 'fail'],
};

const LINK_TEXT = {
  online: 'ESP32 ONLINE',
  connecting: 'MENGHUBUNGKAN…',
  offline: 'ESP32 OFFLINE',
  error: 'PORT ERROR',
};

const $ = (id) => document.getElementById(id);
const grid = $('grid');
const cells = {};            // referensi elemen per cell
let numCells = 0;
let lastEventId = -1;
let latest = null;

/* ------------------------------------------------------------ util */
function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}
function setHtml(el, html) {
  if (el._html !== html) { el.innerHTML = html; el._html = html; }
}
function pad(n) { return String(n).padStart(2, '0'); }
function hms(date) { return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`; }
function fmtUptime(s) {
  if (s == null) return '—';
  const d = Math.floor(s / 86400);
  const rest = `${pad(Math.floor(s / 3600) % 24)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
  return d ? `${d} hari ${rest}` : rest;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(message, kind = 'ok') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  $('toasts').appendChild(el);
  setTimeout(() => el.classList.add('hide'), 2600);
  setTimeout(() => el.remove(), 3000);
  const all = $('toasts').children;
  while (all.length > 4) all[0].remove();
}

async function api(url, body) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    return await res.json();
  } catch (err) {
    return { ok: false, message: 'Server lokal tidak merespon' };
  }
}

/* ------------------------------------------------------------ cell */
function cellTemplate(id) {
  const no = pad(id);
  return `
    <div class="cell-top">
      <span class="cell-no"><small>CELL</small>${no}</span>
      <span class="badge">BELUM DITES</span>
    </div>
    <div class="bay">
      <div class="bay-inside"><div class="led-strip"></div></div>
      <div class="door">
        <div class="door-vents"><i></i><i></i><i></i></div>
        <span class="door-no">${no}</span>
        <span class="door-lock">${ICON.lock}</span>
        <span class="door-handle"></span>
      </div>
    </div>
    <div class="sol-bar"><span></span></div>
    <div class="door-state unknown"><span class="ds-icon">${ICON.doorClosed}</span><span class="ds-text">—</span><span class="open-count"></span></div>
    <div class="io">
      <div class="io-item io-led">${ICON.bulb}<div class="t"><small>LED</small><b>OFF</b></div></div>
      <div class="io-item io-sol">${ICON.bolt}<div class="t"><small>Solenoid</small><b>OFF</b></div></div>
    </div>
    <div class="steps">${'<i></i>'.repeat(6)}</div>
    <p class="test-msg">Belum dites</p>
    <button class="btn-open" type="button">${ICON.unlock}<span>BUKA</span></button>
    <button class="btn-sim" type="button">⇄ Pintu (simulasi)</button>`;
}

function buildCells(n) {
  numCells = n;
  grid.innerHTML = '';
  grid.style.gridTemplateColumns = `repeat(${Math.max(1, Math.ceil(n / 2))}, minmax(0, 1fr))`;
  for (let id = 1; id <= n; id++) {
    const el = document.createElement('article');
    el.className = 'cell stale';
    el.innerHTML = cellTemplate(id);
    grid.appendChild(el);
    const q = (sel) => el.querySelector(sel);
    const ref = {
      el,
      badge: q('.badge'),
      lock: q('.door-lock'),
      bar: q('.sol-bar span'),
      doorState: q('.door-state'),
      dsIcon: q('.ds-icon'),
      dsText: q('.ds-text'),
      openCount: q('.open-count'),
      led: q('.io-led b'),
      sol: q('.io-sol b'),
      steps: [...el.querySelectorAll('.steps i')],
      msg: q('.test-msg'),
      btn: q('.btn-open'),
      btnLabel: q('.btn-open span'),
      prevSol: false,
    };
    ref.btn.addEventListener('click', () => openCell(id));
    q('.btn-sim').addEventListener('click', async () => {
      const r = await api('/api/sim/door', { cell: id });
      toast(r.message, r.ok ? 'ok' : 'err');
    });
    cells[id] = ref;
  }
}

function renderCell(c, s) {
  const r = cells[c.id];
  if (!r) return;
  const el = r.el;
  const online = s.link.online;
  const isOpen = c.door === 'open';
  const queued = c.queued || c.pending === 'queued';

  el.classList.toggle('is-open', isOpen);
  el.classList.toggle('led-on', !!c.led);
  el.classList.toggle('sol-on', !!c.solenoid);
  el.classList.toggle('is-queued', queued && !c.solenoid);
  el.classList.toggle('stale', !!c.stale);
  el.classList.toggle('test-pass', c.test.state === 'pass');
  el.classList.toggle('test-fail', c.test.state === 'fail');

  // progres pulse solenoid: mulai ulang animasi di tepi naik
  if (c.solenoid && !r.prevSol) {
    el.classList.remove('sol-anim');
    void r.bar.offsetWidth;
    el.classList.add('sol-anim');
  }
  r.prevSol = !!c.solenoid;

  setHtml(r.lock, (c.solenoid || isOpen) ? ICON.unlock : ICON.lock);

  const doorKind = c.door === 'unknown' ? 'unknown' : c.door;
  r.doorState.className = `door-state ${doorKind}`;
  setHtml(r.dsIcon, isOpen ? ICON.doorOpen : ICON.doorClosed);
  setText(r.dsText, c.door === 'open' ? 'TERBUKA' : c.door === 'closed' ? 'TERTUTUP' : '—');
  setText(r.openCount, c.open_count ? `dibuka ${c.open_count}×` : '');

  setText(r.led, c.led ? 'ON' : 'OFF');
  setText(r.sol, c.solenoid ? 'AKTIF' : queued ? 'ANTRE' : 'OFF');

  const [badgeText, badgeCls] = TEST_BADGE[c.test.state] || TEST_BADGE.idle;
  setText(r.badge, badgeText);
  r.badge.className = `badge ${badgeCls}`;
  let curMarked = false;
  c.test.steps.forEach((done, k) => {
    let cls = '';
    if (done) cls = 'done';
    else if (c.test.state === 'running' && !curMarked) { cls = 'cur'; curMarked = true; }
    else if (c.test.state === 'fail' && !curMarked) { cls = 'fail'; curMarked = true; }
    if (r.steps[k].className !== cls) r.steps[k].className = cls;
    r.steps[k].title = s.test_steps ? s.test_steps[k] : '';
  });
  setText(r.msg, c.test.msg);
  r.msg.title = c.test.msg;

  let label = 'BUKA';
  if (c.pending === 'sending') label = 'MENGIRIM…';
  else if (c.solenoid) label = 'MEMBUKA…';
  else if (queued) label = 'ANTRE…';
  setText(r.btnLabel, label);
  r.btn.disabled = !online || c.stale || !!c.solenoid || queued || !!c.pending;
}

async function openCell(id) {
  const r = cells[id];
  r.btn.disabled = true;
  setText(r.btnLabel, 'MENGIRIM…');
  const res = await api('/api/open', { cell: id });
  toast(res.message, res.ok ? 'ok' : 'err');
}

/* ------------------------------------------------------------ render global */
function renderLink(s) {
  const l = s.link;
  const link = $('link');
  link.className = `link ${l.state}`;
  setText($('linkTitle'), LINK_TEXT[l.state] || l.state.toUpperCase());
  const parts = [l.port, `${l.baudrate} bps`];
  if (l.online && l.rtt_ms != null) parts.push(`${Math.round(l.rtt_ms)} ms`);
  setText($('linkSub'), parts.join(' · '));

  const banner = $('banner');
  banner.classList.toggle('show', !l.online);
  banner.classList.toggle('info', l.state === 'connecting');
  setText($('bannerText'), l.state === 'connecting'
    ? 'Menghubungi ESP32 lewat RS485…'
    : (l.error || 'ESP32 tidak terhubung'));

  setText($('commAddr'), `alamat ${pad(l.address)}`);
  setText($('kvPort'), l.port);
  setText($('kvBaud'), `${l.baudrate} bps`);
  setText($('kvFw'), l.fw ? `v${l.fw}` : '—');
  setText($('kvUptime'), fmtUptime(l.uptime_s));
  setText($('kvRtt'), l.rtt_ms != null ? `${l.rtt_ms} ms` : '—');
  setText($('kvTxRx'), `${l.tx} / ${l.rx}`);
  setText($('kvTimeout'), String(l.timeouts));
  setText($('kvCrc'), String(l.crc_errors));
  $('kvTimeout').classList.toggle('bad', l.timeouts > 0);
  $('kvCrc').classList.toggle('bad', l.crc_errors > 0);
}

function renderSummary(s) {
  const n = s.num_cells;
  const sum = s.summary;
  setHtml($('sumOpen'), `${sum.open}<small>/${n}</small>`);
  setText($('sumLed'), String(sum.led_on));
  setHtml($('sumSol'), sum.queued ? `${sum.solenoid_on}<small> +${sum.queued} antre</small>` : String(sum.solenoid_on));
  setHtml($('sumPass'), `${sum.test_pass}<small>/${n}</small>`);
  setText($('sumPassK'), sum.test_fail ? `Lulus · ${sum.test_fail} gagal` : 'Test lulus');
  $('btnAll').disabled = !s.link.online;
}

function renderEvents(s) {
  const evs = s.events;
  const newest = evs.length ? evs[evs.length - 1].id : 0;
  if (newest === lastEventId) return;
  lastEventId = newest;
  $('log').innerHTML = evs.slice().reverse().map((e) =>
    `<li class="ev ${e.level}"><time>${hms(new Date(e.t * 1000))}</time><i></i><span>${escapeHtml(e.msg)}</span></li>`
  ).join('');
  setText($('logCount'), `${evs.length} terbaru`);
}

function render(s) {
  latest = s;
  if (s.num_cells !== numCells) buildCells(s.num_cells);
  document.body.classList.toggle('sim', !!s.simulation);
  $('simBadge').classList.toggle('show', !!s.simulation);
  document.documentElement.style.setProperty('--pulse', `${s.solenoid_pulse_ms || 1000}ms`);
  renderLink(s);
  s.cells.forEach((c) => renderCell(c, s));
  renderSummary(s);
  renderEvents(s);
  setText($('modalText'), `Semua ${s.num_cells} cell akan dibuka satu per satu (±${((s.solenoid_pulse_ms || 1000) / 1000).toFixed(0)} detik per cell). Pastikan area di depan pintu aman.`);
}

/* ------------------------------------------------------------ polling */
let serverDown = false;
async function poll() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status);
    render(await res.json());
    if (serverDown) toast('Server lokal kembali terhubung', 'ok');
    serverDown = false;
  } catch (err) {
    if (!serverDown) {
      serverDown = true;
      const banner = $('banner');
      banner.classList.add('show');
      banner.classList.remove('info');
      setText($('bannerText'), 'Server lokal (app.py) tidak merespon — pastikan program berjalan');
      $('link').className = 'link error';
      setText($('linkTitle'), 'SERVER MATI');
      Object.values(cells).forEach((r) => { r.el.classList.add('stale'); r.btn.disabled = true; });
      $('btnAll').disabled = true;
    }
  } finally {
    setTimeout(poll, serverDown ? 1000 : POLL_MS);
  }
}

/* ------------------------------------------------------------ kontrol */
function showModal(show) { $('modal').classList.toggle('show', show); }

$('btnAll').addEventListener('click', () => showModal(true));
$('modalCancel').addEventListener('click', () => showModal(false));
$('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') showModal(false); });
$('modalOk').addEventListener('click', async () => {
  showModal(false);
  const r = await api('/api/open_all');
  toast(r.message, r.ok ? 'ok' : 'err');
});
$('btnStop').addEventListener('click', async () => {
  const r = await api('/api/stop');
  toast(r.ok ? 'STOP dikirim — semua solenoid dimatikan' : r.message, r.ok ? 'ok' : 'err');
});
$('btnReset').addEventListener('click', async () => {
  const r = await api('/api/test/reset');
  toast(r.message, r.ok ? 'ok' : 'err');
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') showModal(false); });

function tickClock() {
  const now = new Date();
  setText($('clockTime'), hms(now));
  setText($('clockDate'), now.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }));
}

buildCells(10);
tickClock();
setInterval(tickClock, 1000);
poll();
