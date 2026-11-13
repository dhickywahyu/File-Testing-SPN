import tkinter as tk
import RPi.GPIO as GPIO
import smbus
import datetime
import time

class PiMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Raspberry Pi GPIO & RTC Monitor")
        self.root.geometry("650x500")
        self.root.configure(padx=20, pady=20)
        
        # --- Konfigurasi GPIO ---
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        self.row1_pins = [24, 8, 12, 6, 14, 18, 20, 19]
        self.row2_pins = [25, 7, 16, 5, 15, 23, 21, 13]
        self.output_pins = [4, 17]
        
        for pin in self.row1_pins + self.row2_pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            
        for pin in self.output_pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            
        self.output_state = False
        
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

        output_frame = tk.LabelFrame(self.root, text="Digital Outputs (Toggle 1s)", font=("Arial", 12, "bold"))
        output_frame.pack(fill=tk.X, pady=10)
        
        out_center_frame = tk.Frame(output_frame)
        out_center_frame.pack(pady=5)
        for pin in self.output_pins:
            canvas, circle = self.create_indicator(out_center_frame, f"GPIO {pin:02d}")
            self.out_canvases[pin] = canvas
            self.out_circles[pin] = circle

        rtc_frame = tk.LabelFrame(self.root, text="Informasi RTC & Waktu", font=("Arial", 12, "bold"))
        rtc_frame.pack(fill=tk.X, pady=10)
        
        self.rtc_status_label = tk.Label(rtc_frame, text="Memeriksa status RTC...", font=("Arial", 11, "bold"))
        self.rtc_status_label.pack(pady=(5, 0))

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
        self.output_state = not self.output_state
        for pin in self.output_pins:
            GPIO.output(pin, self.output_state)
            color = "#00FF00" if self.output_state else "#FF0000"
            self.out_canvases[pin].itemconfig(self.out_circles[pin], fill=color)
            
        self.root.after(1000, self.toggle_outputs)

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
            
            # Membaca byte per byte untuk stabilitas (register 0x00 sampai 0x06)
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
            
        except Exception as e:
            # Print error ke terminal untuk debugging jika masih gagal
            print(f"I2C Error pada address {hex(rtc_address)}: {e}")
            self.rtc_status_label.config(text=f"RTC Tidak Terdeteksi (Address: {hex(rtc_address)})", fg="red")
            self.rtc_time_label.config(text="Waktu RTC: -", fg="red")

        self.root.after(1000, self.update_time_info)

    def on_closing(self):
        GPIO.cleanup()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = PiMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
