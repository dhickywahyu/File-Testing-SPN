# -*- coding: utf-8 -*-
"""Akses langsung register DS3231 lewat I2C. Waktu di RTC disimpan dalam UTC (sama seperti hwclock)."""
import calendar
import fcntl
import os
import time


def _bcd2dec(v):
    return (v >> 4) * 10 + (v & 0x0F)


def _dec2bcd(v):
    return ((v // 10) << 4) | (v % 10)


class RTCError(Exception):
    pass


class RawI2C:
    """Akses /dev/i2c-N langsung (tanpa library) dengan I2C_SLAVE_FORCE."""
    I2C_SLAVE_FORCE = 0x0706

    def __init__(self, bus_no):
        self.fd = os.open("/dev/i2c-%d" % bus_no, os.O_RDWR)
        self.addr = None

    def _select(self, addr):
        if addr != self.addr:
            fcntl.ioctl(self.fd, self.I2C_SLAVE_FORCE, addr)
            self.addr = addr

    def read_i2c_block_data(self, addr, reg, n):
        self._select(addr)
        os.write(self.fd, bytes([reg]))
        return list(os.read(self.fd, n))

    def write_i2c_block_data(self, addr, reg, data):
        self._select(addr)
        os.write(self.fd, bytes([reg] + list(data)))

    def read_byte_data(self, addr, reg):
        return self.read_i2c_block_data(addr, reg, 1)[0]

    def write_byte_data(self, addr, reg, value):
        self.write_i2c_block_data(addr, reg, [value])


class DS3231:
    def __init__(self, bus_no=1, addr=0x68):
        self.bus_no, self.addr = bus_no, addr
        self.dev_path = "/dev/i2c-%d" % bus_no
        if not os.path.exists(self.dev_path):
            raise RTCError("I2C_OFF")
        # force: tetap bisa diakses walau driver kernel rtc-ds1307 (dtoverlay=i2c-rtc) sedang aktif
        try:
            import smbus2
            self.bus = smbus2.SMBus(bus_no, force=True)
            self.lib = "smbus2"
        except ImportError:
            self.bus = RawI2C(bus_no)
            self.lib = "i2c-dev"

    def kernel_driver(self):
        p = "/sys/bus/i2c/devices/%d-%04x/driver" % (self.bus_no, self.addr)
        if os.path.exists(p):
            return os.path.basename(os.path.realpath(p))
        return None

    def read(self):
        """Kembalikan dict: epoch (UTC detik), osf, temp_c, valid_fields."""
        r = self.bus.read_i2c_block_data(self.addr, 0x00, 19)
        sec = _bcd2dec(r[0] & 0x7F)
        minute = _bcd2dec(r[1] & 0x7F)
        h = r[2]
        if h & 0x40:  # mode 12 jam
            hour = _bcd2dec(h & 0x1F) % 12 + (12 if h & 0x20 else 0)
        else:
            hour = _bcd2dec(h & 0x3F)
        date = _bcd2dec(r[4] & 0x3F)
        month = _bcd2dec(r[5] & 0x1F)
        year = 2000 + _bcd2dec(r[6]) + (100 if r[5] & 0x80 else 0)
        status = r[0x0F]
        temp = (r[0x11] if r[0x11] < 128 else r[0x11] - 256) + ((r[0x12] >> 6) * 0.25)
        fields_ok = (sec < 60 and minute < 60 and hour < 24 and 1 <= date <= 31 and 1 <= month <= 12)
        epoch = None
        if fields_ok:
            try:
                epoch = calendar.timegm((year, month, date, hour, minute, sec, 0, 0, 0))
            except Exception:
                fields_ok = False
        return {
            "epoch": epoch,
            "sec": sec,
            "osf": bool(status & 0x80),
            "temp_c": temp,
            "fields_ok": fields_ok,
            "control": r[0x0E],
            "status": status,
        }

    def write_epoch(self, epoch):
        t = time.gmtime(int(epoch))
        year = t.tm_year - 2000
        century = 0x80 if year >= 100 else 0
        data = [
            _dec2bcd(t.tm_sec), _dec2bcd(t.tm_min), _dec2bcd(t.tm_hour),
            _dec2bcd(t.tm_wday + 1), _dec2bcd(t.tm_mday),
            _dec2bcd(t.tm_mon) | century, _dec2bcd(year % 100),
        ]
        self.bus.write_i2c_block_data(self.addr, 0x00, data)
        # bersihkan flag OSF (oscillator stop flag)
        st = self.bus.read_byte_data(self.addr, 0x0F)
        self.bus.write_byte_data(self.addr, 0x0F, st & ~0x80 & 0xFF)
        # pastikan osilator jalan saat pakai baterai (EOSC = 0)
        ctl = self.bus.read_byte_data(self.addr, 0x0E)
        if ctl & 0x80:
            self.bus.write_byte_data(self.addr, 0x0E, ctl & 0x7F)


class SimDS3231:
    lib = "simulasi"

    def __init__(self, *a, **k):
        self.offset = -37.0      # mulai dengan RTC tidak sinkron
        self.osf = True

    def kernel_driver(self):
        return None

    def read(self):
        e = int(time.time() + self.offset)
        return {"epoch": e, "sec": e % 60, "osf": self.osf, "temp_c": 27.25,
                "fields_ok": True, "control": 0x1C, "status": 0x80 if self.osf else 0}

    def write_epoch(self, epoch):
        self.offset = epoch - time.time()
        self.osf = False
