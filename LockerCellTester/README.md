# Locker Cell Tester — Raspberry Pi 4B + ESP32-S3 (RS485)

Sistem test fungsi open cell/locker 10 cell. Operator memilih cell di monitor 15,6" (Raspberry Pi),
perintah dikirim lewat RS485 ke ESP32-S3, solenoid cell aktif 1 detik, sensor pintu (kontak NO)
mendeteksi pintu terbuka dan LED cell menyala sampai pintu ditutup kembali.

Dokumentasi lengkap (analisa pin, wiring, cara kerja, protokol, flowchart, instalasi, troubleshooting, hasil QC):
**[docs/Dokumentasi_Locker_Cell_Tester.html](docs/Dokumentasi_Locker_Cell_Tester.html)** (versi cetak: `docs/Dokumentasi_Locker_Cell_Tester.pdf`).

## Isi folder

| Folder / file | Isi |
|---|---|
| `esp32/LockerController/LockerController.ino` | Firmware ESP32-S3 (Arduino IDE) |
| `raspi/app.py` | Program utama Raspberry Pi: web server UI + master RS485 |
| `raspi/rs485_master.py`, `protocol.py` | Komunikasi RS485, status cell, log, pelacak test |
| `raspi/esp32_simulator.py` | Simulator ESP32 untuk mode `--sim` dan test otomatis |
| `raspi/web/` | UI (HTML/CSS/JS, offline) |
| `raspi/install.sh`, `kiosk.sh`, `start.sh` | Installer, UI layar penuh, jalankan manual |
| `raspi/setup_rtc.sh` | Setup & cek RTC DS3231 (jam tetap benar tanpa internet) |
| `raspi/tests/` | 27 test otomatis |
| `docs/` | Dokumentasi HTML + PDF + screenshot UI |

## Mulai cepat

### ESP32-S3 (Arduino IDE)
Tools: **Board** ESP32S3 Dev Module · **USB CDC On Boot: Disabled** · **PSRAM: Disabled** · Flash Mode QIO 80MHz.
Upload lewat port USB berlabel **UART/COM**. Serial Monitor 115200 baud → ketik `help`.

### Raspberry Pi 4B
```bash
cd ~/LockerCellTester/raspi
bash install.sh
sudo reboot
```

RTC DS3231 (VCC→pin 1, SDA→pin 3, SCL→pin 5, GND→pin 9):
```bash
bash setup_rtc.sh
sudo reboot
bash setup_rtc.sh --check
```

Coba tanpa hardware (mode simulasi), lalu buka http://127.0.0.1:8080:
```bash
python3 app.py --sim
```

## Penting — temuan pada dokumen pin ESP32

1. **GPIO15 tertulis dua kali** (Indikator Pintu 1 dan LED 5). Berdasarkan urutan header kanan DevKitC-1,
   Indikator Pintu 1 = **GPIO45**. Firmware menolak compile bila ada GPIO ganda.
2. **GPIO19/20** (Indikator Pintu 6/5) adalah jalur USB D−/D+: wajib *USB CDC On Boot: Disabled*, pakai port UART.
   Input pintu tidak boleh `INPUT_PULLUP` (pull-up USB D+ ikut aktif → pintu 5 selalu HIGH; diperbaiki di v1.0.1).
3. **GPIO35–37** (Solenoid 10/9/8) bentrok dengan PSRAM octal pada modul **N8R8/N16R8**. Cek tulisan di modul.
4. **Indikator pintu aktif-HIGH** (pintu tertutup = HIGH). Cell tanpa sensor tampil TERBUKA + LED ON (sesuai spesifikasi).
5. **GPIO45** (pintu 1) adalah pin strapping: uji ESP32 tetap bisa boot saat pintu 1 tertutup.
6. Semua GPIO ESP32 & Raspberry Pi 3,3 V (tidak toleran 5 V). Modul RS485 diberi VCC 3,3 V.

Protokol: ASCII `>01,OPEN,3*54` / `<01,ACK,OPEN,3,STARTED*E1`, 38400 bps 8N1, CRC-8.
