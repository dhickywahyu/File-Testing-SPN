import tkinter as tk
from tkinter import ttk
import RPi.GPIO as GPIO
import smbus
import datetime
import time
import serial

class DashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Raspberry Pi Master Dashboard (I/O, RTC, RS485)")
        self.root.geometry("850x750")
        self.root.configure(padx=20, pady=10, bg="#f0f4f8") # Background terang modern
        
        # --- Gaya & Tema Custom ---
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("TLabelframe", background="#ffffff", borderwidth=2)
        self.style.configure("TLabelframe.Label", font=("Segoe UI", 12, "bold"), background="#ffffff", foreground="#2c3e50")
        self.style.configure("TFrame", background="#ffffff")
        self.style.configure("Status.TLabel", background="#ffffff", font=("Segoe UI", 10))
        
        # --- Konfigurasi GPIO ---
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Pengelompokan Pin
        self.row1_pins = [19, 18, 22, 20, 12, 8, 24, 6]
        self.row2_pins = [13, 23, 27, 21, 16, 7, 25, 5]
        self.output_pins = [17, 4]
        
        for pin in self.row1_pins + self.row2_pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            
        for pin in self.output_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            
        self.output_state = False
        
        # --- Konfigurasi Serial RS485 ---
        try:
            self.ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=0.1)
            self.serial_ready = True
        except Exception as e:
            self.serial_ready = False
            self.serial_err = str(e)
            
        # UI Dictionaries
        self.in_canvases = {}
        self.in_circles = {}
        self.in_labels = {}
        self.out_canvases = {}
        self.out_circles = {}
        self.out_labels = {}
        
        self.setup_ui()
        
        # --- Memulai Looping Task ---
        self.poll_inputs()
        self.toggle_outputs()
        self.update_time_info()
        self.test_rs485()

    def create_io_indicator(self, parent, text_title):
        """Membuat widget indikator I/O yang lebih elegan"""
        frame = ttk.Frame(parent)
        frame.pack(side=tk.LEFT, padx=12, pady=5)
        
        title_lbl = ttk.Label(frame, text=text_title, font=("Segoe UI", 10, "bold"), background="#ffffff")
        title_lbl.pack()
        
        canvas = tk.Canvas(frame, width=36, height=36, background="#ffffff", highlightthickness=0)
        # Shadow / Outer ring
        canvas.create_oval(2, 2, 34, 34, fill="#e0e0e0", outline="#b0b0b0", width=1)
        # Inner LED
        circle = canvas.create_oval(6, 6, 30, 30, fill="#e74c3c", outline="")
        canvas.pack(pady=2)
        
        status_lbl = ttk.Label(frame, text="LOW", font=("Segoe UI", 9, "bold"), foreground="#7f8c8d", background="#ffffff")
        status_lbl.pack()
        
        return canvas, circle, status_lbl

    def setup_ui(self):
        # Judul Dashboard Utama
        header = tk.Label(self.root, text="HARDWARE DIAGNOSTIC DASHBOARD", font=("Segoe UI", 18, "bold"), bg="#f0f4f8", fg="#2980b9")
        header.pack(pady=(0, 10))

        # 1. Frame Digital Inputs
        input_frame = ttk.LabelFrame(self.root, text=" 🎛️ Digital Inputs (Pull-Down) ")
        input_frame.pack(fill=tk.X, pady=8, padx=10)
        
        row1_frame = ttk.Frame(input_frame)
        row1_frame.pack(pady=5)
        for pin in self.row1_pins:
            canvas, circle, status_lbl = self.create_io_indicator(row1_frame, f"P-{pin:02d}")
            self.in_canvases[pin] = canvas
            self.in_circles[pin] = circle
            self.in_labels[pin] = status_lbl
            
        row2_frame = ttk.Frame(input_frame)
        row2_frame.pack(pady=5)
        for pin in self.row2_pins:
            canvas, circle, status_lbl = self.create_io_indicator(row2_frame, f"P-{pin:02d}")
            self.in_canvases[pin] = canvas
            self.in_circles[pin] = circle
            self.in_labels[pin] = status_lbl

        # 2. Frame Digital Outputs
        output_frame = ttk.LabelFrame(self.root, text=" 💡 Digital Outputs (ON: 2s, OFF: 1.5s) ")
        output_frame.pack(fill=tk.X, pady=8, padx=10)
        
        out_center_frame = ttk.Frame(output_frame)
        out_center_frame.pack(pady=10)
        for pin in self.output_pins:
            canvas, circle, status_lbl = self.create_io_indicator(out_center_frame, f"GPIO {pin:02d}")
            status_lbl.config(text="OFF")
            self.out_canvases[pin] = canvas
            self.out_circles[pin] = circle
            self.out_labels[pin] = status_lbl

        # 3. Frame RS485 Self-Test
        rs485_frame = ttk.LabelFrame(self.root, text=" 📡 Komunikasi RS485 (TX: 14, RX: 15) ")
        rs485_frame.pack(fill=tk.X, pady=8, padx=10)
        
        self.rs485_status_bg = tk.Label(rs485_frame, text="MENUNGGU PENGUJIAN...", font=("Segoe UI", 12, "bold"), bg="#f39c12", fg="white", pady=5)
        self.rs485_status_bg.pack(fill=tk.X, padx=10, pady=5)
        
        data_frame = ttk.Frame(rs485_frame)
        data_frame.pack(pady=5)
        
        self.rs485_tx_label = tk.Label(data_frame, text="Data Keluar (TX)  : -", font=("Consolas", 11), bg="#ffffff", fg="#2980b9")
        self.rs485_tx_label.grid(row=0, column=0, sticky="w", padx=10)
        
        self.rs485_rx_label = tk.Label(data_frame, text="Data Masuk  (RX)  : -", font=("Consolas", 11), bg="#ffffff", fg="#8e44ad")
        self.rs485_rx_label.grid(row=1, column=0, sticky="w", padx=10)

        # 4. Frame RTC & Waktu
        rtc_frame = ttk.LabelFrame(self.root, text=" 🕒 Informasi Waktu & RTC DS3231 ")
        rtc_frame.pack(fill=tk.X, pady=8, padx=10)
        
        self.rtc_status_label = tk.Label(rtc_frame, text="Mencari Modul RTC...", font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#e67e22")
        self.rtc_status_label.pack(pady=(5,0))

        time_data_frame = ttk.Frame(rtc_frame)
        time_data_frame.pack(pady=10)
        
        ttk.Label(time_data_frame, text="Waktu Lokal / Zona :", style="Status.TLabel", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="e", padx=5)
        self.local_time_label = ttk.Label(time_data_frame, text="-", style="Status.TLabel")
        self.local_time_label.grid(row=0, column=1, sticky="w")

        ttk.Label(time_data_frame, text="Waktu Universal (UTC) :", style="Status.TLabel", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="e", padx=5)
        self.utc_time_label = ttk.Label(time_data_frame, text="-", style="Status.TLabel")
        self.utc_time_label.grid(row=1, column=1, sticky="w")
        
        ttk.Label(time_data_frame, text="Hardware Time (RTC) :", style="Status.TLabel", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="e", padx=5)
        self.rtc_time_label = tk.Label(time_data_frame, text="-", font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#27ae60")
        self.rtc_time_label.grid(row=2, column=1, sticky="w")

    def poll_inputs(self):
        for pin in self.row1_pins + self.row2_pins:
            state = GPIO.input(pin)
            if state == GPIO.HIGH:
                self.in_canvases[pin].itemconfig(self.in_circles[pin], fill="#2ecc71") # Hijau
                self.in_labels[pin].config(text="HIGH", foreground="#27ae60")
            else:
                self.in_canvases[pin].itemconfig(self.in_circles[pin], fill="#e74c3c") # Merah
                self.in_labels[pin].config(text="LOW", foreground="#7f8c8d")
            
        self.root.after(100, self.poll_inputs)

    def toggle_outputs(self):
        # Asymmetric timing
        if self.output_state:
            self.output_state = False
            delay = 1500
        else:
            self.output_state = True
            delay = 2000

        for pin in self.output_pins:
            GPIO.output(pin, self.output_state)
            if self.output_state:
                self.out_canvases[pin].itemconfig(self.out_circles[pin], fill="#2ecc71")
                self.out_labels[pin].config(text="ON", foreground="#27ae60")
            else:
                self.out_canvases[pin].itemconfig(self.out_circles[pin], fill="#e74c3c")
                self.out_labels[pin].config(text="OFF", foreground="#7f8c8d")
            
        self.root.after(delay, self.toggle_outputs)

    def test_rs485(self):
        if not self.serial_ready:
            self.rs485_status_bg.config(text=f"ERROR PORT: {self.serial_err}", bg="#c0392b")
            return

        payload_str = "PING-RS485"
        payload_bytes = f"{payload_str}\n".encode()

        try:
            self.ser.reset_input_buffer()
            self.ser.write(payload_bytes)
            
            # Update UI TX
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            self.rs485_tx_label.config(text=f"Data Keluar (TX)  : '{payload_str}' [{timestamp}]")
            
            # Wajib tunggu balasan
            time.sleep(0.2) 
            
            if self.ser.in_waiting > 0:
                received_bytes = self.ser.readline()
                received_str = received_bytes.decode(errors='replace').strip()
                self.rs485_rx_label.config(text=f"Data Masuk  (RX)  : '{received_str}'")
                
                if received_str == payload_str:
                    self.rs485_status_bg.config(text="STATUS: NORMAL (LINK STABIL)", bg="#27ae60")
                else:
                    self.rs485_status_bg.config(text="STATUS: ERROR (DATA KORUP)", bg="#e67e22")
            else:
                self.rs485_rx_label.config(text="Data Masuk  (RX)  : (KOSONG)")
                self.rs485_status_bg.config(text="STATUS: TIMEOUT (KONEKSI TERPUTUS)", bg="#c0392b")
                
        except Exception as e:
            self.rs485_status_bg.config(text=f"HARDWARE ERROR: {str(e)}", bg="#c0392b")

        self.root.after(2000, self.test_rs485)

    def bcd_to_dec(self, bcd):
        return (bcd >> 4) * 10 + (bcd & 0x0F)

    def update_time_info(self):
        local_time = datetime.datetime.now()
        utc_time = datetime.datetime.utcnow()
        timezone_name = time.tzname[time.daylight]
        
        self.local_time_label.config(text=f"{local_time.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name})")
        self.utc_time_label.config(text=f"{utc_time.strftime('%Y-%m-%d %H:%M:%S')}")

        rtc_address = 0x68
        try:
            bus = smbus.SMBus(1)
            data = []
            for i in range(7):
                data.append(bus.read_byte_data(rtc_address, i))
            bus.close()
            
            detik = self.bcd_to_dec(data[0])
            menit = self.bcd_to_dec(data[1])
            jam = self.bcd_to_dec(data[2] & 0x3F) 
            tanggal = self.bcd_to_dec(data[4])
            bulan = self.bcd_to_dec(data[5] & 0x7F)
            tahun = self.bcd_to_dec(data[6]) + 2000
            
            rtc_time_str = f"{tahun:04d}-{bulan:02d}-{tanggal:02d} {jam:02d}:{menit:02d}:{detik:02d}"
            
            self.rtc_status_label.config(text=f"✅ Modul DS3231 Terdeteksi (Alamat I2C: {hex(rtc_address)})", fg="#27ae60")
            self.rtc_time_label.config(text=rtc_time_str, fg="#27ae60")
            
        except Exception:
            self.rtc_status_label.config(text="❌ Modul RTC Tidak Merespons / Tidak Terpasang", fg="#c0392b")
            self.rtc_time_label.config(text="TIDAK TERSEDIA", fg="#c0392b")

        self.root.after(1000, self.update_time_info)

    def on_closing(self):
        GPIO.cleanup()
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DashboardApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
