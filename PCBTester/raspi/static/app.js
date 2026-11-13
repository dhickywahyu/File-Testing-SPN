"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const STATUS_TXT = { pass: "LULUS", fail: "GAGAL", running: "PROSES", pending: "BELUM" };
const STATUS_IC = { pass: "✓", fail: "✗", running: "…", pending: "–" };

let S = null;            // state terakhir
let lastStateAt = 0;
let diBuilt = false;
let relayDirty = false;
let metaDirty = false;
let dispTextInit = false;
let lastLogKey = "";

/* ---------------- util ---------------- */
function setPill(el, cls, text) {
  el.className = "pill " + (cls || "");
  el.textContent = text;
}
let toastTimer = null;
function toast(msg, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show " + (kind || "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}
async function cmd(name, data) {
  try {
    const r = await fetch("/api/cmd/" + name, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}),
    });
    const j = await r.json();
    if (!j.ok) toast(j.msg || "Gagal", "err");
    else if (j.msg) toast(j.msg, "ok");
    return j;
  } catch (e) {
    toast("Tidak terhubung ke program tester", "err");
    return { ok: false };
  }
}
const fmtNum = (v, d = 1) => (v === null || v === undefined ? "-" : Number(v).toFixed(d).replace(".", ","));

/* ---------------- 1. Digital input ---------------- */
function pinHTML(id) {
  return `<div class="pin" id="${id}"><div class="led"></div>
    <div class="pin-name"></div><div class="pin-lvl"></div><div class="pin-meta"></div>
    <span class="chk">BELUM</span></div>`;
}
function buildDI(labels) {
  const g = $("diGrid");
  let head = `<div class="di-row di-head"><div></div>`;
  let kiri = `<div class="di-row band kiri"><div class="side"><b>KIRI</b><small>Jalur utama</small></div>`;
  let kanan = `<div class="di-row band kanan"><div class="side"><b>KANAN</b><small>Jalur cadangan</small></div>`;
  let act = `<div class="di-row di-active"><div class="side"><b>JALUR AKTIF</b></div>`;
  labels.forEach((L, i) => {
    head += `<div class="lbl" id="lbl${i}"><span>${esc(L.name)}</span><span class="ok">✓</span></div>`;
    kiri += pinHTML("pk" + i);
    kanan += pinHTML("pn" + i);
    act += `<div class="act" id="act${i}">—</div>`;
  });
  g.innerHTML = head + "</div>" + kiri + "</div>" + kanan + "</div>" + act + "</div>";
  diBuilt = true;
}
function renderPin(el, p) {
  const cls = p.error ? "pin err" : p.level ? "pin hi" : "pin lo";
  if (el.className !== cls) el.className = cls;
  el.querySelector(".pin-name").textContent = "GPIO " + p.gpio;
  el.querySelector(".pin-lvl").textContent = p.error ? "ERROR" : p.level ? "HIGH · aktif" : "LOW · mati";
  const meta = el.querySelector(".pin-meta");
  if (p.error) {
    meta.textContent = p.error;
    el.title = p.error;
  } else {
    const g = p.glitches > 10 ? `<span class="warn">Glitch ${p.glitches}</span>` : `Glitch ${p.glitches}`;
    meta.innerHTML = `Tekan ${p.rises} · ${g}`;
    el.title = `GPIO ${p.gpio} · kualitas sinyal: ${p.quality}`;
  }
  const chk = el.querySelector(".chk");
  chk.className = "chk" + (p.tested ? " done" : "");
  chk.textContent = p.tested ? "✓ OK" : "BELUM";
}
function renderDI(di, qcItem) {
  if (!diBuilt) buildDI(di);
  let tested = 0, total = 0;
  di.forEach((L, i) => {
    renderPin($("pk" + i), L.kiri);
    renderPin($("pn" + i), L.kanan);
    tested += L.kiri.tested + L.kanan.tested;
    total += 2;
    const lbl = $("lbl" + i);
    lbl.className = "lbl" + (L.faults ? " fault" : L.ok ? " done" : "");
    const a = $("act" + i);
    let cls = "act", txt = "—";
    if (L.active === "BOTH") { cls += " both"; txt = "⚠ KEDUANYA HIGH"; }
    else if (L.active === "KIRI") { cls += " kiri"; txt = "◀ KIRI · GPIO " + L.kiri.gpio; }
    else if (L.active === "KANAN") { cls += " kanan"; txt = "KANAN · GPIO " + L.kanan.gpio + " ▶"; }
    else if (L.last_path === "KIRI") { cls += " last-kiri"; txt = "terakhir: KIRI"; }
    else if (L.last_path === "KANAN") { cls += " last-kanan"; txt = "terakhir: KANAN"; }
    if (L.faults && L.active !== "BOTH") txt += " · short " + L.faults + "×";
    a.className = cls;
    a.textContent = txt;
  });
  $("diProgress").textContent = `${tested}/${total} pin teruji`;
  setPill($("diPill"), qcItem.status, STATUS_TXT[qcItem.status]);
}

/* ---------------- 2. Relay ---------------- */
let relayAnim = { elapsed: 0, dur: 0, at: 0, running: false, state: false };
function renderRelay(r, qcItem) {
  [0, 1].forEach((i) => {
    const el = $("rl" + i);
    el.className = "rlamp" + (r.state ? " on" : "");
    el.querySelector(".rstate").textContent = r.state ? "ON" : "OFF";
    $("rl" + i + "pin").textContent = "GPIO " + r.pins[i];
  });
  $("relayCycles").textContent = r.cycles;
  $("relaySub").textContent = "Kedua relay ON/OFF bersamaan · " + (r.active_high ? "aktif-HIGH" : "aktif-LOW");
  relayAnim = { elapsed: r.elapsed, dur: r.dur, at: performance.now(), running: r.running, state: r.state };
  const onS = $("onS"), offS = $("offS");
  if (!relayDirty && document.activeElement !== onS && document.activeElement !== offS) {
    onS.value = r.on_s;
    offS.value = r.off_s;
  }
  $("relayStart").disabled = r.running;
  if (r.error) setPill($("relayPill"), "fail", "ERROR");
  else setPill($("relayPill"), qcItem.status, r.running ? "BERJALAN" : STATUS_TXT[qcItem.status]);
  if (r.error) $("relayPhase").textContent = r.error;
}
function relayTick() {
  const a = relayAnim;
  const bar = $("relayBar").parentElement;
  if (a.running && a.dur > 0) {
    const el = a.elapsed + (performance.now() - a.at) / 1000;
    const pct = Math.min(100, (el / a.dur) * 100);
    $("relayBar").style.width = pct + "%";
    bar.className = "bar " + (a.state ? "on" : "off");
    $("relayPhase").textContent = a.state ? "AKTIF (ON)" : "MATI (OFF)";
    $("relayRemain").textContent = "sisa " + Math.max(0, a.dur - el).toFixed(1).replace(".", ",") + " s / " + String(a.dur).replace(".", ",") + " s";
  } else if (!(S && S.relay.error)) {
    $("relayBar").style.width = "0%";
    bar.className = "bar";
    $("relayPhase").textContent = "Berhenti";
    $("relayRemain").textContent = "";
  }
  requestAnimationFrame(relayTick);
}

/* ---------------- 3. RTC ---------------- */
function renderRTC(r, qcItem) {
  const map = { synced: "pass", unsynced: "running", osf: "running", invalid: "fail", stopped: "fail", not_found: "fail", i2c_off: "fail" };
  setPill($("rtcPill"), map[r.code] || "", r.label);
  $("rtcTime").textContent = r.rtc_time || "--:--:--";
  $("rtcTime").style.color = r.detected ? "" : "var(--dim)";
  $("rtcDate").textContent = r.rtc_date ? r.rtc_date + " · " + (r.tz || "") : "RTC tidak terbaca";
  $("rtcDetail").textContent = r.detail || "";
  $("rtcSys").textContent = r.sys_time;
  if (r.diff === null) $("rtcDiff").textContent = "-";
  else {
    const ok = Math.abs(r.diff) <= 2;
    $("rtcDiff").innerHTML = `<span class="${ok ? "ok-t" : "warn-t"}">${r.diff > 0 ? "+" : ""}${r.diff} s</span>`;
  }
  $("rtcNtp").innerHTML = r.ntp === true ? '<span class="ok-t">Tersinkron</span>' : r.ntp === false ? '<span class="warn-t">Tidak tersedia</span>' : "-";
  $("rtcTemp").textContent = r.temp_c === null || r.temp_c === undefined ? "-" : fmtNum(r.temp_c, 2) + " °C";
  if (!r.detected) $("rtcOsf").textContent = "-";
  else {
    const run = r.ticking ? '<span class="ok-t">Berjalan</span>' : '<span class="warn-t">Memeriksa…</span>';
    const osf = r.osf ? '<span class="warn-t">OSF aktif</span>' : r.osf_at_start ? '<span class="warn-t">OSF awal</span>' : '<span class="ok-t">OSF ok</span>';
    $("rtcOsf").innerHTML = run + " · " + osf;
  }
  $("rtcLast").textContent = r.last_sync ? `${r.last_sync.at} · ${r.last_sync.dir}` : "-";
  $("rtcLast").title = r.last_sync ? r.last_sync.reason : "";
  $("sysTime").textContent = r.sys_time;
  $("sysDate").textContent = r.sys_date + " · " + (r.tz || "");
}

/* ---------------- 4. RS485 ---------------- */
function renderRS(r) {
  const map = { good: "pass", unstable: "running", init: "info", down: "fail", port: "fail" };
  setPill($("rsPill"), map[r.code], r.label);
  $("rsDetail").textContent = r.detail;
  $("rsPort").textContent = `${r.port} · ${r.baud} bps · TX 14 · RX 15`;
  $("rsPort").title = "PING dikirim tiap 250 ms, ESP32 membalas PONG dengan data yang sama + CRC16";
  $("rsRate").textContent = r.hist.length ? fmtNum(r.rate, 0) + "%" : "-";
  let h = "";
  for (let i = 0; i < 20; i++) {
    const v = r.hist[i];
    h += `<i class="${v === 1 ? "ok" : v === 0 ? "ng" : ""}"></i>`;
  }
  $("rsHist").innerHTML = h;
  $("rsSent").textContent = r.sent;
  $("rsOk").textContent = r.ok;
  const setBad = (id, v) => { $(id).textContent = v; $(id).parentElement.className = "m" + (v > 0 ? " bad" : ""); };
  setBad("rsTo", r.timeouts);
  setBad("rsCrc", r.crc_err);
  setBad("rsNack", r.nack);
  setBad("rsMis", r.mismatch);
  $("rsRtt").textContent = r.rtt_last === null ? "-" : `${fmtNum(r.rtt_last)} ms (rata2 ${fmtNum(r.rtt_avg)} · maks ${fmtNum(r.rtt_max)})`;
  $("rsEsp").textContent = r.esp ? `uptime ${r.esp.uptime_s} s · terima ${r.esp.rx_ok} OK / ${r.esp.rx_err} error` : "belum ada data";
  $("rsEcho").textContent = r.echo ? "Echo transceiver terdeteksi (diabaikan)" : "";
}

/* ---------------- 5. MAX7219 ---------------- */
const cv = $("matrix");
const ctx = cv.getContext("2d");
let lastFrame = null;
let fpsCount = 0, fpsT = performance.now();
function sizeCanvas() {
  const wrap = cv.parentElement, pad = 12;
  const w = Math.max(64, Math.min(wrap.clientWidth - 2 * pad, (wrap.clientHeight - 2 * pad) * 4));
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = w + "px";
  cv.style.height = w / 4 + "px";
  cv.width = Math.round(w * dpr);
  cv.height = Math.round((w / 4) * dpr);
  drawMatrix(lastFrame ? lastFrame.cols : new Array(32).fill(0));
}
function drawMatrix(cols) {
  const W = cols.length, cw = cv.width / W, ch = cv.height / 8;
  ctx.clearRect(0, 0, cv.width, cv.height);
  const r = Math.min(cw, ch) * 0.38;
  // pemisah modul
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let m = 1; m < W / 8; m++) {
    ctx.beginPath(); ctx.moveTo(m * 8 * cw, 0); ctx.lineTo(m * 8 * cw, cv.height); ctx.stroke();
  }
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#2a0d0d";
  for (let x = 0; x < W; x++) for (let y = 0; y < 8; y++) {
    if (!((cols[x] >> y) & 1)) { ctx.beginPath(); ctx.arc((x + 0.5) * cw, (y + 0.5) * ch, r, 0, 6.2832); ctx.fill(); }
  }
  ctx.shadowColor = "rgba(255,40,40,0.9)";
  ctx.shadowBlur = r * 1.4;
  ctx.fillStyle = "#ff3030";
  for (let x = 0; x < W; x++) for (let y = 0; y < 8; y++) {
    if ((cols[x] >> y) & 1) { ctx.beginPath(); ctx.arc((x + 0.5) * cw, (y + 0.5) * ch, r, 0, 6.2832); ctx.fill(); }
  }
  ctx.shadowBlur = 0;
  ctx.fillStyle = "rgba(255,210,210,0.55)";
  for (let x = 0; x < W; x++) for (let y = 0; y < 8; y++) {
    if ((cols[x] >> y) & 1) { ctx.beginPath(); ctx.arc((x + 0.42) * cw, (y + 0.4) * ch, r * 0.35, 0, 6.2832); ctx.fill(); }
  }
}
function renderFrame(f) {
  lastFrame = f;
  drawMatrix(f.cols);
  $("dispPhase").textContent = f.phase || "-";
  $("dispFrame").textContent = f.id;
  $("dispWrite").textContent = fmtNum(f.ms, 1) + " ms";
  if (f.ma !== undefined) {
    const req = S ? S.display.brightness : f.level;
    const lim = f.level < req ? ` · kecerahan dibatasi ${req}→${f.level}` : ` · kecerahan ${f.level}`;
    $("dispMa").textContent = `${f.ma} / ${f.budget_ma} mA · ${f.leds} LED${lim}`;
    $("dispMa").parentElement.className = "ma" + (f.level < req ? " lim" : "");
  }
  const lat = Date.now() - f.t * 1000;
  $("dispLat").textContent = lat >= -50 && lat < 5000 ? Math.max(0, Math.round(lat)) + " ms" : "n/a";
  fpsCount++;
  const now = performance.now();
  if (now - fpsT >= 1000) {
    $("dispFps").textContent = Math.round((fpsCount * 1000) / (now - fpsT));
    fpsCount = 0; fpsT = now;
  }
}
function renderDisplay(d, qcItem) {
  document.querySelectorAll("#dispMode button").forEach((b) => b.classList.toggle("sel", b.dataset.mode === d.mode));
  $("dispText").textContent = d.text;
  if (!dispTextInit) { $("dispInput").value = d.text; dispTextInit = true; }
  if (!sliding.br) { $("brRange").value = d.brightness; $("brVal").textContent = d.brightness; }
  if (!sliding.sp) { $("spRange").value = d.scroll_ms; $("spVal").textContent = d.scroll_ms + " ms"; }
  if (document.activeElement !== $("rotSel")) $("rotSel").value = String(d.rotation);
  $("flipChk").checked = d.flip;
  $("revChk").checked = d.reverse;
  $("dispPins").textContent = `CLK GPIO${d.pins.CLK} · CS GPIO${d.pins.CS} · DIN GPIO${d.pins.DIN} · mode: ${d.mode_label}`;
  if (d.error) setPill($("dispPill"), "fail", "DRIVER ERROR");
  else setPill($("dispPill"), qcItem.status, STATUS_TXT[qcItem.status]);
}

/* ---------------- Konfirmasi operator ---------------- */
function renderConfirm(conf) {
  document.querySelectorAll(".confirm").forEach((c) => {
    const v = conf[c.dataset.item];
    c.className = "confirm" + (v ? " " + v : "");
    c.querySelectorAll(".cf").forEach((b) => b.classList.toggle("sel", b.dataset.v === v));
  });
}

/* ---------------- 6. QC ---------------- */
function renderQC(q, meta) {
  const v = $("verdict");
  v.className = "verdict " + q.overall;
  $("vIcon").textContent = q.overall === "pass" ? "✓" : q.overall === "fail" ? "✗" : "…";
  $("vTitle").textContent = q.label;
  $("vSub").textContent = `${q.n_pass} dari ${q.n_total} test lulus`;
  $("topVerdict").className = "top-verdict " + q.overall;
  $("topVerdictText").textContent = q.label + ` (${q.n_pass}/${q.n_total})`;
  $("qcList").innerHTML = q.items.map((i) =>
    `<li class="${i.status}"><span class="ic">${STATUS_IC[i.status]}</span>
      <div><div class="nm">${esc(i.name)}</div><div class="dt">${esc(i.detail)}</div></div>
      <span class="st">${STATUS_TXT[i.status]}</span></li>`).join("");
  if (!metaDirty) {
    if (document.activeElement !== $("serial")) $("serial").value = meta.serial;
    if (document.activeElement !== $("operator")) $("operator").value = meta.operator;
  }
}
function renderLog(log) {
  const key = log.length + (log.length ? log[log.length - 1].t + log[log.length - 1].msg : "");
  if (key === lastLogKey) return;
  lastLogKey = key;
  $("log").innerHTML = log.slice().reverse().map((l) =>
    `<li><span class="t">${l.t}</span><span class="${l.lv}">${esc(l.msg)}</span></li>`).join("");
}

/* ---------------- render utama ---------------- */
function render(s) {
  S = s;
  lastStateAt = performance.now();
  const qi = Object.fromEntries(s.qc.items.map((i) => [i.key, i]));
  $("simBadge").classList.toggle("hidden", !s.sim);
  renderDI(s.di, qi.di);
  renderRelay(s.relay, qi.relay);
  renderRTC(s.rtc, qi.rtc);
  renderRS(s.rs485);
  renderDisplay(s.display, qi.display);
  renderConfirm(s.confirm);
  renderQC(s.qc, s.meta);
  renderLog(s.log);
}

/* ---------------- koneksi SSE ---------------- */
function setConn(ok, text) {
  $("conn").className = "conn " + (ok ? "ok" : "bad");
  $("connText").textContent = text;
}
function connect() {
  const es = new EventSource("/api/stream");
  es.addEventListener("state", (e) => render(JSON.parse(e.data)));
  es.addEventListener("display", (e) => renderFrame(JSON.parse(e.data)));
  es.onopen = () => setConn(true, "Terhubung · " + (S ? S.backend : ""));
  es.onerror = () => setConn(false, "Terputus – mencoba lagi…");
}
setInterval(() => {
  if (lastStateAt && performance.now() - lastStateAt > 3000) setConn(false, "Tidak ada data dari program");
  else if (S) setConn(true, "Terhubung · GPIO " + S.backend);
}, 1000);

/* ---------------- event UI ---------------- */
const sliding = { br: false, sp: false };
function relayTimes() {
  const on = parseFloat(String($("onS").value).replace(",", "."));
  const off = parseFloat(String($("offS").value).replace(",", "."));
  if (!(on > 0) || !(off > 0)) { toast("Isi waktu aktif & mati dengan angka > 0", "err"); return null; }
  return { on_s: on, off_s: off };
}
["onS", "offS"].forEach((id) => $(id).addEventListener("input", () => (relayDirty = true)));
$("relayApply").onclick = async () => { const t = relayTimes(); if (t) { await cmd("relay_set", t); relayDirty = false; } };
$("relayDefault").onclick = async () => { relayDirty = false; await cmd("relay_default"); };
$("relayStart").onclick = async () => {
  const t = relayTimes(); if (!t) return;
  await cmd("relay_start", t); relayDirty = false;
};
$("relayStop").onclick = () => cmd("relay_stop");

$("rtcS2R").onclick = () => cmd("rtc_sys_to_rtc");
$("rtcR2S").onclick = () => cmd("rtc_rtc_to_sys");
$("rtcClient").onclick = () => {
  const now = new Date();
  if (confirm("Setel jam Raspberry Pi & RTC ke jam perangkat ini?\n" + now.toLocaleString("id-ID"))) cmd("rtc_from_client", { epoch_ms: Date.now() });
};
$("rsReset").onclick = () => cmd("rs485_reset");
$("diReset").onclick = () => cmd("di_reset");

document.querySelectorAll("#dispMode button").forEach((b) => (b.onclick = () => cmd("disp_set", { mode: b.dataset.mode })));
$("dispSend").onclick = () => cmd("disp_set", { text: $("dispInput").value || " ", mode: "text" });
$("dispInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("dispSend").click(); });
$("brRange").addEventListener("input", () => { sliding.br = true; $("brVal").textContent = $("brRange").value; });
$("brRange").addEventListener("change", async () => { await cmd("disp_set", { brightness: +$("brRange").value }); sliding.br = false; });
$("spRange").addEventListener("input", () => { sliding.sp = true; $("spVal").textContent = $("spRange").value + " ms"; });
$("spRange").addEventListener("change", async () => { await cmd("disp_set", { scroll_ms: +$("spRange").value }); sliding.sp = false; });
$("rotSel").onchange = () => cmd("disp_set", { rotation: +$("rotSel").value });
$("flipChk").onchange = () => cmd("disp_set", { flip: $("flipChk").checked });
$("revChk").onchange = () => cmd("disp_set", { reverse: $("revChk").checked });

document.querySelectorAll(".confirm").forEach((c) => {
  c.querySelectorAll(".cf").forEach((b) => (b.onclick = () => {
    const cur = S ? S.confirm[c.dataset.item] : null;
    cmd("confirm", { item: c.dataset.item, value: cur === b.dataset.v ? null : b.dataset.v });
  }));
});

let metaTimer = null;
["serial", "operator"].forEach((id) => $(id).addEventListener("input", () => {
  metaDirty = true;
  clearTimeout(metaTimer);
  metaTimer = setTimeout(async () => {
    await cmd("qc_meta", { serial: $("serial").value, operator: $("operator").value });
    metaDirty = false;
  }, 500);
}));
$("saveReport").onclick = () => {
  if (!$("serial").value.trim() && !confirm("No. seri PCB masih kosong. Tetap simpan laporan?")) return;
  cmd("qc_save", { serial: $("serial").value, operator: $("operator").value });
};
$("resetAll").onclick = () => {
  if (confirm("Reset semua hasil test untuk PCB berikutnya?")) cmd("qc_reset");
};

new ResizeObserver(sizeCanvas).observe(cv.parentElement);
sizeCanvas();
requestAnimationFrame(relayTick);
connect();
