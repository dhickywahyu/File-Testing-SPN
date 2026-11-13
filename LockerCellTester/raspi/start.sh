#!/usr/bin/env bash
# Menjalankan program secara manual (tanpa service): backend + UI kiosk.
#   bash start.sh          -> hardware nyata (port dari config.json)
#   bash start.sh --sim    -> mode simulasi tanpa hardware
# Tutup UI dengan Alt+F4; backend ikut berhenti.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

if systemctl is-active --quiet locker-tester 2>/dev/null; then
  echo "Service locker-tester sedang berjalan (port 8080 terpakai)."
  echo "Hentikan dulu: sudo systemctl stop locker-tester"
  exit 1
fi

python3 app.py "$@" &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null' EXIT
bash ./kiosk.sh
