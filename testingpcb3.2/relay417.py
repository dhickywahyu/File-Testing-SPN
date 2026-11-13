import RPi.GPIO as GPIO
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

class GPIORhythmApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor GPIO Ritme")
        self.root.geometry("400x350")
        self.root.resizable(False, False)

        # Variabel State
        self.is_running = False
        self.thread = None
        self.selected_pin = tk.IntVar(value=4) # Default ke PIN 4

        self.setup_ui()

    def setup_ui(self):
        # Frame Pemilihan Pin
        frame_pin = ttk.LabelFrame(self.root, text=" Pilih Pin GPIO ", padding=10)
        frame_pin.pack(pady=10, padx=20, fill="x")

        ttk.Radiobutton(frame_pin, text="GPIO 4", variable=self.selected_pin, value=4).pack(side="left", padx=20)
        ttk.Radiobutton(frame_pin, text="GPIO 17", variable=self.selected_pin, value=17).pack(side="left", padx=20)

        # Status Label
        self.lbl_status = tk.Label(self.root, text="Status: Berhenti", font=("Helvetica", 12, "bold"))
        self.lbl_status.pack(pady=10)

        self.lbl_detail = tk.Label(self.root, text="-", font=("Helvetica", 10))
        self.lbl_detail.pack(pady=5)

        # Indikator Lampu (Canvas)
        self.canvas = tk.Canvas(self.root, width=100, height=100)
        self.canvas.pack(pady=10)
        self.lampu_ui = self.canvas.create_oval(25, 25, 75, 75, fill="gray", outline="black")

        # Frame Tombol
        frame_btn = tk.Frame(self.root)
        frame_btn.pack(pady=10)

        self.btn_start = tk.Button(frame_btn, text="MULAI", bg="green", fg="white", width=12, command=self.start_program)
        self.btn_start.pack(side="left", padx=10)

        self.btn_stop = tk.Button(frame_btn, text="BERHENTI", bg="red", fg="white", width=12, state="disabled", command=self.stop_program)
        self.btn_stop.pack(side="left", padx=10)

    # --- FUNGSI UPDATE UI ---
    def update_ui(self, status, detail, warna_lampu):
        self.lbl_status.config(text=f"Status: {status}")
        self.lbl_detail.config(text=detail)
        self.canvas.itemconfig(self.lampu_ui, fill=warna_lampu)

    # --- FUNGSI DELAY RESPONSIP ---
    def responsive_sleep(self, duration):
        """Fungsi sleep yang bisa diinterupsi oleh tombol Stop"""
        start_time = time.time()
        while time.time() - start_time < duration:
            if not self.is_running:
                return False
            time.sleep(0.05) # Cek setiap 50ms
        return True

    # --- LOGIKA RITME ---
    def jalankan_ritme(self, waktu_aktif, waktu_mati, durasi_total, pin, nama_langkah):
        waktu_mulai = time.time()
        
        while (time.time() - waktu_mulai) < durasi_total:
            if not self.is_running: return False
            
            # Fase Aktif
            GPIO.output(pin, GPIO.HIGH)
            self.root.after(0, self.update_ui, nama_langkah, "Lampu MENYALA (HIGH)", "red")
            if not self.responsive_sleep(waktu_aktif): return False
            
            # Fase Mati
            GPIO.output(pin, GPIO.LOW)
            self.root.after(0, self.update_ui, nama_langkah, "Lampu MATI (LOW)", "gray")
            if not self.responsive_sleep(waktu_mati): return False
        
        # Jeda 2 detik
        GPIO.output(pin, GPIO.LOW)
        self.root.after(0, self.update_ui, "Jeda Transisi", "Menunggu 2 detik ke langkah selanjutnya...", "yellow")
        if not self.responsive_sleep(2.0): return False

        return True

    def loop_utama(self):
        pin = self.selected_pin.get()
        
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

        try:
            while self.is_running:
                if not self.jalankan_ritme(0.25, 0.25, 10, pin, "Langkah 1 (0.25s / 0.25s)"): break
                if not self.jalankan_ritme(0.5, 0.5, 10, pin, "Langkah 2 (0.5s / 0.5s)"): break
                if not self.jalankan_ritme(1.0, 1.0, 10, pin, "Langkah 3 (1.0s / 1.0s)"): break
                if not self.jalankan_ritme(3.0, 3.0, 10, pin, "Langkah 4 (3.0s / 3.0s)"): break
        finally:
            # Pastikan pin mati dan dibersihkan saat loop berhenti
            GPIO.output(pin, GPIO.LOW)
            GPIO.cleanup()
            self.root.after(0, self.update_ui, "Berhenti", "Program dihentikan.", "gray")
            
            # Kembalikan status tombol
            def reset_buttons():
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
            self.root.after(0, reset_buttons)

    # --- KONTROL PROGRAM ---
    def start_program(self):
        if self.is_running: return
        self.is_running = True
        
        # Kunci tombol saat berjalan
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        # Jalankan loop di thread terpisah agar UI tidak freeze
        self.thread = threading.Thread(target=self.loop_utama, daemon=True)
        self.thread.start()

    def stop_program(self):
        self.is_running = False
        self.update_ui("Menghentikan...", "Menunggu siklus selesai...", "gray")
        self.btn_stop.config(state="disabled")

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("Keluar", "Program masih berjalan. Ingin menghentikan dan keluar?"):
                self.is_running = False
                self.root.destroy()
        else:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = GPIORhythmApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
