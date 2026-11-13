# PCB QC Tester – Raspberry Pi 4B (PCB v3.3)

Program untuk menguji fungsi PCB v3.3: Digital Input (16 GPIO), Relay, RTC DS3231,
RS485 (dengan ESP32-S3 sebagai lawan komunikasi), Mini Display MAX7219 32×8,
lalu menyimpulkan **LULUS / TIDAK LULUS QC**. UI berupa halaman web lokal yang
dibuka Chromium layar penuh (kiosk). Tata letak disesuaikan untuk monitor 15,6"
(1920×1080 maupun 1366×768, tanpa scroll).

```
pcb_tester/
├── raspi/                    -> disalin ke Raspberry Pi
│   ├── app.py                program utama (web server + QC)
│   ├── config.py             SEMUA pin & parameter (sesuai Excel v3.3)
│   ├── testers.py            logika pengujian tiap fungsi
│   ├── hw/                   driver GPIO, MAX7219, DS3231, protokol RS485
│   ├── static/               UI (index.html, style.css, app.js)
│   ├── install.sh            instalasi otomatis + autostart (Pi baru)
│   ├── kiosk.sh              membuka UI layar penuh
│   └── switch-tester.sh      pindah PCB Tester <-> Locker Cell Tester
└── esp32/RS485_Responder/    sketch Arduino untuk ESP32-S3-DevKitC
```

## Pemetaan pin (BCM / nomor GPIO)

| Fungsi | Jalur KIRI | Jalur KANAN |
|---|---|---|
| BUTTON 1 | GPIO9 | GPIO25 |
| BUTTON 2 | GPIO8 | GPIO7 |
| BUTTON 3 | GPIO12 | GPIO16 |
| BUTTON 4 | GPIO20 | GPIO21 |
| LOOP 1 | GPIO22 | GPIO27 |
| LOOP 2 | GPIO18 | GPIO10 |
| FEEDBACK VLD | GPIO6 | GPIO5 |
| FEEDBACK GATE | GPIO26 | GPIO13 |
| Relay (ON/OFF bersamaan) | GPIO4 | GPIO17 |
| RTC DS3231 | SDA GPIO2 | SCL GPIO3 |
| RS485 | TX GPIO14 | RX GPIO15 |
| MAX7219 | CLK GPIO23 · CS GPIO24 · DIN GPIO19 | |

> GPIO7/8/9/10 adalah pin SPI0 dan GPIO4 pin 1-Wire, jadi **SPI0 dan 1-Wire harus OFF**
> (`install.sh` menanganinya). MAX7219 dijalankan secara *bit-bang* karena pin 23/24/19
> bukan pin SPI hardware.

## Instalasi di Raspberry Pi

1. Salin folder `raspi` ke Pi, misalnya ke `/home/pi/pcb_tester/raspi`.
2. Jalankan:
   ```bash
   cd /home/pi/pcb_tester/raspi && bash install.sh
   ```
   Skrip ini: memasang `python3-lgpio`, `python3-serial`, `smbus2`; mengaktifkan I2C & UART
   hardware; mematikan serial console, Bluetooth (`dtoverlay=disable-bt` agar UART PL011
   stabil), SPI0 & 1-Wire; membuat service `pcb-tester` (jalan otomatis saat boot) dan
   autostart Chromium kiosk. Backup config lama: `config.txt.bak-pcbtester`.
3. `sudo reboot` → UI tampil otomatis.

Menjalankan manual (tanpa service):
```bash
sudo python3 app.py
```
`sudo` diperlukan agar program boleh mengubah jam sistem (sinkron RTC → sistem).
Mode simulasi (bisa di PC/laptop untuk melihat UI tanpa hardware): `python3 app.py --sim`.

### Instalasi yang sudah terpasang di Raspi `raspi-testing-pcb` (10.10.0.30)

- Lokasi program: `/home/pi/PCBTester/raspi` · service `pcb-tester` (root, autostart) ·
  kiosk autostart `~/.config/autostart/pcb-tester-kiosk.desktop`.
- OS Bullseye → backend GPIO **RPi.GPIO**; RTC dibaca langsung lewat `/dev/i2c-1`
  (kompatibel dengan `dtoverlay=i2c-rtc,ds3231` yang sudah aktif). `config.txt` **tidak diubah**.
- Locker Cell Tester **dinonaktifkan, tidak dihapus**, karena memakai `/dev/serial0` & port 8080
  yang sama. Pindah aplikasi kapan saja:
  ```bash
  ~/PCBTester/raspi/switch-tester.sh locker
  ```
  ```bash
  ~/PCBTester/raspi/switch-tester.sh pcb
  ```
- UI juga bisa dibuka dari PC lain di jaringan: `http://10.10.0.30:8080`.

## Program ESP32-S3 (lawan RS485)

1. Arduino IDE → Board Manager → pasang **esp32 by Espressif** (2.x atau 3.x).
2. Board: **ESP32S3 Dev Module**. Buka `esp32/RS485_Responder/RS485_Responder.ino`, upload.
3. Wiring modul RS485 di sisi ESP32: **GPIO17 → DI/TXD**, **GPIO18 ← RO/RXD**, A↔A, B↔B,
   **GND ESP32 ↔ GND PCB**. Bila modulnya MAX485 biasa (punya pin DE/RE), sambungkan DE+RE ke
   sebuah GPIO dan isi `RS485_DE_PIN`. Baudrate default 115200 (harus sama dengan `config.py`).
4. LED RGB ESP32: hijau = komunikasi baik, kedip biru = paket masuk, oranye = frame rusak,
   merah kedip = tidak ada paket. Serial Monitor 115200 menampilkan statistik.

Protokol: Raspi mengirim `$PING,<seq>,<data acak>*CRC` tiap 250 ms; ESP32 membalas
`$PONG` berisi data yang sama + CRC16. Raspi mengecek nomor urut, isi data, dan CRC, jadi
kedua arah (Raspi→ESP & ESP→Raspi) terbukti. Bila ESP menerima frame rusak ia membalas `NACK`
sehingga arah yang bermasalah bisa diketahui.

## SOP pengujian satu PCB

1. Isi **No. seri PCB** dan **Operator** di panel QC (kanan).
2. **Digital Input** – untuk tiap label, tekan tombol dengan saklar pemilih di posisi KIRI,
   lalu pindahkan saklar ke KANAN dan tekan lagi. Pin yang menerima 3,3 V menyala **hijau**,
   pin lainnya **merah**. Setiap pin diberi tanda `✓ OK` setelah terbukti LOW → HIGH.
   Baris *JALUR AKTIF* menunjukkan jalur yang sedang/terakhir dipakai. Bila kedua jalur HIGH
   bersamaan (> 60 ms) muncul peringatan merah (indikasi short) dan test GAGAL.
3. **Relay** – atur waktu aktif/mati (default 1,5 s / 1,0 s), tekan **Mulai**. Setelah ≥ 5
   siklus, konfirmasi bahwa relay berbunyi klik & indikator menyala.
4. **RTC** – otomatis: terdeteksi di I2C 0x68, detik berjalan, lalu disinkronkan.
5. **RS485** – otomatis: lulus setelah ≥ 20 balasan valid dengan tingkat sukses ≥ 95 %.
6. **MAX7219** – mode *Auto Test* menjalankan: **uji bertahap** (modul 1 → 4 bergantian,
   64 LED per modul, modul lain mati), scan baris, scan kolom, papan catur per modul, nomor
   modul 1–4, lalu teks berjalan. Mode *Bertahap 8×8* hanya menjalankan uji bertahap.
   Mode "semua LED nyala" dan register Display-Test **sengaja dihapus** (merusak AMS1117,
   lihat dokumen RCA). Tampilan di UI adalah cermin frame yang sama persis; angka *Delay ke
   UI*, *Kirim ke MAX7219* dan *Arus ≈* (estimasi arus VCC display) ikut ditampilkan.
   Konfirmasi 2 pertanyaan operator.
7. Panel QC menampilkan **LULUS QC** bila kelima test lulus. Tekan **Simpan Laporan**
   (tersimpan di `raspi/reports/`: JSON detail per PCB + `qc_log.csv` rekap, siap dibuka
   Excel), lalu **PCB Baru** untuk PCB berikutnya.

## Sinkronisasi RTC otomatis

| Kondisi | Tindakan program |
|---|---|
| Pi terhubung internet (NTP tersinkron) | Jam sistem ditulis ke RTC bila selisih > 2 s |
| Tanpa internet, waktu RTC valid | Jam sistem diambil dari RTC |
| Tanpa internet, RTC belum pernah diset (flag OSF) | Jam sistem ditulis ke RTC (dengan peringatan) |

RTC menyimpan waktu **UTC** (sama seperti standar `hwclock` Linux); tampilan memakai zona
waktu Pi (`sudo raspi-config` → Localisation → Timezone → Asia/Jakarta). Tombol manual:
*Sistem → RTC*, *RTC → Sistem*, *Jam perangkat ini* (memakai jam perangkat yang membuka UI).
Status yang mungkin: TERSINKRON, BELUM SINKRON, WAKTU BELUM DISET (OSF / baterai lemah),
OSILATOR BERHENTI, TIDAK TERHUBUNG, I2C TIDAK AKTIF.

Jangan aktifkan `dtoverlay=i2c-rtc,ds3231` bersamaan: program membaca register DS3231
secara langsung (termasuk suhu chip & flag OSF).

## Kalibrasi orientasi MAX7219

Modul 4-in-1 berbeda-beda susunan internalnya. Pada mode *Auto Test*, fase **Scan kolom**
harus bergerak kiri → kanan dan **Identitas modul** harus tampil `1 2 3 4` tegak dari kiri.
Bila belum, ubah **Orientasi modul** (0/90/180/270°), **Cermin**, atau **Balik urutan** di UI
sampai benar – perubahan langsung berlaku dan tersimpan di `settings.json`.

## Tentang pengukuran tegangan

Raspberry Pi 4B **tidak punya ADC**, sehingga tegangan yang diterima GPIO tidak bisa diukur;
UI menampilkan level logika (HIGH/LOW) dan kualitas sinyal berdasarkan jumlah
*glitch/bounce* (pulsa < 15 ms). Untuk pengukuran tegangan nyata perlu ADC eksternal
(mis. ADS1115 via I2C) – bisa ditambahkan kemudian.

## Parameter penting (`raspi/config.py`)

| Parameter | Default | Keterangan |
|---|---|---|
| `DI_INTERNAL_PULL` | `"down"` | Pull-down internal Pi aktif – di PCB v3.3 jalur yang tidak dipilih saklar mengambang (terukur di hardware) |
| `RELAY_ACTIVE_HIGH` | `True` | Ubah ke `False` bila driver relay aktif-LOW |
| `RS485_BAUD` | `115200` | Harus sama dengan sketch ESP32 |
| `RS485_DE_PIN` | `None` | Isi nomor GPIO bila transceiver RS485 di PCB punya pin DE/RE |
| `MAX7219_ROTATION` | `90` | Nilai awal orientasi (bisa diubah dari UI) |
| `MAX7219_CURRENT_BUDGET_MA` | `120` | Batas arus rata-rata display; kecerahan diturunkan otomatis. Batas termal AMS1117 12→5 V. Naikkan ke 800 hanya setelah suplai diganti buck converter |
| `MAX7219_ISEG_MA` | `40` | Arus segmen MAX7219 (RSET 10 kΩ); sesuaikan bila RSET modul berbeda |
| `HTTP_PORT` | `8080` | Port UI |

## Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| Pin tampil **ERROR / GPIO sibuk** | Pin diklaim driver lain: pastikan SPI0, 1-Wire, I2S OFF lalu reboot |
| Pin berkedip-kedip sendiri, glitch tinggi | Resistor pull-down PCB tidak terpasang/putus (input mengambang) |
| RTC **I2C TIDAK AKTIF** | `sudo raspi-config` → Interface → I2C → Enable, reboot |
| RTC **TIDAK TERHUBUNG** | `i2cdetect -y 1` harus menampilkan `68`. Cek SDA/SCL/VCC/GND |
| RTC **WAKTU BELUM DISET** berulang setelah restart Pi | Baterai RTC lemah/habis |
| RS485 **PORT ERROR** | UART belum aktif / serial console masih aktif → jalankan ulang `install.sh` |
| RS485 **TIDAK ADA RESPON** | A/B tertukar, GND tidak tersambung, baud beda, atau sketch ESP32 belum jalan |
| RS485 **CRC / NACK** naik | Noise / kabel panjang: pasang terminasi 120 Ω, turunkan baud |
| Display tidak menyala sama sekali | Cek VCC 5 V modul, CLK/CS/DIN; perhatikan status "Driver error" |
| Log program | `journalctl -u pcb-tester -f` |
