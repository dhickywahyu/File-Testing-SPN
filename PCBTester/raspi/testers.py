# -*- coding: utf-8 -*-
"""Thread-thread pengujian: Digital Input, Relay, RTC, RS485, MAX7219."""
import random
import subprocess
import threading
import time
from collections import deque

from hw.gpio_backend import GPIOError
from hw.ds3231 import DS3231, SimDS3231, RTCError
from hw.max7219 import Max7219, SimMax7219, text_to_columns
from hw.rs485 import SimSerial, make_frame, parse_frame

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def fmt_date(epoch):
    t = time.localtime(epoch)
    return "%s, %02d %s %d" % (HARI[t.tm_wday], t.tm_mday, BULAN[t.tm_mon - 1], t.tm_year)


def fmt_time(epoch):
    return time.strftime("%H:%M:%S", time.localtime(epoch))


class Hub:
    """Titik pusat: event log, notifikasi ke UI, flag stop."""

    def __init__(self):
        self.cond = threading.Condition()
        self.version = 0
        self.stop = threading.Event()
        self.log = deque(maxlen=200)
        self._log_lock = threading.Lock()

    def notify(self):
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def wake(self):
        with self.cond:
            self.cond.notify_all()

    def add_log(self, msg, level="info"):
        with self._log_lock:
            self.log.append({"t": time.strftime("%H:%M:%S"), "msg": msg, "lv": level})
        self.notify()


def qc(status, detail):
    return {"status": status, "detail": detail}


# =============================================================================
# 1. DIGITAL INPUT
# =============================================================================
class Pin:
    def __init__(self, gpio, side):
        self.gpio, self.side = gpio, side
        self.error = None
        self.level = 0
        self.reset()

    def reset(self):
        self.last_change = time.monotonic()
        self.rises = 0
        self.glitches = 0
        self.seen_low = False
        self.tested = False

    def snap(self):
        g = self.glitches
        quality = "Stabil" if g == 0 else ("Bounce ringan" if g <= 10 else "Tidak stabil")
        return {"gpio": self.gpio, "side": self.side, "level": self.level, "rises": self.rises,
                "glitches": g, "quality": quality, "tested": self.tested, "error": self.error}


class DILabel:
    def __init__(self, name, kiri, kanan):
        self.name = name
        self.kiri = Pin(kiri, "KIRI")
        self.kanan = Pin(kanan, "KANAN")
        self.reset()

    def reset(self):
        self.both_since = None
        self.fault_active = False
        self.faults = 0
        self.last_path = None
        self.active = None
        self.kiri.reset()
        self.kanan.reset()


class DigitalInputMonitor(threading.Thread):
    def __init__(self, hub, gpio, cfg):
        super().__init__(daemon=True, name="DI")
        self.hub, self.gpio, self.cfg = hub, gpio, cfg
        self.lock = threading.Lock()
        self.labels = [DILabel(n, a, b) for n, a, b in cfg.DIGITAL_INPUTS]
        for L in self.labels:
            for p in (L.kiri, L.kanan):
                try:
                    gpio.setup_input(p.gpio, cfg.DI_INTERNAL_PULL)
                    p.level = 1 if gpio.read(p.gpio) else 0
                except (GPIOError, Exception) as e:
                    p.error = str(e)
                    hub.add_log("%s %s: %s" % (L.name, p.side, e), "err")

    def reset(self):
        with self.lock:
            for L in self.labels:
                L.reset()
        self.hub.notify()

    def run(self):
        c = self.cfg
        glitch_s, min_high_s, fault_s = c.DI_GLITCH_MS / 1000.0, c.DI_MIN_HIGH_MS / 1000.0, c.DI_BOTH_HIGH_FAULT_MS / 1000.0
        interval = c.DI_POLL_INTERVAL_S
        while not self.hub.stop.is_set():
            now = time.monotonic()
            changed = False
            logs = []
            with self.lock:
                for L in self.labels:
                    for p in (L.kiri, L.kanan):
                        if p.error:
                            continue
                        try:
                            v = 1 if self.gpio.read(p.gpio) else 0
                        except Exception as e:
                            p.error = "Gagal membaca: %s" % e
                            changed = True
                            continue
                        if v != p.level:
                            if now - p.last_change < glitch_s:
                                p.glitches += 1
                            p.level, p.last_change = v, now
                            if v:
                                p.rises += 1
                            changed = True
                        if v == 0:
                            p.seen_low = True
                        elif p.seen_low and not p.tested and now - p.last_change >= min_high_s:
                            p.tested = True
                            changed = True
                            logs.append(("%s - jalur %s (GPIO%d) teruji" % (L.name, p.side, p.gpio), "ok"))
                    both = L.kiri.level and L.kanan.level
                    if both:
                        if L.both_since is None:
                            L.both_since = now
                        elif not L.fault_active and now - L.both_since >= fault_s:
                            L.fault_active = True
                            L.faults += 1
                            changed = True
                            logs.append(("%s: KEDUA jalur HIGH bersamaan (GPIO%d & GPIO%d) - kemungkinan short!"
                                         % (L.name, L.kiri.gpio, L.kanan.gpio), "err"))
                    else:
                        L.both_since = None
                        if L.fault_active:
                            L.fault_active = False
                            changed = True
                    act = "BOTH" if (both and L.fault_active) else ("KIRI" if L.kiri.level and not L.kanan.level
                                                                    else "KANAN" if L.kanan.level and not L.kiri.level else None)
                    if act in ("KIRI", "KANAN") and act != L.last_path:
                        if L.last_path is not None:
                            p = L.kiri if act == "KIRI" else L.kanan
                            logs.append(("%s: jalur aktif pindah ke %s (GPIO%d)" % (L.name, act, p.gpio), "info"))
                        L.last_path = act
                    L.active = act
            for m, lv in logs:
                self.hub.add_log(m, lv)
            if changed:
                self.hub.notify()
            time.sleep(interval)

    def snapshot(self):
        with self.lock:
            return [{"name": L.name, "kiri": L.kiri.snap(), "kanan": L.kanan.snap(), "active": L.active,
                     "last_path": L.last_path, "faults": L.faults, "fault_active": L.fault_active,
                     "ok": L.kiri.tested and L.kanan.tested and L.faults == 0}
                    for L in self.labels]

    def qc(self):
        with self.lock:
            pins = [p for L in self.labels for p in (L.kiri, L.kanan)]
            tested = sum(1 for p in pins if p.tested)
            errs = [p for p in pins if p.error]
            faults = [L.name for L in self.labels if L.faults]
        if errs:
            return qc("fail", "GPIO error: " + ", ".join("GPIO%d" % p.gpio for p in errs))
        if faults:
            return qc("fail", "Kedua jalur HIGH bersamaan: " + ", ".join(faults))
        if tested == len(pins):
            return qc("pass", "%d/%d pin teruji, tidak ada short" % (tested, len(pins)))
        if tested == 0:
            return qc("pending", "Tekan tiap tombol pada jalur KIRI lalu KANAN")
        return qc("running", "%d/%d pin teruji" % (tested, len(pins)))


# =============================================================================
# 2. RELAY
# =============================================================================
class RelayController(threading.Thread):
    def __init__(self, hub, gpio, cfg, settings):
        super().__init__(daemon=True, name="Relay")
        self.hub, self.gpio, self.cfg = hub, gpio, cfg
        self.pins = list(cfg.RELAY_PINS)
        self.active_high = cfg.RELAY_ACTIVE_HIGH
        self.on_s = float(settings.get("relay_on_s", cfg.RELAY_DEFAULT_ON_S))
        self.off_s = float(settings.get("relay_off_s", cfg.RELAY_DEFAULT_OFF_S))
        self.running = False
        self.state = False
        self.cycles = 0
        self.phase_t0 = time.monotonic()
        self.phase_dur = 0.0
        self.error = None
        self.wake = threading.Event()
        for p in self.pins:
            try:
                gpio.setup_output(p, self._lvl(False))
            except Exception as e:
                self.error = str(e)
                hub.add_log("Relay: %s" % e, "err")

    def _lvl(self, on):
        return 1 if on == self.active_high else 0

    def _apply(self, on):
        lv = self._lvl(on)
        try:
            for p in self.pins:  # kedua relay diubah berurutan dalam hitungan mikrodetik
                self.gpio.write(p, lv)
        except Exception as e:
            self.error = str(e)
        self.state = on
        self.phase_t0 = time.monotonic()
        self.hub.notify()

    def start_cycle(self):
        if self.error:
            return False
        self.running = True
        self.wake.set()
        self.hub.add_log("Relay: siklus dimulai (ON %.2f s / OFF %.2f s)" % (self.on_s, self.off_s))
        return True

    def stop_cycle(self):
        self.running = False
        self.wake.set()
        self.hub.add_log("Relay: siklus dihentikan setelah %d siklus" % self.cycles)

    def set_times(self, on_s, off_s):
        self.on_s = min(3600.0, max(0.05, float(on_s)))
        self.off_s = min(3600.0, max(0.05, float(off_s)))
        self.hub.add_log("Relay: waktu diubah -> ON %.2f s / OFF %.2f s" % (self.on_s, self.off_s))
        self.hub.notify()

    def _wait(self, dur):
        """Tunggu dur detik. True bila dihentikan."""
        end = time.monotonic() + dur
        while True:
            rem = end - time.monotonic()
            if rem <= 0:
                return False
            if self.wake.wait(min(rem, 0.1)):
                self.wake.clear()
                if not self.running or self.hub.stop.is_set():
                    return True

    def run(self):
        while not self.hub.stop.is_set():
            if not self.running or self.error:
                if self.state:
                    self.phase_dur = 0
                    self._apply(False)
                self.wake.wait(0.2)
                self.wake.clear()
                continue
            self.phase_dur = self.on_s
            self._apply(True)
            if self._wait(self.on_s):
                continue
            self.phase_dur = self.off_s
            self._apply(False)
            if self._wait(self.off_s):
                continue
            self.cycles += 1
            self.hub.notify()
        self._apply(False)

    def reset(self):
        self.cycles = 0
        self.hub.notify()

    def snapshot(self):
        return {"running": self.running, "state": self.state, "on_s": self.on_s, "off_s": self.off_s,
                "cycles": self.cycles, "elapsed": time.monotonic() - self.phase_t0, "dur": self.phase_dur,
                "pins": self.pins, "active_high": self.active_high, "error": self.error,
                "default_on": self.cfg.RELAY_DEFAULT_ON_S, "default_off": self.cfg.RELAY_DEFAULT_OFF_S}


# =============================================================================
# 3. RTC DS3231
# =============================================================================
class RTCMonitor(threading.Thread):
    def __init__(self, hub, cfg, sim=False):
        super().__init__(daemon=True, name="RTC")
        self.hub, self.cfg, self.sim = hub, cfg, sim
        self.dev = None
        self.io = threading.Lock()
        self.bus_error = None
        self.detected = False
        self.last = None
        self.err = None
        self.fail_since = None
        self.ntp = None
        self._ntp_next = 0
        self.osf_at_start = None
        self.sec_changes = 0
        self._last_sec = None
        self._last_sec_t = time.monotonic()
        self.last_sync = None
        self.action_msg = None
        self._auto_next = 0
        self.passed = False
        self.started = time.monotonic()

    # -- util ---------------------------------------------------------------
    def _open(self):
        try:
            self.dev = SimDS3231() if self.sim else DS3231(self.cfg.RTC_I2C_BUS, self.cfg.RTC_I2C_ADDR)
            self.bus_error = None
        except RTCError:
            self.bus_error = "I2C belum aktif (/dev/i2c-%d tidak ada). Aktifkan lewat: sudo raspi-config -> Interface -> I2C" % self.cfg.RTC_I2C_BUS
        except Exception as e:
            self.bus_error = "Gagal membuka I2C: %s" % e

    def _check_ntp(self):
        if self.sim:
            return False
        try:
            out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            return out == "yes"
        except Exception:
            return None

    def _set_system(self, epoch):
        if self.sim:
            return True, ""
        try:
            r = subprocess.run(["date", "-u", "-s", "@%d" % int(epoch)], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return True, ""
            return False, (r.stderr.strip() or "gagal") + " (jalankan program dengan sudo)"
        except Exception as e:
            return False, str(e)

    def _mark_sync(self, direction, reason):
        self.last_sync = {"dir": direction, "reason": reason, "at": time.time()}

    # -- aksi sinkronisasi ---------------------------------------------------
    def sys_to_rtc(self, reason="manual"):
        if not self.dev:
            return False, "RTC tidak terhubung"
        with self.io:
            t = time.time()
            time.sleep(1.0 - (t % 1.0) + 0.003)   # tulis tepat di awal detik -> error < 10 ms
            try:
                self.dev.write_epoch(int(time.time()))
            except Exception as e:
                return False, "Gagal menulis RTC: %s" % e
        self._mark_sync("Sistem -> RTC", reason)
        self.hub.add_log("RTC: waktu sistem ditulis ke RTC (%s)" % reason, "ok")
        return True, "Waktu sistem ditulis ke RTC"

    def rtc_to_sys(self, reason="manual"):
        if not self.dev:
            return False, "RTC tidak terhubung"
        with self.io:
            try:
                d0 = self.dev.read()
                if not d0["fields_ok"] or d0["osf"]:
                    return False, "Waktu RTC tidak valid (OSF) - tidak dipakai untuk jam sistem"
                end = time.monotonic() + 1.2   # tunggu pergantian detik RTC agar presisi
                d = d0
                while d["sec"] == d0["sec"] and time.monotonic() < end:
                    time.sleep(0.005)
                    d = self.dev.read()
            except Exception as e:
                return False, "Gagal membaca RTC: %s" % e
        ok, msg = self._set_system(d["epoch"])
        if not ok:
            self.hub.add_log("RTC: gagal set jam sistem - %s" % msg, "err")
            return False, "Gagal set jam sistem: " + msg
        self._mark_sync("RTC -> Sistem", reason)
        self.hub.add_log("RTC: jam sistem diambil dari RTC (%s)" % reason, "ok")
        return True, "Jam sistem disetel dari RTC"

    def set_from_client(self, epoch_ms):
        ok, msg = self._set_system(epoch_ms / 1000.0)
        if not ok:
            return False, "Gagal set jam sistem: " + msg
        self.hub.add_log("Jam sistem disetel dari jam perangkat/browser", "info")
        return self.sys_to_rtc("jam perangkat")

    # -- loop ---------------------------------------------------------------
    def run(self):
        while not self.hub.stop.is_set():
            now = time.monotonic()
            if self.dev is None:
                self._open()
                if self.dev is None:
                    self.detected = False
                    self.fail_since = self.fail_since or now
                    self.hub.notify()
                    self.hub.stop.wait(2)
                    continue
            if now >= self._ntp_next:
                self.ntp = self._check_ntp()
                self._ntp_next = now + 15
            try:
                with self.io:
                    d = self.dev.read()
                if not self.detected:
                    self.hub.add_log("RTC DS3231 terdeteksi di I2C-%d alamat 0x%02X" % (self.cfg.RTC_I2C_BUS, self.cfg.RTC_I2C_ADDR), "ok")
                self.detected, self.err, self.fail_since = True, None, None
                self.last = d
                if self.osf_at_start is None:
                    self.osf_at_start = d["osf"]
                    if d["osf"]:
                        self.hub.add_log("RTC: flag OSF aktif - waktu RTC belum pernah diset / baterai sempat habis", "warn")
                if d["sec"] != self._last_sec:
                    if self._last_sec is not None:
                        self.sec_changes += 1
                    self._last_sec, self._last_sec_t = d["sec"], now
                self._auto_sync(d, now)
            except Exception as e:
                if self.detected:
                    self.hub.add_log("RTC: koneksi I2C hilang (%s)" % e, "err")
                self.detected = False
                self.err = str(e)
                self.fail_since = self.fail_since or now
            self.hub.notify()
            self.hub.stop.wait(0.5)

    def _auto_sync(self, d, now):
        if now < self._auto_next:
            return
        tol = self.cfg.RTC_SYNC_TOLERANCE_S
        invalid = d["osf"] or not d["fields_ok"]
        diff = (d["epoch"] - time.time()) if d["fields_ok"] else None
        if not invalid and abs(diff) <= tol:
            return
        self._auto_next = now + 20
        if invalid:
            src = "otomatis, NTP" if self.ntp else "otomatis, jam sistem tanpa NTP"
            ok, msg = self.sys_to_rtc(src)
        elif self.ntp:
            ok, msg = self.sys_to_rtc("otomatis, NTP")
        else:
            ok, msg = self.rtc_to_sys("otomatis, tanpa NTP")
        self.action_msg = None if ok else msg

    def _status(self):
        now = time.monotonic()
        if self.bus_error:
            return "i2c_off", "I2C TIDAK AKTIF", self.bus_error
        if not self.detected:
            return "not_found", "TIDAK TERHUBUNG", ("Tidak ada respon di I2C-%d alamat 0x%02X. Cek SDA (GPIO2), SCL (GPIO3), VCC & GND. %s"
                                                    % (self.cfg.RTC_I2C_BUS, self.cfg.RTC_I2C_ADDR, self.err or ""))
        d = self.last
        if not d["fields_ok"]:
            return "invalid", "DATA TIDAK VALID", "Isi register waktu tidak masuk akal"
        if d["osf"]:
            return "osf", "WAKTU BELUM DISET", "Flag OSF aktif (osilator pernah berhenti / baterai lemah)"
        if now - self._last_sec_t > 2.5:
            return "stopped", "OSILATOR BERHENTI", "Detik RTC tidak bertambah - cek kristal / IC"
        diff = d["epoch"] - time.time()
        if abs(diff) > self.cfg.RTC_SYNC_TOLERANCE_S:
            return "unsynced", "BELUM SINKRON", self.action_msg or "Selisih %.0f detik dengan jam sistem" % diff
        src = "NTP (internet)" if self.ntp else "jam sistem / RTC (tanpa NTP)"
        return "synced", "TERSINKRON", "Referensi: " + src

    def snapshot(self):
        code, label, detail = self._status()
        d = self.last or {}
        now = time.time()
        rtc_epoch = d.get("epoch") if self.detected else None
        out = {"code": code, "label": label, "detail": detail, "detected": self.detected,
               "sys_time": fmt_time(now), "sys_date": fmt_date(now), "tz": time.strftime("%Z"),
               "rtc_time": fmt_time(rtc_epoch) if rtc_epoch else None,
               "rtc_date": fmt_date(rtc_epoch) if rtc_epoch else None,
               "diff": int(rtc_epoch - int(now)) if rtc_epoch else None,   # resolusi RTC = 1 detik
               "temp_c": d.get("temp_c") if self.detected else None,
               "osf": d.get("osf"), "osf_at_start": self.osf_at_start, "ntp": self.ntp,
               "bus": self.cfg.RTC_I2C_BUS, "addr": "0x%02X" % self.cfg.RTC_I2C_ADDR,
               "lib": getattr(self.dev, "lib", None),
               "driver": self.dev.kernel_driver() if self.dev else None,
               "ticking": self.sec_changes >= 2 and time.monotonic() - self._last_sec_t <= 2.5,
               "last_sync": None}
        if self.last_sync:
            ls = self.last_sync
            out["last_sync"] = {"dir": ls["dir"], "reason": ls["reason"], "at": fmt_time(ls["at"])}
        return out

    def qc(self):
        code, label, detail = self._status()
        ticking = self.sec_changes >= 2
        if code == "synced" and ticking:
            self.passed = True
        if self.passed:
            return qc("pass", "Terdeteksi, detik berjalan, tersinkron")
        if code in ("i2c_off", "not_found") and self.fail_since and time.monotonic() - self.fail_since > 5:
            return qc("fail", label.capitalize())
        if code == "stopped":
            return qc("fail", "Osilator RTC berhenti")
        return qc("running", label.capitalize())

    def reset(self):
        self.passed = False
        self.sec_changes = 0


# =============================================================================
# 4. RS485
# =============================================================================
class RS485Tester(threading.Thread):
    def __init__(self, hub, gpio, cfg, sim=False):
        super().__init__(daemon=True, name="RS485")
        self.hub, self.gpio, self.cfg, self.sim = hub, gpio, cfg, sim
        self.ser = None
        self.port_error = None
        self.de = cfg.RS485_DE_PIN
        if self.de is not None:
            try:
                gpio.setup_output(self.de, 0)
            except Exception as e:
                self.port_error = "Pin DE/RE: %s" % e
        self.seq = 0
        self.passed = False
        self._last_code = None
        self.reset()

    def reset(self):
        self.hist = deque(maxlen=20)
        self.rtts = deque(maxlen=50)
        self.sent = self.ok = self.timeouts = self.crc_err = self.nack = self.mismatch = self.garbage = 0
        self.last_rtt = None
        self.echo = False
        self.esp = None
        self.last_ok_at = None
        self.passed = False
        self.hub.notify()

    def _open(self):
        if self.sim:
            self.ser = SimSerial()
            return
        import serial  # pyserial
        self.ser = serial.Serial(self.cfg.RS485_PORT, self.cfg.RS485_BAUD, timeout=0.02, write_timeout=0.5)

    def run(self):
        c = self.cfg
        next_t = time.monotonic()
        while not self.hub.stop.is_set():
            if self.ser is None:
                try:
                    self._open()
                    if self.port_error:
                        self.hub.add_log("RS485: port %s terbuka" % c.RS485_PORT, "ok")
                    self.port_error = None
                except Exception as e:
                    msg = "Tidak bisa membuka %s: %s" % (c.RS485_PORT, e)
                    if msg != self.port_error:
                        self.hub.add_log("RS485: " + msg, "err")
                    self.port_error = msg
                    self.hub.notify()
                    self.hub.stop.wait(2)
                    continue
            self.seq = (self.seq + 1) % 1000000
            payload = "%012X" % random.getrandbits(48)
            body = "PING,%d,%s" % (self.seq, payload)
            try:
                self.ser.reset_input_buffer()
                if self.de is not None:
                    self.gpio.write(self.de, 1)
                self.ser.write(make_frame(body))
                self.ser.flush()
                if self.de is not None:
                    self.gpio.write(self.de, 0)
            except Exception as e:
                self.port_error = "Gagal kirim: %s" % e
                self.hub.add_log("RS485: " + self.port_error, "err")
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                continue
            t0 = time.monotonic()
            self.sent += 1
            res = self._await(self.seq, payload, t0)
            if res == "ok":
                self.ok += 1
                self.last_ok_at = time.time()
            elif res == "timeout":
                self.timeouts += 1
            elif res == "crc":
                self.crc_err += 1
            elif res == "nack":
                self.nack += 1
            elif res == "mismatch":
                self.mismatch += 1
            self.hist.append(res == "ok")
            code, label, _ = self._status()
            if code != self._last_code:
                lv = {"good": "ok", "unstable": "warn"}.get(code, "err")
                self.hub.add_log("RS485: %s" % label, lv)
                self._last_code = code
            self.hub.notify()
            next_t += c.RS485_INTERVAL_S
            delay = next_t - time.monotonic()
            if delay < 0:
                next_t = time.monotonic()
                delay = 0
            self.hub.stop.wait(delay)

    def _await(self, seq, payload, t0):
        buf = b""
        deadline = t0 + self.cfg.RS485_TIMEOUT_S
        while time.monotonic() < deadline:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                txt = line.decode("ascii", "replace").strip()
                if not txt:
                    continue
                fields, crc_ok = parse_frame(txt)
                if fields is None:
                    self.garbage += 1
                    continue
                if fields[0] == "PING":      # echo kiriman sendiri (transceiver tanpa RE terpisah)
                    self.echo = True
                    continue
                if not crc_ok:
                    return "crc"
                if fields[0] == "NACK":
                    return "nack"
                if fields[0] == "PONG" and len(fields) >= 6:
                    if fields[1] != str(seq):
                        continue             # balasan terlambat untuk PING sebelumnya
                    if fields[2] != payload:
                        return "mismatch"
                    rtt = (time.monotonic() - t0) * 1000.0
                    self.last_rtt = rtt
                    self.rtts.append(rtt)
                    try:
                        self.esp = {"uptime_s": int(fields[3]) // 1000, "rx_ok": int(fields[4]), "rx_err": int(fields[5])}
                    except ValueError:
                        pass
                    return "ok"
                self.garbage += 1
        return "timeout"

    def _rate(self):
        return 100.0 * sum(self.hist) / len(self.hist) if self.hist else 0.0

    def _status(self):
        if self.port_error:
            return "port", "PORT ERROR", self.port_error
        if self.sent == 0:
            return "init", "MEMULAI", "Menunggu PING pertama"
        last5 = list(self.hist)[-5:]
        if len(last5) >= 5 and not any(last5):
            if self.ok == 0:
                return "down", "TIDAK ADA RESPON", "ESP32 tidak membalas. Cek A/B, GND, baudrate & sketch ESP32"
            return "down", "KONEKSI TERPUTUS", "5 PING terakhir tidak dibalas"
        # histeresis: masuk "BAIK" pada >= 95 %, baru turun ke "TIDAK STABIL" bila < 85 %
        limit = self.cfg.RS485_QC_MIN_RATE if self._last_code != "good" else self.cfg.RS485_QC_MIN_RATE - 10
        if len(self.hist) >= 5 and self._rate() >= limit:
            return "good", "KOMUNIKASI BAIK", "Raspi <-> ESP32 bertukar data dengan benar"
        if len(self.hist) < 5:
            return "init", "MENGUJI", "Mengumpulkan data"
        return "unstable", "TIDAK STABIL", "Ada paket hilang / rusak"

    def snapshot(self):
        code, label, detail = self._status()
        rt = list(self.rtts)
        return {"code": code, "label": label, "detail": detail, "port": self.cfg.RS485_PORT,
                "baud": self.cfg.RS485_BAUD, "sent": self.sent, "ok": self.ok, "timeouts": self.timeouts,
                "crc_err": self.crc_err, "nack": self.nack, "mismatch": self.mismatch, "garbage": self.garbage,
                "rate": round(self._rate(), 1), "hist": [1 if h else 0 for h in self.hist],
                "rtt_last": round(self.last_rtt, 1) if self.last_rtt else None,
                "rtt_avg": round(sum(rt) / len(rt), 1) if rt else None,
                "rtt_max": round(max(rt), 1) if rt else None,
                "echo": self.echo, "esp": self.esp,
                "last_ok": fmt_time(self.last_ok_at) if self.last_ok_at else None}

    def qc(self):
        c = self.cfg
        if not self.passed and self.ok >= c.RS485_QC_MIN_OK and len(self.hist) == self.hist.maxlen \
                and self._rate() >= c.RS485_QC_MIN_RATE:
            self.passed = True
        if self.passed:
            return qc("pass", "%d paket OK, sukses %.0f%%" % (self.ok, self._rate()))
        if self.port_error:
            return qc("fail", "Port serial error")
        if self.sent >= 40 and self.ok == 0:
            return qc("fail", "Tidak ada respon dari ESP32")
        if self.sent == 0:
            return qc("pending", "Menunggu")
        return qc("running", "%d/%d paket OK" % (min(self.ok, c.RS485_QC_MIN_OK), c.RS485_QC_MIN_OK))


# =============================================================================
# 5. MAX7219
# =============================================================================
class DisplayController(threading.Thread):
    """
    Uji MAX7219 32x8 (4 modul 8x8) dengan PROTEKSI ARUS SUPLAI:
    - tidak ada lagi mode "semua LED nyala" / register Display-Test (memaksa 256 LED kecerahan maks ~1,27 A)
    - uji semua LED dilakukan BERTAHAP: satu modul 8x8 (64 LED) menyala bergantian, modul lain mati
    - setiap frame diestimasi arusnya; kecerahan otomatis diturunkan agar tidak melewati
      MAX7219_CURRENT_BUDGET_MA (lihat config.py & dokumen RCA AMS1117)
    """
    MODES = {"auto": "Auto Test", "step": "Bertahap per Modul", "text": "Teks Berjalan", "off": "Mati"}

    def __init__(self, hub, gpio, cfg, settings, sim=False):
        super().__init__(daemon=True, name="MAX7219")
        self.hub, self.cfg = hub, cfg
        self.n = cfg.MAX7219_MODULES
        self.width = self.n * 8
        mode = settings.get("disp_mode", "auto")
        self.mode = mode if mode in self.MODES else ("step" if mode == "all_on" else "auto")
        self.text = settings.get("disp_text", cfg.MAX7219_DEFAULT_TEXT)
        self.brightness = int(settings.get("disp_brightness", cfg.MAX7219_BRIGHTNESS))
        self.rotation = int(settings.get("disp_rotation", cfg.MAX7219_ROTATION))
        self.flip = bool(settings.get("disp_flip", cfg.MAX7219_FLIP))
        self.reverse = bool(settings.get("disp_reverse", cfg.MAX7219_REVERSE_ORDER))
        self.scroll_ms = int(settings.get("disp_scroll_ms", cfg.MAX7219_SCROLL_MS))
        self.budget_ma = max(80.0, float(cfg.MAX7219_CURRENT_BUDGET_MA))
        self.error = None
        self.lock = threading.Lock()
        self.frame = [0] * self.width
        self.frame_id = 0
        self.frame_t = 0.0
        self.write_ms = 0.0
        self.phase = ""
        self.leds_on = 0
        self.level = 0          # intensitas yang benar-benar dipakai (0..15)
        self.est_ma = 0.0       # estimasi arus rata-rata display (mA)
        self.peak_ma = 0.0      # estimasi tertinggi sejak program jalan
        self._hw_level = None
        self._limited_logged = False
        self.restart = threading.Event()
        try:
            if sim:
                self.dev = SimMax7219(modules=self.n)
            else:
                self.dev = Max7219(gpio, cfg.MAX7219_CLK, cfg.MAX7219_CS, cfg.MAX7219_DIN, self.n)
            self._apply_orientation()
        except Exception as e:
            self.dev = None
            self.error = str(e)
            hub.add_log("MAX7219: %s" % e, "err")

    def _apply_orientation(self):
        if self.dev:
            self.dev.rotation, self.dev.flip, self.dev.reverse = self.rotation, self.flip, self.reverse

    # -- estimasi arus -------------------------------------------------------
    def estimate_ma(self, leds_on, level):
        """Arus rata-rata = LED nyala x ISEG x 1/8 (multiplex) x duty intensitas (2k+1)/32 + arus diam chip."""
        c = self.cfg
        return leds_on * c.MAX7219_ISEG_MA / 8.0 * (2 * level + 1) / 32.0 + c.MAX7219_IQ_MA * self.n

    def _safe_level(self, leds_on):
        for k in range(self.brightness, -1, -1):
            ma = self.estimate_ma(leds_on, k)
            if ma <= self.budget_ma:
                return k, ma
        return None, self.estimate_ma(leds_on, 0)

    def update(self, **kw):
        restart = False
        if "mode" in kw and kw["mode"] in self.MODES:
            self.mode = kw["mode"]
            restart = True
        if "text" in kw:
            t = "".join(ch for ch in str(kw["text"]) if 32 <= ord(ch) <= 126)[:120]
            self.text = t or " "
            restart = True
        if "scroll_ms" in kw:
            self.scroll_ms = max(10, min(500, int(kw["scroll_ms"])))
        if "brightness" in kw:   # diterapkan di frame berikutnya, tetap lewat pembatas arus
            self.brightness = max(0, min(15, int(kw["brightness"])))
            self._limited_logged = False
        for k in ("rotation", "flip", "reverse"):
            if k in kw:
                setattr(self, k, int(kw[k]) if k == "rotation" else bool(kw[k]))
                restart = restart or self.mode in ("step", "off")
        self._apply_orientation()
        if restart:
            self.restart.set()
        self.hub.notify()

    # -- pembuat frame -------------------------------------------------------
    def _scroll(self, text, phase):
        cols = [0] * self.width + text_to_columns(text) + [0] * self.width
        step = self.scroll_ms / 1000.0
        for i in range(len(cols) - self.width + 1):
            yield cols[i:i + self.width], phase, step

    def _steps(self):
        """Semua LED diuji bergantian per modul 8x8 - hanya 64 LED yang menyala pada satu waktu."""
        W, hold = self.width, self.cfg.MAX7219_STEP_HOLD_S
        for m in range(self.n):
            fb = [0] * W
            for c in range(m * 8, m * 8 + 8):
                fb[c] = 0xFF
            yield fb, "Bertahap: modul %d/%d menyala (64 LED), modul lain mati" % (m + 1, self.n), hold

    def _sequence(self):
        W = self.width
        if self.mode == "off":
            yield [0] * W, "Display dimatikan", 1.0
            return
        if self.mode == "step":
            yield from self._steps()
            return
        if self.mode == "text":
            yield from self._scroll(self.text, "Teks Berjalan")
            return
        # --- AUTO TEST ---
        yield from self._steps()
        for r in range(8):
            yield [1 << r] * W, "Scan baris %d/8" % (r + 1), 0.18
        for c in range(W):
            fb = [0] * W
            fb[c] = 0xFF
            yield fb, "Scan kolom %d/%d" % (c + 1, W), 0.05
        for k in range(2 * self.n):   # papan catur per modul, bergantian (32 LED per langkah)
            m = k % self.n
            fb = [0] * W
            for c in range(m * 8, m * 8 + 8):
                fb[c] = 0x55 if (c + k // self.n) % 2 == 0 else 0xAA
            yield fb, "Pola papan catur modul %d" % (m + 1), 0.4
        fb = [0] * W
        for m in range(self.n):
            glyph = text_to_columns(str(m + 1), spacing=0)
            for i, col in enumerate(glyph):
                fb[m * 8 + 1 + i] = col << 1
        yield fb, "Identitas modul 1-%d (kiri -> kanan)" % self.n, 2.0
        yield from self._scroll(self.text, "Teks Berjalan")
        yield [0] * W, "Jeda", 0.3

    def _push(self, fb, phase):
        t0 = time.perf_counter()
        leds = sum(bin(c & 0xFF).count("1") for c in fb)
        level, ma = self._safe_level(leds)
        if level is None:   # bahkan kecerahan 0 melebihi batas -> frame tidak ditampilkan
            fb, leds = [0] * self.width, 0
            level, ma = 0, self.estimate_ma(0, 0)
            phase += " [DIBLOK: melebihi batas arus]"
        if level < self.brightness and not self._limited_logged:
            self._limited_logged = True
            self.hub.add_log("MAX7219: kecerahan dibatasi %d -> %d agar arus <= %d mA (%d LED nyala)"
                             % (self.brightness, level, self.budget_ma, leds), "warn")
        if self.dev:
            try:
                # urutan aman: turunkan kecerahan SEBELUM LED bertambah, naikkan SESUDAH LED berkurang
                if self._hw_level is None or level < self._hw_level:
                    self.dev.set_brightness(level)
                    self._hw_level = level
                self.dev.show(fb)
                if level > self._hw_level:
                    self.dev.set_brightness(level)
                    self._hw_level = level
                if self.error:
                    self.hub.add_log("MAX7219: pengiriman data kembali normal", "ok")
                self.error = None
            except Exception as e:
                if not self.error:
                    self.hub.add_log("MAX7219: %s" % e, "err")
                self.error = str(e)
        dt = (time.perf_counter() - t0) * 1000.0
        with self.lock:
            self.frame = list(fb)
            self.frame_id += 1
            self.frame_t = time.time()
            self.write_ms = dt
            self.phase = phase
            self.leds_on, self.level, self.est_ma = leds, level, ma
            self.peak_ma = max(self.peak_ma, ma)
        self.hub.wake()

    def run(self):
        while not self.hub.stop.is_set():
            self.restart.clear()
            if self.dev:
                try:  # inisialisasi ulang tiap siklus -> pulih otomatis bila modul dicabut/pasang
                    self.dev.init(0)
                    self._hw_level = 0
                except Exception as e:
                    self.error = str(e)
            for fb, phase, hold in self._sequence():
                t0 = time.monotonic()
                self._push(fb, phase)
                wait = max(0.0, hold - (time.monotonic() - t0))
                if self.restart.wait(wait) or self.hub.stop.is_set():
                    break
        if self.dev:
            try:
                self.dev.clear()
            except Exception:
                pass

    def frame_snapshot(self):
        with self.lock:
            return {"id": self.frame_id, "t": self.frame_t, "cols": self.frame, "ms": round(self.write_ms, 2),
                    "phase": self.phase, "leds": self.leds_on, "level": self.level,
                    "ma": round(self.est_ma), "peak_ma": round(self.peak_ma), "budget_ma": round(self.budget_ma)}

    def snapshot(self):
        return {"mode": self.mode, "mode_label": self.MODES.get(self.mode), "text": self.text,
                "brightness": self.brightness, "rotation": self.rotation, "flip": self.flip,
                "reverse": self.reverse, "scroll_ms": self.scroll_ms, "error": self.error,
                "pins": {"CLK": self.cfg.MAX7219_CLK, "CS": self.cfg.MAX7219_CS, "DIN": self.cfg.MAX7219_DIN},
                "width": self.width, "budget_ma": round(self.budget_ma)}
