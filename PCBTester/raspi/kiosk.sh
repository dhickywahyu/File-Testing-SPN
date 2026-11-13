#!/bin/bash
# Buka UI PCB QC Tester layar penuh (Chromium kiosk). Keluar: Alt+F4.
URL="${PCB_URL:-http://127.0.0.1:8080}"

# cegah dua jendela kiosk berjalan bersamaan
exec 9>"/tmp/pcb-kiosk-$(id -u).lock"
flock -n 9 || exit 0

# tunggu program tester siap (maks 90 detik)
for _ in $(seq 1 90); do
  python3 -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1] + '/api/state', timeout=1)" "$URL" \
    >/dev/null 2>&1 && break
  sleep 1
done

# layar jangan mati / screensaver
command -v xset >/dev/null 2>&1 && xset s off -dpms s noblank 2>/dev/null

BROWSER="$(command -v chromium-browser || command -v chromium)"
exec "$BROWSER" --user-data-dir="$HOME/.config/pcb-kiosk-chromium" \
  --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --disable-features=Translate \
  --password-store=basic --check-for-update-interval=31536000 \
  --incognito "$URL"
