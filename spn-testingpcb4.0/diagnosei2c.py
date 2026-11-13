#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          I2C & DS3231 DIAGNOSTIC TOOL                       ║
║  Jalankan: sudo python3 diagnose_i2c.py                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys
import subprocess

EXPECTED_DEVICES = {
    0x20: "MCP23017 — Digital Input #1",
    0x21: "MCP23017 — Digital Input #2",
    0x25: "MCP23017 — Digital Output",
    0x68: "DS3231SN# — RTC",
}

def header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")

def check_pass(msg):
    print(f"  ✅  {msg}")

def check_fail(msg):
    print(f"  ❌  {msg}")

def check_warn(msg):
    print(f"  ⚠️   {msg}")

def check_info(msg):
    print(f"  ℹ️   {msg}")


def main():
    print("\n🔧  I2C & DS3231 DIAGNOSTIC TOOL\n")

    # ── TEST 1: Running as root? ──────────────────────────────
    header("TEST 1: Permission Check")
    euid = os.geteuid()
    if euid == 0:
        check_pass("Running as root (sudo)")
    else:
        check_warn(f"Running as UID {euid} (bukan root)")
        # Check i2c group membership
        import grp
        try:
            i2c_group = grp.getgrnam("i2c")
            username = os.getlogin()
            if username in i2c_group.gr_mem:
                check_pass(f"User '{username}' ada di group 'i2c'")
            else:
                check_fail(f"User '{username}' TIDAK ada di group 'i2c'")
                check_info("Perbaiki: sudo usermod -aG i2c $USER  lalu reboot")
        except KeyError:
            check_warn("Group 'i2c' tidak ditemukan di sistem")
        except OSError:
            pass

    # ── TEST 2: I2C kernel module loaded? ─────────────────────
    header("TEST 2: I2C Kernel Module")
    try:
        lsmod = subprocess.run(["lsmod"], capture_output=True, text=True)
        if "i2c_dev" in lsmod.stdout:
            check_pass("Module 'i2c_dev' loaded")
        else:
            check_fail("Module 'i2c_dev' TIDAK loaded")
            check_info("Perbaiki: sudo modprobe i2c-dev")
            check_info("Atau aktifkan I2C via: sudo raspi-config → Interface Options → I2C")

        if "i2c_bcm" in lsmod.stdout:
            check_pass("Module 'i2c_bcm2835' loaded (RPi I2C hardware)")
        else:
            check_warn("Module 'i2c_bcm2835' tidak terdeteksi di lsmod")
    except FileNotFoundError:
        check_warn("lsmod command tidak ditemukan")

    # ── TEST 3: /dev/i2c-1 exists? ────────────────────────────
    header("TEST 3: I2C Device Node")
    i2c_dev = "/dev/i2c-1"
    if os.path.exists(i2c_dev):
        check_pass(f"{i2c_dev} exists")
        # Check permissions
        stat = os.stat(i2c_dev)
        mode = oct(stat.st_mode)[-3:]
        check_info(f"Permissions: {mode}")
        if os.access(i2c_dev, os.R_OK | os.W_OK):
            check_pass(f"{i2c_dev} readable & writable by current user")
        else:
            check_fail(f"{i2c_dev} TIDAK bisa dibaca/tulis oleh current user")
            check_info("Perbaiki: sudo chmod 666 /dev/i2c-1  (sementara)")
            check_info("Atau: sudo usermod -aG i2c $USER  lalu reboot (permanen)")
    else:
        check_fail(f"{i2c_dev} TIDAK ADA")
        check_info("I2C belum diaktifkan. Jalankan: sudo raspi-config → I2C → Enable")

    # ── TEST 4: i2cdetect scan ────────────────────────────────
    header("TEST 4: I2C Bus Scan (i2cdetect)")
    try:
        result = subprocess.run(
            ["i2cdetect", "-y", "1"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            check_pass("i2cdetect berhasil dijalankan")
            print(f"\n{result.stdout}")

            # Parse detected addresses
            detected = set()
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split(":")[1] if ":" in line else ""
                for token in parts.split():
                    token = token.strip()
                    if token != "--" and token != "UU" and len(token) == 2:
                        try:
                            detected.add(int(token, 16))
                        except ValueError:
                            pass
                    elif token == "UU":
                        # UU means device is used by a kernel driver
                        # We need the column position to figure out address
                        pass

            print("  Detected addresses:", [f"0x{a:02X}" for a in sorted(detected)])
            print()

            for addr, name in sorted(EXPECTED_DEVICES.items()):
                if addr in detected:
                    check_pass(f"0x{addr:02X} — {name}")
                else:
                    check_fail(f"0x{addr:02X} — {name} → TIDAK TERDETEKSI")

            # Special check for 0x68
            if 0x68 not in detected:
                print()
                check_fail("DS3231SN# (0x68) tidak ditemukan di I2C bus!")
                check_info("Kemungkinan penyebab:")
                check_info("  1. Kabel SDA/SCL belum tersambung / terbalik")
                check_info("  2. Kabel VCC/GND belum tersambung")
                check_info("  3. Soldering cold joint / bad connection")
                check_info("  4. Chip DS3231 rusak")
                check_info("  5. Alamat I2C di-override oleh kernel driver (cek 'UU')")
        else:
            check_fail(f"i2cdetect gagal: {result.stderr.strip()}")
    except FileNotFoundError:
        check_fail("i2cdetect tidak terinstall")
        check_info("Install: sudo apt install -y i2c-tools")
    except subprocess.TimeoutExpired:
        check_fail("i2cdetect timeout")

    # ── TEST 5: Check if kernel RTC driver claims the device ──
    header("TEST 5: Kernel RTC Driver Check")
    check_info("Jika kernel driver rtc-ds1307 sudah claim DS3231,")
    check_info("maka alamat 0x68 akan muncul sebagai 'UU' di i2cdetect")
    check_info("dan smbus TIDAK BISA mengakses device secara langsung.")
    print()

    # Check /sys/class/rtc
    rtc_path = "/sys/class/rtc"
    if os.path.exists(rtc_path):
        rtc_devices = os.listdir(rtc_path)
        if rtc_devices:
            check_info(f"RTC devices di /sys/class/rtc/: {rtc_devices}")
            for rtc_dev in rtc_devices:
                name_path = os.path.join(rtc_path, rtc_dev, "name")
                if os.path.exists(name_path):
                    with open(name_path) as f:
                        check_info(f"  {rtc_dev} → name: {f.read().strip()}")
        else:
            check_info("Tidak ada RTC device di /sys/class/rtc/")
    else:
        check_info("/sys/class/rtc/ tidak ditemukan")

    # Check /boot/config.txt or /boot/firmware/config.txt for dtoverlay
    for config_path in ["/boot/firmware/config.txt", "/boot/config.txt"]:
        if os.path.exists(config_path):
            check_info(f"Checking {config_path} for RTC overlay...")
            with open(config_path) as f:
                content = f.read()
            rtc_lines = [
                line.strip() for line in content.split("\n")
                if "rtc" in line.lower() or "ds3231" in line.lower() or "ds1307" in line.lower()
            ]
            if rtc_lines:
                for line in rtc_lines:
                    check_warn(f"Ditemukan: {line}")
                print()
                check_warn("⚡ Kernel driver RTC aktif! Ini bisa meng-claim 0x68")
                check_warn("   sehingga smbus tidak bisa akses DS3231 secara langsung.")
                check_info("SOLUSI A: Hapus/comment baris dtoverlay RTC di config.txt lalu reboot")
                check_info("SOLUSI B: Gunakan /dev/rtc0 untuk baca waktu (lihat program utama)")
            else:
                check_pass("Tidak ada RTC dtoverlay di config.txt")
            break

    # ── TEST 6: Direct smbus probe ──────────────────────────
    header("TEST 6: Direct smbus Probe ke 0x68")
    try:
        try:
            import smbus
            bus = smbus.SMBus(1)
            check_pass("smbus.SMBus(1) berhasil dibuka (native library)")
        except ImportError:
            import smbus2
            bus = smbus2.SMBus(1)
            check_pass("smbus2.SMBus(1) berhasil dibuka (fallback library)")

        try:
            val = bus.read_byte_data(0x68, 0x00)
            check_pass(f"read_byte_data(0x68, 0x00) = 0x{val:02X} — DS3231 MERESPONS!")

            # Read time registers byte-by-byte (proven stable)
            data = []
            for reg in range(7):
                data.append(bus.read_byte_data(0x68, reg))
            bcd = lambda b: (b >> 4) * 10 + (b & 0x0F)
            sec = bcd(data[0] & 0x7F)
            mn  = bcd(data[1] & 0x7F)
            hr  = bcd(data[2] & 0x3F)
            day = bcd(data[4] & 0x3F)
            mon = bcd(data[5] & 0x7F)
            yr  = bcd(data[6]) + 2000
            check_pass(f"RTC Time: {yr:04d}-{mon:02d}-{day:02d} {hr:02d}:{mn:02d}:{sec:02d}")

            # Read temperature byte-by-byte
            msb = bus.read_byte_data(0x68, 0x11)
            lsb = bus.read_byte_data(0x68, 0x12)
            temp = msb + (lsb >> 6) * 0.25
            check_pass(f"RTC Temp: {temp:.2f} °C")

        except OSError as e:
            check_fail(f"OSError saat baca 0x68: {e}")
            check_info(f"errno: {e.errno} — biasanya device tidak ada atau di-claim kernel driver")
        except IOError as e:
            check_fail(f"IOError saat baca 0x68: {e}")
        except Exception as e:
            check_fail(f"Exception lain: {type(e).__name__}: {e}")

        bus.close()
    except ImportError:
        check_fail("smbus tidak terinstall → sudo apt install python3-smbus")
    except PermissionError as e:
        check_fail(f"PermissionError: {e}")
        check_info("Jalankan dengan sudo: sudo python3 diagnose_i2c.py")
    except FileNotFoundError:
        check_fail("/dev/i2c-1 tidak ditemukan — I2C belum diaktifkan")
    except Exception as e:
        check_fail(f"Error membuka SMBus: {type(e).__name__}: {e}")

    # ── SUMMARY ───────────────────────────────────────────────
    header("RINGKASAN")
    print("""
  Jika DS3231 TIDAK terdeteksi di TEST 4 (i2cdetect):
    → Periksa wiring SDA, SCL, VCC, GND

  Jika DS3231 muncul sebagai 'UU' di i2cdetect:
    → Kernel driver sudah meng-claim device
    → Hapus dtoverlay di /boot/firmware/config.txt lalu reboot
    → ATAU program akan otomatis fallback ke /dev/rtc0

  Jika DS3231 terdeteksi di i2cdetect tapi TEST 6 gagal:
    → Kemungkinan permission issue → jalankan dengan sudo

  Jika semua TEST pass tapi program utama masih tidak deteksi:
    → Jalankan program utama dengan sudo:
       sudo python3 pcb_tester.py
""")


if __name__ == "__main__":
    main()
