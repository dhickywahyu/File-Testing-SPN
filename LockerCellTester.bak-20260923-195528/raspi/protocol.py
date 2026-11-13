"""
Protokol RS485 Raspberry Pi <-> ESP32 (ASCII, 8N1).

    Master (Raspberry Pi) -> ESP32 :  >AA,CMD[,ARG]*CC\\n
    ESP32 -> Master               :  <AA,RESP,...*CC\\n

AA = alamat node 2 digit, CC = CRC-8 (poly 0x07, init 0x00) dari teks di antara
karakter awal ('>' / '<') dan '*', ditulis 2 digit HEX. Harus identik dengan
firmware esp32/LockerController/LockerController.ino.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

MASTER_START = ">"
SLAVE_START = "<"


class FrameError(ValueError):
    """Frame rusak: format salah atau CRC tidak cocok."""


class CrcError(FrameError):
    pass


def crc8(data: bytes) -> int:
    """CRC-8/SMBUS: poly 0x07, init 0x00, tanpa refleksi. crc8(b'123456789') == 0xF4."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_frame(start: str, fields: List[str]) -> bytes:
    payload = ",".join(fields)
    return f"{start}{payload}*{crc8(payload.encode('ascii')):02X}\n".encode("ascii")


def build_request(address: int, command: str, *args: object) -> bytes:
    return build_frame(MASTER_START, [f"{address:02d}", command, *(str(a) for a in args)])


def parse_frame(line: bytes, start: str = SLAVE_START) -> List[str]:
    """Validasi satu baris frame dan kembalikan field-nya: ['01', 'STAT', ...]."""
    try:
        text = line.decode("ascii").strip("\r\n")
    except UnicodeDecodeError as exc:
        raise FrameError("karakter non-ASCII") from exc
    if not text.startswith(start):
        raise FrameError(f"karakter awal bukan '{start}'")
    star = text.rfind("*")
    if star < 0 or len(text) - star != 3:
        raise FrameError("checksum tidak ditemukan")
    payload = text[1:star]
    try:
        received = int(text[star + 1:], 16)
    except ValueError as exc:
        raise FrameError("checksum bukan HEX") from exc
    if crc8(payload.encode("ascii")) != received:
        raise CrcError("CRC tidak cocok")
    fields = payload.split(",")
    if len(fields) < 2 or not fields[0].isdigit():
        raise FrameError("field alamat/perintah tidak valid")
    return fields


@dataclass
class Status:
    door_open: List[bool]
    led: List[bool]
    solenoid: List[bool]
    queued: List[bool]
    uptime_s: int


def _bits(text: str, n_cells: int, name: str) -> List[bool]:
    if len(text) != n_cells or any(ch not in "01" for ch in text):
        raise FrameError(f"field {name} tidak valid: {text!r}")
    return [ch == "1" for ch in text]


def parse_status(fields: List[str], n_cells: int) -> Status:
    """fields = ['01', 'STAT', pintu, led, solenoid, antre, uptime]"""
    if len(fields) != 7 or fields[1] != "STAT":
        raise FrameError("balasan STAT tidak valid")
    door = fields[2]
    if len(door) != n_cells or any(ch not in "OC" for ch in door):
        raise FrameError(f"field pintu tidak valid: {door!r}")
    if not fields[6].isdigit():
        raise FrameError("uptime tidak valid")
    return Status(
        door_open=[ch == "O" for ch in door],
        led=_bits(fields[3], n_cells, "LED"),
        solenoid=_bits(fields[4], n_cells, "solenoid"),
        queued=_bits(fields[5], n_cells, "antre"),
        uptime_s=int(fields[6]),
    )
