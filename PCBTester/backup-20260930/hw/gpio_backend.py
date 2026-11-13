# -*- coding: utf-8 -*-
"""Abstraksi GPIO: lgpio (Raspberry Pi OS Bookworm) -> RPi.GPIO -> simulasi."""
import threading


class GPIOError(Exception):
    pass


class LgpioBackend:
    name = "lgpio"

    def __init__(self):
        import lgpio
        self.lg = lgpio
        self.h = None
        last = None
        for chip in (0, 4):
            try:
                self.h = lgpio.gpiochip_open(chip)
                break
            except Exception as e:  # noqa
                last = e
        if self.h is None:
            raise GPIOError("Tidak bisa membuka gpiochip: %s" % last)
        self._pulls = {
            "none": getattr(lgpio, "SET_PULL_NONE", 0),
            "down": getattr(lgpio, "SET_PULL_DOWN", 0),
            "up": getattr(lgpio, "SET_PULL_UP", 0),
        }

    def setup_input(self, pin, pull="none"):
        try:
            self.lg.gpio_claim_input(self.h, pin, self._pulls.get(pull, 0))
        except Exception as e:
            raise GPIOError(_busy_msg(pin, e))

    def setup_output(self, pin, value=0):
        try:
            self.lg.gpio_claim_output(self.h, pin, int(value))
        except Exception as e:
            raise GPIOError(_busy_msg(pin, e))

    def read(self, pin):
        return self.lg.gpio_read(self.h, pin)

    def write(self, pin, value):
        self.lg.gpio_write(self.h, pin, 1 if value else 0)

    def close(self):
        try:
            self.lg.gpiochip_close(self.h)
        except Exception:
            pass


class RPiGPIOBackend:
    name = "RPi.GPIO"

    def __init__(self):
        import RPi.GPIO as GPIO
        self.G = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

    def setup_input(self, pin, pull="none"):
        pud = {"none": self.G.PUD_OFF, "down": self.G.PUD_DOWN, "up": self.G.PUD_UP}[pull]
        try:
            self.G.setup(pin, self.G.IN, pull_up_down=pud)
        except Exception as e:
            raise GPIOError(_busy_msg(pin, e))

    def setup_output(self, pin, value=0):
        try:
            self.G.setup(pin, self.G.OUT, initial=self.G.HIGH if value else self.G.LOW)
        except Exception as e:
            raise GPIOError(_busy_msg(pin, e))

    def read(self, pin):
        return self.G.input(pin)

    def write(self, pin, value):
        self.G.output(pin, self.G.HIGH if value else self.G.LOW)

    def close(self):
        try:
            self.G.cleanup()
        except Exception:
            pass


class SimBackend:
    """GPIO palsu untuk menjalankan UI di PC (python app.py --sim)."""
    name = "SIMULASI"

    def __init__(self):
        self.levels = {}
        self.lock = threading.Lock()

    def setup_input(self, pin, pull="none"):
        self.levels.setdefault(pin, 0)

    def setup_output(self, pin, value=0):
        self.levels[pin] = int(value)

    def read(self, pin):
        return self.levels.get(pin, 0)

    def write(self, pin, value):
        self.levels[pin] = 1 if value else 0

    def sim_set(self, pin, value):
        self.levels[pin] = 1 if value else 0

    def close(self):
        pass


def _busy_msg(pin, e):
    s = str(e)
    hint = ""
    if pin in (7, 8, 9, 10, 11):
        hint = " (pastikan SPI0 dinonaktifkan: dtparam=spi=off)"
    elif pin == 4:
        hint = " (pastikan 1-Wire tidak aktif)"
    elif pin in (18, 19, 20, 21):
        hint = " (pastikan audio I2S/PCM & SPI1 tidak aktif)"
    return "GPIO%d tidak bisa dipakai: %s%s" % (pin, s, hint)


def open_backend(sim=False):
    if sim:
        return SimBackend()
    errors = []
    for cls in (LgpioBackend, RPiGPIOBackend):
        try:
            return cls()
        except Exception as e:
            errors.append("%s: %s" % (cls.name, e))
    raise GPIOError("Library GPIO tidak tersedia -> " + " | ".join(errors))
