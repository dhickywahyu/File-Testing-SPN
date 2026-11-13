#!/usr/bin/env python3
"""
Locker Cell Tester — program Raspberry Pi 4B (kontroler utama).

Menjalankan:
  - thread master RS485 (rs485_master.py) yang berkomunikasi dengan ESP32, dan
  - web server lokal yang menyajikan UI (folder web/) + API JSON untuk UI.
UI ditampilkan di monitor oleh Chromium mode kiosk (lihat kiosk.sh).

Contoh:
  python3 app.py                 # hardware nyata, port dari config.json (/dev/serial0)
  python3 app.py --sim           # mode simulasi tanpa hardware (demo / latihan)
  python3 app.py --port /dev/ttyUSB0
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from esp32_simulator import SimulatedESP32
from rs485_master import LockerMaster, serial_transport_factory

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

DEFAULT_CONFIG: Dict[str, Any] = {
    "serial_port": "/dev/serial0",
    "baudrate": 38400,
    "node_address": 1,
    "num_cells": 10,
    "poll_interval_ms": 150,
    "response_timeout_ms": 200,
    "command_retries": 3,
    "offline_after_failures": 3,
    "reconnect_interval_s": 2,
    "solenoid_pulse_ms": 1000,
    "solenoid_detect_timeout_s": 3,
    "door_open_timeout_s": 4,
    "unauthorized_open_window_s": 10,
    "test_timeout_s": 120,
    "http_host": "127.0.0.1",
    "http_port": 8080,
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def load_config(path: Path) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if path.is_file():
        with path.open(encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def make_handler(master: LockerMaster, sim: Optional[SimulatedESP32]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LockerCellTester/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # jangan banjiri log dengan polling UI
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/state":
                self._json(200, master.snapshot())
                return
            if path == "/":
                path = "/index.html"
            target = (WEB_DIR / path.lstrip("/")).resolve()
            if WEB_DIR not in target.parents or not target.is_file():
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, 4096)) or b"{}") if length else {}
                cell = int(body.get("cell", 0)) if isinstance(body, dict) else 0
            except (ValueError, TypeError):
                self._json(400, {"ok": False, "message": "Request tidak valid"})
                return
            logging.info("HTTP POST %s cell=%s dari %s [%s]", path, cell, self.client_address[0],
                         self.headers.get("User-Agent", "-")[:60])

            if path == "/api/open":
                ok, msg = master.request_open(cell)
            elif path == "/api/open_all":
                ok, msg = master.request_open_all()
            elif path == "/api/stop":
                ok, msg = master.request_stop()
            elif path == "/api/test/reset":
                ok, msg = master.reset_tests()
            elif path == "/api/sim/door" and sim is not None:
                if not 1 <= cell <= sim.num_cells:
                    ok, msg = False, "Nomor cell tidak valid"
                else:
                    is_open = sim.toggle_door(cell)
                    ok, msg = True, f"[SIMULASI] Pintu cell {cell:02d} {'dibuka' if is_open else 'ditutup'}"
            else:
                self._json(404, {"ok": False, "message": "Endpoint tidak ada"})
                return
            self._json(200 if ok else 409, {"ok": ok, "message": msg})

    return Handler


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    file_handler = RotatingFileHandler(log_dir / "locker.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def main() -> int:
    parser = argparse.ArgumentParser(description="Locker Cell Tester (Raspberry Pi + ESP32 via RS485)")
    parser.add_argument("--config", default=str(BASE_DIR / "config.json"), help="file konfigurasi JSON")
    parser.add_argument("--sim", action="store_true", help="mode simulasi tanpa hardware")
    parser.add_argument("--sim-faulty", default="", help="(simulasi) cell rusak, mis. '3,7'")
    parser.add_argument("--port", help="port serial, menimpa config (mis. /dev/ttyAMA0, /dev/ttyUSB0)")
    parser.add_argument("--host", help="alamat web server (default 127.0.0.1 = hanya monitor lokal)")
    parser.add_argument("--http-port", type=int, help="port web server (default 8080)")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.port:
        cfg["serial_port"] = args.port
    if args.host:
        cfg["http_host"] = args.host
    if args.http_port:
        cfg["http_port"] = args.http_port
    setup_logging(BASE_DIR / "logs")

    sim: Optional[SimulatedESP32] = None
    if args.sim:
        faulty = [int(x) for x in args.sim_faulty.split(",") if x.strip().isdigit()]
        sim = SimulatedESP32(num_cells=cfg["num_cells"], address=cfg["node_address"],
                             pulse_s=cfg["solenoid_pulse_ms"] / 1000.0, faulty_cells=faulty)
        cfg["simulation"] = True
        cfg["serial_port"] = "SIMULASI"
        factory = lambda: sim  # noqa: E731
    else:
        factory = serial_transport_factory(cfg["serial_port"], cfg["baudrate"])

    master = LockerMaster(cfg, factory)
    try:
        server = ThreadingHTTPServer((cfg["http_host"], cfg["http_port"]), make_handler(master, sim))
    except OSError as exc:
        logging.error("Web server tidak bisa dijalankan di %s:%s (%s). Program sudah berjalan?",
                      cfg["http_host"], cfg["http_port"], exc)
        return 1
    server.daemon_threads = True

    def shutdown(*_: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    master.start()
    logging.info("UI siap di http://%s:%s %s", cfg["http_host"], cfg["http_port"], "(SIMULASI)" if sim else "")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        master.stop()
        server.server_close()
        logging.info("Program dihentikan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
