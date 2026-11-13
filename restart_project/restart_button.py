# Impor pustaka yang diperlukan
import RPi.GPIO as GPIO  # Untuk mengontrol pin GPIO
import os                # Untuk menjalankan perintah sistem (seperti restart)
import signal            # Untuk menjaga skrip tetap berjalan efisien

# Tentukan nomor pin BCM yang digunakan untuk tombol
RESTART_PIN = 5

# Definisikan fungsi yang akan dijalankan ketika tombol ditekan (callback)
def restart_pi(channel):
    """Fungsi ini dipanggil saat event terdeteksi pada pin."""
    print("Tombol restart ditekan! Merestart Raspberry Pi...")
    # Menjalankan perintah shell untuk me-restart sistem
    os.system("sudo shutdown -r now")

# Pengaturan awal pustaka RPi.GPIO
GPIO.setmode(GPIO.BCM)  # Menggunakan skema penomoran BCM (Broadcom)
GPIO.setup(RESTART_PIN, GPIO.IN) # Mengatur pin sebagai input

# Menambahkan deteksi event pada pin yang ditentukan
# Memicu pada 'rising edge', yaitu transisi dari LOW ke HIGH
# 'bouncetime' mencegah pemicuan ganda akibat getaran mekanis sakelar
GPIO.add_event_detect(RESTART_PIN, GPIO.RISING, callback=restart_pi, bouncetime=5000)

# Pesan untuk memberitahu pengguna bahwa skrip sedang berjalan
print("Skrip tombol restart aktif. Tekan tombol untuk me-restart.")
print("Tekan Ctrl+C di terminal untuk menghentikan skrip secara manual.")

try:
    # Menjaga skrip agar tetap berjalan di latar belakang tanpa membebani CPU
    signal.pause()
except KeyboardInterrupt:
    # Menangani jika pengguna menghentikan skrip dengan Ctrl+C
    print("Keluar dari skrip.")
finally:
    # Membersihkan konfigurasi GPIO sebelum skrip benar-benar berhenti
    GPIO.cleanup()
