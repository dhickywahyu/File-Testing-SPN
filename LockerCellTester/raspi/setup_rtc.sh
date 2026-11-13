#!/usr/bin/env bash
# =============================================================================
#  Setup RTC DS3231 (DS3231SN) untuk Raspberry Pi — Locker Cell Tester
#
#  Wiring modul RTC ke header 40-pin Raspberry Pi:
#     VCC -> pin 1 (3V3)   SDA -> pin 3 (GPIO2)   SCL -> pin 5 (GPIO3)   GND -> pin 9
#
#  Jalankan sebagai user biasa:
#     bash setup_rtc.sh          -> pasang konfigurasi, lalu: sudo reboot
#     bash setup_rtc.sh --check  -> cek status RTC & sinkronisasi (setelah reboot)
#
#  Cara kerja:
#   - Overlay kernel i2c-rtc,ds3231 -> RTC muncul sebagai /dev/rtc0
#   - Saat boot   : waktu sistem diambil dari RTC (service locker-rtc), sebelum sinkron NTP
#   - Tiap 1 jam  : bila waktu sudah tersinkron internet (NTP), waktu disimpan ke RTC
#   - Saat shutdown: waktu disimpan ke RTC (bila tersinkron NTP)
#   RTC selalu menyimpan waktu UTC; zona waktu tampilan mengikuti setting sistem.
# =============================================================================
set -euo pipefail

BOOT_DIR=/boot/firmware
[ -f "$BOOT_DIR/config.txt" ] || BOOT_DIR=/boot
CONFIG="$BOOT_DIR/config.txt"

# hwclock & i2cdetect ada di /usr/sbin (tidak ada di PATH user biasa) -> cek lewat sudo
have() { sudo sh -c "command -v $1" >/dev/null 2>&1; }

check() {
  echo "== I2C bus 1 (alamat DS3231 = 0x68, tampil 'UU' bila driver aktif)"
  if have i2cdetect; then sudo i2cdetect -y 1 | sed -n '1p;8p'; else echo "  (i2c-tools belum terpasang)"; fi
  echo "== Device RTC"
  if [ -e /dev/rtc0 ]; then
    echo "  /dev/rtc0 ada: $(cat /sys/class/rtc/rtc0/name 2>/dev/null)"
    echo "  Waktu RTC  : $(sudo hwclock --rtc=/dev/rtc0 --get 2>&1)"
  else
    echo "  /dev/rtc0 TIDAK ADA — cek wiring & reboot setelah setup"
  fi
  echo "  Waktu sistem: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "== Sinkronisasi"
  timedatectl | sed 's/^/  /'
  echo "== Service"
  systemctl --no-pager --lines=0 status locker-rtc.service locker-rtc-save.timer 2>/dev/null | grep -E "●|Active:" | sed 's/^/  /'
}

if [ "${1:-}" = "--check" ]; then
  check
  exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "Jalankan tanpa sudo:  bash setup_rtc.sh"
  exit 1
fi

step() { printf '\n\033[1;36m[%s] %s\033[0m\n' "$1" "$2"; }

step 1/5 "Paket: i2c-tools & hwclock"
if ! have i2cdetect || ! have hwclock; then
  sudo apt-get update || true
  have i2cdetect || sudo apt-get install -y i2c-tools || echo "  (lewati: i2c-tools gagal dipasang)"
  have hwclock || sudo apt-get install -y util-linux-extra || sudo apt-get install -y util-linux
fi
have hwclock || { echo "hwclock tidak tersedia, hentikan."; exit 1; }
if have i2cdetect; then
  scan=$(sudo i2cdetect -y 1 2>&1 || true)       # simpan dulu: grep -q + pipefail bisa salah lapor (SIGPIPE)
  if grep -qE '^60:.*( 68|UU)' <<< "$scan"; then
    echo "  DS3231 terdeteksi di I2C bus 1 (0x68)"
  else
    echo "  PERINGATAN: DS3231 (0x68) tidak terdeteksi. Cek wiring SDA/SCL/VCC/GND."
  fi
fi

step 2/5 "Aktifkan I2C & overlay RTC DS3231 di $CONFIG"
[ -f "$CONFIG.bak-rtc" ] || sudo cp "$CONFIG" "$CONFIG.bak-rtc"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_i2c 0
else
  grep -q '^dtparam=i2c_arm=on' "$CONFIG" || echo 'dtparam=i2c_arm=on' | sudo tee -a "$CONFIG" >/dev/null
fi
if ! grep -q '^dtoverlay=i2c-rtc,ds3231' "$CONFIG"; then
  if grep -qE '^#\s*dtoverlay=i2c-rtc,ds3231\s*$' "$CONFIG"; then
    sudo sed -i -E 's/^#\s*(dtoverlay=i2c-rtc,ds3231)\s*$/\1/' "$CONFIG"      # aktifkan baris yang dikomentari
  else
    echo 'dtoverlay=i2c-rtc,ds3231' | sudo tee -a "$CONFIG" >/dev/null
  fi
fi
grep -n 'i2c-rtc' "$CONFIG" | sed 's/^/  /'

step 3/5 "Nonaktifkan fake-hwclock (digantikan RTC)"
sudo systemctl disable --now fake-hwclock.service >/dev/null 2>&1 || true

step 4/5 "Pasang script & service sinkronisasi RTC"
sudo tee /usr/local/sbin/locker-rtc >/dev/null <<'EOF'
#!/bin/sh
# locker-rtc load|save [--force] — sinkronisasi waktu sistem <-> RTC DS3231 (/dev/rtc0, UTC)
RTC=/dev/rtc0
MIN_VALID=1735689600   # 2025-01-01: waktu RTC lebih lama dari ini dianggap belum di-set / baterai habis
HWCLOCK=$(command -v hwclock || echo /sbin/hwclock)
i=0
while [ ! -e "$RTC" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
[ -e "$RTC" ] || { echo "locker-rtc: $RTC tidak ditemukan"; exit 0; }
case "$1" in
  load)
    rtc_epoch=$(cat /sys/class/rtc/rtc0/since_epoch 2>/dev/null || echo 0)
    if [ "$rtc_epoch" -lt "$MIN_VALID" ]; then
      echo "locker-rtc: waktu RTC tidak valid ($rtc_epoch), jam sistem tidak diubah"
      exit 0
    fi
    "$HWCLOCK" --rtc="$RTC" --hctosys --utc && echo "locker-rtc: jam sistem diset dari RTC: $(date)"
    ;;
  save)
    synced=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
    if [ "$synced" = "yes" ] || [ "$2" = "--force" ]; then
      "$HWCLOCK" --rtc="$RTC" --systohc --utc && echo "locker-rtc: RTC diperbarui: $(date)"
    else
      echo "locker-rtc: belum tersinkron NTP, RTC tidak ditimpa"
    fi
    ;;
  *) echo "pakai: locker-rtc load|save [--force]"; exit 1 ;;
esac
EOF
sudo chmod 755 /usr/local/sbin/locker-rtc

sudo tee /etc/systemd/system/locker-rtc.service >/dev/null <<'EOF'
[Unit]
Description=Jam sistem dari RTC DS3231 (boot) & simpan ke RTC (shutdown)
DefaultDependencies=no
After=systemd-udev-trigger.service systemd-modules-load.service
Before=time-sync.target sysinit.target shutdown.target
Wants=time-sync.target
Conflicts=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/locker-rtc load
ExecStop=/usr/local/sbin/locker-rtc save

[Install]
WantedBy=sysinit.target
EOF

sudo tee /etc/systemd/system/locker-rtc-save.service >/dev/null <<'EOF'
[Unit]
Description=Simpan waktu NTP ke RTC DS3231

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/locker-rtc save
EOF

sudo tee /etc/systemd/system/locker-rtc-save.timer >/dev/null <<'EOF'
[Unit]
Description=Simpan waktu NTP ke RTC DS3231 tiap jam

[Timer]
OnBootSec=3min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable locker-rtc.service
sudo systemctl enable --now locker-rtc-save.timer

step 5/5 "Sinkronisasi awal (isi RTC dengan waktu NTP sekarang)"
if [ ! -e /dev/rtc0 ] && command -v dtoverlay >/dev/null 2>&1; then
  sudo dtoverlay i2c-rtc ds3231 >/dev/null 2>&1 || true     # muat driver sekarang tanpa menunggu reboot
  sleep 1
fi
if [ -e /dev/rtc0 ]; then
  sudo /usr/local/sbin/locker-rtc save
  echo "  Waktu RTC: $(sudo hwclock --rtc=/dev/rtc0 --get 2>&1)"
else
  echo "  /dev/rtc0 belum ada (overlay aktif setelah reboot)."
fi

printf '\n\033[1;32mSetup RTC selesai.\033[0m Reboot lalu cek:  sudo reboot  ->  bash setup_rtc.sh --check\n'
