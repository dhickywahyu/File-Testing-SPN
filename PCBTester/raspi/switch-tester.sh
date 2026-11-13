#!/bin/bash
# Pindah aplikasi tester yang aktif (dan jalan otomatis saat boot) di Raspi ini.
#   ./switch-tester.sh pcb      -> PCB QC Tester v3.3
#   ./switch-tester.sh locker   -> Locker Cell Tester
#   ./switch-tester.sh          -> tampilkan status
# Keduanya memakai /dev/serial0 dan port 8080, jadi hanya satu yang boleh aktif.
PCB_KIOSK=/home/pi/PCBTester/raspi/kiosk.sh
LOCKER_KIOSK=/home/pi/LockerCellTester/raspi/kiosk.sh
AUTO=$HOME/.config/autostart
OFF=$HOME/.config/autostart-disabled

status() {
  for s in pcb-tester locker-tester; do
    printf "%-15s aktif=%-9s boot=%s\n" "$s" "$(systemctl is-active $s)" "$(systemctl is-enabled $s 2>/dev/null)"
  done
  echo "kiosk autostart: $(ls $AUTO 2>/dev/null | tr '\n' ' ')"
}

case "$1" in
  pcb)    ON=pcb-tester;    OFFSVC=locker-tester; KON=pcb-tester-kiosk; KOFF=locker-kiosk; KIOSK=$PCB_KIOSK ;;
  locker) ON=locker-tester; OFFSVC=pcb-tester;    KON=locker-kiosk;     KOFF=pcb-tester-kiosk; KIOSK=$LOCKER_KIOSK ;;
  *) status; exit 0 ;;
esac

sudo systemctl disable --now "$OFFSVC" 2>/dev/null
sudo systemctl enable --now "$ON"
mkdir -p "$AUTO" "$OFF"
[ -f "$AUTO/$KOFF.desktop" ] && mv "$AUTO/$KOFF.desktop" "$OFF/"
[ -f "$OFF/$KON.desktop" ] && mv "$OFF/$KON.desktop" "$AUTO/"

# ganti jendela kiosk di layar sekarang juga (bila desktop sedang login)
pkill -f "chromium.*--kiosk" 2>/dev/null
sleep 1
if [ -n "$(pgrep -u "$(id -u)" lxsession)" ]; then
  DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority nohup "$KIOSK" >/dev/null 2>&1 &
fi
echo "Aktif sekarang: $ON"
status
