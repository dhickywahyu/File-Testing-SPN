#!/usr/bin/env bash
# Menampilkan UI Locker Cell Tester layar penuh di monitor (Chromium mode kiosk).
# Keluar dari kiosk: Alt+F4 (atau Ctrl+W).
URL="${LOCKER_URL:-http://127.0.0.1:8080}"

# cegah dua jendela kiosk berjalan bersamaan
exec 9>"/tmp/locker-kiosk-$(id -u).lock"
flock -n 9 || exit 0

# tunggu backend (app.py / service locker-tester) siap, maks 90 detik
for _ in $(seq 1 90); do
  python3 -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1] + '/api/state', timeout=1)" "$URL" \
    >/dev/null 2>&1 && break
  sleep 1
done

BROWSER="$(command -v chromium || command -v chromium-browser || true)"
if [ -z "$BROWSER" ]; then
  echo "Chromium tidak ditemukan. Pasang dengan: sudo apt install chromium" >&2
  exit 1
fi

# matikan screensaver / layar mati otomatis (sesi X11)
if command -v xset >/dev/null 2>&1; then
  xset s off -dpms s noblank 2>/dev/null || true
fi

# profil terpisah: kiosk tidak tercampur dengan jendela Chromium biasa
exec "$BROWSER" --user-data-dir="$HOME/.config/locker-kiosk-chromium" \
  --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --disable-features=Translate \
  --password-store=basic --check-for-update-interval=31536000 \
  --incognito "$URL"
