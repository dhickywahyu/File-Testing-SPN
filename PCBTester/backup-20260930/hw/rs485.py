# -*- coding: utf-8 -*-
"""
Protokol uji RS485 (teks ASCII, sama persis dengan sketch ESP32):
  Raspi -> ESP32 : $PING,<seq>,<payload-hex>*<CRC16>\r\n
  ESP32 -> Raspi : $PONG,<seq>,<payload-hex>,<uptime_ms>,<rx_ok>,<rx_err>*<CRC16>\r\n
  ESP32 -> Raspi : $NACK,<seq>*<CRC16>\r\n   (ESP menerima frame rusak / CRC salah)
CRC16 = CRC-16/MODBUS (poly 0xA001, init 0xFFFF) dari teks antara '$' dan '*'.
"""
import random
import threading
import time


def crc16(text):
    crc = 0xFFFF
    for ch in text.encode("ascii", "replace"):
        crc ^= ch
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def make_frame(body):
    return ("$%s*%04X\r\n" % (body, crc16(body))).encode("ascii")


def parse_frame(line):
    """Kembalikan (fields, crc_ok) atau (None, False) bila format tidak dikenal."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None, False
    body, _, crc_txt = line[1:].rpartition("*")
    try:
        crc_ok = int(crc_txt[:4], 16) == crc16(body)
    except ValueError:
        crc_ok = False
    return body.split(","), crc_ok


class SimSerial:
    """Meniru ESP32 responder: balas PONG dengan delay kecil, sesekali hilang/rusak."""

    def __init__(self, *a, **k):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.rx_ok = 0
        self.t0 = time.monotonic()
        self.port = "SIM"

    def reset_input_buffer(self):
        with self.lock:
            self.buf.clear()

    def write(self, data):
        fields, ok = parse_frame(data.decode("ascii", "replace"))
        if not fields or fields[0] != "PING":
            return len(data)
        roll = random.random()
        if roll < 0.008:
            return len(data)  # hilang -> timeout
        self.rx_ok += 1
        body = "PONG,%s,%s,%d,%d,0" % (fields[1], fields[2], int((time.monotonic() - self.t0) * 1000), self.rx_ok)
        frame = make_frame(body)
        if roll < 0.012:
            frame = frame.replace(b"PONG", b"PXNG")  # simulasi data rusak

        def deliver():
            time.sleep(random.uniform(0.006, 0.012))
            with self.lock:
                self.buf.extend(frame)
        threading.Thread(target=deliver, daemon=True).start()
        return len(data)

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return len(self.buf)

    def read(self, n=1):
        deadline = time.monotonic() + 0.02
        while not self.buf and time.monotonic() < deadline:
            time.sleep(0.001)
        with self.lock:
            out = bytes(self.buf[:n])
            del self.buf[:n]
        return out

    def close(self):
        pass
