#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCB QC Tester - Raspberry Pi 4B
Jalankan :  sudo python3 app.py            (hardware asli)
            python3 app.py --sim           (simulasi, bisa di PC/laptop)
UI       :  http://localhost:8080
"""
import argparse
import csv
import json
import mimetypes
import os
import random
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config as CFG  # noqa: E402
from hw.gpio_backend import open_backend  # noqa: E402
from testers import (Hub, DigitalInputMonitor, RelayController, RTCMonitor,  # noqa: E402
                     RS485Tester, DisplayController)

STATIC = os.path.join(BASE, "static")
SETTINGS_FILE = os.path.join(BASE, "settings.json")
REPORT_DIR = os.path.join(BASE, "reports")

QC_NAMES = [
    ("di", "Digital Input (8 label x 2 jalur)"),
    ("relay", "Digital Output - Relay"),
    ("rtc", "RTC DS3231"),
    ("rs485", "RS485 (Raspi <-> ESP32)"),
    ("display", "Mini Display MAX7219"),
]


class App:
    def __init__(self, sim=False):
        self.sim = sim
        self.hub = Hub()
        self.settings = self._load_settings()
        self.gpio = open_backend(sim)
        self.hub.add_log("Program dimulai - backend GPIO: %s" % self.gpio.name, "info")
        self.confirm = {"relay": None, "disp_leds": None, "disp_scroll": None}
        self.meta = {"serial": "", "operator": self.settings.get("operator", "")}
        self.started_at = time.time()
        self.di = DigitalInputMonitor(self.hub, self.gpio, CFG)
        self.relay = RelayController(self.hub, self.gpio, CFG, self.settings)
        self.rtc = RTCMonitor(self.hub, CFG, sim)
        self.rs485 = RS485Tester(self.hub, self.gpio, CFG, sim)
        self.display = DisplayController(self.hub, self.gpio, CFG, self.settings, sim)
        self.threads = [self.di, self.relay, self.rtc, self.rs485, self.display]

    # -- settings -------------------------------------------------------------
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self):
        d = self.display
        s = {"relay_on_s": self.relay.on_s, "relay_off_s": self.relay.off_s,
             "disp_mode": d.mode, "disp_text": d.text, "disp_brightness": d.brightness,
             "disp_rotation": d.rotation, "disp_flip": d.flip, "disp_reverse": d.reverse,
             "disp_scroll_ms": d.scroll_ms, "operator": self.meta.get("operator", "")}
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
        except Exception as e:
            self.hub.add_log("Gagal menyimpan settings: %s" % e, "warn")

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        for t in self.threads:
            t.start()
        if self.sim:
            threading.Thread(target=self._sim_inputs, daemon=True).start()

    def shutdown(self):
        self.hub.stop.set()
        self.relay.running = False
        self.relay.wake.set()
        for t in self.threads:
            t.join(timeout=2)
        try:
            self.relay._apply(False)
        except Exception:
            pass
        self.gpio.close()

    def _sim_inputs(self):
        """Simulasi operator menekan tombol secara acak (hanya mode --sim)."""
        path = {L.name: random.choice(("kiri", "kanan")) for L in self.di.labels}
        while not self.hub.stop.is_set():
            L = random.choice(self.di.labels)
            if random.random() < 0.35:
                path[L.name] = "kanan" if path[L.name] == "kiri" else "kiri"
            pin = getattr(L, path[L.name]).gpio
            self.gpio.sim_set(pin, 1)
            self.hub.stop.wait(random.uniform(0.25, 0.7))
            self.gpio.sim_set(pin, 0)
            self.hub.stop.wait(random.uniform(0.6, 1.8))

    # -- QC -------------------------------------------------------------------
    def _qc_relay(self):
        r, c = self.relay, self.confirm["relay"]
        need = CFG.RELAY_QC_MIN_CYCLES
        if r.error:
            return {"status": "fail", "detail": "GPIO relay error"}
        if c == "fail":
            return {"status": "fail", "detail": "Operator: relay tidak bekerja"}
        if r.cycles >= need and c == "pass":
            return {"status": "pass", "detail": "%d siklus, dikonfirmasi operator" % r.cycles}
        if r.cycles >= need:
            return {"status": "running", "detail": "Menunggu konfirmasi operator"}
        if r.cycles == 0 and not r.running:
            return {"status": "pending", "detail": "Tekan Mulai (min. %d siklus)" % need}
        return {"status": "running", "detail": "Siklus %d/%d" % (r.cycles, need)}

    def _qc_display(self):
        d, a, b = self.display, self.confirm["disp_leds"], self.confirm["disp_scroll"]
        if d.error:
            return {"status": "fail", "detail": "Driver error: " + d.error[:40]}
        if a == "fail" or b == "fail":
            return {"status": "fail", "detail": "Operator: " + ("ada LED mati" if a == "fail" else "teks tidak terbaca")}
        if a == "pass" and b == "pass":
            return {"status": "pass", "detail": "4 modul x 64 LED (bertahap) & teks OK"}
        done = (a == "pass") + (b == "pass")
        return {"status": "running", "detail": "Konfirmasi operator %d/2" % done}

    def qc_snapshot(self):
        res = {"di": self.di.qc(), "relay": self._qc_relay(), "rtc": self.rtc.qc(),
               "rs485": self.rs485.qc(), "display": self._qc_display()}
        items = [dict(key=k, name=n, **res[k]) for k, n in QC_NAMES]
        st = [i["status"] for i in items]
        n_pass = st.count("pass")
        if "fail" in st:
            overall, label = "fail", "TIDAK LULUS QC"
        elif n_pass == len(st):
            overall, label = "pass", "LULUS QC"
        else:
            overall, label = "running", "PENGUJIAN BERLANGSUNG"
        return {"items": items, "overall": overall, "label": label, "n_pass": n_pass, "n_total": len(st)}

    # -- state ----------------------------------------------------------------
    def state(self):
        with self.hub._log_lock:
            log = list(self.hub.log)[-60:]
        return {
            "t": time.time(), "sim": self.sim, "backend": self.gpio.name, "version": self.hub.version,
            "di": self.di.snapshot(), "relay": self.relay.snapshot(), "rtc": self.rtc.snapshot(),
            "rs485": self.rs485.snapshot(), "display": self.display.snapshot(),
            "confirm": self.confirm, "meta": self.meta, "qc": self.qc_snapshot(), "log": log,
        }

    # -- perintah dari UI -------------------------------------------------------
    def command(self, cmd, d):
        h = self.hub
        if cmd == "relay_start":
            if "on_s" in d:
                self.relay.set_times(d["on_s"], d["off_s"])
            ok = self.relay.start_cycle()
            self._save_settings()
            return ok, None if ok else "Relay error: %s" % self.relay.error
        if cmd == "relay_stop":
            self.relay.stop_cycle()
            return True, None
        if cmd == "relay_set":
            self.relay.set_times(d["on_s"], d["off_s"])
            self._save_settings()
            return True, "Waktu relay diterapkan"
        if cmd == "relay_default":
            self.relay.set_times(CFG.RELAY_DEFAULT_ON_S, CFG.RELAY_DEFAULT_OFF_S)
            self._save_settings()
            return True, "Default %.1f s / %.1f s" % (CFG.RELAY_DEFAULT_ON_S, CFG.RELAY_DEFAULT_OFF_S)
        if cmd == "confirm":
            item, val = d.get("item"), d.get("value")
            if item not in self.confirm or val not in ("pass", "fail", None):
                return False, "Parameter salah"
            self.confirm[item] = val
            names = {"relay": "Relay", "disp_leds": "Display - semua LED", "disp_scroll": "Display - teks berjalan"}
            if val:
                h.add_log("Operator: %s -> %s" % (names[item], "OK" if val == "pass" else "GAGAL"),
                          "ok" if val == "pass" else "err")
            h.notify()
            return True, None
        if cmd == "rtc_sys_to_rtc":
            return self.rtc.sys_to_rtc("manual")
        if cmd == "rtc_rtc_to_sys":
            return self.rtc.rtc_to_sys("manual")
        if cmd == "rtc_from_client":
            return self.rtc.set_from_client(float(d["epoch_ms"]))
        if cmd == "disp_set":
            allowed = {k: d[k] for k in ("mode", "text", "brightness", "rotation", "flip", "reverse", "scroll_ms") if k in d}
            self.display.update(**allowed)
            self._save_settings()
            return True, None
        if cmd == "rs485_reset":
            self.rs485.reset()
            return True, "Statistik RS485 direset"
        if cmd == "di_reset":
            self.di.reset()
            return True, "Monitoring digital input direset"
        if cmd == "qc_meta":
            self.meta["serial"] = str(d.get("serial", ""))[:40]
            self.meta["operator"] = str(d.get("operator", ""))[:40]
            self._save_settings()
            h.notify()
            return True, None
        if cmd == "qc_reset":
            self.di.reset()
            self.relay.reset()
            self.rs485.reset()
            self.rtc.reset()
            for k in self.confirm:
                self.confirm[k] = None
            self.meta["serial"] = ""
            h.add_log("=== Pengujian PCB baru dimulai ===", "info")
            return True, "Semua hasil test direset - siap untuk PCB berikutnya"
        if cmd == "qc_save":
            self.meta["serial"] = str(d.get("serial", self.meta["serial"]))[:40]
            self.meta["operator"] = str(d.get("operator", self.meta["operator"]))[:40]
            return self.save_report()
        return False, "Perintah tidak dikenal: %s" % cmd

    def save_report(self):
        os.makedirs(REPORT_DIR, exist_ok=True)
        st = self.state()
        q = st["qc"]
        serial = self.meta["serial"].strip() or "TANPA-SERIAL"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", serial)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        jpath = os.path.join(REPORT_DIR, "QC_%s_%s.json" % (safe, stamp))
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2, ensure_ascii=False)
        cpath = os.path.join(REPORT_DIR, "qc_log.csv")
        new = not os.path.exists(cpath)
        with open(cpath, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.writer(f, delimiter=";")  # ";" = pemisah default Excel regional Indonesia
            if new:
                w.writerow(["waktu", "serial", "operator", "hasil"] + [n for _, n in QC_NAMES] + ["detail"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), serial, self.meta["operator"], q["label"]]
                       + [i["status"].upper() for i in q["items"]]
                       + [" | ".join("%s: %s" % (i["key"], i["detail"]) for i in q["items"])])
        self.hub.add_log("Laporan disimpan: %s (%s)" % (os.path.basename(jpath), q["label"]), "ok")
        return True, "Laporan tersimpan: reports/%s" % os.path.basename(jpath)


APP = None


class Handler(BaseHTTPRequestHandler):
    server_version = "PCBTester/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/static/index.html"
        if path == "/api/state":
            return self._json(APP.state())
        if path == "/api/stream":
            return self._stream()
        if path.startswith("/static/"):
            fp = os.path.normpath(os.path.join(STATIC, path[len("/static/"):]))
            if fp.startswith(STATIC) and os.path.isfile(fp):
                with open(fp, "rb") as f:
                    body = f.read()
                self.send_response(200)
                ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_error(404)

    def do_POST(self):
        if not self.path.startswith("/api/cmd/"):
            return self.send_error(404)
        cmd = self.path[len("/api/cmd/"):]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
            ok, msg = APP.command(cmd, data)
            self._json({"ok": bool(ok), "msg": msg})
        except Exception as e:
            self._json({"ok": False, "msg": "Error: %s" % e}, 500)

    def _send_event(self, name, obj):
        data = json.dumps(obj, separators=(",", ":"))
        self.wfile.write(("event: %s\ndata: %s\n\n" % (name, data)).encode("utf-8"))
        self.wfile.flush()

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        hub = APP.hub
        last_ver, last_frame, last_state = -1, -1, 0.0
        try:
            while not hub.stop.is_set():
                with hub.cond:
                    hub.cond.wait(0.1)
                now = time.monotonic()
                fid = APP.display.frame_id
                if fid != last_frame:
                    self._send_event("display", APP.display.frame_snapshot())
                    last_frame = fid
                if (hub.version != last_ver and now - last_state >= 0.05) or now - last_state >= 0.25:
                    last_ver = hub.version
                    last_state = now
                    self._send_event("state", APP.state())
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass


def main():
    global APP
    ap = argparse.ArgumentParser(description="PCB QC Tester")
    ap.add_argument("--sim", action="store_true", help="mode simulasi tanpa hardware")
    ap.add_argument("--port", type=int, default=CFG.HTTP_PORT)
    args = ap.parse_args()

    APP = App(sim=args.sim)
    APP.start()
    srv = ThreadingHTTPServer((CFG.HTTP_HOST, args.port), Handler)
    srv.daemon_threads = True

    def _stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print("PCB QC Tester berjalan -> buka http://localhost:%d  (%s)" % (args.port, "SIMULASI" if args.sim else APP.gpio.name))
    try:
        srv.serve_forever(poll_interval=0.3)
    finally:
        APP.shutdown()
        srv.server_close()
        print("Program dihentikan, relay OFF.")


if __name__ == "__main__":
    main()
