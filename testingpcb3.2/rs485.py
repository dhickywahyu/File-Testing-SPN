import tkinter as tk
import serial
import time

class RS485DiagnosticApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Diagnostic Tool: RS485 Link Tester")
        self.root.geometry("600x350")
        self.root.configure(padx=20, pady=20)
        
        # --- Buka Port Serial ---
        try:
            self.ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=0.1)
            self.serial_ready = True
        except Exception as e:
            self.serial_ready = False
            self.error_msg = str(e)
            
        self.setup_ui()
        self.test_rs485()

    def setup_ui(self):
        # Header
        header = tk.Label(self.root, text="RS485 DIAGNOSTIC TEST", font=("Arial", 16, "bold"))
        header.pack(pady=(0, 15))
        
        # Frame Utama
        main_frame = tk.LabelFrame(self.root, text="Pengujian Jalur Komunikasi (TX: 14, RX: 15)", font=("Arial", 12))
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Indikator Status
        self.status_label = tk.Label(main_frame, text="Memulai Pengujian...", font=("Arial", 14, "bold"))
        self.status_label.pack(pady=15)
        
        # Indikator Data TX
        self.tx_label = tk.Label(main_frame, text="Mengirim   (TX) : -", font=("Courier", 12), fg="blue")
        self.tx_label.pack(pady=5)
        
        # Indikator Data RX
        self.rx_label = tk.Label(main_frame, text="Menerima   (RX) : -", font=("Courier", 12), fg="purple")
        self.rx_label.pack(pady=5)
        
        # Pesan Bantuan/Resolusi
        self.info_label = tk.Label(main_frame, text="", font=("Arial", 10, "italic"), fg="gray")
        self.info_label.pack(pady=15)

    def test_rs485(self):
        if not self.serial_ready:
            self.status_label.config(text="GAGAL MEMBUKA PORT SERIAL", fg="red")
            self.info_label.config(text=f"Error: {self.error_msg}")
            return

        payload_str = "TES-RS485-OK"
        payload_bytes = f"{payload_str}\n".encode()

        try:
            # 1. Bersihkan jalur
            self.ser.reset_input_buffer()
            
            # 2. Kirim Data
            self.ser.write(payload_bytes)
            self.tx_label.config(text=f"Mengirim   (TX) : {payload_str}")
            
            # 3. Tunggu Balasan (0.2 detik = 200 ms)
            time.sleep(0.2)
            
            # 4. Evaluasi Balasan
            if self.ser.in_waiting > 0:
                received_bytes = self.ser.readline()
                received_str = received_bytes.decode(errors='replace').strip()
                self.rx_label.config(text=f"Menerima   (RX) : {received_str}")
                
                if received_str == payload_str:
                    self.status_label.config(text="STATUS: NORMAL (PASSED)", fg="green")
                    self.info_label.config(text="Jalur RS485 Berfungsi Sempurna. Hardware Aman.")
                else:
                    self.status_label.config(text="STATUS: ERROR (DATA KORUP)", fg="orange")
                    self.info_label.config(text="Data berubah di jalan. Cek kabel panjang / butuh resistor terminasi.")
            else:
                self.rx_label.config(text="Menerima   (RX) : (KOSONG)")
                self.status_label.config(text="STATUS: TIMEOUT (FAILED)", fg="red")
                self.info_label.config(text="Kabel A/B terputus, Modul rusak, atau ESP32 tidak menyala.")
                
        except Exception as e:
            self.status_label.config(text="ERROR SISTEM", fg="red")
            self.info_label.config(text=str(e))

        # Looping setiap 2 detik
        self.root.after(2000, self.test_rs485)

if __name__ == "__main__":
    root = tk.Tk()
    app = RS485DiagnosticApp(root)
    root.mainloop()
