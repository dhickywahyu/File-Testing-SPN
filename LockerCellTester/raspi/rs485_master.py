"""
Master RS485 (Raspberry Pi): satu-satunya thread yang berbicara dengan ESP32.

- Polling STAT secara periodik -> status pintu / LED / solenoid / antrean tiap cell.
- Mengirim perintah OPEN / STOP dari UI (antrean prioritas, STOP didahulukan).
- Retry otomatis, deteksi ESP32 offline, deteksi ESP32 restart (uptime reset).
- Mencatat event (log aktivitas) dan melacak hasil test tiap cell:
    Perintah -> Solenoid aktif -> Pintu terbuka -> LED ON -> Pintu tertutup -> LED OFF  => LULUS
"""
from __future__ import annotations

import itertools
import logging
import queue
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from protocol import CrcError, FrameError, Status, build_request, parse_frame, parse_status

log = logging.getLogger("locker")

TEST_STEPS = ["Perintah", "Solenoid", "Pintu terbuka", "LED ON", "Pintu tertutup", "LED OFF"]
S_CMD, S_SOL, S_OPEN, S_LED_ON, S_CLOSE, S_LED_OFF = range(6)

PRIO_STOP, PRIO_NORMAL = 0, 1

MIN_FIRMWARE = (1, 0, 1)   # firmware ESP32 minimum: logika indikator pintu & GPIO20 sudah diperbaiki


def version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def serial_transport_factory(port: str, baudrate: int) -> Callable[[], Any]:
    """Pembuka port serial nyata (pyserial). Contoh port: /dev/serial0, /dev/ttyAMA0, /dev/ttyUSB0."""
    def factory() -> Any:
        try:
            import serial  # pyserial: sudo apt install python3-serial
        except ImportError as exc:
            raise OSError("pyserial belum terpasang (sudo apt install python3-serial)") from exc
        return serial.serial_for_url(port, baudrate=baudrate, bytesize=8, parity="N", stopbits=1,
                                     timeout=0.02, write_timeout=1.0)
    return factory


class LockerMaster:
    def __init__(self, cfg: Dict[str, Any], transport_factory: Callable[[], Any],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.n = int(cfg["num_cells"])
        self.addr = int(cfg["node_address"])
        self.poll_s = cfg["poll_interval_ms"] / 1000.0
        self.timeout_s = cfg["response_timeout_ms"] / 1000.0
        self._factory = transport_factory
        self._clock = clock

        self._lock = threading.RLock()
        self._cmds: "queue.PriorityQueue" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rs485-master", daemon=True)
        self._transport: Any = None

        self._fail_count = 0
        self._need_ping = True
        self._last_status: Optional[Status] = None
        self._last_uptime: Optional[int] = None
        self._last_open_ack = [-1e9] * self.n        # waktu (clock) ACK OPEN / solenoid aktif terakhir per cell
        self._test_t: List[Dict[str, Any]] = [{} for _ in range(self.n)]
        self._last_conn_error = ""
        self._event_id = 0
        self.events: deque = deque(maxlen=300)

        self.link: Dict[str, Any] = {
            "state": "connecting",   # connecting | online | offline | error
            "online": False,
            "port": cfg["serial_port"],
            "baudrate": cfg["baudrate"],
            "address": self.addr,
            "fw": None,
            "reset_reason": None,
            "uptime_s": None,
            "rtt_ms": None,
            "last_ok": None,
            "tx": 0, "rx": 0, "timeouts": 0, "crc_errors": 0, "bad_frames": 0, "echo": 0, "restarts": 0,
            "error": None,
        }
        self.cells: List[Dict[str, Any]] = [self._new_cell(i + 1) for i in range(self.n)]

    # ================================================================ util
    @staticmethod
    def _new_test() -> Dict[str, Any]:
        return {"state": "idle", "steps": [False] * len(TEST_STEPS), "msg": "Belum dites"}

    def _new_cell(self, cell_id: int) -> Dict[str, Any]:
        return {
            "id": cell_id, "door": "unknown", "led": False, "solenoid": False, "queued": False,
            "pending": None, "stale": True, "open_count": 0, "last_change": None,
            "test": self._new_test(),
        }

    def _event(self, level: str, msg: str, cell: Optional[int] = None) -> None:
        with self._lock:
            self._event_id += 1
            self.events.append({"id": self._event_id, "t": time.time(), "level": level, "cell": cell, "msg": msg})
        getattr(log, "error" if level == "error" else "warning" if level == "warn" else "info")(msg)

    # ============================================================ lifecycle
    def start(self) -> None:
        self._event("info", f"Program dimulai. Port {self.cfg['serial_port']} @ {self.cfg['baudrate']} bps, "
                            f"alamat ESP32 {self.addr:02d}")
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=2)
        self._close_transport()

    # ============================================================ API untuk UI
    def request_open(self, cell: int) -> Tuple[bool, str]:
        if not 1 <= cell <= self.n:
            return False, "Nomor cell tidak valid"
        with self._lock:
            if not self.link["online"]:
                return False, "ESP32 belum terhubung"
            c = self.cells[cell - 1]
            if c["pending"] == "sending":
                return False, f"Perintah cell {cell:02d} sedang dikirim"
            c["pending"] = "sending"
        self._cmds.put((PRIO_NORMAL, next(self._seq), ("OPEN", cell)))
        self._event("info", f"Perintah BUKA cell {cell:02d} dikirim ke ESP32", cell)
        return True, f"Perintah buka cell {cell:02d} dikirim"

    def request_open_all(self) -> Tuple[bool, str]:
        with self._lock:
            if not self.link["online"]:
                return False, "ESP32 belum terhubung"
            targets = [c["id"] for c in self.cells if not (c["solenoid"] or c["queued"] or c["pending"])]
            for cid in targets:
                self.cells[cid - 1]["pending"] = "sending"
        for cid in targets:
            self._cmds.put((PRIO_NORMAL, next(self._seq), ("OPEN", cid)))
        self._event("info", f"Buka semua cell berurutan ({len(targets)} perintah)")
        return True, f"{len(targets)} cell akan dibuka berurutan"

    def request_stop(self) -> Tuple[bool, str]:
        while True:                                  # buang semua perintah yang belum terkirim
            try:
                self._cmds.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            for c in self.cells:
                if c["pending"] == "sending":
                    c["pending"] = None
        self._cmds.put((PRIO_STOP, next(self._seq), ("STOP",)))
        return True, "STOP dikirim"

    def reset_tests(self) -> Tuple[bool, str]:
        with self._lock:
            for i, c in enumerate(self.cells):
                c["test"] = self._new_test()
                c["open_count"] = 0
                self._test_t[i] = {}
        self._event("info", "Hasil test direset")
        return True, "Hasil test direset"

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            link = dict(self.link)
            link["last_seen_s"] = (self._clock() - link["last_ok"]) if link["last_ok"] else None
            link.pop("last_ok")
            cells = [dict(c, test=dict(c["test"], steps=list(c["test"]["steps"]))) for c in self.cells]
            tests = [c["test"]["state"] for c in cells]
            summary = {
                "open": sum(c["door"] == "open" for c in cells),
                "closed": sum(c["door"] == "closed" for c in cells),
                "led_on": sum(bool(c["led"]) for c in cells),
                "solenoid_on": sum(bool(c["solenoid"]) for c in cells),
                "queued": sum(bool(c["queued"]) for c in cells),
                "test_pass": tests.count("pass"),
                "test_fail": tests.count("fail"),
                "test_running": tests.count("running"),
            }
            return {
                "server_time": time.time(),
                "simulation": bool(self.cfg.get("simulation")),
                "num_cells": self.n,
                "solenoid_pulse_ms": self.cfg.get("solenoid_pulse_ms", 1000),
                "test_steps": TEST_STEPS,
                "link": link,
                "cells": cells,
                "summary": summary,
                "events": list(self.events)[-80:],
            }

    # ============================================================ thread utama
    def _run(self) -> None:
        next_poll = 0.0
        while not self._stop_evt.is_set():
            if self._transport is None and not self._connect():
                self._stop_evt.wait(self.cfg["reconnect_interval_s"])
                continue
            try:
                try:
                    _, _, cmd = self._cmds.get(timeout=max(0.0, next_poll - self._clock()))
                except queue.Empty:
                    cmd = None
                if cmd is not None:
                    self._execute(cmd)
                    continue
                next_poll = self._clock() + self.poll_s
                if self._need_ping:
                    self._do_ping()
                self._do_stat()
            except OSError as exc:                  # termasuk serial.SerialException
                self._on_transport_error(exc)
            except Exception:                       # jangan biarkan thread mati
                log.exception("Kesalahan tak terduga di thread RS485")
                self._stop_evt.wait(0.5)

    def _connect(self) -> bool:
        try:
            self._transport = self._factory()
        except Exception as exc:  # noqa: BLE001 - tampilkan apa pun penyebabnya di UI
            msg = str(exc) or exc.__class__.__name__
            with self._lock:
                self.link.update(state="error", online=False, error=msg)
            if msg != self._last_conn_error:
                self._event("error", f"Port {self.cfg['serial_port']} tidak bisa dibuka: {msg}")
                self._last_conn_error = msg
            return False
        self._last_conn_error = ""
        self._fail_count = 0
        self._need_ping = True
        with self._lock:
            self.link.update(state="connecting", error=None)
        self._event("info", f"Port {self.cfg['serial_port']} dibuka, menghubungi ESP32…")
        return True

    def _close_transport(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:  # noqa: BLE001
                pass
            self._transport = None

    def _on_transport_error(self, exc: Exception) -> None:
        self._close_transport()
        self._set_offline(f"Port serial error: {exc}")

    # ============================================================ transaksi
    def _transaction(self, command: str, *args: object, expect: Tuple[str, ...], retries: int = 1) -> Optional[List[str]]:
        frame = build_request(self.addr, command, *args)
        t = self._transport
        for _ in range(max(1, retries)):
            t.reset_input_buffer()
            t0 = self._clock()
            t.write(frame)
            with self._lock:
                self.link["tx"] += 1
            fields = self._read_reply(t, expect, t0 + self.timeout_s)
            if fields is not None:
                self._on_reply_ok(self._clock() - t0)
                return fields
            with self._lock:
                self.link["timeouts"] += 1
        self._on_no_reply()
        return None

    def _read_reply(self, t: Any, expect: Tuple[str, ...], deadline: float) -> Optional[List[str]]:
        buf = bytearray()
        while self._clock() < deadline:
            chunk = t.read(1)
            if not chunk:
                continue
            waiting = getattr(t, "in_waiting", 0)
            if waiting:
                chunk += t.read(waiting)
            buf += chunk
            while b"\n" in buf:
                line, _, rest = bytes(buf).partition(b"\n")
                buf = bytearray(rest)
                start = line.find(b"<")
                if start < 0:
                    if line.strip().startswith(b">"):
                        with self._lock:
                            self.link["echo"] += 1   # gema frame sendiri (modul RS485 tertentu)
                    continue
                try:
                    fields = parse_frame(line[start:])
                except CrcError:
                    with self._lock:
                        self.link["crc_errors"] += 1
                    continue
                except FrameError:
                    with self._lock:
                        self.link["bad_frames"] += 1
                    continue
                if int(fields[0]) == self.addr and fields[1] in expect:
                    return fields
                with self._lock:
                    self.link["bad_frames"] += 1
        return None

    def _on_reply_ok(self, rtt_s: float) -> None:
        self._fail_count = 0
        came_online = False
        with self._lock:
            self.link["rx"] += 1
            self.link["rtt_ms"] = round(rtt_s * 1000, 1)
            self.link["last_ok"] = self._clock()
            if not self.link["online"]:
                self.link.update(state="online", online=True, error=None)
                came_online = True
        if came_online:
            self._need_ping = True

    def _on_no_reply(self) -> None:
        self._fail_count += 1
        with self._lock:
            online = self.link["online"]
            connecting = self.link["state"] == "connecting"
        if (online or connecting) and self._fail_count >= self.cfg["offline_after_failures"]:
            self._set_offline("ESP32 tidak merespon. Cek kabel RS485 (A/B), catu daya ESP32, baudrate & alamat.")

    def _set_offline(self, reason: str) -> None:
        with self._lock:
            was_online = self.link["online"]
            already = self.link["state"] == "offline" and self.link["error"] == reason
            self.link.update(state="offline", online=False, error=reason)
            for i, c in enumerate(self.cells):
                c["stale"] = True
                c["pending"] = None
                if c["test"]["state"] == "running":
                    self._finish_test(i, False, "Komunikasi RS485 terputus saat test")
        self._last_status = None
        if not already:
            self._event("error", ("Koneksi ESP32 terputus: " if was_online else "") + reason)

    # ============================================================ perintah
    def _execute(self, cmd: Tuple) -> None:
        if cmd[0] == "OPEN":
            self._cmd_open(cmd[1])
        elif cmd[0] == "STOP":
            fields = self._transaction("STOP", expect=("ACK", "NAK"), retries=self.cfg["command_retries"])
            if fields and fields[1] == "ACK":
                with self._lock:
                    for i, c in enumerate(self.cells):
                        c["pending"] = None
                        if c["test"]["state"] == "running":
                            self._finish_test(i, False, "Dihentikan (STOP)", log_event=False)
                self._event("warn", "STOP: semua solenoid dimatikan & antrean ESP32 dikosongkan")
            else:
                self._event("error", "STOP gagal: ESP32 tidak membalas")

    def _cmd_open(self, cell: int) -> None:
        fields = self._transaction("OPEN", cell, expect=("ACK", "NAK"), retries=self.cfg["command_retries"])
        with self._lock:
            c = self.cells[cell - 1]
            c["pending"] = None
            if fields is None:
                self._event("error", f"Cell {cell:02d}: perintah BUKA gagal, ESP32 tidak membalas", cell)
                return
            if fields[1] == "NAK" or len(fields) < 5 or fields[2] != "OPEN" or fields[3] != str(cell):
                self._event("error", f"Cell {cell:02d}: perintah BUKA ditolak ESP32 ({','.join(fields[1:])})", cell)
                return
            result = fields[4]
            now = self._clock()
            self._last_open_ack[cell - 1] = now
            if result in ("STARTED", "ALREADY_ON"):
                c["solenoid"] = True
                self._event("info", f"Cell {cell:02d}: solenoid AKTIF ({self.cfg.get('solenoid_pulse_ms', 1000)} ms)", cell)
            elif result in ("QUEUED", "ALREADY_QUEUED"):
                c["queued"] = True
                c["pending"] = "queued"
                self._event("info", f"Cell {cell:02d}: masuk antrean (menunggu solenoid lain selesai)", cell)
            else:
                self._event("warn", f"Cell {cell:02d}: balasan tidak dikenal '{result}'", cell)
                return
            if result in ("STARTED", "QUEUED"):
                c["open_count"] += 1
                self._start_test(cell - 1, now)

    def _do_ping(self) -> None:
        fields = self._transaction("PING", expect=("PONG",), retries=1)
        if not fields:
            return
        self._need_ping = False
        fw = fields[2] if len(fields) > 2 else "?"
        reason = fields[4] if len(fields) > 4 else "?"
        with self._lock:
            self.link.update(fw=fw, reset_reason=reason)
        self._event("ok", f"ESP32 terhubung · FW {fw} · reset terakhir: {reason}")
        if version_tuple(fw) < MIN_FIRMWARE:
            self._event("warn", f"Firmware ESP32 v{fw} versi lama: status pintu bisa terbalik. "
                                f"Upload firmware v{'.'.join(map(str, MIN_FIRMWARE))} dari folder esp32/")
        if len(fields) > 3 and fields[3].isdigit() and int(fields[3]) != self.n:
            self._event("error", f"Jumlah cell ESP32 ({fields[3]}) berbeda dengan config ({self.n})")
        if reason in ("BROWNOUT", "PANIC", "WDT"):
            self._event("warn", f"ESP32 terakhir restart karena {reason}. "
                                "Periksa catu daya (drop tegangan saat solenoid aktif?)")

    def _do_stat(self) -> None:
        fields = self._transaction("STAT", expect=("STAT",), retries=1)
        if not fields:
            return
        try:
            status = parse_status(fields, self.n)
        except FrameError as exc:
            with self._lock:
                self.link["bad_frames"] += 1
            log.warning("STAT tidak valid: %s (%s)", exc, fields)
            return
        self._apply_status(status)

    # ============================================================ status & test
    def _apply_status(self, st: Status) -> None:
        now = self._clock()
        with self._lock:
            first = self._last_status is None
            if self._last_uptime is not None and st.uptime_s + 2 < self._last_uptime:
                self.link["restarts"] += 1
                self._need_ping = True
                self._event("warn", "ESP32 restart terdeteksi (uptime kembali ke 0)")
            self._last_uptime = st.uptime_s
            self.link["uptime_s"] = st.uptime_s

            for i, c in enumerate(self.cells):
                cid = i + 1
                door = "open" if st.door_open[i] else "closed"
                if st.solenoid[i] or st.queued[i]:
                    self._last_open_ack[i] = now     # perintah buka masih berjalan (antre/aktif)
                if not first:
                    if c["door"] != door:
                        c["last_change"] = time.time()
                        if door == "open":
                            authorized = now - self._last_open_ack[i] <= self.cfg["unauthorized_open_window_s"]
                            if authorized:
                                self._event("open", f"Cell {cid:02d}: pintu TERBUKA · LED ON", cid)
                            else:
                                self._event("warn", f"Cell {cid:02d}: pintu TERBUKA tanpa perintah "
                                                    "(dibuka paksa / cek sensor pintu) · LED ON", cid)
                        else:
                            self._event("ok", f"Cell {cid:02d}: pintu TERTUTUP · LED OFF", cid)
                    if st.solenoid[i] and not c["solenoid"] and c["queued"]:
                        self._event("info", f"Cell {cid:02d}: solenoid AKTIF (giliran dari antrean)", cid)
                    elif c["solenoid"] and not st.solenoid[i]:
                        self._event("muted", f"Cell {cid:02d}: solenoid OFF", cid)
                elif c["last_change"] is None:
                    c["last_change"] = time.time()
                c.update(door=door, led=st.led[i], solenoid=st.solenoid[i], queued=st.queued[i], stale=False)
                if c["pending"] == "queued" and not st.queued[i]:
                    c["pending"] = None
                self._update_test(i, st, now)
            self._last_status = st
        if first:
            opened = [f"{i + 1:02d}" for i, o in enumerate(st.door_open) if o]
            self._event("info", "Status awal diterima. Pintu terbuka: " + (", ".join(opened) if opened else "tidak ada"))

    def _start_test(self, i: int, now: float) -> None:
        test = self._new_test()
        test.update(state="running", msg="Menunggu solenoid aktif…")
        test["steps"][S_CMD] = True
        c = self.cells[i]
        if c["door"] == "open":
            test["steps"][S_OPEN] = True
            test["steps"][S_LED_ON] = bool(c["led"])
            test["msg"] = "Pintu sudah terbuka sebelum perintah — tutup pintu untuk menyelesaikan test"
        c["test"] = test
        self._test_t[i] = {"start": now, "ref": now, "sol_off": None,
                           "door_open": now if c["door"] == "open" else None, "door_closed": None}

    def _finish_test(self, i: int, passed: bool, msg: str, log_event: bool = True) -> None:
        test = self.cells[i]["test"]
        test.update(state="pass" if passed else "fail", msg=msg)
        if log_event:
            cid = i + 1
            if passed:
                self._event("ok", f"TEST cell {cid:02d} LULUS: solenoid, sensor pintu & LED berfungsi", cid)
            else:
                self._event("error", f"TEST cell {cid:02d} GAGAL: {msg}", cid)

    def _update_test(self, i: int, st: Status, now: float) -> None:
        test = self.cells[i]["test"]
        if test["state"] != "running":
            return
        tt, steps = self._test_t[i], test["steps"]
        if st.queued[i]:
            tt["ref"] = tt["start"] = now      # waktu antre tidak dihitung sebagai waktu test
            test["msg"] = "Menunggu giliran (antrean solenoid)…"
            return
        if st.solenoid[i]:
            steps[S_SOL] = True
            test["msg"] = "Solenoid aktif, menunggu pintu terbuka…"
        elif steps[S_SOL] and tt["sol_off"] is None:
            tt["sol_off"] = now

        if st.door_open[i]:
            if not steps[S_OPEN]:
                steps[S_OPEN] = True
                steps[S_SOL] = True          # pintu terbuka setelah perintah = solenoid bekerja
                tt["door_open"] = now
            if st.led[i]:
                steps[S_LED_ON] = True
            if steps[S_LED_ON]:
                test["msg"] = "Pintu terbuka & LED ON — tutup kembali pintu"
        elif steps[S_OPEN]:
            if not steps[S_CLOSE]:
                steps[S_CLOSE] = True
                tt["door_closed"] = now
            if not st.led[i]:
                steps[S_LED_OFF] = True

        if all(steps):
            self._finish_test(i, True, "Semua fungsi OK")
            return
        cfg = self.cfg
        if not steps[S_SOL] and now - tt["ref"] > cfg["solenoid_detect_timeout_s"]:
            self._finish_test(i, False, "Solenoid tidak terdeteksi aktif")
        elif steps[S_SOL] and not steps[S_OPEN] and tt["sol_off"] is not None \
                and now - tt["sol_off"] > cfg["door_open_timeout_s"]:
            self._finish_test(i, False, "Pintu tidak terbuka setelah solenoid aktif "
                                        "(cek solenoid, mekanik pintu, atau sensor pintu)")
        elif st.door_open[i] and not st.led[i] and tt["door_open"] is not None and now - tt["door_open"] > 1.0:
            self._finish_test(i, False, "LED tidak aktif saat pintu terbuka")
        elif steps[S_CLOSE] and st.led[i] and tt["door_closed"] is not None and now - tt["door_closed"] > 1.0:
            self._finish_test(i, False, "LED tidak mati saat pintu tertutup")
        elif now - tt["start"] > cfg["test_timeout_s"]:
            self._finish_test(i, False, f"Test tidak selesai dalam {cfg['test_timeout_s']} detik: pintu tidak "
                                        "terdeteksi tertutup kembali (cek sensor pintu)")
