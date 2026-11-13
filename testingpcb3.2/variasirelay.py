import RPi.GPIO as GPIO
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

class GPIORhythmApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor GPIO Ritme - Advanced")
        self.root.geometry("450x620")
        self.root.resizable(False, False)

        # Variabel State
        self.is_running = False
        self.thread = None
        
        # Variabel Input Pengaturan Umum
        self.selected_pin = tk.IntVar(value=4)       
        self.str_durasi = tk.StringVar(value="10")   
        self.str_jeda = tk.StringVar(value="2")      

        # Variabel Input Siklus (dalam milidetik)
        self.step_vars = []
        default_cycles = [(250, 250), (500, 500), (1000, 1000), (3000, 3000)]
        for on_ms, off_ms in default_cycles:
            self.step_vars.append({
                "on": tk.StringVar(value=str(on_ms)),
                "off": tk.StringVar(value=str(off_ms))
            })

        self.setup_ui()

    def setup_ui(self):
        # 1. Frame Pemilihan Pin
        frame_pin = ttk.LabelFrame(self.root, text=" 1. Pilih Pin GPIO ", padding=10)
        frame_pin.pack(pady=5, padx=20, fill="x")
        ttk.Radiobutton(frame_pin, text="GPIO 4", variable=self.selected_pin, value=4).pack(side="left", padx=20)
        ttk.Radiobutton(frame_pin, text="GPIO 17", variable=self.selected_pin, value=17).pack(side="left", padx=20)

        # 2. Frame Pengaturan Umum
        frame_waktu = ttk.LabelFrame(self.root, text=" 2. Pengaturan Umum (Detik) ", padding=10)
        frame_waktu.pack(pady=5, padx=20, fill="x")
        ttk.Label(frame_waktu, text="Total Durasi per Langkah:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(frame_waktu, textvariable=self.str_durasi, width=8).grid(row=0, column=1, pady=2, padx=10)
        ttk.Label(frame_waktu, text="Jeda antar Langkah:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(frame_waktu, textvariable=self.str_jeda, width=8).grid(row=1, column=1, pady=2, padx=10)

        # 3. Frame Pengaturan Siklus (Milidetik)
        frame_siklus = ttk.LabelFrame(self.root, text=" 3. Pengaturan Siklus / Ritme (Milidetik) ", padding=10)
        frame_siklus.pack(pady=5, padx=20, fill="x")
        
        # Header Tabel UI
        ttk.Label(frame_siklus, text="Langkah", font=("Helvetica", 9, "bold")).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(frame_siklus, text="Aktif (ms)", font=("Helvetica", 9, "bold")).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(frame_siklus, text="Mati (ms)", font=("Helvetica", 9, "bold")).grid(row=0, column=2, padx=5, pady=5)

        # Baris Input untuk 4 Langkah
        for i in range(4):
            ttk.Label(frame_siklus, text=f"Langkah {i+1}:").grid(row=i+1, column=0, sticky="w", pady=2)
            ttk.Entry(frame_siklus, textvariable=self.step_vars[i]["on"], width=10).grid(row=i+1, column=1, padx=10, pady=2)
            ttk.Entry(frame_siklus, textvariable=self.step_vars[i]["off"], width=10).grid(row=i+1, column=2, padx=10, pady=2)

        # 4. Status Label & Canvas
        self.lbl_status = tk.Label(self.root, text="Status: Berhenti", font=("Helvetica", 11, "bold"))
        self.lbl_status.pack(pady=5)
        self.lbl_detail = tk.Label(self.root, text="-", font=("Helvetica", 10))
        self.lbl_detail.pack(pady=2)

        self.canvas = tk.Canvas(self.root, width=60, height=60)
        self.canvas.pack(pady=5)
        self.lampu_ui = self.canvas.create_oval(10, 10, 50, 50, fill="gray", outline="black")

        # 5. Frame Tombol
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

    def responsive_sleep(self, duration):
        start_time = time.time()
        while time.time() - start_time < duration:
            if not self.is_running:
                return False
            time.sleep(0.01) # Cek setiap 10ms agar lebih responsif untuk siklus ms kecil
        return True

    # --- LOGIKA RITME HARD-STOP ---
    def jalankan_ritme(self, waktu_aktif_s, waktu_mati_s, durasi_total, jeda, pin, nama_langkah):
        waktu_mulai = time.time()
        
        while self.is_running:
            waktu_berjalan = time.time() - waktu_mulai
            sisa_waktu = durasi_total - waktu_berjalan
            if sisa_waktu <= 0: break 
            
            # Fase Aktif
            waktu_aktif_nyata = min(waktu_aktif_s, sisa_waktu)
            GPIO.output(pin, GPIO.HIGH)
            self.root.after(0, self.update_ui, nama_langkah, f"MENYALA ({waktu_aktif_nyata:.2f}s tersisa)", "red")
            if not self.responsive_sleep(waktu_aktif_nyata): return False
            
            waktu_berjalan = time.time() - waktu_mulai
            sisa_waktu = durasi_total - waktu_berjalan
            if sisa_waktu <= 0: break 
                
            # Fase Mati
            waktu_mati_nyata = min(waktu_mati_s, sisa_waktu)
            GPIO.output(pin, GPIO.LOW)
            self.root.after(0, self.update_ui, nama_langkah, f"MATI ({waktu_mati_nyata:.2f}s tersisa)", "gray")
            if not self.responsive_sleep(waktu_mati_nyata): return False
        
        # Jeda Transisi
        if self.is_running:
            GPIO.output(pin, GPIO.LOW)
            self.root.after(0, self.update_ui, "Jeda Transisi", f"Menunggu {jeda} detik...", "yellow")
            if not self.responsive_sleep(jeda): return False

        return True

    # --- THREAD UTAMA ---
    def loop_utama(self, durasi, jeda, cycles):
        pin = self.selected_pin.get()
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

        try:
            while self.is_running:
                for i, (on_ms, off_ms) in enumerate(cycles):
                    # Konversi ms ke detik untuk fungsi time.sleep
                    on_s = on_ms / 1000.0
                    off_s = off_ms / 1000.0
                    nama = f"Langkah {i+1} ({on_ms}ms / {off_ms}ms)"
                    
                    if not self.jalankan_ritme(on_s, off_s, durasi, jeda, pin, nama):
                        break # Memutuskan for loop jika stop ditekan
        finally:
            GPIO.output(pin, GPIO.LOW)
            GPIO.cleanup()
            self.root.after(0, self.update_ui, "Berhenti", "Program dihentikan.", "gray")
            
            def reset_buttons():
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
            self.root.after(0, reset_buttons)

    # --- VALIDASI & KONTROL ---
    def start_program(self):
        if self.is_running: return

        try:
            # Validasi pengaturan umum
            durasi_val = float(self.str_durasi.get())
            jeda_val = float(self.str_jeda.get())
            if durasi_val <= 0 or jeda_val < 0: raise ValueError
            
            # Validasi pengaturan siklus (harus integer karena ms)
            cycles = []
            for step in self.step_vars:
                on_ms = int(step["on"].get())
                off_ms = int(step["off"].get())
                if on_ms <= 0 or off_ms < 0: raise ValueError
                cycles.append((on_ms, off_ms))
                
        except ValueError:
            messagebox.showerror("Error Input", "Masukkan angka yang valid!\n- Durasi & jeda: Detik (bisa desimal)\n- Siklus Aktif/Mati: Milidetik bulat (contoh: 250)")
            return

        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        self.thread = threading.Thread(target=self.loop_utama, args=(durasi_val, jeda_val, cycles), daemon=True)
        self.thread.start()

    def stop_program(self):
        self.is_running = False
        self.update_ui("Menghentikan...", "Menunggu eksekusi berhenti...", "gray")
        self.btn_stop.config(state="disabled")

    def on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("Keluar", "Program masih berjalan. Keluar?"):
                self.is_running = False
                self.root.destroy()
        else:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = GPIORhythmApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
