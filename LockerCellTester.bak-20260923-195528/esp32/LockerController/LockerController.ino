/*
 * ============================================================================
 *  LockerController.ino — Firmware ESP32-S3-DevKitC-1 (kontroler sekunder)
 *  Sistem Test Open Cell / Locker 10 cell, komunikasi RS485 dengan Raspberry Pi 4B
 * ============================================================================
 *
 *  TUGAS FIRMWARE
 *   1. Menerima perintah dari Raspberry Pi lewat RS485 (UART1: TX=GPIO17, RX=GPIO18).
 *   2. OPEN,n -> Solenoid Lock cell-n aktif selama 1 detik (non-blocking, pakai millis()).
 *   3. Membaca Indikator Pintu (kontak NO) 10 cell, dengan debounce:
 *        Pintu TERTUTUP -> kontak NO tertekan/terhubung -> input AKTIF
 *        Pintu TERBUKA  -> kontak NO lepas              -> input TIDAK AKTIF
 *   4. LED cell-n MENYALA selama pintu cell-n terbuka dan MATI saat pintu ditutup.
 *      Logika ini berjalan lokal di ESP32, jadi tetap bekerja walaupun Raspberry Pi mati.
 *   5. Menjawab STAT (status seluruh cell) setiap kali diminta Raspberry Pi.
 *
 *  SETTING ARDUINO IDE (menu Tools)
 *   Board            : ESP32S3 Dev Module
 *   USB CDC On Boot  : Disabled     <- WAJIB (GPIO19/20 dipakai Indikator Pintu 6 & 5)
 *   PSRAM            : Disabled     <- JANGAN "OPI PSRAM" (GPIO35/36/37 dipakai Solenoid 10/9/8)
 *   Flash Mode       : QIO 80MHz
 *   Flash Size       : sesuai modul (lihat tulisan di tutup modul, mis. N8 = 8MB, N16 = 16MB)
 *   Port upload      : port USB berlabel "UART"/"COM" (chip USB-to-UART), BUKAN port "USB"
 *   Serial Monitor   : 115200 baud, line ending "Newline" -> log + perintah debug (ketik: help)
 *
 *  PROTOKOL RS485 (ASCII, 8N1)
 *   Master -> ESP32 :  >AA,CMD[,ARG]*CC\n
 *   ESP32 -> Master :  <AA,RESP,...*CC\n
 *     AA = alamat node 2 digit (01), CC = CRC-8 (poly 0x07, init 0x00) dari teks
 *     di antara karakter awal dan '*', ditulis 2 digit HEX.
 *   Perintah:
 *     PING      -> <01,PONG,<versi fw>,<jumlah cell>,<alasan reset>
 *     STAT      -> <01,STAT,<pintu>,<led>,<solenoid>,<antre>,<uptime detik>
 *                    pintu    : 10 karakter, 'C' = tertutup, 'O' = terbuka (cell 1 paling kiri)
 *                    led/sol/antre : 10 karakter '1'/'0'
 *     OPEN,n    -> <01,ACK,OPEN,n,STARTED|QUEUED|ALREADY_ON|ALREADY_QUEUED
 *                  <01,NAK,OPEN,BADARG   (n di luar 1..10)
 *     STOP      -> <01,ACK,STOP          (semua solenoid OFF + antrean dikosongkan)
 *   Frame dengan CRC salah / alamat lain diabaikan (tidak dibalas).
 *
 *  Diuji compile dengan Arduino-ESP32 core 3.3.12 (Espressif).
 * ============================================================================
 */

#include <Arduino.h>
#include <stdarg.h>
#include "esp_system.h"
#include "soc/soc.h"
#include "soc/usb_serial_jtag_reg.h"

// ============================================================================
// 1. KONFIGURASI (ubah bagian ini saja bila hardware berbeda)
// ============================================================================
#define FW_VERSION            "1.0.0"
#define NODE_ADDRESS          1        // alamat ESP32 di bus RS485 (1..99), sama dengan raspi/config.json

// --- RS485 (UART1) ---
#define RS485_BAUD            38400    // harus sama dengan "baudrate" di raspi/config.json
#define RS485_TX_PIN          17       // ESP32 TX -> DI / TXD modul RS485
#define RS485_RX_PIN          18       // ESP32 RX <- RO / RXD modul RS485
#define RS485_DE_PIN          -1       // -1 = modul RS485 auto-direction (hanya TX/RX).
                                       // Isi nomor GPIO (mis. 10) bila memakai MAX485 dengan pin DE/RE.
#define RS485_TURNAROUND_US   1500     // jeda sebelum membalas, beri waktu transceiver master kembali ke mode terima
#define FRAME_TIMEOUT_MS      50       // frame yang terputus di tengah (> 50 ms tanpa data) dibuang

// --- Serial debug (port USB "UART") ---
#define DEBUG_BAUD            115200

// --- Timing ---
#define SOLENOID_PULSE_MS     1000     // lama solenoid aktif per perintah OPEN (1 detik)
#define MAX_ACTIVE_SOLENOIDS  1        // maks. solenoid aktif bersamaan, sisanya antre (melindungi catu daya)
#define DOOR_DEBOUNCE_MS      50       // debounce indikator pintu

// --- Level logika hardware ---
#define SOLENOID_ON_LEVEL     HIGH     // level GPIO untuk MENGAKTIFKAN solenoid (driver MOSFET/transistor aktif-HIGH)
#define LED_ON_LEVEL          HIGH     // level GPIO untuk MENYALAKAN LED
#define DOOR_CLOSED_LEVEL     LOW      // level GPIO saat pintu TERTUTUP (kontak NO menghubungkan GPIO ke GND)
#define DOOR_INPUT_MODE       INPUT_PULLUP
// Jika kontak NO menghubungkan GPIO ke 3V3 (bukan ke GND), ganti menjadi:
//   #define DOOR_CLOSED_LEVEL HIGH   dan   #define DOOR_INPUT_MODE INPUT_PULLDOWN
// Gunakan perintah "diag" di Serial Monitor untuk melihat level mentah tiap pin pintu.

// ============================================================================
// 2. PETA PIN (sesuai dokumen "Pin PCB Cell raspi-esp32")
// ============================================================================
constexpr uint8_t NUM_CELLS = 10;
//                                         Cell:  1   2   3   4   5   6   7   8   9  10
constexpr uint8_t SOLENOID_PIN[NUM_CELLS] = {     1,  2, 42, 41, 40, 39, 38, 37, 36, 35 };
constexpr uint8_t DOOR_PIN[NUM_CELLS]     = {    45, 48, 47, 21, 20, 19, 11, 12, 13, 14 };
constexpr uint8_t LED_PIN[NUM_CELLS]      = {     4,  5,  6,  7, 15, 16,  8,  3, 46,  9 };
// KOREKSI DOKUMEN: "Indikator Pintu 1" tertulis GPIO15, padahal GPIO15 sudah dipakai LED 5.
// Pada header kanan ESP32-S3-DevKitC-1, pin setelah GPIO0 adalah GPIO45, sehingga
// Indikator Pintu 1 = GPIO45. Bila PCB Anda benar-benar ke GPIO lain, ubah DOOR_PIN[0].

// ============================================================================
// 3. STATE (didefinisikan sebelum fungsi apa pun agar prototipe otomatis Arduino valid)
// ============================================================================
HardwareSerial &RS485 = Serial1;

struct Cell {
  bool     solenoidOn;
  uint32_t solenoidOnAt;      // millis() saat solenoid mulai aktif
  bool     queued;            // menunggu giliran solenoid
  bool     doorOpen;          // status pintu hasil debounce
  bool     doorRawOpen;       // pembacaan mentah terakhir
  uint32_t doorRawChangedAt;  // millis() saat pembacaan mentah terakhir berubah
  bool     ledOn;
  uint32_t openCount;         // jumlah aktivasi solenoid sejak boot
};
Cell cells[NUM_CELLS];

uint8_t openQueue[NUM_CELLS];  // antrean FIFO berisi index cell (0..9)
uint8_t queueHead = 0;
uint8_t queueLen = 0;

struct Stats {
  uint32_t rxFrames, txFrames, crcErrors, badFrames, otherAddress, unknownCmd, overflows;
} stats = {};

enum OpenResult { OPEN_STARTED, OPEN_QUEUED, OPEN_ALREADY_ON, OPEN_ALREADY_QUEUED };
const char *const OPEN_RESULT_TEXT[] = { "STARTED", "QUEUED", "ALREADY_ON", "ALREADY_QUEUED" };

char rxBuf[72];
uint8_t rxLen = 0;
uint32_t rxLastByteAt = 0;

char dbgBuf[48];
uint8_t dbgLen = 0;

// ============================================================================
// 4. PEMERIKSAAN OTOMATIS SAAT COMPILE (QC) — compile GAGAL bila setting salah
// ============================================================================
#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "Board salah. Pilih Tools > Board > esp32 > ESP32S3 Dev Module."
#endif
#if ARDUINO_USB_CDC_ON_BOOT
#error "Tools > USB CDC On Boot harus 'Disabled'. GPIO19/GPIO20 (USB D-/D+) dipakai Indikator Pintu 6 & 5."
#endif
#if (defined(BOARD_HAS_PSRAM) && defined(CONFIG_SPIRAM_MODE_OCT)) || defined(CONFIG_ESPTOOLPY_OCT_FLASH)
#error "Tools > PSRAM jangan 'OPI PSRAM' dan Flash Mode jangan 'OPI'. GPIO35/36/37 dipakai Solenoid 10/9/8."
#endif

constexpr int PIN_COUNT_TOTAL = 3 * NUM_CELLS + 2 + (RS485_DE_PIN >= 0 ? 1 : 0);

constexpr int pinAt(int k) {
  return k < NUM_CELLS             ? SOLENOID_PIN[k]
       : k < 2 * NUM_CELLS         ? DOOR_PIN[k - NUM_CELLS]
       : k < 3 * NUM_CELLS         ? LED_PIN[k - 2 * NUM_CELLS]
       : k == 3 * NUM_CELLS        ? RS485_TX_PIN
       : k == 3 * NUM_CELLS + 1    ? RS485_RX_PIN
       : RS485_DE_PIN;
}
constexpr bool pinClashFrom(int i, int j) {
  return j >= PIN_COUNT_TOTAL ? false : (pinAt(i) == pinAt(j) || pinClashFrom(i, j + 1));
}
constexpr bool anyPinClash(int i = 0) {
  return i >= PIN_COUNT_TOTAL ? false : (pinClashFrom(i, i + 1) || anyPinClash(i + 1));
}
// GPIO yang boleh dipakai pada ESP32-S3-DevKitC-1 (modul WROOM-1 / WROOM-1U)
constexpr bool pinUsable(int p) {
  return p >= 0 && p <= 48
      && !(p >= 22 && p <= 25)   // tidak ada di ESP32-S3
      && !(p >= 26 && p <= 32)   // dipakai SPI flash internal
      && p != 43 && p != 44;     // UART0 -> Serial Monitor & upload
}
constexpr bool allPinsUsable(int i = 0) {
  return i >= PIN_COUNT_TOTAL ? true : (pinUsable(pinAt(i)) && allPinsUsable(i + 1));
}
static_assert(sizeof(SOLENOID_PIN) == NUM_CELLS && sizeof(DOOR_PIN) == NUM_CELLS && sizeof(LED_PIN) == NUM_CELLS,
              "Jumlah pin per fungsi harus sama dengan NUM_CELLS.");
static_assert(!anyPinClash(), "PIN GANDA: ada GPIO yang dipakai dua fungsi. Periksa SOLENOID_PIN / DOOR_PIN / LED_PIN / RS485.");
static_assert(allPinsUsable(), "Ada GPIO terlarang (22-32 = flash/tidak ada, 43/44 = UART0 Serial Monitor).");
static_assert(NODE_ADDRESS >= 1 && NODE_ADDRESS <= 99, "NODE_ADDRESS harus 1..99.");
static_assert(SOLENOID_PULSE_MS > 0 && MAX_ACTIVE_SOLENOIDS >= 1, "Konfigurasi timing solenoid tidak valid.");

// ============================================================================
// 5. UTILITAS
// ============================================================================
uint8_t crc8(const char *data, size_t len) {
  uint8_t crc = 0x00;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint8_t)data[i];
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

// Parse bilangan desimal 1..3 digit. Hasil -1 bila tidak valid.
int parseUInt(const char *s) {
  if (s == nullptr || *s == '\0' || strlen(s) > 3) return -1;
  int v = 0;
  for (; *s; s++) {
    if (*s < '0' || *s > '9') return -1;
    v = v * 10 + (*s - '0');
  }
  return v;
}

// Memecah string "a,b,c" di tempat (in-place). Mengembalikan jumlah field.
int splitFields(char *s, char *field[], int maxFields) {
  int n = 0;
  field[n++] = s;
  for (; *s && n < maxFields; s++) {
    if (*s == ',') {
      *s = '\0';
      field[n++] = s + 1;
    }
  }
  return n;
}

void logEvent(const char *fmt, ...) {
  char msg[128];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(msg, sizeof(msg), fmt, ap);
  va_end(ap);
  uint32_t ms = millis();
  Serial.printf("[%6lu.%03lu] %s\n", (unsigned long)(ms / 1000), (unsigned long)(ms % 1000), msg);
}

const char *resetReasonText() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:   return "POWERON";
    case ESP_RST_EXT:       return "EXT";
    case ESP_RST_SW:        return "SW";
    case ESP_RST_PANIC:     return "PANIC";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:       return "WDT";
    case ESP_RST_BROWNOUT:  return "BROWNOUT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    default:                return "OTHER";
  }
}

inline uint8_t levelFor(bool active, uint8_t activeLevel) {
  return active ? activeLevel : (activeLevel == HIGH ? LOW : HIGH);
}

// ============================================================================
// 6. HARDWARE: SOLENOID, LED, PINTU
// ============================================================================
void setSolenoid(uint8_t i, bool on) {
  digitalWrite(SOLENOID_PIN[i], levelFor(on, SOLENOID_ON_LEVEL));
  cells[i].solenoidOn = on;
}

void setLed(uint8_t i, bool on) {
  digitalWrite(LED_PIN[i], levelFor(on, LED_ON_LEVEL));
  cells[i].ledOn = on;
}

bool readDoorOpenRaw(uint8_t i) {
  return digitalRead(DOOR_PIN[i]) != DOOR_CLOSED_LEVEL;
}

uint8_t activeSolenoidCount() {
  uint8_t n = 0;
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    if (cells[i].solenoidOn) n++;
  }
  return n;
}

void startSolenoid(uint8_t i, uint32_t now) {
  setSolenoid(i, true);
  cells[i].solenoidOnAt = now;
  cells[i].openCount++;
  logEvent("CELL %02u | SOLENOID ON  (%u ms)", i + 1, (unsigned)SOLENOID_PULSE_MS);
}

// Permintaan buka cell index i (0..9). Solenoid langsung aktif bila slot tersedia, jika tidak masuk antrean.
OpenResult requestOpen(uint8_t i, uint32_t now) {
  Cell &c = cells[i];
  if (c.solenoidOn) return OPEN_ALREADY_ON;
  if (c.queued) return OPEN_ALREADY_QUEUED;
  if (queueLen == 0 && activeSolenoidCount() < MAX_ACTIVE_SOLENOIDS) {
    startSolenoid(i, now);
    return OPEN_STARTED;
  }
  openQueue[(queueHead + queueLen) % NUM_CELLS] = i;
  queueLen++;
  c.queued = true;
  logEvent("CELL %02u | ANTRE (posisi %u)", i + 1, queueLen);
  return OPEN_QUEUED;
}

// Mematikan solenoid yang sudah aktif >= SOLENOID_PULSE_MS lalu menjalankan antrean.
void updateSolenoids(uint32_t now) {
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    if (cells[i].solenoidOn && (uint32_t)(now - cells[i].solenoidOnAt) >= SOLENOID_PULSE_MS) {
      setSolenoid(i, false);
      logEvent("CELL %02u | SOLENOID OFF", i + 1);
    }
  }
  while (queueLen > 0 && activeSolenoidCount() < MAX_ACTIVE_SOLENOIDS) {
    uint8_t i = openQueue[queueHead];
    queueHead = (queueHead + 1) % NUM_CELLS;
    queueLen--;
    cells[i].queued = false;
    startSolenoid(i, now);
  }
}

void stopAll() {
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    setSolenoid(i, false);
    cells[i].queued = false;
  }
  queueHead = 0;
  queueLen = 0;
  logEvent("STOP | semua solenoid OFF, antrean dikosongkan");
}

// Debounce indikator pintu. LED mengikuti status pintu: terbuka = ON, tertutup = OFF.
void updateDoors(uint32_t now) {
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    Cell &c = cells[i];
    bool raw = readDoorOpenRaw(i);
    if (raw != c.doorRawOpen) {
      c.doorRawOpen = raw;
      c.doorRawChangedAt = now;
    } else if (raw != c.doorOpen && (uint32_t)(now - c.doorRawChangedAt) >= DOOR_DEBOUNCE_MS) {
      c.doorOpen = raw;
      setLed(i, raw);
      logEvent(raw ? "CELL %02u | PINTU TERBUKA  -> LED ON" : "CELL %02u | PINTU TERTUTUP -> LED OFF", i + 1);
    }
  }
}

// GPIO19 (USB D-) dan GPIO20 (USB D+) secara default terhubung ke PHY USB-Serial/JTAG internal,
// dengan pull-up pada D+. Lepaskan agar keduanya bisa dibaca sebagai input biasa (Indikator Pintu 6 & 5).
void releaseUsbPins() {
  CLEAR_PERI_REG_MASK(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_USB_PAD_ENABLE);
}

// ============================================================================
// 7. RS485: KIRIM & TERIMA FRAME
// ============================================================================
void sendFrame(const char *payload) {
  char out[112];
  int n = snprintf(out, sizeof(out), "<%s*%02X\n", payload, crc8(payload, strlen(payload)));
  if (n <= 0 || n >= (int)sizeof(out)) return;
  delayMicroseconds(RS485_TURNAROUND_US);
#if RS485_DE_PIN >= 0
  digitalWrite(RS485_DE_PIN, HIGH);
#endif
  RS485.write((const uint8_t *)out, n);
  RS485.flush();  // tunggu sampai semua byte benar-benar terkirim
#if RS485_DE_PIN >= 0
  digitalWrite(RS485_DE_PIN, LOW);
#endif
  stats.txFrames++;
}

void fillStatus(char *door, char *led, char *sol, char *que) {
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    door[i] = cells[i].doorOpen ? 'O' : 'C';
    led[i] = cells[i].ledOn ? '1' : '0';
    sol[i] = cells[i].solenoidOn ? '1' : '0';
    que[i] = cells[i].queued ? '1' : '0';
  }
  door[NUM_CELLS] = led[NUM_CELLS] = sol[NUM_CELLS] = que[NUM_CELLS] = '\0';
}

// frame = ">AA,CMD[,ARG]*CC" (tanpa '\n')
void handleRs485Frame(char *frame, uint32_t now) {
  stats.rxFrames++;
  char *star = strrchr(frame, '*');
  if (star == nullptr || strlen(star) != 3) { stats.badFrames++; return; }
  int hi = hexNibble(star[1]), lo = hexNibble(star[2]);
  if (hi < 0 || lo < 0) { stats.badFrames++; return; }
  *star = '\0';
  char *payload = frame + 1;
  if (crc8(payload, strlen(payload)) != (uint8_t)((hi << 4) | lo)) { stats.crcErrors++; return; }

  char *field[6];
  int nf = splitFields(payload, field, 6);
  if (nf < 2) { stats.badFrames++; return; }
  if (parseUInt(field[0]) != NODE_ADDRESS) { stats.otherAddress++; return; }

  const char *cmd = field[1];
  char reply[96];
  if (strcmp(cmd, "STAT") == 0) {
    char d[NUM_CELLS + 1], l[NUM_CELLS + 1], s[NUM_CELLS + 1], q[NUM_CELLS + 1];
    fillStatus(d, l, s, q);
    snprintf(reply, sizeof(reply), "%02d,STAT,%s,%s,%s,%s,%lu", NODE_ADDRESS, d, l, s, q, (unsigned long)(now / 1000));
  } else if (strcmp(cmd, "OPEN") == 0) {
    int n = (nf >= 3) ? parseUInt(field[2]) : -1;
    if (n < 1 || n > NUM_CELLS) {
      snprintf(reply, sizeof(reply), "%02d,NAK,OPEN,BADARG", NODE_ADDRESS);
    } else {
      OpenResult r = requestOpen((uint8_t)(n - 1), now);
      logEvent("RS485 | OPEN %d -> %s", n, OPEN_RESULT_TEXT[r]);
      snprintf(reply, sizeof(reply), "%02d,ACK,OPEN,%d,%s", NODE_ADDRESS, n, OPEN_RESULT_TEXT[r]);
    }
  } else if (strcmp(cmd, "STOP") == 0) {
    stopAll();
    snprintf(reply, sizeof(reply), "%02d,ACK,STOP", NODE_ADDRESS);
  } else if (strcmp(cmd, "PING") == 0) {
    snprintf(reply, sizeof(reply), "%02d,PONG,%s,%u,%s", NODE_ADDRESS, FW_VERSION, (unsigned)NUM_CELLS, resetReasonText());
    logEvent("RS485 | PING dari master");
  } else {
    stats.unknownCmd++;
    snprintf(reply, sizeof(reply), "%02d,NAK,%s,UNKNOWN", NODE_ADDRESS, cmd);
  }
  sendFrame(reply);
}

void pollRs485(uint32_t now) {
  if (rxLen > 0 && (uint32_t)(now - rxLastByteAt) > FRAME_TIMEOUT_MS) {
    rxLen = 0;  // frame terputus, buang
    stats.badFrames++;
  }
  while (RS485.available() > 0) {
    char ch = (char)RS485.read();
    rxLastByteAt = now;
    if (ch == '>') {            // awal frame master (sekaligus sinkronisasi ulang)
      rxLen = 0;
      rxBuf[rxLen++] = ch;
      continue;
    }
    if (rxLen == 0) continue;   // abaikan noise / echo di luar frame
    if (ch == '\r') continue;
    if (ch == '\n') {
      rxBuf[rxLen] = '\0';
      handleRs485Frame(rxBuf, now);
      rxLen = 0;
      continue;
    }
    if (rxLen < sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = ch;
    } else {
      rxLen = 0;
      stats.overflows++;
    }
  }
}

// ============================================================================
// 8. SERIAL MONITOR (DEBUG): perintah teks untuk test tanpa Raspberry Pi
// ============================================================================
void printStatusTable() {
  Serial.println(F(" Cell | GPIO pintu | Pintu    | LED | Solenoid | Antre | Dibuka"));
  Serial.println(F(" -----+------------+----------+-----+----------+-------+-------"));
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    const Cell &c = cells[i];
    Serial.printf("  %02u  | GPIO%-2u %-4s | %-8s | %-3s | %-8s | %-5s | %lu\n", i + 1, DOOR_PIN[i],
                  digitalRead(DOOR_PIN[i]) == HIGH ? "HIGH" : "LOW", c.doorOpen ? "TERBUKA" : "TERTUTUP",
                  c.ledOn ? "ON" : "OFF", c.solenoidOn ? "AKTIF" : "OFF", c.queued ? "YA" : "-",
                  (unsigned long)c.openCount);
  }
}

void printHelp() {
  Serial.println(F("Perintah debug (Serial Monitor, line ending: Newline):"));
  Serial.println(F("  open N  : buka cell N (1..10) -> solenoid aktif 1 detik"));
  Serial.println(F("  all     : buka semua cell berurutan"));
  Serial.println(F("  stop    : matikan semua solenoid & kosongkan antrean"));
  Serial.println(F("  stat    : tabel status semua cell"));
  Serial.println(F("  diag    : level mentah pin pintu + statistik RS485"));
  Serial.println(F("  help    : daftar perintah"));
}

void printDiag() {
  printStatusTable();
  Serial.printf("Level pintu TERTUTUP = %s (mode %s)\n", DOOR_CLOSED_LEVEL == HIGH ? "HIGH" : "LOW",
                DOOR_INPUT_MODE == INPUT_PULLUP ? "INPUT_PULLUP" : DOOR_INPUT_MODE == INPUT_PULLDOWN ? "INPUT_PULLDOWN" : "INPUT");
  Serial.printf("RS485: rx=%lu tx=%lu crcErr=%lu badFrame=%lu alamatLain=%lu cmdTakDikenal=%lu overflow=%lu\n",
                (unsigned long)stats.rxFrames, (unsigned long)stats.txFrames, (unsigned long)stats.crcErrors,
                (unsigned long)stats.badFrames, (unsigned long)stats.otherAddress, (unsigned long)stats.unknownCmd,
                (unsigned long)stats.overflows);
  Serial.printf("Uptime %lu s, reset terakhir: %s, heap bebas %u byte\n", (unsigned long)(millis() / 1000),
                resetReasonText(), (unsigned)ESP.getFreeHeap());
}

void handleDebugCommand(char *line, uint32_t now) {
  for (char *p = line; *p; p++) *p = (char)tolower((unsigned char)*p);
  while (*line == ' ') line++;

  if (strncmp(line, "open", 4) == 0) {
    int n = parseUInt(line[4] == ' ' ? line + 5 : "");
    if (n < 1 || n > NUM_CELLS) {
      Serial.println(F("Format: open N   (N = 1..10)"));
      return;
    }
    OpenResult r = requestOpen((uint8_t)(n - 1), now);
    logEvent("DEBUG | OPEN %d -> %s", n, OPEN_RESULT_TEXT[r]);
  } else if (strcmp(line, "all") == 0) {
    for (uint8_t i = 0; i < NUM_CELLS; i++) requestOpen(i, now);
    logEvent("DEBUG | buka semua cell berurutan");
  } else if (strcmp(line, "stop") == 0) {
    stopAll();
  } else if (strcmp(line, "stat") == 0) {
    printStatusTable();
  } else if (strcmp(line, "diag") == 0) {
    printDiag();
  } else if (strcmp(line, "help") == 0 || strcmp(line, "?") == 0) {
    printHelp();
  } else {
    Serial.printf("Perintah tidak dikenal: '%s' (ketik help)\n", line);
  }
}

void pollDebugSerial(uint32_t now) {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r' || ch == '\n') {
      if (dbgLen > 0) {
        dbgBuf[dbgLen] = '\0';
        handleDebugCommand(dbgBuf, now);
        dbgLen = 0;
      }
    } else if (dbgLen < sizeof(dbgBuf) - 1) {
      dbgBuf[dbgLen++] = ch;
    }
  }
}

// ============================================================================
// 9. SETUP & LOOP
// ============================================================================
void printBanner(bool crcOk) {
  Serial.println();
  Serial.println(F("=================================================================="));
  Serial.printf(" LOCKER CONTROLLER ESP32-S3  |  FW %s  |  Node %02d  |  %u cell\n", FW_VERSION, NODE_ADDRESS, (unsigned)NUM_CELLS);
  Serial.printf(" RS485 UART1 %d bps 8N1 (TX=GPIO%d, RX=GPIO%d, DE=%d)\n", RS485_BAUD, RS485_TX_PIN, RS485_RX_PIN, RS485_DE_PIN);
  Serial.printf(" Pulse solenoid %d ms, maks %d aktif bersamaan | reset: %s\n", SOLENOID_PULSE_MS, MAX_ACTIVE_SOLENOIDS, resetReasonText());
  Serial.printf(" Self-test CRC-8: %s\n", crcOk ? "OK" : "GAGAL!");
  Serial.println(F("=================================================================="));
  Serial.println(F(" Cell | Solenoid | Ind.Pintu | LED    | Status awal"));
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    Serial.printf("  %02u  | GPIO%-4u | GPIO%-5u | GPIO%-2u | %s\n", i + 1, SOLENOID_PIN[i], DOOR_PIN[i], LED_PIN[i],
                  cells[i].doorOpen ? "TERBUKA (LED ON)" : "TERTUTUP");
  }
  Serial.println(F("Ketik 'help' untuk perintah debug."));
}

void setup() {
  // 1) Output dulu: solenoid & LED langsung OFF agar tidak ada aktivasi liar saat boot.
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    pinMode(SOLENOID_PIN[i], OUTPUT);
    setSolenoid(i, false);
    pinMode(LED_PIN[i], OUTPUT);
    setLed(i, false);
  }
#if RS485_DE_PIN >= 0
  pinMode(RS485_DE_PIN, OUTPUT);
  digitalWrite(RS485_DE_PIN, LOW);  // mode terima
#endif

  // 2) Input indikator pintu (GPIO19/20 dilepas dari PHY USB terlebih dahulu).
  releaseUsbPins();
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    pinMode(DOOR_PIN[i], DOOR_INPUT_MODE);
  }

  // 3) Serial debug & RS485.
  Serial.setTxBufferSize(1024);
  Serial.begin(DEBUG_BAUD);
  RS485.setRxBufferSize(512);
  RS485.begin(RS485_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);

  // 4) Status awal pintu (tanpa debounce) + LED sesuai status pintu.
  delay(20);  // beri waktu pull-up/pull-down stabil
  uint32_t now = millis();
  for (uint8_t i = 0; i < NUM_CELLS; i++) {
    bool open = readDoorOpenRaw(i);
    cells[i].doorOpen = cells[i].doorRawOpen = open;
    cells[i].doorRawChangedAt = now;
    setLed(i, open);
  }

  bool crcOk = crc8("123456789", 9) == 0xF4;  // nilai cek standar CRC-8/SMBUS
  printBanner(crcOk);

  enableLoopWDT();  // reset otomatis bila loop macet > 5 detik (solenoid kembali OFF)
}

void loop() {
  uint32_t now = millis();
  pollRs485(now);
  pollDebugSerial(now);
  updateSolenoids(now);
  updateDoors(now);
}
