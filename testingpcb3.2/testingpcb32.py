import tkinter as tk
import RPi.GPIO as GPIO
import smbus
import datetime
import time
import serial

class PiMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Raspberry Pi Hardware Monitor (GPIO, RTC, RS485)")
        self.root.geometry("750x650")
        self.root.configure(padx=20, pady=20)
        
        # --- Konfigurasi GPIO ---
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Pengelompokan Pin Input
        self.row1_pins = [19, 18, 22, 20, 12, 8, 24, 6]
        self.row2_pins = [13, 23, 27, 21, 16, 7, 25, 5]
        self.output_pins = [17, 4]
        
        # Setup Input (Pull-Down)
        for pin in self.row1_pins + self.row2_pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            
        # Setup Output
        for pin in self.output_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            
        self.output_state = False
        
        # --- Konfigurasi Serial RS485 ---
        try:
            # RPi 4 hardware serial port alias
            self.ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=0.1)
            self.serial_ready = True
        except Exception as e:
            print(f"Serial Error: {e}")
            self.serial_ready = False
            
        # --- UI Elements ---
        self.in_canvases = {}
        self.in_circles = {}
        self.out_canvases = {}
        self.out_circles = {}
        
        self.setup_ui()
        
        # --- Memulai Looping Task ---
        self.poll_inputs()
        self.toggle_outputs()
        self.update_time_info()
        self.test_rs485()

    def create_indicator(self, parent, text_label):
        frame = tk.Frame(parent)
        frame.pack(side=tk.LEFT, padx=10, pady=5)
        
        canvas = tk.Canvas(frame, width=30, height=30, highlightthickness=0)
        circle = canvas.create_oval(2, 2, 28, 28, fill="red", outline="black")
        canvas.pack()
        
        label = tk.Label(frame, text=text_label, font=("Arial", 10, "bold"))
        label.pack()
        
        return canvas, circle

    def setup_ui(self):
        # 1. Frame Digital Inputs
        input_frame = tk.LabelFrame(self.root, text="Digital Inputs (Pull-Down)", font=("Arial", 12, "bold"))
        input_frame.pack(fill=tk.X, pady=10)
        
        row1_frame = tk.Frame(input_frame)
        row1_frame.pack(pady=5)
        for pin in self.row1_pins:
            canvas, circle = self.create_indicator(row1_frame, f"GPIO {pin:02d}")
            self.in_canvases[pin] = canvas
            self.in_circles[pin] = circle
            
        row2_frame = tk.Frame(input_frame)
        row2_frame.pack(pady=5)
        for pin in self.row2_pins:
            canvas, circle = self.create_indicator(row2_frame, f"GPIO {pin:02d}")
            self.in_canvases[pin] = canvas
            self.in_circles[pin] = circle

        # 2. Frame Digital Outputs
        output_frame = tk.LabelFrame(self.root, text="Digital Outputs (ON: 2s, OFF: 1.5s)", font=("Arial", 12, "bold"))
        output_frame.pack(fill=tk.X, pady=10)
        
        out_center_frame = tk.Frame(output_frame)
        out_center_frame.pack(pady=5)
        for pin in self.output_pins:
            canvas, circle = self.create_indicator(out_center_frame, f"GPIO {pin:02d}")
            self.out_canvases[pin] = canvas
            self.out_circles[pin] = circle

        # 3. Frame RS485 Self-Test
        rs485_frame = tk.LabelFrame(self.root, text="RS485 Self-Testing (TX: 14, RX: 15)", font=("Arial", 12, "bold"))
        rs485_frame.pack(fill=tk.X, pady=10)
        
        self.rs485_status_label = tk.Label(rs485_frame, text="Inisialisasi Serial...", font=("Arial", 11, "bold"))
        self.rs485_status_label.pack(pady=5)
        
        self.rs485_data_label = tk.Label(rs485_frame, text="Data Loopback: -", font=("Arial", 11))
        self.rs485_data_label.pack(pady=(0, 5))

        # 4. Frame RTC & Waktu
        rtc_frame = tk.LabelFrame(self.root, text="Informasi RTC DS3231 & Waktu", font=("Arial", 12, "bold"))
        rtc_frame.pack(fill=tk.X, pady=10)
        
        self.rtc_status_label = tk.Label(rtc_frame, text="Memeriksa status RTC...", font=("Arial", 11, "bold"))
        self.rtc_status_label.pack(pady=5)

        self.local_time_label = tk.Label(rtc_frame, text="Waktu Lokal: -", font=("Arial", 11))
        self.local_time_label.pack()

        self.utc_time_label = tk.Label(rtc_frame, text="Waktu Universal (UTC): -", font=("Arial", 11))
        self.utc_time_label.pack()
        
        self.timezone_label = tk.Label(rtc_frame, text="Zona Waktu: -", font=("Arial", 11))
        self.timezone_label.pack()

        self.rtc_time_label = tk.Label(rtc_frame, text="Waktu RTC: -", font=("Arial", 11, "bold"), fg="blue")
        self.rtc_time_label.pack(pady=(0, 5))

    def poll_inputs(self):
        for pin in self.row1_pins + self.row2_pins:
            state = GPIO.input(pin)
            color = "#00FF00" if state == GPIO.HIGH else "#FF0000"
            self.in_canvases[pin].itemconfig(self.in_circles[pin], fill=color)
            
        self.root.after(100, self.poll_inputs)

    def toggle_outputs(self):
        # Penentuan delay waktu berdasarkan state (Asimetris)
        if self.output_state:
            # Jika sedang menyala, matikan dan tunggu 1.5 detik (1500 ms)
            self.output_state = False
            delay = 1500
        else:
            # Jika sedang mati, nyalakan dan tunggu 2 detik (2000 ms)
            self.output_state = True
            delay = 2000

        for pin in self.output_pins:
            GPIO.output(pin, self.output_state)
            color = "#00FF00" if self.output_state else "#FF0000"
            self.out_canvases[pin].itemconfig(self.out_circles[pin], fill=color)
            
        self.root.after(delay, self.toggle_outputs)

    def test_rs485(self):
        if not self.serial_ready:
            self.rs485_status_label.config(text="Gagal membuka /dev/serial0", fg="red")
            return

        test_payload = b"PING\n"
        try:
            # Kosongkan buffer lalu kirim data
            self.ser.reset_input_buffer()
            self.ser.write(test_payload)
            
            # KUNCI PERBAIKAN: Jeda diperlama menjadi 200ms agar balasan dari ESP32 sempat masuk
            time.sleep(0.2) 
            
            if self.ser.in_waiting > 0:
                received = self.ser.readline()
                if received == test_payload:
                    self.rs485_status_label.config(text="Status RS485: NORMAL (Kirim & Terima Sukses)", fg="green")
                    self.rs485_data_label.config(text=f"Data Loopback: TX='{test_payload.decode().strip()}' -> RX='{received.decode().strip()}'")
                else:
                    self.rs485_status_label.config(text="Status RS485: ERROR (Data Korup)", fg="orange")
                    self.rs485_data_label.config(text=f"Data Loopback: RX='{received}'")
            else:
                self.rs485_status_label.config(text="Status RS485: TIMEOUT (Tidak ada data RX)", fg="red")
                self.rs485_data_label.config(text="Data Loopback: -")
                
        except Exception as e:
            self.rs485_status_label.config(text=f"Error Modul: {e}", fg="red")

        # Ulangi pengetesan setiap 2 detik
        self.root.after(2000, self.test_rs485)

    def bcd_to_dec(self, bcd):
        return (bcd >> 4) * 10 + (bcd & 0x0F)

    def update_time_info(self):
        local_time = datetime.datetime.now()
        utc_time = datetime.datetime.utcnow()
        timezone_name = time.tzname[time.daylight]
        
        self.local_time_label.config(text=f"Waktu Lokal: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.utc_time_label.config(text=f"Waktu Universal (UTC): {utc_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.timezone_label.config(text=f"Zona Waktu: {timezone_name}")

        rtc_address = 0x68
        try:
            bus = smbus.SMBus(1)
            # Membaca byte per byte untuk stabilitas
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
            
            self.rtc_status_label.config(text=f"RTC Terdeteksi (Address: {hex(rtc_address)})", fg="green")
            self.rtc_time_label.config(text=f"Waktu RTC: {rtc_time_str}", fg="blue")
            
        except Exception:
            self.rtc_status_label.config(text=f"RTC Tidak Terdeteksi (Address: {hex(rtc_address)})", fg="red")
            self.rtc_time_label.config(text="Waktu RTC: -", fg="red")

        self.root.after(1000, self.update_time_info)

    def on_closing(self):
        GPIO.cleanup()
        if hasattr(self, 'ser') and self.ser.is_open:
            self.ser.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = PiMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
