#!/bin/bash
# =====================================================================
#  Instalasi PCB QC Tester di Raspberry Pi 4B (Raspberry Pi OS Bookworm)
#  Jalankan dari folder raspi:   bash install.sh
# =====================================================================
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

echo ">> [1/6] Paket Python"
sudo apt-get update
sudo apt-get install -y python3-lgpio python3-serial i2c-tools || true
sudo apt-get install -y python3-smbus2 || sudo apt-get install -y python3-smbus || true
python3 -c "import smbus2" 2>/dev/null || python3 -c "import smbus" 2>/dev/null || \
    sudo pip3 install --break-system-packages smbus2

echo ">> [2/6] Aktifkan I2C (RTC) dan UART hardware (RS485), matikan serial console"
sudo raspi-config nonint do_i2c 0
if sudo raspi-config nonint do_serial_hw 0 2>/dev/null; then
    sudo raspi-config nonint do_serial_cons 1
else
    sudo raspi-config nonint do_serial 2        # raspi-config versi lama: 2 = hardware ON, console OFF
fi

CONFIG=/boot/firmware/config.txt; [ -f "$CONFIG" ] || CONFIG=/boot/config.txt
echo ">> [3/6] Menyesuaikan $CONFIG"
sudo cp "$CONFIG" "$CONFIG.bak-pcbtester"
# UART PL011 yang stabil di GPIO14/15 (Bluetooth dimatikan)
grep -q '^dtoverlay=disable-bt' "$CONFIG" || echo 'dtoverlay=disable-bt' | sudo tee -a "$CONFIG" >/dev/null
sudo systemctl disable hciuart 2>/dev/null || true
# GPIO 7,8,9,10 dipakai sebagai input -> SPI0 harus OFF
sudo sed -i 's/^dtparam=spi=on/#dtparam=spi=on  # dimatikan oleh PCB tester (GPIO7-10 dipakai input)/' "$CONFIG"
# GPIO4 dipakai relay -> 1-Wire harus OFF
sudo sed -i 's/^dtoverlay=w1-gpio/#dtoverlay=w1-gpio  # dimatikan oleh PCB tester (GPIO4 dipakai relay)/' "$CONFIG"
# GPIO18-21 dipakai -> audio I2S tidak boleh aktif
sudo sed -i 's/^dtparam=i2s=on/#dtparam=i2s=on  # dimatikan oleh PCB tester/' "$CONFIG"

echo ">> [4/6] Service systemd (program berjalan otomatis saat boot, sebagai root agar bisa set jam)"
sudo tee /etc/systemd/system/pcb-tester.service >/dev/null <<EOF
[Unit]
Description=PCB QC Tester (web UI port 8080)
After=network.target time-sync.target

[Service]
ExecStart=/usr/bin/python3 $APP_DIR/app.py
WorkingDirectory=$APP_DIR
Restart=always
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable pcb-tester.service

echo ">> [5/6] Kiosk: Chromium layar penuh otomatis saat desktop login"
chmod +x "$APP_DIR/kiosk.sh"
mkdir -p "$USER_HOME/.config/autostart"
cat > "$USER_HOME/.config/autostart/pcb-tester-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PCB QC Tester Kiosk
Exec=$APP_DIR/kiosk.sh
X-GNOME-Autostart-enabled=true
EOF
chown -R "$USER_NAME":"$USER_NAME" "$USER_HOME/.config/autostart"
sudo chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

echo ">> [6/6] Selesai. REBOOT diperlukan agar I2C/UART/overlay aktif:  sudo reboot"
echo "   Setelah reboot UI terbuka otomatis. Manual: http://localhost:8080"
echo "   Log program:  journalctl -u pcb-tester -f"
