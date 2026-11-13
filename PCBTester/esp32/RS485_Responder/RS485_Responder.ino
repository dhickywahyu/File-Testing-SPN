/*
  =====================================================================
   RS485 Responder - pasangan program "PCB QC Tester" (Raspberry Pi 4B)
   Board  : ESP32-S3-DevKitC-1 (Arduino IDE, core "esp32" by Espressif 2.x / 3.x)
  =====================================================================
   Cara kerja:
     Raspi mengirim   : $PING,<seq>,<payload>*<CRC16>\r\n   (tiap 250 ms)
     ESP32 membalas   : $PONG,<seq>,<payload>,<uptime_ms>,<rx_ok>,<rx_err>*<CRC16>\r\n
     Bila frame rusak : $NACK,<seq>*<CRC16>\r\n
   CRC16 = CRC-16/MODBUS dari teks di antara '$' dan '*'.
   Raspi memeriksa: seq sama, payload sama persis, CRC benar -> komunikasi 2 arah terbukti.

   Wiring modul RS485 (TTL <-> RS485) di sisi ESP32:
     GPIO17 (TX)  ->  DI / TXD modul
     GPIO18 (RX)  <-  RO / RXD modul
     DE + RE      ->  RS485_DE_PIN (hanya untuk modul MAX485 biasa; modul auto-direction: -1)
     VCC 3V3/5V, GND modul -> ESP32 ; GND juga disambung ke GND PCB yang diuji
     A  <-> A (PCB) ,  B <-> B (PCB)

   LED RGB onboard:
     HIJAU  = komunikasi baik (paket valid < 2 detik terakhir)
     BIRU   = kedip singkat tiap paket diterima
     ORANYE = ada frame rusak (CRC salah)
     MERAH  = tidak ada paket > 3 detik
   Serial Monitor (115200) menampilkan statistik tiap 2 detik.
*/
#include <Arduino.h>

// ---------------- KONFIGURASI ----------------
#define RS485_RX_PIN   18
#define RS485_TX_PIN   17
#define RS485_DE_PIN   -1        // isi nomor GPIO bila modul memakai pin DE/RE, -1 = auto-direction
#define RS485_BAUD     115200    // HARUS sama dengan RS485_BAUD di raspi/config.py
// LED RGB onboard: DevKitC-1 v1.0 = GPIO48, v1.1 = GPIO38 (RGB_BUILTIN dari definisi board)
// ---------------------------------------------

HardwareSerial RS485(1);

static char     lineBuf[200];
static size_t   lineLen   = 0;
static uint32_t rxOk      = 0;
static uint32_t rxErr     = 0;
static uint32_t lastOkMs  = 0;
static uint32_t lastErrMs = 0;
static uint32_t lastPrint = 0;
static uint32_t flashUntil = 0;
static char     lastSeq[16] = "-";

uint16_t crc16(const char *s, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint8_t)s[i];
    for (uint8_t b = 0; b < 8; b++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
  }
  return crc;
}

void setLed(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#else
  neopixelWrite(RGB_BUILTIN, r, g, b);
#endif
#endif
}

void sendFrame(const char *body) {
  char out[240];
  int n = snprintf(out, sizeof(out), "$%s*%04X\r\n", body, crc16(body, strlen(body)));
  if (RS485_DE_PIN >= 0) { digitalWrite(RS485_DE_PIN, HIGH); delayMicroseconds(10); }
  RS485.write((const uint8_t *)out, n);
  RS485.flush();                                   // tunggu byte terakhir benar-benar terkirim
  if (RS485_DE_PIN >= 0) digitalWrite(RS485_DE_PIN, LOW);
}

void handleLine(char *line) {
  size_t len = strlen(line);
  while (len && (line[len - 1] == '\r' || line[len - 1] == ' ')) line[--len] = 0;
  if (len == 0) return;

  char *start = strchr(line, '$');                 // abaikan byte sampah sebelum '$'
  char *star  = start ? strrchr(start, '*') : NULL;
  if (!start || !star) { rxErr++; lastErrMs = millis(); return; }
  *star = 0;
  const char *body = start + 1;

  // ambil seq (field ke-2) untuk NACK / PONG
  char seq[16] = "0";
  const char *c1 = strchr(body, ',');
  if (c1) {
    const char *c2 = strchr(c1 + 1, ',');
    size_t sl = c2 ? (size_t)(c2 - c1 - 1) : strlen(c1 + 1);
    if (sl > 0 && sl < sizeof(seq)) { memcpy(seq, c1 + 1, sl); seq[sl] = 0; }
  }

  uint16_t got  = (uint16_t)strtoul(star + 1, NULL, 16);
  uint16_t calc = crc16(body, strlen(body));
  if (got != calc) {
    rxErr++;
    lastErrMs = millis();
    char nack[32];
    snprintf(nack, sizeof(nack), "NACK,%s", seq);
    sendFrame(nack);
    return;
  }
  if (strncmp(body, "PING,", 5) != 0) return;     // frame lain (mis. echo PONG sendiri) diabaikan

  const char *payload = "";
  const char *c2 = c1 ? strchr(c1 + 1, ',') : NULL;
  if (c2) payload = c2 + 1;

  rxOk++;
  lastOkMs = millis();
  strncpy(lastSeq, seq, sizeof(lastSeq) - 1);
  char resp[200];
  snprintf(resp, sizeof(resp), "PONG,%s,%s,%lu,%lu,%lu", seq, payload,
           (unsigned long)millis(), (unsigned long)rxOk, (unsigned long)rxErr);
  sendFrame(resp);
  flashUntil = millis() + 40;
}

void updateLed() {
  uint32_t now = millis();
  if (now < flashUntil)                                   setLed(0, 0, 40);   // biru: paket masuk
  else if (lastErrMs && now - lastErrMs < 1000)           setLed(40, 15, 0);  // oranye: frame rusak
  else if (lastOkMs && now - lastOkMs < 2000)             setLed(0, 35, 0);   // hijau: komunikasi baik
  else if (!lastOkMs || now - lastOkMs > 3000)            setLed((now / 500) % 2 ? 40 : 0, 0, 0); // merah kedip
}

void setup() {
  Serial.begin(115200);
  if (RS485_DE_PIN >= 0) { pinMode(RS485_DE_PIN, OUTPUT); digitalWrite(RS485_DE_PIN, LOW); }
  RS485.setRxBufferSize(1024);
  RS485.begin(RS485_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);
  setLed(0, 0, 0);
  delay(300);
  Serial.println();
  Serial.println(F("=== RS485 Responder - PCB QC Tester ==="));
  Serial.printf("UART1 RX=GPIO%d TX=GPIO%d DE=%d  baud=%d\n", RS485_RX_PIN, RS485_TX_PIN, RS485_DE_PIN, RS485_BAUD);
}

void loop() {
  while (RS485.available()) {
    char ch = (char)RS485.read();
    if (ch == '\n') {
      lineBuf[lineLen] = 0;
      handleLine(lineBuf);
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = ch;
    } else {                                    // baris terlalu panjang -> buang
      lineLen = 0;
      rxErr++;
      lastErrMs = millis();
    }
  }
  updateLed();

  uint32_t now = millis();
  if (now - lastPrint >= 2000) {
    lastPrint = now;
    const char *st = (lastOkMs && now - lastOkMs < 2000) ? "BAIK" : (lastOkMs ? "TERPUTUS" : "MENUNGGU PING");
    Serial.printf("[RS485] status=%s  diterima_OK=%lu  error=%lu  seq_terakhir=%s  paket_terakhir=%lums lalu\n",
                  st, (unsigned long)rxOk, (unsigned long)rxErr, lastSeq,
                  (unsigned long)(lastOkMs ? now - lastOkMs : 0));
  }
}
