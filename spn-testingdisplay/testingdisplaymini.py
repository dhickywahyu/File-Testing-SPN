from luma.led_matrix.device import max7219
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.core.legacy import text, show_message
from luma.core.legacy.font import proportional, CP437_FONT, TINY_FONT
import time

def main():
    # Inisialisasi SPI dan Device
    serial = spi(port=0, device=0, gpio=noop())
    # Sesuaikan block_orientation jika teks terbalik/miring (-90, 0, 90)
    device = max7219(serial, cascaded=4, block_orientation=-90, rotate=0)
    device.contrast(50) # Set kecerahan (0-255)

    daftar_harga = ["Rp 1.000", "Rp 100.000"]

    print("Memulai perbandingan mode tampilan...")

    try:
        while True:
            for harga in daftar_harga:
                # --- MODE 1: STATIC ---
                print(f"Menampilkan {harga} (Static)")
                with canvas(device) as draw:
                    # Menggunakan text() untuk tampilan diam
                    # Teks diletakkan di koordinat (0, 0)
                    text(draw, (0, 0), harga, fill="white", font=proportional(CP437_FONT))
                time.sleep(3) # Diam selama 3 detik

                # Bersihkan layar sebentar
                device.clear()
                time.sleep(0.5)

                # --- MODE 2: TEKS BERJALAN (SCROLLING) ---
                print(f"Menampilkan {harga} (Scrolling)")
                # show_message menangani pergerakan teks secara otomatis
                show_message(device, harga, fill="white", 
                             font=proportional(CP437_FONT), 
                             scroll_delay=0.05)
                
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram dihentikan.")
        device.clear()

if __name__ == "__main__":
    main()
