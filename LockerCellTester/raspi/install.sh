#!/usr/bin/env bash
# =============================================================================
#  Installer Locker Cell Tester untuk Raspberry Pi OS (Bookworm / Bullseye)
#
#  Jalankan sebagai user desktop biasa (BUKAN dengan sudo):
#      cd ~/LockerCellTester/raspi && bash install.sh
#  Opsi: KEEP_BT=1 bash install.sh   -> Bluetooth tidak dimatikan (UART memakai mini-UART)
#
#  Yang dilakukan:
#   1. Memasang python3-serial & chromium
#   2. Menambahkan user ke grup dialout (akses port serial)
#   3. Mengaktifkan UART GPIO14 (TX) / GPIO15 (RX) dan melepas login console dari serial
#   4. Memasang service systemd "locker-tester" (backend otomatis jalan saat boot)
#   5. Autostart Chromium kiosk (UI layar penuh) saat desktop login
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="$(id -un)"
SERVICE_FILE=/etc/systemd/system/locker-tester.service

if [ "$(id -u)" -eq 0 ]; then
  echo "Jalankan tanpa sudo:  bash install.sh   (sudo akan diminta bila perlu)"
  exit 1
fi

step() { printf '\n\033[1;36m[%s] %s\033[0m\n' "$1" "$2"; }

step 1/5 "Memasang paket: python3-serial, chromium"
sudo apt-get update
sudo apt-get install -y python3 python3-serial
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
fi

step 2/5 "Izin akses port serial (grup dialout) untuk user $RUN_USER"
sudo usermod -aG dialout "$RUN_USER"

step 3/5 "Mengaktifkan UART GPIO14/GPIO15 untuk RS485"
BOOT_DIR=/boot/firmware
[ -f "$BOOT_DIR/config.txt" ] || BOOT_DIR=/boot
CONFIG="$BOOT_DIR/config.txt"
CMDLINE="$BOOT_DIR/cmdline.txt"
[ -f "$CONFIG.bak-locker" ] || sudo cp "$CONFIG" "$CONFIG.bak-locker"
[ -f "$CMDLINE.bak-locker" ] || sudo cp "$CMDLINE" "$CMDLINE.bak-locker"
grep -q '^enable_uart=1' "$CONFIG" || echo 'enable_uart=1' | sudo tee -a "$CONFIG" >/dev/null
if [ "${KEEP_BT:-0}" != "1" ]; then
  # PL011 (ttyAMA0) dipindah ke GPIO14/15 -> baudrate stabil. Bluetooth dinonaktifkan.
  grep -q '^dtoverlay=disable-bt' "$CONFIG" || echo 'dtoverlay=disable-bt' | sudo tee -a "$CONFIG" >/dev/null
  sudo systemctl disable hciuart >/dev/null 2>&1 || true
fi
# Login console di port serial harus dimatikan agar UART bebas dipakai RS485
sudo sed -i -E 's/console=(serial0|ttyAMA0|ttyS0),[0-9]+ ?//g' "$CMDLINE"
for tty in serial0 ttyAMA0 ttyS0; do
  sudo systemctl disable "serial-getty@$tty.service" >/dev/null 2>&1 || true
done
echo "  config.txt : $CONFIG (backup: $CONFIG.bak-locker)"
echo "  cmdline.txt: $CMDLINE (backup: $CMDLINE.bak-locker)"

step 4/5 "Memasang service backend (systemd): locker-tester"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Locker Cell Tester (master RS485 + web UI)
After=network.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=dialout
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 "$APP_DIR/app.py"
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable locker-tester.service
sudo systemctl restart locker-tester.service

step 5/5 "Autostart UI layar penuh (Chromium kiosk)"
chmod +x "$APP_DIR/kiosk.sh" "$APP_DIR/start.sh"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/locker-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Locker Cell Tester (kiosk)
Exec=$APP_DIR/kiosk.sh
X-GNOME-Autostart-enabled=true
EOF

printf '\n\033[1;32mInstalasi selesai.\033[0m Reboot agar UART & grup dialout aktif:  sudo reboot\n'
echo "Setelah reboot: backend berjalan otomatis dan UI tampil layar penuh."
echo "Cek backend : systemctl status locker-tester    |  log: journalctl -u locker-tester -f"
