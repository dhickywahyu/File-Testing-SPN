"""Unit test protokol RS485. Jalankan dari folder raspi/:  python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import (CrcError, FrameError, build_frame, build_request, crc8,  # noqa: E402
                      parse_frame, parse_status)


class TestCrc(unittest.TestCase):
    def test_check_value(self):
        # nilai cek standar CRC-8/SMBUS, sama dengan self-test di firmware ESP32
        self.assertEqual(crc8(b"123456789"), 0xF4)

    def test_empty(self):
        self.assertEqual(crc8(b""), 0x00)


class TestFrames(unittest.TestCase):
    def test_request_format(self):
        frame = build_request(1, "OPEN", 3)
        self.assertTrue(frame.startswith(b">01,OPEN,3*"))
        self.assertTrue(frame.endswith(b"\n"))
        self.assertEqual(frame[-3:-1], f"{crc8(b'01,OPEN,3'):02X}".encode())

    def test_roundtrip(self):
        line = build_frame("<", ["01", "ACK", "OPEN", "3", "STARTED"])
        self.assertEqual(parse_frame(line), ["01", "ACK", "OPEN", "3", "STARTED"])

    def test_lowercase_hex_accepted(self):
        line = build_frame("<", ["01", "PONG", "1.0.0", "10", "POWERON"]).decode().strip()
        star = line.rfind("*")
        self.assertEqual(parse_frame((line[:star + 1] + line[star + 1:].lower()).encode())[1], "PONG")

    def test_crc_error_detected(self):
        line = bytearray(build_frame("<", ["01", "STAT", "CCCCCCCCCC", "0" * 10, "0" * 10, "0" * 10, "5"]))
        line[10] = ord("O")   # 1 karakter berubah karena noise
        with self.assertRaises(CrcError):
            parse_frame(bytes(line))

    def test_malformed(self):
        for bad in (b"", b"<01,STAT", b"<01,STAT*G1\n", b">01,STAT*00\n", b"<01*0\n", b"\xff\xfe\n"):
            with self.subTest(bad=bad), self.assertRaises(FrameError):
                parse_frame(bad)


class TestStatus(unittest.TestCase):
    def test_parse(self):
        fields = ["01", "STAT", "CCOCCCCCCO", "0010000001", "0100000000", "0001000000", "42"]
        st = parse_status(fields, 10)
        self.assertEqual(st.door_open, [False, False, True] + [False] * 6 + [True])
        self.assertEqual(st.led[2], True)
        self.assertEqual(st.solenoid[1], True)
        self.assertEqual(st.queued[3], True)
        self.assertEqual(st.uptime_s, 42)

    def test_wrong_cell_count(self):
        with self.assertRaises(FrameError):
            parse_status(["01", "STAT", "CCCCC", "00000", "00000", "00000", "1"], 10)

    def test_bad_chars(self):
        with self.assertRaises(FrameError):
            parse_status(["01", "STAT", "CCCCCCCCCX", "0" * 10, "0" * 10, "0" * 10, "1"], 10)


if __name__ == "__main__":
    unittest.main()
