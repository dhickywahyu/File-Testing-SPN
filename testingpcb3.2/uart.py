import serial
import time

def test_uart_loopback():
    print("="*50)
    print("--- MEMULAI TES UART LOOPBACK INTERNAL ---")
    print("="*50)
    
    try:
        # Buka port serial bawaan Raspi
        ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=1)
        print("[OK] Port /dev/serial0 berhasil dibuka.")
        
        # Pesan yang akan dikirim
        pesan_kirim = b"TES-PIN-14-15\n"
        
        # Kosongkan sisa antrean data lama jika ada
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Kirim pesan dari Pin 14 (TX)
        print(f"[->] Mengirim Data keluar dari Pin 14 : {pesan_kirim.decode().strip()}")
        ser.write(pesan_kirim)
        ser.flush()
        
        # Beri waktu sebentar agar listrik mengalir lewat kabel jumper
        time.sleep(0.1)
        
        # Cek apakah ada data yang masuk ke Pin 15 (RX)
        if ser.in_waiting > 0:
            data_masuk = ser.readline()
            print(f"[<-] Menerima Data masuk ke Pin 15    : {data_masuk.decode().strip()}")
            
            if data_masuk == pesan_kirim:
                print("\n[KESIMPULAN]: NORMAL (PASSED) \xE2\x9C\x85")
                print("Perangkat keras Pin 14 (TX) dan Pin 15 (RX) berfungsi SEMPURNA.")
                print("Sistem Operasi (OS) tidak bermasalah.")
            else:
                print("\n[KESIMPULAN]: ERROR (DATA KORUP) \xE2\x9A\xA0\xEF\xB8\x8F")
                print(f"Data yang diterima rusak: {data_masuk}")
        else:
            print("\n[KESIMPULAN]: TIMEOUT (FAILED) \xE2\x9D\x8C")
            print("Pin 15 tidak menerima sinyal apa pun.")
            print("Cek kembali apakah kabel jumper benar-benar terhubung antara pin 14 dan 15.")
            
        ser.close()

    except Exception as e:
        print("\n[KESIMPULAN]: GAGAL MEMBUKA PORT \xE2\x9D\x8C")
        print(f"Pesan Error: {e}")
        print("Pastikan port serial sudah aktif di pengaturan (raspi-config).")

if __name__ == "__main__":
    test_uart_loopback()
