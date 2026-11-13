"""
Simulator ESP32 untuk mode demo (--sim) dan pengujian otomatis tanpa hardware.

Logikanya meniru firmware LockerController.ino (antrean solenoid, pulse 1 detik,
LED mengikuti pintu, format balasan & CRC), plus "fisik" sederhana:
pintu terdorong terbuka sesaat setelah solenoid aktif dan (opsional) menutup
sendiri setelah beberapa detik. Objek ini berperilaku seperti port serial
(write / read / in_waiting / reset_input_buffer / close).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Iterable, List, Optional

from protocol import MASTER_START, SLAVE_START, CrcError, FrameError, build_frame, parse_frame


class _SimCell:
    def __init__(self) -> None:
        self.solenoid = False
        self.solenoid_at = 0.0
        self.queued = False
        self.door_open = False
        self.led = False
        self.open_at: Optional[float] = None   # jadwal pintu terdorong terbuka
        self.close_at: Optional[float] = None  # jadwal pintu menutup sendiri


class SimulatedESP32:
    def __init__(
        self,
        num_cells: int = 10,
        address: int = 1,
        pulse_s: float = 1.0,
        max_active: int = 1,
        open_delay_s: float = 0.25,
        auto_close_s: float = 5.0,
        faulty_cells: Iterable[int] = (),
        latency_s: float = 0.003,
        read_timeout_s: float = 0.02,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.num_cells = num_cells
        self.address = address
        self.pulse_s = pulse_s
        self.max_active = max_active
        self.open_delay_s = open_delay_s
        self.auto_close_s = auto_close_s
        self.faulty_cells = set(faulty_cells)
        self.latency_s = latency_s
        self.timeout = read_timeout_s
        self.clock = clock
        self.online = True             # False = ESP32 "mati" / kabel putus (tidak membalas)
        self.fw_version = "1.0.1-sim"
        self.reset_reason = "POWERON"

        self._cond = threading.Condition(threading.RLock())
        self._rx = bytearray()
        self._pending: List[tuple] = []   # (siap_pada, bytes)
        self._tx = bytearray()
        self._queue: deque = deque()
        self._boot_at = clock()
        self.cells = [_SimCell() for _ in range(num_cells)]
        self.history: List[int] = []      # urutan cell yang solenoid-nya aktif (untuk pengujian)

    # ------------------------------------------------------------------ fisik
    def _start_solenoid(self, i: int, now: float) -> None:
        c = self.cells[i]
        c.solenoid, c.solenoid_at = True, now
        self.history.append(i + 1)
        if not c.door_open and (i + 1) not in self.faulty_cells:
            c.open_at = now + self.open_delay_s

    def _set_door(self, i: int, is_open: bool, now: float) -> None:
        c = self.cells[i]
        c.door_open = is_open
        c.led = is_open                      # LED mengikuti pintu, sama seperti firmware
        c.open_at = None
        c.close_at = now + self.auto_close_s if (is_open and self.auto_close_s > 0) else None

    def _update(self, now: float) -> None:
        for i, c in enumerate(self.cells):
            if c.solenoid and now - c.solenoid_at >= self.pulse_s:
                c.solenoid = False
            if c.open_at is not None and now >= c.open_at:
                self._set_door(i, True, now)
            if c.close_at is not None and now >= c.close_at:
                self._set_door(i, False, now)
        while self._queue and sum(c.solenoid for c in self.cells) < self.max_active:
            i = self._queue.popleft()
            self.cells[i].queued = False
            self._start_solenoid(i, now)

    # --------------------------------------------------------------- protokol
    def _request_open(self, i: int, now: float) -> str:
        c = self.cells[i]
        if c.solenoid:
            return "ALREADY_ON"
        if c.queued:
            return "ALREADY_QUEUED"
        if not self._queue and sum(x.solenoid for x in self.cells) < self.max_active:
            self._start_solenoid(i, now)
            return "STARTED"
        self._queue.append(i)
        c.queued = True
        return "QUEUED"

    def _handle(self, line: bytes, now: float) -> Optional[List[str]]:
        try:
            fields = parse_frame(line, start=MASTER_START)
        except (CrcError, FrameError):
            return None                      # firmware mengabaikan frame rusak
        if int(fields[0]) != self.address:
            return None
        addr, cmd, args = f"{self.address:02d}", fields[1], fields[2:]
        if cmd == "STAT":
            door = "".join("O" if c.door_open else "C" for c in self.cells)
            bits = lambda attr: "".join("1" if getattr(c, attr) else "0" for c in self.cells)  # noqa: E731
            uptime = int(now - self._boot_at)
            return [addr, "STAT", door, bits("led"), bits("solenoid"), bits("queued"), str(uptime)]
        if cmd == "OPEN":
            n = int(args[0]) if args and args[0].isdigit() else -1
            if not 1 <= n <= self.num_cells:
                return [addr, "NAK", "OPEN", "BADARG"]
            return [addr, "ACK", "OPEN", str(n), self._request_open(n - 1, now)]
        if cmd == "STOP":
            for c in self.cells:
                c.solenoid = c.queued = False
                c.open_at = None
            self._queue.clear()
            return [addr, "ACK", "STOP"]
        if cmd == "PING":
            return [addr, "PONG", self.fw_version, str(self.num_cells), self.reset_reason]
        return [addr, "NAK", cmd, "UNKNOWN"]

    # --------------------------------------------------- antarmuka port serial
    def write(self, data: bytes) -> int:
        with self._cond:
            now = self.clock()
            self._update(now)
            if not self.online:
                return len(data)
            for b in data:
                ch = bytes([b])
                if ch == MASTER_START.encode():
                    self._rx = bytearray(ch)
                elif not self._rx:
                    continue
                elif ch == b"\n":
                    reply = self._handle(bytes(self._rx), now)
                    self._rx = bytearray()
                    if reply is not None:
                        self._pending.append((now + self.latency_s, build_frame(SLAVE_START, reply)))
                elif ch != b"\r":
                    self._rx += ch
            self._cond.notify_all()
        return len(data)

    def _release_pending(self) -> None:
        now = self.clock()
        ready = [p for p in self._pending if p[0] <= now]
        self._pending = [p for p in self._pending if p[0] > now]
        for _, frame in ready:
            self._tx += frame

    @property
    def in_waiting(self) -> int:
        with self._cond:
            self._release_pending()
            return len(self._tx)

    def read(self, size: int = 1) -> bytes:
        deadline = time.monotonic() + (self.timeout or 0)
        with self._cond:
            while True:
                self._release_pending()
                if self._tx:
                    out = bytes(self._tx[:size])
                    del self._tx[:size]
                    return out
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cond.wait(min(remaining, 0.002))

    def reset_input_buffer(self) -> None:
        with self._cond:
            self._tx.clear()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    # ----------------------------------------------------- kontrol simulasi
    def toggle_door(self, cell: int) -> bool:
        with self._cond:
            now = self.clock()
            self._update(now)
            c = self.cells[cell - 1]
            self._set_door(cell - 1, not c.door_open, now)
            return c.door_open

    def set_door(self, cell: int, is_open: bool) -> None:
        with self._cond:
            now = self.clock()
            self._update(now)
            self._set_door(cell - 1, is_open, now)

    def reboot(self, reason: str = "BROWNOUT") -> None:
        with self._cond:
            now = self.clock()
            self._boot_at = now
            self.reset_reason = reason
            self._queue.clear()
            for c in self.cells:
                c.solenoid = c.queued = False
                c.open_at = None

    def tick(self) -> None:
        with self._cond:
            self._update(self.clock())
