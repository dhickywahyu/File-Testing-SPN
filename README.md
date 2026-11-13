# File Testing SPN

Backup file dari Raspberry Pi 4B **raspi-testing-pcb** (`/home/pi`), diambil 13 Nov 2026.

## Isi

| Folder / file | Keterangan |
|---|---|
| `PCBTester/` | Program tester PCB (dipakai oleh `pcb-tester.service`) |
| `LockerCellTester/` | Tester locker cell + firmware ESP32 (dipakai oleh `locker-tester.service`) |
| `LockerCellTester.bak-20260923-195528/` | Backup lama LockerCellTester |
| `spn-advertisement/`, `spn-testingdisplay/`, `spn-testingpcb3.0/`, `spn-testingpcb4.0/`, `testingpcb3.2/`, `test-relay/`, `test-serial/`, `restart_project/` | Proyek & skrip testing lain |
| `setup_rtc.sh` | Skrip setup RTC |
| `system-config/systemd/` | Service systemd custom (salin ke `/etc/systemd/system/`) |
| `system-config/boot/` | `config.txt` & `cmdline.txt` dari `/boot` (referensi saja) |

**Tidak ikut di-backup:** OS, `.platformio` (toolchain), cache/config desktop, `venv`, `__pycache__`, `.pio`, `.ssh`,
serta `spn-gate/` dan `spn-dds-hardware/` (repo private perusahaan — clone langsung dari
`github.com/soulparking/spn-gate` branch `master` dan `github.com/soulparking/spn-dds-hardware`
branch `dev/panel-dispenser-pro`; `.env` spn-gate dibuat ulang dari `.env.example`).

## Restore di Raspberry Pi lain

```bash
cd ~
git clone https://github.com/dhickywahyu/File-Testing-SPN.git
cp -r File-Testing-SPN/. ~/          # atau salin folder yang diperlukan saja

# Service systemd
sudo cp ~/File-Testing-SPN/system-config/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pcb-tester.service    # sesuaikan service yang dipakai

# Virtualenv Python dibuat ulang per proyek bila perlu, contoh:
cd ~/test-serial && python3 -m venv venv && . venv/bin/activate
```
