#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║              PCB TESTING TOOL — Raspberry Pi 4B                 ║
║                                                                  ║
║  Digital Input  : 2x MCP23017 (0x20, 0x21) — 32 buttons        ║
║  Digital Output : 1x MCP23017 (0x25) + 8 GPIO — 24 outputs     ║
║  RTC            : DS3231SN# (0x68)                              ║
╚══════════════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import struct
from datetime import datetime, timezone

# ─── Hardware abstraction ─────────────────────────────────────────
# Import smbus (native RPi) first, fallback to smbus2
SIMULATION_MODE = False
smbus_module = None
try:
    import smbus
    smbus_module = smbus
    print("[INFO] Using 'smbus' (native)")
except ImportError:
    try:
        import smbus2 as smbus
        smbus_module = smbus
        print("[INFO] Using 'smbus2' (fallback)")
    except ImportError:
        smbus_module = None

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

if smbus_module is None or GPIO is None:
    SIMULATION_MODE = True
    BUS = None
    print("[INFO] smbus/RPi.GPIO not found — running in SIMULATION mode")
else:
    try:
        BUS = smbus_module.SMBus(1)
    except Exception as e:
        SIMULATION_MODE = True
        BUS = None
        print(f"[WARN] Could not open SMBus(1): {e} — SIMULATION mode")


# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════

# MCP23017 I2C addresses
ADDR_INPUT_1  = 0x20   # Digital input #1
ADDR_INPUT_2  = 0x21   # Digital input #2
ADDR_OUTPUT   = 0x25   # Digital output (MOSFET/relay)
ADDR_RTC      = 0x68   # DS3231SN#

# MCP23017 register map
IODIRA  = 0x00
IODIRB  = 0x01
GPPUA   = 0x0C
GPPUB   = 0x0D
GPIOA   = 0x12
GPIOB   = 0x13
OLATA   = 0x14
OLATB   = 0x15

# Raspberry Pi GPIO pins used as digital outputs
RPI_OUTPUT_PINS = [5, 6, 13, 16, 19, 20, 17, 27]

# Output toggle timing (seconds)
ON_DURATION  = 1.0
OFF_DURATION = 1.5

# UI refresh interval (ms)
INPUT_POLL_MS  = 100
RTC_POLL_MS    = 500

# ═══════════════════════════════════════════════════════════════════
# COLOUR PALETTE — industrial/utilitarian theme
# ═══════════════════════════════════════════════════════════════════
CLR_BG          = "#1a1d23"
CLR_PANEL       = "#22262e"
CLR_PANEL_HDR   = "#2c313a"
CLR_BORDER      = "#3a3f4b"
CLR_TEXT        = "#d1d5db"
CLR_TEXT_DIM    = "#6b7280"
CLR_TEXT_BRIGHT = "#f3f4f6"
CLR_ACCENT      = "#60a5fa"
CLR_ON          = "#22c55e"
CLR_ON_GLOW     = "#16a34a"
CLR_OFF         = "#dc2626"
CLR_OFF_DIM     = "#7f1d1d"
CLR_WARN        = "#f59e0b"


# ═══════════════════════════════════════════════════════════════════
# MCP23017 DRIVER
# ═══════════════════════════════════════════════════════════════════
class MCP23017:
    """Minimal MCP23017 driver over smbus."""

    def __init__(self, bus, address):
        self.bus = bus
        self.addr = address

    def _write(self, reg, val):
        if not SIMULATION_MODE:
            self.bus.write_byte_data(self.addr, reg, val)

    def _read(self, reg):
        if SIMULATION_MODE:
            return 0x00
        return self.bus.read_byte_data(self.addr, reg)

    # ── configuration ──────────────────────────────────────────
    def config_all_input(self):
        """Set all 16 pins as inputs (IODIR = 0xFF). No internal pull-ups (external pulldown)."""
        self._write(IODIRA, 0xFF)
        self._write(IODIRB, 0xFF)
        self._write(GPPUA,  0x00)   # disable internal pull-ups
        self._write(GPPUB,  0x00)

    def config_all_output(self):
        """Set all 16 pins as outputs (IODIR = 0x00)."""
        self._write(IODIRA, 0x00)
        self._write(IODIRB, 0x00)

    # ── read / write ───────────────────────────────────────────
    def read_port_a(self):
        return self._read(GPIOA)

    def read_port_b(self):
        return self._read(GPIOB)

    def read_all(self):
        """Return (portA_byte, portB_byte)."""
        return self.read_port_a(), self.read_port_b()

    def write_port_a(self, val):
        self._write(OLATA, val & 0xFF)

    def write_port_b(self, val):
        self._write(OLATB, val & 0xFF)

    def write_all(self, val_a, val_b):
        self.write_port_a(val_a)
        self.write_port_b(val_b)


# ═══════════════════════════════════════════════════════════════════
# DS3231 RTC DRIVER
# Matches proven working approach: fresh SMBus per read, byte-by-byte
# ═══════════════════════════════════════════════════════════════════
class DS3231:
    """Read date/time from DS3231SN# RTC over I2C.

    Key design choices (proven to work on actual hardware):
      - Open and close SMBus(1) on EVERY read cycle (not persistent)
      - Read registers byte-by-byte (not block read) for stability
      - Simple try/except detection — if read works, device is present
    """

    def __init__(self, address=ADDR_RTC):
        self.addr = address
        self.last_error = ""
        self.detected = False

    @staticmethod
    def _bcd_to_dec(bcd):
        return (bcd >> 4) * 10 + (bcd & 0x0F)

    def _open_bus(self):
        """Open a fresh SMBus connection (closed after each use)."""
        if SIMULATION_MODE or smbus_module is None:
            return None
        try:
            return smbus_module.SMBus(1)
        except Exception as e:
            self.last_error = f"SMBus open failed: {e}"
            return None

    def is_present(self):
        """Probe DS3231 by attempting to read register 0x00.
        Opens and closes a fresh bus — matching proven working pattern."""
        if SIMULATION_MODE or smbus_module is None:
            self.last_error = "Simulation mode — no hardware"
            self.detected = False
            return False

        bus = self._open_bus()
        if bus is None:
            self.detected = False
            return False

        try:
            bus.read_byte_data(self.addr, 0x00)
            self.last_error = ""
            self.detected = True
            return True
        except Exception as e:
            self.last_error = f"I2C probe 0x{self.addr:02X}: {e}"
            self.detected = False
            return False
        finally:
            try:
                bus.close()
            except Exception:
                pass

    def read_datetime(self):
        """Read date/time from DS3231 registers 0x00–0x06.
        Uses byte-by-byte read with fresh bus (proven stable)."""
        if SIMULATION_MODE or smbus_module is None:
            return None

        bus = self._open_bus()
        if bus is None:
            return None

        try:
            # Read 7 registers byte-by-byte for stability
            data = []
            for reg in range(7):
                data.append(bus.read_byte_data(self.addr, reg))

            sec = self._bcd_to_dec(data[0] & 0x7F)
            mn  = self._bcd_to_dec(data[1] & 0x7F)
            hr  = self._bcd_to_dec(data[2] & 0x3F)
            day = self._bcd_to_dec(data[4] & 0x3F)
            mon = self._bcd_to_dec(data[5] & 0x7F)   # bit7 = century
            yr  = self._bcd_to_dec(data[6]) + 2000

            self.last_error = ""
            self.detected = True
            return datetime(yr, mon, day, hr, mn, sec)

        except Exception as e:
            self.last_error = f"RTC read: {e}"
            self.detected = False
            return None
        finally:
            try:
                bus.close()
            except Exception:
                pass

    def read_temperature(self):
        """Read DS3231 on-chip temperature from registers 0x11–0x12.
        Uses byte-by-byte read with fresh bus."""
        if SIMULATION_MODE or smbus_module is None:
            return None

        bus = self._open_bus()
        if bus is None:
            return None

        try:
            msb = bus.read_byte_data(self.addr, 0x11)
            lsb = bus.read_byte_data(self.addr, 0x12)
            temp = msb + (lsb >> 6) * 0.25
            return temp
        except Exception as e:
            self.last_error = f"Temp read: {e}"
            return None
        finally:
            try:
                bus.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
# GPIO OUTPUT HELPER
# ═══════════════════════════════════════════════════════════════════
def setup_rpi_gpio():
    if SIMULATION_MODE:
        return
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in RPI_OUTPUT_PINS:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)


def set_rpi_outputs(state: bool):
    """Set all Raspberry Pi GPIO output pins HIGH or LOW."""
    if SIMULATION_MODE:
        return
    for pin in RPI_OUTPUT_PINS:
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)


# ═══════════════════════════════════════════════════════════════════
# TKINTER APPLICATION
# ═══════════════════════════════════════════════════════════════════
class PCBTesterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PCB Testing Tool — Raspberry Pi 4B")
        self.root.configure(bg=CLR_BG)
        self.root.attributes("-fullscreen", False)
        self.root.geometry("1280x820")
        self.root.minsize(1024, 700)

        # ── Hardware init ──────────────────────────────────────
        self.mcp_in1 = MCP23017(BUS, ADDR_INPUT_1)
        self.mcp_in2 = MCP23017(BUS, ADDR_INPUT_2)
        self.mcp_out = MCP23017(BUS, ADDR_OUTPUT)
        self.rtc     = DS3231()        # opens fresh bus per read

        self.mcp_in1.config_all_input()
        self.mcp_in2.config_all_input()
        self.mcp_out.config_all_output()
        setup_rpi_gpio()

        # Output state
        self.output_active = False
        self.running = True

        # ── LED indicator storage ──────────────────────────────
        self.input_leds  = {}   # key: (addr, port, bit) → canvas oval id
        self.output_leds = {}   # key: label → canvas oval id

        # ── Build UI ───────────────────────────────────────────
        self._build_ui()

        # ── Start background threads ───────────────────────────
        self._start_output_toggle_thread()
        self._poll_inputs()
        self._poll_rtc()

        # ── Graceful shutdown ──────────────────────────────────
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ───────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ───────────────────────────────────────────────────────────
    def _build_ui(self):
        # Title bar
        title_frame = tk.Frame(self.root, bg=CLR_PANEL_HDR, pady=8)
        title_frame.pack(fill=tk.X)
        tk.Label(
            title_frame,
            text="⚙  PCB TESTING TOOL",
            font=("Courier New", 18, "bold"),
            fg=CLR_ACCENT, bg=CLR_PANEL_HDR
        ).pack(side=tk.LEFT, padx=16)

        sim_text = "  ◉ SIMULATION" if SIMULATION_MODE else "  ◉ HARDWARE CONNECTED"
        sim_clr  = CLR_WARN if SIMULATION_MODE else CLR_ON
        tk.Label(
            title_frame,
            text=sim_text,
            font=("Courier New", 10, "bold"),
            fg=sim_clr, bg=CLR_PANEL_HDR
        ).pack(side=tk.RIGHT, padx=16)

        # Main container with scrollbar support
        main = tk.Frame(self.root, bg=CLR_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # LEFT column: Digital inputs
        left = tk.Frame(main, bg=CLR_BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self._build_input_panel(left, f"DIGITAL INPUT — 0x20", ADDR_INPUT_1)
        self._build_input_panel(left, f"DIGITAL INPUT — 0x21", ADDR_INPUT_2)

        # RIGHT column: Digital outputs + RTC
        right = tk.Frame(main, bg=CLR_BG)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self._build_output_panel(right)
        self._build_rtc_panel(right)

    # ── INPUT PANEL ────────────────────────────────────────────
    def _build_input_panel(self, parent, title, address):
        panel = tk.LabelFrame(
            parent, text=f"  {title}  ",
            font=("Courier New", 11, "bold"),
            fg=CLR_ACCENT, bg=CLR_PANEL,
            highlightbackground=CLR_BORDER,
            highlightthickness=1,
            bd=0, padx=8, pady=6
        )
        panel.pack(fill=tk.X, pady=(0, 6))

        for port_name, port_label in [("A", "PORT A (GPA0–GPA7)"), ("B", "PORT B (GPB0–GPB7)")]:
            sub = tk.Frame(panel, bg=CLR_PANEL)
            sub.pack(fill=tk.X, pady=(2, 4))

            tk.Label(
                sub, text=port_label,
                font=("Courier New", 9, "bold"),
                fg=CLR_TEXT_DIM, bg=CLR_PANEL
            ).pack(anchor=tk.W)

            row = tk.Frame(sub, bg=CLR_PANEL)
            row.pack(fill=tk.X, pady=2)

            for bit in range(8):
                pin_prefix = "GPA" if port_name == "A" else "GPB"
                pin_label = f"{pin_prefix}{bit}"
                self._create_led_indicator(
                    row, pin_label,
                    key=(address, port_name, bit)
                )

    # ── OUTPUT PANEL ───────────────────────────────────────────
    def _build_output_panel(self, parent):
        panel = tk.LabelFrame(
            parent, text="  DIGITAL OUTPUT  ",
            font=("Courier New", 11, "bold"),
            fg=CLR_ACCENT, bg=CLR_PANEL,
            highlightbackground=CLR_BORDER,
            highlightthickness=1,
            bd=0, padx=8, pady=6
        )
        panel.pack(fill=tk.X, pady=(0, 6))

        # Status label
        self.output_status_var = tk.StringVar(value="OUTPUT: OFF")
        self.output_status_label = tk.Label(
            panel,
            textvariable=self.output_status_var,
            font=("Courier New", 10, "bold"),
            fg=CLR_OFF, bg=CLR_PANEL
        )
        self.output_status_label.pack(anchor=tk.W, pady=(0, 4))

        # Timing info
        tk.Label(
            panel,
            text=f"Cycle: ON {ON_DURATION}s → OFF {OFF_DURATION}s → repeat",
            font=("Courier New", 8),
            fg=CLR_TEXT_DIM, bg=CLR_PANEL
        ).pack(anchor=tk.W, pady=(0, 6))

        # MCP23017 0x25 outputs
        for port_name, port_label in [("A", "MCP 0x25 PORT A (GPA0–GPA7)"), ("B", "MCP 0x25 PORT B (GPB0–GPB7)")]:
            sub = tk.Frame(panel, bg=CLR_PANEL)
            sub.pack(fill=tk.X, pady=(2, 4))

            tk.Label(
                sub, text=port_label,
                font=("Courier New", 9, "bold"),
                fg=CLR_TEXT_DIM, bg=CLR_PANEL
            ).pack(anchor=tk.W)

            row = tk.Frame(sub, bg=CLR_PANEL)
            row.pack(fill=tk.X, pady=2)

            for bit in range(8):
                pin_prefix = "GPA" if port_name == "A" else "GPB"
                pin_label = f"{pin_prefix}{bit}"
                key = f"mcp25_{port_name}_{bit}"
                self._create_led_indicator(row, pin_label, key=key, is_output=True)

        # RPi GPIO outputs
        sub = tk.Frame(panel, bg=CLR_PANEL)
        sub.pack(fill=tk.X, pady=(2, 4))

        tk.Label(
            sub, text="RPi GPIO OUTPUTS",
            font=("Courier New", 9, "bold"),
            fg=CLR_TEXT_DIM, bg=CLR_PANEL
        ).pack(anchor=tk.W)

        row = tk.Frame(sub, bg=CLR_PANEL)
        row.pack(fill=tk.X, pady=2)

        for pin in RPI_OUTPUT_PINS:
            pin_label = f"GPIO{pin}"
            key = f"gpio_{pin}"
            self._create_led_indicator(row, pin_label, key=key, is_output=True)

    # ── RTC PANEL ──────────────────────────────────────────────
    def _build_rtc_panel(self, parent):
        panel = tk.LabelFrame(
            parent, text="  RTC DS3231SN#  ",
            font=("Courier New", 11, "bold"),
            fg=CLR_ACCENT, bg=CLR_PANEL,
            highlightbackground=CLR_BORDER,
            highlightthickness=1,
            bd=0, padx=12, pady=8
        )
        panel.pack(fill=tk.X, pady=(0, 6))

        # ── Detection status indicator (line 1: LED + status) ──
        det_frame = tk.Frame(panel, bg=CLR_PANEL)
        det_frame.pack(fill=tk.X, pady=(0, 2))

        # LED canvas for detection
        self.rtc_det_canvas = tk.Canvas(
            det_frame, width=20, height=20,
            bg=CLR_PANEL, highlightthickness=0
        )
        self.rtc_det_canvas.pack(side=tk.LEFT)
        self.rtc_det_glow = self.rtc_det_canvas.create_oval(1, 1, 19, 19, fill=CLR_OFF_DIM, outline="", width=0)
        self.rtc_det_led  = self.rtc_det_canvas.create_oval(3, 3, 17, 17, fill=CLR_OFF, outline="#333", width=1)

        # Status text
        self.rtc_det_var = tk.StringVar(value="DETECTING...")
        self.rtc_det_label = tk.Label(
            det_frame,
            textvariable=self.rtc_det_var,
            font=("Courier New", 10, "bold"),
            fg=CLR_WARN, bg=CLR_PANEL
        )
        self.rtc_det_label.pack(side=tk.LEFT, padx=(6, 0))

        # ── Detection detail (line 2: address + mode + error) ──
        det_detail_frame = tk.Frame(panel, bg=CLR_PANEL)
        det_detail_frame.pack(fill=tk.X, pady=(0, 2))

        self.rtc_detail_var = tk.StringVar(value=f"Addr: 0x{ADDR_RTC:02X}  |  Mode: —")
        tk.Label(
            det_detail_frame,
            textvariable=self.rtc_detail_var,
            font=("Courier New", 8),
            fg=CLR_TEXT_DIM, bg=CLR_PANEL,
            anchor=tk.W
        ).pack(anchor=tk.W)

        # Error detail line
        self.rtc_error_var = tk.StringVar(value="")
        self.rtc_error_label = tk.Label(
            panel,
            textvariable=self.rtc_error_var,
            font=("Courier New", 8),
            fg=CLR_OFF, bg=CLR_PANEL,
            anchor=tk.W, wraplength=500, justify=tk.LEFT
        )
        self.rtc_error_label.pack(fill=tk.X, pady=(0, 2))

        # Separator
        sep = tk.Frame(panel, bg=CLR_BORDER, height=1)
        sep.pack(fill=tk.X, pady=(2, 6))

        # ── Time display rows ──────────────────────────────────
        self.rtc_vars = {}
        self.rtc_value_labels = {}
        labels = [
            ("local_time",  "Local Time (System)"),
            ("utc_time",    "Universal Time (UTC)"),
            ("rtc_time",    "RTC Time (DS3231)"),
            ("timezone",    "Timezone"),
            ("rtc_temp",    "RTC Temperature"),
        ]

        for key, label_text in labels:
            row = tk.Frame(panel, bg=CLR_PANEL)
            row.pack(fill=tk.X, pady=2)

            tk.Label(
                row, text=f"{label_text}:",
                font=("Courier New", 9),
                fg=CLR_TEXT_DIM, bg=CLR_PANEL,
                width=24, anchor=tk.W
            ).pack(side=tk.LEFT)

            var = tk.StringVar(value="—")
            self.rtc_vars[key] = var

            val_label = tk.Label(
                row, textvariable=var,
                font=("Courier New", 12, "bold"),
                fg=CLR_TEXT_BRIGHT, bg=CLR_PANEL,
                anchor=tk.W
            )
            val_label.pack(side=tk.LEFT, padx=(8, 0))
            self.rtc_value_labels[key] = val_label

    # ── LED INDICATOR WIDGET ───────────────────────────────────
    def _create_led_indicator(self, parent, label, key, is_output=False):
        """Create a single LED indicator with label below it."""
        frame = tk.Frame(parent, bg=CLR_PANEL, padx=3, pady=2)
        frame.pack(side=tk.LEFT, expand=True)

        canvas = tk.Canvas(
            frame, width=28, height=28,
            bg=CLR_PANEL, highlightthickness=0
        )
        canvas.pack()

        # Outer glow ring
        glow = canvas.create_oval(2, 2, 26, 26, fill=CLR_OFF_DIM, outline="", width=0)
        # Inner LED
        led = canvas.create_oval(5, 5, 23, 23, fill=CLR_OFF, outline="#333", width=1)

        tk.Label(
            frame, text=label,
            font=("Courier New", 7),
            fg=CLR_TEXT_DIM, bg=CLR_PANEL
        ).pack()

        store = self.output_leds if is_output else self.input_leds
        store[key] = (canvas, glow, led)

    def _set_led(self, store, key, active: bool):
        """Update an LED indicator's colour."""
        if key not in store:
            return
        canvas, glow, led = store[key]
        if active:
            canvas.itemconfig(glow, fill=CLR_ON_GLOW)
            canvas.itemconfig(led,  fill=CLR_ON)
        else:
            canvas.itemconfig(glow, fill=CLR_OFF_DIM)
            canvas.itemconfig(led,  fill=CLR_OFF)

    # ───────────────────────────────────────────────────────────
    # POLLING: DIGITAL INPUTS
    # ───────────────────────────────────────────────────────────
    def _poll_inputs(self):
        if not self.running:
            return
        try:
            for addr, mcp in [(ADDR_INPUT_1, self.mcp_in1), (ADDR_INPUT_2, self.mcp_in2)]:
                port_a, port_b = mcp.read_all()
                for bit in range(8):
                    self._set_led(self.input_leds, (addr, "A", bit), bool(port_a & (1 << bit)))
                    self._set_led(self.input_leds, (addr, "B", bit), bool(port_b & (1 << bit)))
        except Exception as e:
            print(f"[ERR] Input poll: {e}")

        self.root.after(INPUT_POLL_MS, self._poll_inputs)

    # ───────────────────────────────────────────────────────────
    # POLLING: RTC
    # ───────────────────────────────────────────────────────────
    def _poll_rtc(self):
        if not self.running:
            return
        try:
            # ── 1. Check if DS3231 is physically present on I2C bus ──
            rtc_detected = self.rtc.is_present()
            self._update_rtc_detection_ui(rtc_detected)

            # ── 2. System local time (always available) ──────────
            now_local = datetime.now()
            self.rtc_vars["local_time"].set(now_local.strftime("%Y-%m-%d  %H:%M:%S"))

            # ── 3. UTC time (always available) ───────────────────
            now_utc = datetime.now(timezone.utc)
            self.rtc_vars["utc_time"].set(now_utc.strftime("%Y-%m-%d  %H:%M:%S"))

            # ── 4. Timezone (always available) ───────────────────
            tz_name = time.strftime("%Z")
            utc_off = time.strftime("%z")
            if utc_off:
                self.rtc_vars["timezone"].set(f"{tz_name} (UTC{utc_off[:3]}:{utc_off[3:]})")
            else:
                self.rtc_vars["timezone"].set(f"{tz_name}")

            # ── 5. RTC time & temp (only if detected) ────────────
            if rtc_detected:
                rtc_dt = self.rtc.read_datetime()
                if rtc_dt:
                    self.rtc_vars["rtc_time"].set(rtc_dt.strftime("%Y-%m-%d  %H:%M:%S"))
                    self.rtc_value_labels["rtc_time"].config(fg=CLR_TEXT_BRIGHT)
                else:
                    self.rtc_vars["rtc_time"].set("READ ERROR")
                    self.rtc_value_labels["rtc_time"].config(fg=CLR_OFF)

                temp = self.rtc.read_temperature()
                if temp is not None:
                    self.rtc_vars["rtc_temp"].set(f"{temp:.2f} °C")
                    self.rtc_value_labels["rtc_temp"].config(fg=CLR_TEXT_BRIGHT)
                else:
                    self.rtc_vars["rtc_temp"].set("READ ERROR")
                    self.rtc_value_labels["rtc_temp"].config(fg=CLR_OFF)
            else:
                self.rtc_vars["rtc_time"].set("NOT DETECTED")
                self.rtc_value_labels["rtc_time"].config(fg=CLR_OFF)
                self.rtc_vars["rtc_temp"].set("NOT DETECTED")
                self.rtc_value_labels["rtc_temp"].config(fg=CLR_OFF)

        except Exception as e:
            print(f"[ERR] RTC poll: {e}")

        self.root.after(RTC_POLL_MS, self._poll_rtc)

    def _update_rtc_detection_ui(self, detected: bool):
        """Update the RTC detection LED indicator and error detail."""
        err = self.rtc.last_error

        if detected:
            self.rtc_det_canvas.itemconfig(self.rtc_det_glow, fill=CLR_ON_GLOW)
            self.rtc_det_canvas.itemconfig(self.rtc_det_led,  fill=CLR_ON)
            self.rtc_det_var.set("DETECTED")
            self.rtc_det_label.config(fg=CLR_ON)

            self.rtc_detail_var.set(f"Addr: 0x{ADDR_RTC:02X}  |  I2C Bus: SMBus(1)")
            self.rtc_error_var.set("")
        else:
            self.rtc_det_canvas.itemconfig(self.rtc_det_glow, fill=CLR_OFF_DIM)
            self.rtc_det_canvas.itemconfig(self.rtc_det_led,  fill=CLR_OFF)
            self.rtc_det_var.set("NOT DETECTED")
            self.rtc_det_label.config(fg=CLR_OFF)

            self.rtc_detail_var.set(f"Addr: 0x{ADDR_RTC:02X}  |  I2C Bus: SMBus(1)")
            if err:
                self.rtc_error_var.set(f"Error: {err}")
            else:
                self.rtc_error_var.set("Error: no response at I2C address")

    # ───────────────────────────────────────────────────────────
    # OUTPUT TOGGLE THREAD
    # ───────────────────────────────────────────────────────────
    def _start_output_toggle_thread(self):
        self._toggle_thread = threading.Thread(target=self._output_toggle_loop, daemon=True)
        self._toggle_thread.start()

    def _output_toggle_loop(self):
        """Toggle all digital outputs: ON 1s → OFF 1.5s → repeat."""
        while self.running:
            # ── ON phase ───────────────────────────────────
            self._set_all_outputs(True)
            self._sleep_checked(ON_DURATION)

            # ── OFF phase ──────────────────────────────────
            self._set_all_outputs(False)
            self._sleep_checked(OFF_DURATION)

    def _sleep_checked(self, duration):
        """Sleep in small steps so we can exit quickly on close."""
        end = time.monotonic() + duration
        while self.running and time.monotonic() < end:
            time.sleep(0.05)

    def _set_all_outputs(self, state: bool):
        self.output_active = state
        try:
            val = 0xFF if state else 0x00
            self.mcp_out.write_all(val, val)
            set_rpi_outputs(state)
        except Exception as e:
            print(f"[ERR] Output write: {e}")

        # Update UI from thread-safe callback
        self.root.after(0, self._update_output_ui, state)

    def _update_output_ui(self, state: bool):
        # Status label
        if state:
            self.output_status_var.set("OUTPUT: ON  ██████████")
            self.output_status_label.config(fg=CLR_ON)
        else:
            self.output_status_var.set("OUTPUT: OFF ░░░░░░░░░░")
            self.output_status_label.config(fg=CLR_OFF)

        # MCP25 LEDs
        for port_name in ("A", "B"):
            for bit in range(8):
                key = f"mcp25_{port_name}_{bit}"
                self._set_led(self.output_leds, key, state)

        # GPIO LEDs
        for pin in RPI_OUTPUT_PINS:
            key = f"gpio_{pin}"
            self._set_led(self.output_leds, key, state)

    # ───────────────────────────────────────────────────────────
    # SHUTDOWN
    # ───────────────────────────────────────────────────────────
    def _on_close(self):
        self.running = False
        try:
            self.mcp_out.write_all(0x00, 0x00)
            set_rpi_outputs(False)
            if not SIMULATION_MODE:
                GPIO.cleanup()
        except Exception:
            pass
        self.root.destroy()


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = PCBTesterApp(root)
    root.mainloop()
