# -*- coding: utf-8 -*-
"""
Konfigurasi PCB Tester - sesuai "Konfigurasi GPIO Raspi di PCB v3.3.xlsx".
Semua nomor pin memakai penomoran BCM (GPIOxx), bukan nomor fisik header.
"""

# ---------------------------------------------------------------------------
# 1. DIGITAL INPUT  (label, GPIO jalur KIRI, GPIO jalur KANAN)
#    Pull-down di PCB: tombol ditekan -> GPIO menerima 3,3 V (HIGH)
# ---------------------------------------------------------------------------
DIGITAL_INPUTS = [
    ("BUTTON 1",      9, 25),
    ("BUTTON 2",      8,  7),
    ("BUTTON 3",     12, 16),
    ("BUTTON 4",     20, 21),
    ("LOOP 1",       22, 27),
    ("LOOP 2",       18, 10),
    ("FEEDBACK VLD",  6,  5),
    ("FEEDBACK GATE", 26, 13),
]

# Pull-down internal Raspi AKTIF: pada PCB v3.3 GPIO jalur yang TIDAK dipilih saklar dibiarkan
# mengambang (terukur di hardware), sehingga tanpa pull-down internal terbaca HIGH palsu.
# "none" = tanpa pull internal, "down" = pull-down internal (~50 kOhm).
DI_INTERNAL_PULL = "down"
DI_POLL_INTERVAL_S = 0.002        # 500 Hz sampling
DI_GLITCH_MS = 15                 # pulsa lebih pendek dari ini dihitung glitch/bounce
DI_MIN_HIGH_MS = 30               # HIGH minimal agar pin dianggap "teruji"
DI_BOTH_HIGH_FAULT_MS = 60        # kedua jalur HIGH bersamaan selama ini = FAULT

# ---------------------------------------------------------------------------
# 2. DIGITAL OUTPUT - Relay (keduanya ON/OFF bersamaan)
# ---------------------------------------------------------------------------
RELAY_PINS = (4, 17)
RELAY_ACTIVE_HIGH = True          # ubah ke False bila driver relay aktif-LOW
RELAY_DEFAULT_ON_S = 1.5
RELAY_DEFAULT_OFF_S = 1.0
RELAY_QC_MIN_CYCLES = 5

# ---------------------------------------------------------------------------
# 3. RTC DS3231SN#  (SDA = GPIO2, SCL = GPIO3 -> I2C bus 1)
# ---------------------------------------------------------------------------
RTC_I2C_BUS = 1
RTC_I2C_ADDR = 0x68
RTC_SYNC_TOLERANCE_S = 2          # selisih RTC vs sistem yang masih dianggap sinkron

# ---------------------------------------------------------------------------
# 4. RS485  (TX = GPIO14, RX = GPIO15 -> UART /dev/serial0)
# ---------------------------------------------------------------------------
RS485_PORT = "/dev/serial0"
RS485_BAUD = 115200               # HARUS sama dengan sketch ESP32
RS485_DE_PIN = None               # None = modul RS485 auto-direction. Isi nomor GPIO bila ada pin DE/RE.
RS485_INTERVAL_S = 0.25           # jeda antar PING
RS485_TIMEOUT_S = 0.30            # batas tunggu PONG
RS485_QC_MIN_OK = 20              # minimal jumlah PONG sukses untuk lulus QC
RS485_QC_MIN_RATE = 95.0          # % sukses dari 20 percobaan terakhir

# ---------------------------------------------------------------------------
# 5. MAX7219 32x8 (4 modul 8x8)  - bit-bang (bukan pin SPI hardware)
# ---------------------------------------------------------------------------
MAX7219_CLK = 23
MAX7219_CS = 24
MAX7219_DIN = 19
MAX7219_MODULES = 4
# Nilai default orientasi (bisa diubah langsung dari UI, tersimpan di settings.json)
MAX7219_ROTATION = 90             # 0 / 90 / 180 / 270  (modul FC-16 umumnya 90 atau 270)
MAX7219_FLIP = False
MAX7219_REVERSE_ORDER = False
MAX7219_BRIGHTNESS = 4            # 0..15
MAX7219_SCROLL_MS = 45            # ms per langkah geser
MAX7219_DEFAULT_TEXT = "TEST DISPLAY MAX7219 32x8 - OK"
MAX7219_STEP_HOLD_S = 2.0         # lama tiap modul 8x8 menyala pada uji bertahap

# --- Proteksi suplai VCC display (lihat dokumen RCA kerusakan AMS1117) ---------
# Arus rata-rata display = LED nyala x ISEG / 8 x (2k+1)/32 + IQ x 4 modul  (k = intensitas 0..15)
MAX7219_ISEG_MA = 40.0            # arus segmen puncak, RSET 10 kOhm (modul FC-16 umum)
MAX7219_IQ_MA = 8.0               # arus diam per chip MAX7219
# Batas arus rata-rata display. AMS1117 12V->5V (SOT-223) hanya aman membuang ~0,8 W panas
# = +-110 mA kontinu. JANGAN dinaikkan selama suplai display masih AMS1117 dari 12 V.
# Setelah diganti buck converter 12->5 V (mis. modul MP1584EN 3 A) boleh dinaikkan s/d 800.
MAX7219_CURRENT_BUDGET_MA = 120

# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
