"""
Test integrasi: LockerMaster (program Raspberry Pi) <-> SimulatedESP32 lewat antarmuka serial,
termasuk gangguan jalur RS485 dan API web. Timing dipercepat (pulse 0,3 s) agar test cepat.
Jalankan dari folder raspi/:  python3 -m unittest discover -s tests -v
"""
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402
from esp32_simulator import SimulatedESP32  # noqa: E402
from rs485_master import LockerMaster  # noqa: E402

FAST_CFG = dict(
    app.DEFAULT_CONFIG,
    serial_port="SIMULASI",
    poll_interval_ms=40,
    response_timeout_ms=120,
    reconnect_interval_s=0.2,
    solenoid_pulse_ms=300,
    solenoid_detect_timeout_s=1.5,
    door_open_timeout_s=0.8,
    unauthorized_open_window_s=3,
    test_timeout_s=2.5,
)


def wait_until(pred, timeout=5.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


class NoisyLine:
    """Membungkus port: tiap balasan ke-N dirusak 1 bit, plus gema frame sendiri & byte sampah."""

    def __init__(self, inner, corrupt_every=4):
        self.inner = inner
        self.corrupt_every = corrupt_every
        self.writes = 0
        self.pending = bytearray()

    @property
    def in_waiting(self):
        return len(self.pending) + self.inner.in_waiting

    def write(self, data):
        self.writes += 1
        self.pending += data + b"\x00\xfe"          # echo transceiver + sampah
        return self.inner.write(data)

    def read(self, size=1):
        if not self.pending:
            chunk = self.inner.read(1)
            if chunk and self.inner.in_waiting:
                chunk += self.inner.read(self.inner.in_waiting)
            if len(chunk) > 8 and self.writes % self.corrupt_every == 0:
                chunk = bytearray(chunk)
                chunk[len(chunk) // 2] ^= 0x01
            self.pending += chunk
        out = bytes(self.pending[:size])
        del self.pending[:size]
        return out

    def reset_input_buffer(self):
        self.pending.clear()
        self.inner.reset_input_buffer()

    def close(self):
        pass


class Rig:
    def __init__(self, faulty=(), noisy=False, auto_close_s=0.5, fw=None):
        self.sim = SimulatedESP32(pulse_s=0.3, open_delay_s=0.08, auto_close_s=auto_close_s, faulty_cells=faulty)
        if fw:
            self.sim.fw_version = fw
        port = NoisyLine(self.sim) if noisy else self.sim
        self.master = LockerMaster(dict(FAST_CFG), lambda: port)
        self.master.start()
        assert wait_until(lambda: self.snap()["link"]["fw"] and not any(c["stale"] for c in self.snap()["cells"]),
                          3), "tidak online"

    def snap(self):
        return self.master.snapshot()

    def cell(self, cid):
        return self.snap()["cells"][cid - 1]

    def events(self, text):
        return [e for e in self.snap()["events"] if text in e["msg"]]

    def close(self):
        self.master.stop()


class TestMasterWithSimulator(unittest.TestCase):
    def setUp(self):
        self.rigs = []

    def tearDown(self):
        for r in self.rigs:
            r.close()

    def rig(self, **kw):
        r = Rig(**kw)
        self.rigs.append(r)
        return r

    def test_connect_ping(self):
        r = self.rig()
        link = r.snap()["link"]
        self.assertEqual(link["fw"], "1.0.1-sim")
        self.assertEqual(link["reset_reason"], "POWERON")
        self.assertTrue(r.events("ESP32 terhubung"))
        self.assertFalse(r.events("versi lama"))
        self.assertTrue(all(c["door"] == "closed" and not c["stale"] for c in r.snap()["cells"]))

    def test_startup_all_cells_standby(self):
        r = self.rig()
        time.sleep(0.5)
        self.assertTrue(all(c["test"]["state"] == "idle" and not c["pending"] for c in r.snap()["cells"]))
        self.assertFalse(r.events("Perintah BUKA"), "tidak boleh ada perintah buka otomatis saat start")
        self.assertEqual(r.sim.history, [], "tidak boleh ada solenoid aktif saat start")

    def test_old_firmware_warning(self):
        r = self.rig(fw="1.0.0")
        self.assertTrue(wait_until(lambda: r.events("versi lama"), 1))

    def test_stuck_door_times_out(self):
        r = self.rig(auto_close_s=0)            # pintu terbuka dan tidak pernah terbaca tertutup
        r.master.request_open(5)
        self.assertTrue(wait_until(lambda: r.cell(5)["test"]["state"] == "running" and r.cell(5)["door"] == "open", 1))
        self.assertTrue(wait_until(lambda: r.cell(5)["test"]["state"] == "fail", 4), r.cell(5)["test"])
        self.assertIn("tidak selesai", r.cell(5)["test"]["msg"])

    def test_open_cell_full_cycle_pass(self):
        r = self.rig()
        ok, _ = r.master.request_open(3)
        self.assertTrue(ok)
        self.assertTrue(wait_until(lambda: r.cell(3)["solenoid"], 1))
        self.assertTrue(wait_until(lambda: r.cell(3)["door"] == "open" and r.cell(3)["led"], 1.5))
        self.assertTrue(wait_until(lambda: not r.cell(3)["solenoid"], 1.5), "solenoid harus OFF setelah pulse")
        self.assertTrue(wait_until(lambda: r.cell(3)["door"] == "closed" and not r.cell(3)["led"], 2))
        self.assertTrue(wait_until(lambda: r.cell(3)["test"]["state"] == "pass", 1))
        self.assertEqual(r.cell(3)["test"]["steps"], [True] * 6)
        self.assertEqual(r.cell(3)["open_count"], 1)
        # cell lain tidak tersentuh
        self.assertTrue(all(c["test"]["state"] == "idle" for c in r.snap()["cells"] if c["id"] != 3))
        self.assertFalse(r.events("tanpa perintah"))

    def test_open_all_sequential_fifo(self):
        r = self.rig()
        max_active = 0

        def sample():
            nonlocal max_active
            r.sim.tick()
            max_active = max(max_active, sum(c.solenoid for c in r.sim.cells))
            return all(c["test"]["state"] == "pass" for c in r.snap()["cells"])

        ok, _ = r.master.request_open_all()
        self.assertTrue(ok)
        self.assertTrue(wait_until(sample, 10, step=0.01), [c["test"] for c in r.snap()["cells"]])
        self.assertEqual(max_active, 1, "hanya 1 solenoid boleh aktif bersamaan")
        self.assertEqual(r.sim.history, list(range(1, 11)), "urutan buka harus 1..10 (FIFO)")
        self.assertFalse(r.events("tanpa perintah"), "cell yang menunggu antrean tidak boleh dianggap dibuka paksa")

    def test_faulty_cell_fails(self):
        r = self.rig(faulty=[7])
        r.master.request_open(7)
        self.assertTrue(wait_until(lambda: r.cell(7)["test"]["state"] == "fail", 3))
        self.assertIn("Pintu tidak terbuka", r.cell(7)["test"]["msg"])
        self.assertTrue(r.events("TEST cell 07 GAGAL"))

    def test_unauthorized_open_warning(self):
        r = self.rig(auto_close_s=0)
        r.sim.set_door(5, True)
        self.assertTrue(wait_until(lambda: r.events("Cell 05: pintu TERBUKA tanpa perintah"), 1))
        self.assertTrue(r.cell(5)["led"], "LED harus ON saat pintu terbuka")
        r.sim.set_door(5, False)
        self.assertTrue(wait_until(lambda: not r.cell(5)["led"] and r.cell(5)["door"] == "closed", 1))

    def test_stop_clears_queue(self):
        r = self.rig()
        r.master.request_open_all()
        self.assertTrue(wait_until(lambda: r.snap()["summary"]["queued"] >= 3, 2))
        r.master.request_stop()
        self.assertTrue(wait_until(lambda: r.events("STOP: semua solenoid dimatikan"), 1))
        time.sleep(0.2)
        s = r.snap()["summary"]
        self.assertEqual((s["solenoid_on"], s["queued"], s["test_running"]), (0, 0, 0))
        started = len(r.sim.history)
        time.sleep(0.6)
        self.assertEqual(len(r.sim.history), started, "tidak boleh ada solenoid aktif setelah STOP")

    def test_offline_and_recovery(self):
        r = self.rig()
        r.sim.online = False
        self.assertTrue(wait_until(lambda: r.snap()["link"]["state"] == "offline", 2))
        self.assertTrue(all(c["stale"] for c in r.snap()["cells"]))
        ok, msg = r.master.request_open(1)
        self.assertFalse(ok)
        self.assertEqual(len(r.events("Koneksi ESP32 terputus")), 1, "event offline tidak boleh berulang")
        r.sim.online = True
        self.assertTrue(wait_until(lambda: r.snap()["link"]["online"] and not r.cell(1)["stale"], 2))
        self.assertTrue(wait_until(lambda: len(r.events("ESP32 terhubung")) >= 2, 1), "PING ulang setelah pulih")

    def test_reboot_detected(self):
        r = self.rig()
        r.sim._boot_at -= 100          # anggap ESP32 sudah hidup 100 detik
        self.assertTrue(wait_until(lambda: (r.snap()["link"]["uptime_s"] or 0) >= 100, 1))
        r.sim.reboot("BROWNOUT")
        self.assertTrue(wait_until(lambda: r.events("ESP32 restart terdeteksi"), 1))
        self.assertTrue(wait_until(lambda: r.events("restart karena BROWNOUT"), 1))
        self.assertEqual(r.snap()["link"]["restarts"], 1)

    def test_noisy_line(self):
        r = self.rig(noisy=True)
        r.master.request_open(2)
        self.assertTrue(wait_until(lambda: r.cell(2)["test"]["state"] == "pass", 4), r.cell(2)["test"])
        link = r.snap()["link"]
        self.assertGreater(link["crc_errors"], 0)
        self.assertGreater(link["echo"], 0)
        self.assertTrue(link["online"])


class TestWebApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = SimulatedESP32(pulse_s=0.3, open_delay_s=0.08, auto_close_s=0.5)
        cfg = dict(FAST_CFG, simulation=True)
        cls.master = LockerMaster(cfg, lambda: cls.sim)
        cls.master.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(cls.master, cls.sim))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        wait_until(lambda: cls.master.snapshot()["link"]["online"], 3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.master.stop()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as res:
            return res.status, res.headers.get("Content-Type"), res.read()

    def post(self, path, body=None, raw=None):
        data = raw if raw is not None else json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read() or b"{}")

    def test_static_files(self):
        for path, ctype in (("/", "text/html"), ("/app.js", "javascript"), ("/style.css", "text/css")):
            status, ct, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(ctype, ct)
            self.assertGreater(len(body), 500)

    def test_path_traversal_blocked(self):
        for path in ("/../app.py", "/%2e%2e/app.py", "/web/../../app.py"):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(path)
            with ctx.exception:
                self.assertEqual(ctx.exception.code, 404)

    def test_state_json(self):
        _, ct, body = self.get("/api/state")
        s = json.loads(body)
        self.assertIn("application/json", ct)
        self.assertEqual(len(s["cells"]), 10)
        self.assertTrue(s["simulation"])
        self.assertEqual(s["test_steps"][0], "Perintah")

    def test_open_and_errors(self):
        self.assertEqual(self.post("/api/open", {"cell": 4})[0], 200)
        self.assertTrue(wait_until(lambda: self.master.snapshot()["cells"][3]["test"]["state"] == "pass", 3))
        self.assertEqual(self.post("/api/open", {"cell": 11})[0], 409)
        self.assertEqual(self.post("/api/open", raw=b"{bukan json")[0], 400)
        self.assertEqual(self.post("/api/tidak-ada")[0], 404)

    def test_sim_toggle_and_reset(self):
        status, body = self.post("/api/sim/door", {"cell": 9})
        self.assertEqual(status, 200)
        self.assertIn("dibuka", body["message"])
        self.assertTrue(wait_until(lambda: self.master.snapshot()["cells"][8]["door"] == "open", 1))
        self.assertEqual(self.post("/api/test/reset")[0], 200)


if __name__ == "__main__":
    unittest.main()
