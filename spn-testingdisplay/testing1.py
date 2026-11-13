from luma.led_matrix.device import max7219
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.core.legacy import text, show_message
from luma.core.legacy.font import proportional, TINY_FONT
import time

def main():
    # Inisialisasi SPI dan Device
    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=4, block_orientation=-90, rotate=0)
    device.contrast(50) 

    daftar_harga = ["Rp 1.000", "Rp 100.000"]

    print("Memulai program dengan TINY_FONT dan margin (jarak atas/bawah)...")

    try:
        while True:
            for harga in daftar_harga:
                # --- MODE 1: STATIC (DIAM) ---
                print(f"Menampilkan {harga} (Static)")
                with canvas(device) as draw:
                    # Perubahan 1: Koordinat y diubah menjadi 1 (format: (x, y))
                    # Ini menggeser teks 1 piksel ke bawah
                    text(draw, (0, 1), harga, fill="white", font=proportional(TINY_FONT))
                time.sleep(3)

                device.clear()
                time.sleep(0.5)

                # --- MODE 2: SCROLLING (BERJALAN) ---
                print(f"Menampilkan {harga} (Scrolling)")
                # Perubahan 2: Menambahkan argumen y_offset=1
                show_message(device, harga, fill="white", 
                             font=proportional(TINY_FONT), 
                             scroll_delay=0.05,
                             y_offset=1) 
                
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nProgram dihentikan.")
        device.clear()

if __name__ == "__main__":
    main()
