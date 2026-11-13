#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 MAX7219 32x8 (4x 8x8 cascade) - Raspberry Pi 4B - BIT-BANG SPI
 Test Program: Running Text & Static Text untuk Display Tarif Parkir
=============================================================================

 WIRING (bit-bang, BUKAN hardware SPI):

   MAX7219 modul        Raspberry Pi 4B (BCM numbering)
   -------------        -------------------------------
   VCC  ----------->    5V eksternal (buck converter, BUKAN AMS1117)
   GND  ----------->    GND (pin 6/9/14/...) + GND supply disatukan
   DIN  ----------->    GPIO19  (pin 35)   [via level shifter 74HCT125]
   CLK  ----------->    GPIO23  (pin 16)   [via level shifter 74HCT125]
   CS   ----------->    GPIO24  (pin 18)   [via level shifter 74HCT125]

 CATATAN PENTING:
   * GPIO19/23/24 TIDAK punya fungsi alternatif SPI MOSI/SCLK/CE di BCM2711.
     Karena itu program ini memakai software SPI (bit-bang) murni.
     Tidak perlu `raspi-config` -> enable SPI. Tidak perlu spidev.
   * MAX7219 VIH minimum = 3.5V. GPIO Pi hanya 3.3V -> DI BAWAH SPEC.
     Gunakan buffer 74HCT125 (supply 5V) ATAU turunkan V+ modul ke 4.2-4.5V.
   * AMS1117-5.0 TIDAK BOLEH dipakai sebagai supply display (lihat analisis).

 PEMAKAIAN:
   python3 max7219_tarif_parkir.py --mode selftest
   python3 max7219_tarif_parkir.py --mode orient          # cari orientasi
   python3 max7219_tarif_parkir.py --mode static --text "5.000"
   python3 max7219_tarif_parkir.py --mode scroll --text "TARIF PARKIR MOBIL Rp5.000/JAM"
   python3 max7219_tarif_parkir.py --mode tarif           # demo aplikasi
   python3 max7219_tarif_parkir.py --mode clear

 Author: dibuat untuk Dhicky - PT Solusi Parkir Nusantara
=============================================================================
"""

import argparse
import sys
import time

# ----------------------------------------------------------------------------
# KONFIGURASI DEFAULT
# ----------------------------------------------------------------------------
PIN_DIN = 19
PIN_CLK = 23
PIN_CS = 24
CASCADE = 4          # jumlah chip MAX7219 (4 x 8x8 = 32x8)
DEFAULT_ORIENT = 0   # 0..15, cari nilai yang benar dengan --mode orient
DEFAULT_INTENSITY = 3  # 0..15. JAGA RENDAH bila supply terbatas!

# Register MAX7219
REG_NOOP = 0x00
REG_DIGIT0 = 0x01
REG_DECODEMODE = 0x09
REG_INTENSITY = 0x0A
REG_SCANLIMIT = 0x0B
REG_SHUTDOWN = 0x0C
REG_DISPLAYTEST = 0x0F


# ============================================================================
# FONT 5x7  (tiap karakter = 5 kolom, bit0 = baris paling atas)
# ============================================================================
FONT = {
    ' ': [0x00, 0x00, 0x00, 0x00, 0x00],
    '!': [0x00, 0x00, 0x5F, 0x00, 0x00],
    '"': [0x00, 0x07, 0x00, 0x07, 0x00],
    '#': [0x14, 0x7F, 0x14, 0x7F, 0x14],
    '$': [0x24, 0x2A, 0x7F, 0x2A, 0x12],
    '%': [0x23, 0x13, 0x08, 0x64, 0x62],
    '&': [0x36, 0x49, 0x55, 0x22, 0x50],
    "'": [0x00, 0x05, 0x03, 0x00, 0x00],
    '(': [0x00, 0x1C, 0x22, 0x41, 0x00],
    ')': [0x00, 0x41, 0x22, 0x1C, 0x00],
    '*': [0x14, 0x08, 0x3E, 0x08, 0x14],
    '+': [0x08, 0x08, 0x3E, 0x08, 0x08],
    ',': [0x00, 0x50, 0x30, 0x00, 0x00],
    '-': [0x08, 0x08, 0x08, 0x08, 0x08],
    '.': [0x00, 0x60, 0x60, 0x00, 0x00],
    '/': [0x20, 0x10, 0x08, 0x04, 0x02],
    '0': [0x3E, 0x51, 0x49, 0x45, 0x3E],
    '1': [0x00, 0x42, 0x7F, 0x40, 0x00],
    '2': [0x42, 0x61, 0x51, 0x49, 0x46],
    '3': [0x21, 0x41, 0x45, 0x4B, 0x31],
    '4': [0x18, 0x14, 0x12, 0x7F, 0x10],
    '5': [0x27, 0x45, 0x45, 0x45, 0x39],
    '6': [0x3C, 0x4A, 0x49, 0x49, 0x30],
    '7': [0x01, 0x71, 0x09, 0x05, 0x03],
    '8': [0x36, 0x49, 0x49, 0x49, 0x36],
    '9': [0x06, 0x49, 0x49, 0x29, 0x1E],
    ':': [0x00, 0x36, 0x36, 0x00, 0x00],
    ';': [0x00, 0x56, 0x36, 0x00, 0x00],
    '<': [0x08, 0x14, 0x22, 0x41, 0x00],
    '=': [0x14, 0x14, 0x14, 0x14, 0x14],
    '>': [0x00, 0x41, 0x22, 0x14, 0x08],
    '?': [0x02, 0x01, 0x51, 0x09, 0x06],
    '@': [0x32, 0x49, 0x79, 0x41, 0x3E],
    'A': [0x7E, 0x11, 0x11, 0x11, 0x7E],
    'B': [0x7F, 0x49, 0x49, 0x49, 0x36],
    'C': [0x3E, 0x41, 0x41, 0x41, 0x22],
    'D': [0x7F, 0x41, 0x41, 0x22, 0x1C],
    'E': [0x7F, 0x49, 0x49, 0x49, 0x41],
    'F': [0x7F, 0x09, 0x09, 0x09, 0x01],
    'G': [0x3E, 0x41, 0x49, 0x49, 0x7A],
    'H': [0x7F, 0x08, 0x08, 0x08, 0x7F],
    'I': [0x00, 0x41, 0x7F, 0x41, 0x00],
    'J': [0x20, 0x40, 0x41, 0x3F, 0x01],
    'K': [0x7F, 0x08, 0x14, 0x22, 0x41],
    'L': [0x7F, 0x40, 0x40, 0x40, 0x40],
    'M': [0x7F, 0x02, 0x0C, 0x02, 0x7F],
    'N': [0x7F, 0x04, 0x08, 0x10, 0x7F],
    'O': [0x3E, 0x41, 0x41, 0x41, 0x3E],
    'P': [0x7F, 0x09, 0x09, 0x09, 0x06],
    'Q': [0x3E, 0x41, 0x51, 0x21, 0x5E],
    'R': [0x7F, 0x09, 0x19, 0x29, 0x46],
    'S': [0x46, 0x49, 0x49, 0x49, 0x31],
    'T': [0x01, 0x01, 0x7F, 0x01, 0x01],
    'U': [0x3F, 0x40, 0x40, 0x40, 0x3F],
    'V': [0x1F, 0x20, 0x40, 0x20, 0x1F],
    'W': [0x3F, 0x40, 0x38, 0x40, 0x3F],
    'X': [0x63, 0x14, 0x08, 0x14, 0x63],
    'Y': [0x07, 0x08, 0x70, 0x08, 0x07],
    'Z': [0x61, 0x51, 0x49, 0x45, 0x43],
    '[': [0x00, 0x7F, 0x41, 0x41, 0x00],
    ']': [0x00, 0x41, 0x41, 0x7F, 0x00],
    '_': [0x40, 0x40, 0x40, 0x40, 0x40],
    'a': [0x20, 0x54, 0x54, 0x54, 0x78],
    'b': [0x7F, 0x48, 0x44, 0x44, 0x38],
    'c': [0x38, 0x44, 0x44, 0x44, 0x20],
    'd': [0x38, 0x44, 0x44, 0x48, 0x7F],
    'e': [0x38, 0x54, 0x54, 0x54, 0x18],
    'f': [0x08, 0x7E, 0x09, 0x01, 0x02],
    'g': [0x0C, 0x52, 0x52, 0x52, 0x3E],
    'h': [0x7F, 0x08, 0x04, 0x04, 0x78],
    'i': [0x00, 0x44, 0x7D, 0x40, 0x00],
    'j': [0x20, 0x40, 0x44, 0x3D, 0x00],
    'k': [0x7F, 0x10, 0x28, 0x44, 0x00],
    'l': [0x00, 0x41, 0x7F, 0x40, 0x00],
    'm': [0x7C, 0x04, 0x18, 0x04, 0x78],
    'n': [0x7C, 0x08, 0x04, 0x04, 0x78],
    'o': [0x38, 0x44, 0x44, 0x44, 0x38],
    'p': [0x7C, 0x14, 0x14, 0x14, 0x08],
    'q': [0x08, 0x14, 0x14, 0x18, 0x7C],
    'r': [0x7C, 0x08, 0x04, 0x04, 0x08],
    's': [0x48, 0x54, 0x54, 0x54, 0x20],
    't': [0x04, 0x3F, 0x44, 0x40, 0x20],
    'u': [0x3C, 0x40, 0x40, 0x20, 0x7C],
    'v': [0x1C, 0x20, 0x40, 0x20, 0x1C],
    'w': [0x3C, 0x40, 0x30, 0x40, 0x3C],
    'x': [0x44, 0x28, 0x10, 0x28, 0x44],
    'y': [0x0C, 0x50, 0x50, 0x50, 0x3C],
    'z': [0x44, 0x64, 0x54, 0x4C, 0x44],
}

# Font angka 3x5 (narrow) -- untuk menampilkan lebih banyak digit di 32 kolom
FONT_NARROW = {
    ' ': [0x00, 0x00, 0x00],
    '0': [0x1F, 0x11, 0x1F],
    '1': [0x00, 0x1F, 0x00],
    '2': [0x1D, 0x15, 0x17],
    '3': [0x15, 0x15, 0x1F],
    '4': [0x07, 0x04, 0x1F],
    '5': [0x17, 0x15, 0x1D],
    '6': [0x1F, 0x15, 0x1D],
    '7': [0x01, 0x01, 0x1F],
    '8': [0x1F, 0x15, 0x1F],
    '9': [0x17, 0x15, 0x1F],
    '.': [0x00, 0x10, 0x00],
    ':': [0x00, 0x0A, 0x00],
    '-': [0x04, 0x04, 0x04],
    '/': [0x18, 0x04, 0x03],
    'R': [0x1F, 0x05, 0x1A],
    'p': [0x1F, 0x05, 0x02],
}


# ============================================================================
# GPIO BACKEND  (lgpio -> RPi.GPIO -> pigpio)
# ============================================================================
class _Lgpio:
    name = "lgpio"

    def __init__(self):
        import lgpio
        self.lg = lgpio
        self.h = None
        self.pins = []

    def setup(self, pins):
        err = None
        for chip in (0, 4):
            try:
                self.h = self.lg.gpiochip_open(chip)
                break
            except Exception as e:      # noqa: BLE001
                err = e
        if self.h is None:
            raise RuntimeError("lgpio: gagal membuka gpiochip: %s" % err)
        self.pins = list(pins)
        for p in self.pins:
            self.lg.gpio_claim_output(self.h, p, 0)

    def write(self, pin, val):
        self.lg.gpio_write(self.h, pin, val)

    def cleanup(self):
        if self.h is None:
            return
        for p in self.pins:
            try:
                self.lg.gpio_free(self.h, p)
            except Exception:           # noqa: BLE001
                pass
        self.lg.gpiochip_close(self.h)
        self.h = None


class _RpiGpio:
    name = "RPi.GPIO"

    def __init__(self):
        import RPi.GPIO as GPIO
        self.G = GPIO

    def setup(self, pins):
        self.G.setwarnings(False)
        self.G.setmode(self.G.BCM)
        for p in pins:
            self.G.setup(p, self.G.OUT, initial=self.G.LOW)

    def write(self, pin, val):
        self.G.output(pin, val)

    def cleanup(self):
        self.G.cleanup()


class _Pigpio:
    name = "pigpio"

    def __init__(self):
        import pigpio
        self.pigpio = pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon tidak jalan (sudo pigpiod)")

    def setup(self, pins):
        for p in pins:
            self.pi.set_mode(p, self.pigpio.OUTPUT)
            self.pi.write(p, 0)

    def write(self, pin, val):
        self.pi.write(pin, val)

    def cleanup(self):
        self.pi.stop()


def make_backend(prefer=None):
    """Pilih backend GPIO yang tersedia. lgpio paling cepat & paling kompatibel
    dengan Raspberry Pi OS Bookworm ke atas."""
    order = [_Lgpio, _RpiGpio, _Pigpio]
    if prefer:
        byname = {"lgpio": _Lgpio, "rpigpio": _RpiGpio, "pigpio": _Pigpio}
        cls = byname.get(prefer.lower())
        if cls is None:
            raise SystemExit("Backend tidak dikenal: %s" % prefer)
        order = [cls]
    errs = []
    for cls in order:
        try:
            return cls()
        except Exception as e:          # noqa: BLE001
            errs.append("%s: %s" % (cls.name, e))
    raise SystemExit(
        "Tidak ada backend GPIO yang bisa dipakai.\n  " + "\n  ".join(errs) +
        "\n\nInstall salah satu:\n"
        "  sudo apt install python3-lgpio        (direkomendasikan)\n"
        "  sudo apt install python3-rpi-lgpio    (shim RPi.GPIO untuk Bookworm)\n"
        "  sudo apt install pigpio python3-pigpio && sudo systemctl enable --now pigpiod\n")


# ============================================================================
# DRIVER MAX7219 (bit-bang)
# ============================================================================
class Max7219:
    """Driver MAX7219 cascade dengan software SPI.

    Frame buffer disimpan sebagai list kolom; tiap kolom 1 byte,
    bit0 = baris paling atas, bit7 = baris paling bawah.
    """

    def __init__(self, gpio, din=PIN_DIN, clk=PIN_CLK, cs=PIN_CS,
                 cascade=CASCADE, orient=DEFAULT_ORIENT,
                 intensity=DEFAULT_INTENSITY):
        self.gpio = gpio
        self.din, self.clk, self.cs = din, clk, cs
        self.cascade = cascade
        self.width = cascade * 8
        self.height = 8
        self.set_orient(orient)
        self.buf = [0] * self.width

        self.gpio.setup([din, clk, cs])
        self.gpio.write(self.cs, 1)
        self.gpio.write(self.clk, 0)
        self._init_chips(intensity)

    # ---------------- orientasi ----------------
    def set_orient(self, orient):
        """orient = 4 bit:
             bit0 transpose   (digit = baris, bukan kolom)
             bit1 rev_digit   (balik urutan digit/kolom dalam blok)
             bit2 rev_bit     (balik urutan bit dalam byte)
             bit3 rev_chip    (balik urutan blok dalam rantai)"""
        self.orient = orient & 0x0F
        self.transpose = bool(orient & 0x01)
        self.rev_digit = bool(orient & 0x02)
        self.rev_bit = bool(orient & 0x04)
        self.rev_chip = bool(orient & 0x08)

    # ---------------- low level ----------------
    def _shift_byte(self, b):
        w = self.gpio.write
        din, clk = self.din, self.clk
        for i in (7, 6, 5, 4, 3, 2, 1, 0):
            w(din, (b >> i) & 1)
            w(clk, 1)          # data di-latch pada rising edge CLK
            w(clk, 0)

    def _send(self, packets):
        """packets[i] = (addr, data) untuk chip ke-i, i=0 adalah chip
        yang paling dekat dengan DIN. Paket pertama yang dikirim akan
        berakhir di chip paling ujung rantai, karena itu di-reverse."""
        self.gpio.write(self.cs, 0)
        for addr, data in reversed(packets):
            self._shift_byte(addr)
            self._shift_byte(data)
        self.gpio.write(self.cs, 1)

    def _broadcast(self, reg, val):
        self._send([(reg, val)] * self.cascade)

    def _init_chips(self, intensity):
        self._broadcast(REG_DISPLAYTEST, 0x00)   # keluar dari mode test
        self._broadcast(REG_SCANLIMIT, 0x07)     # scan 8 digit (baris/kolom)
        self._broadcast(REG_DECODEMODE, 0x00)    # no decode (matrix mode)
        self._broadcast(REG_INTENSITY, intensity & 0x0F)
        self._broadcast(REG_SHUTDOWN, 0x01)      # normal operation
        self.clear()
        self.flush()

    # ---------------- kontrol ----------------
    def set_intensity(self, level):
        self._broadcast(REG_INTENSITY, max(0, min(15, int(level))))

    def shutdown(self, on=True):
        self._broadcast(REG_SHUTDOWN, 0x00 if on else 0x01)

    def display_test(self, on=True):
        self._broadcast(REG_DISPLAYTEST, 0x01 if on else 0x00)

    def clear(self):
        self.buf = [0] * self.width

    def fill(self):
        self.buf = [0xFF] * self.width

    # ---------------- render ----------------
    def flush(self):
        n = self.cascade
        for d in range(8):
            packets = []
            for chip in range(n):
                blk = (n - 1 - chip) if self.rev_chip else chip
                base = blk * 8
                di = (7 - d) if self.rev_digit else d
                bits = []
                if self.transpose:
                    # digit = baris di -> ambil 8 kolom pada baris itu
                    for c in range(8):
                        bits.append((self.buf[base + c] >> di) & 1)
                else:
                    # digit = kolom di -> ambil 8 baris pada kolom itu
                    col = self.buf[base + di]
                    for r in range(8):
                        bits.append((col >> r) & 1)
                if self.rev_bit:
                    bits.reverse()
                val = 0
                for i, b in enumerate(bits):
                    if b:
                        val |= 1 << (7 - i)
                packets.append((REG_DIGIT0 + d, val))
            self._send(packets)

    # ---------------- gambar ----------------
    def set_pixel(self, x, y, on=True):
        if 0 <= x < self.width and 0 <= y < 8:
            if on:
                self.buf[x] |= (1 << y)
            else:
                self.buf[x] &= ~(1 << y) & 0xFF

    def blit(self, cols, x=0):
        for i, c in enumerate(cols):
            xi = x + i
            if 0 <= xi < self.width:
                self.buf[xi] = c & 0xFF

    def cleanup(self):
        try:
            self.clear()
            self.flush()
            self.shutdown(False)
        except Exception:               # noqa: BLE001
            pass
        self.gpio.cleanup()


# ============================================================================
# TEXT RENDERING
# ============================================================================
def text_columns(text, spacing=1, narrow=False, y_offset=1):
    """Ubah string jadi list kolom byte. y_offset menggeser font 7 baris
    ke bawah 1 piksel supaya terlihat center di matriks 8 baris."""
    table = FONT_NARROW if narrow else FONT
    cols = []
    for ch in text:
        glyph = table.get(ch)
        if glyph is None:
            glyph = table.get(ch.upper())
        if glyph is None:
            glyph = table.get(ch.lower())
        if glyph is None:
            glyph = table[' ']
        for c in glyph:
            cols.append((c << y_offset) & 0xFF)
        cols.extend([0] * spacing)
    if cols and spacing:
        cols = cols[:-spacing]
    return cols


def show_static(dev, text, narrow=False, align="center"):
    """Tampilkan teks diam. Return True bila muat, False bila kepanjangan."""
    cols = text_columns(text, narrow=narrow)
    dev.clear()
    if len(cols) > dev.width:
        dev.blit(cols[:dev.width], 0)
        dev.flush()
        return False
    if align == "left":
        x = 0
    elif align == "right":
        x = dev.width - len(cols)
    else:
        x = (dev.width - len(cols)) // 2
    dev.blit(cols, x)
    dev.flush()
    return True


def scroll_text(dev, text, speed=0.04, loops=1, narrow=False, gap=None):
    """Running text dari kanan ke kiri."""
    if gap is None:
        gap = dev.width
    cols = [0] * gap + text_columns(text, narrow=narrow) + [0] * gap
    total = len(cols)
    count = 0
    while loops <= 0 or count < loops:
        for start in range(total - dev.width + 1):
            dev.buf = cols[start:start + dev.width]
            dev.flush()
            time.sleep(speed)
        count += 1


# ============================================================================
# TARIF PARKIR
# ============================================================================
TARIF = {
    "MOTOR": {"jam1": 2000, "jam_berikut": 1000, "maks": 10000},
    "MOBIL": {"jam1": 5000, "jam_berikut": 3000, "maks": 40000},
}


def format_rupiah(nilai):
    return "{:,}".format(int(nilai)).replace(",", ".")


def hitung_tarif(jenis, menit):
    t = TARIF[jenis]
    jam = max(1, -(-int(menit) // 60))          # pembulatan ke atas
    total = t["jam1"] + (jam - 1) * t["jam_berikut"]
    return min(total, t["maks"]), jam


# ============================================================================
# MODE TEST
# ============================================================================
def mode_selftest(dev):
    print("[1/6] Display test register -- SEMUA LED harus menyala penuh")
    dev.display_test(True)
    time.sleep(2)
    dev.display_test(False)
    time.sleep(0.5)

    print("[2/6] Sweep kolom kiri -> kanan (cek urutan & orientasi chip)")
    for x in range(dev.width):
        dev.clear()
        for y in range(8):
            dev.set_pixel(x, y, True)
        dev.flush()
        time.sleep(0.03)

    print("[3/6] Sweep baris atas -> bawah")
    for y in range(8):
        dev.clear()
        for x in range(dev.width):
            dev.set_pixel(x, y, True)
        dev.flush()
        time.sleep(0.15)

    print("[4/6] Titik diagonal")
    dev.clear()
    for x in range(dev.width):
        dev.set_pixel(x, x % 8, True)
    dev.flush()
    time.sleep(1.5)

    print("[5/6] Sweep brightness 0 -> 15 (amati kestabilan supply)")
    dev.fill()
    dev.flush()
    for lv in range(16):
        dev.set_intensity(lv)
        print("      intensity = %2d" % lv)
        time.sleep(0.35)
    dev.set_intensity(DEFAULT_INTENSITY)

    print("[6/6] Static text + running text")
    show_static(dev, "TEST")
    time.sleep(1.5)
    scroll_text(dev, "MAX7219 OK", loops=1)
    dev.clear()
    dev.flush()
    print("Selftest selesai.")


def mode_orient(dev):
    """Cari nilai --orient yang benar untuk modul Anda."""
    print("\nMencari orientasi yang benar.")
    print("Amati display: yang BENAR menampilkan '1234' tegak, berurutan")
    print("dari kiri ke kanan, tidak terbalik/tercermin.\n")
    for o in range(16):
        dev.set_orient(o)
        show_static(dev, "1234")
        print("  orient = %2d   (transpose=%d rev_digit=%d rev_bit=%d rev_chip=%d)"
              % (o, o & 1, (o >> 1) & 1, (o >> 2) & 1, (o >> 3) & 1))
        time.sleep(2.5)
    dev.clear()
    dev.flush()
    print("\nCatat nilai yang benar, lalu jalankan dengan --orient <nilai>,")
    print("atau ubah DEFAULT_ORIENT di bagian atas file ini.")


def mode_tarif(dev, speed):
    """Demo aplikasi: siklus tampilan tarif parkir."""
    print("Demo tarif parkir. Ctrl+C untuk berhenti.")
    while True:
        for jenis in ("MOTOR", "MOBIL"):
            t = TARIF[jenis]
            scroll_text(dev, "TARIF %s" % jenis, speed=speed, loops=1)
            show_static(dev, format_rupiah(t["jam1"]))
            time.sleep(2.0)
            scroll_text(dev,
                        "JAM I Rp%s - BERIKUTNYA Rp%s/JAM - MAKS Rp%s"
                        % (format_rupiah(t["jam1"]),
                           format_rupiah(t["jam_berikut"]),
                           format_rupiah(t["maks"])),
                        speed=speed, loops=1)
        # contoh perhitungan transaksi
        total, jam = hitung_tarif("MOBIL", 185)
        scroll_text(dev, "DURASI %d JAM - BAYAR Rp%s"
                    % (jam, format_rupiah(total)), speed=speed, loops=1)
        show_static(dev, format_rupiah(total))
        time.sleep(3.0)


# ============================================================================
# MAIN
# ============================================================================
def main():
    p = argparse.ArgumentParser(
        description="Test MAX7219 32x8 bit-bang di Raspberry Pi 4B",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", default="selftest",
                   choices=["selftest", "orient", "static", "scroll",
                            "tarif", "clear"])
    p.add_argument("--text", default="Rp5.000/JAM")
    p.add_argument("--intensity", type=int, default=DEFAULT_INTENSITY,
                   help="0-15 (default %d). Jaga rendah bila supply terbatas."
                        % DEFAULT_INTENSITY)
    p.add_argument("--speed", type=float, default=0.04,
                   help="detik per langkah scroll (default 0.04)")
    p.add_argument("--loops", type=int, default=0,
                   help="jumlah putaran scroll, 0 = tak terbatas")
    p.add_argument("--orient", type=int, default=DEFAULT_ORIENT,
                   help="0-15, lihat --mode orient")
    p.add_argument("--cascade", type=int, default=CASCADE)
    p.add_argument("--narrow", action="store_true",
                   help="pakai font angka 3x5 (muat lebih banyak digit)")
    p.add_argument("--din", type=int, default=PIN_DIN)
    p.add_argument("--clk", type=int, default=PIN_CLK)
    p.add_argument("--cs", type=int, default=PIN_CS)
    p.add_argument("--backend", default=None,
                   choices=["lgpio", "rpigpio", "pigpio"])
    args = p.parse_args()

    gpio = make_backend(args.backend)
    print("GPIO backend : %s" % gpio.name)
    print("Pin          : DIN=GPIO%d  CLK=GPIO%d  CS=GPIO%d (bit-bang, bukan SPI HW)"
          % (args.din, args.clk, args.cs))
    print("Cascade      : %d chip (%d x 8 piksel)" % (args.cascade, args.cascade * 8))
    print("Orientasi    : %d | Intensity: %d\n" % (args.orient, args.intensity))

    dev = Max7219(gpio, din=args.din, clk=args.clk, cs=args.cs,
                  cascade=args.cascade, orient=args.orient,
                  intensity=args.intensity)
    try:
        if args.mode == "selftest":
            mode_selftest(dev)
        elif args.mode == "orient":
            mode_orient(dev)
        elif args.mode == "static":
            ok = show_static(dev, args.text, narrow=args.narrow)
            if not ok:
                print("PERINGATAN: teks lebih lebar dari %d kolom, terpotong."
                      % dev.width)
                print("Gunakan --mode scroll atau --narrow.")
            print("Menampilkan statis. Ctrl+C untuk keluar.")
            while True:
                time.sleep(1)
        elif args.mode == "scroll":
            scroll_text(dev, args.text, speed=args.speed,
                        loops=args.loops, narrow=args.narrow)
        elif args.mode == "tarif":
            mode_tarif(dev, args.speed)
        elif args.mode == "clear":
            dev.clear()
            dev.flush()
    except KeyboardInterrupt:
        print("\nDihentikan oleh user.")
    finally:
        dev.cleanup()


if __name__ == "__main__":
    if sys.version_info < (3, 6):
        raise SystemExit("Butuh Python 3.6+")
    main()
