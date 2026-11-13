import serial
import time
import sys
import threading

class RaspberryPiSerial:
    def __init__(self, port='/dev/ttyAMA0', baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.is_connected = False
        self.running = False

    def check_connection(self):
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.write(b'AT\r\n')
                time.sleep(0.1)
                response = self.serial_conn.read_all()
                if response:
                    print(f"Connection OK - Received: {response.decode('utf-8', errors='ignore')}")
                    return True
                else:
                    print("Connection test: No response")
                    return False
            else:
                print("Serial port not open")
                return False
        except Exception as e:
            print(f"Connection check failed: {e}")
            return False

    def connect(self):
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )

            if self.serial_conn.is_open:
                self.is_connected = True
                print(f"Connected to {self.port} at {self.baudrate} baud")
                return True
            else:
                print("Failed to open serial port")
                return False

        except serial.SerialException as e:
            print(f"Serial connection error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False

    def disconnect(self):
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.is_connected = False
            print("Disconnected from serial port")

    def write_data(self, data):
        try:
            if self.is_connected and self.serial_conn:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                bytes_written = self.serial_conn.write(data)
                print(f"Sent {bytes_written} bytes: {data}")
                return bytes_written
            else:
                print("Not connected to serial port")
                return 0
        except Exception as e:
            print(f"Write error: {e}")
            return 0

    def read_data(self):
        try:
            if self.is_connected and self.serial_conn:
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read_all()
                    if data:
                        decoded_data = data.decode('utf-8', errors='ignore')
                        print(f"Received: {decoded_data}")
                        return decoded_data
            return None
        except Exception as e:
            print(f"Read error: {e}")
            return None

    def start_listening(self):
        self.running = True
        listen_thread = threading.Thread(target=self._listen_loop)
        listen_thread.daemon = True
        listen_thread.start()
        print("Started listening for serial data...")

    def _listen_loop(self):
        while self.running and self.is_connected:
            try:
                data = self.read_data()
                if data:
                    print(f"[RECEIVED] {data.strip()}")
                time.sleep(0.1)
            except Exception as e:
                print(f"Listen loop error: {e}")
                break

def main():
    # Initialize serial communication on Raspberry Pi UART pins
    # Pin 2 (5V), Pin 6 (GND), Pin 8 (GPIO14/TXD), Pin 10 (GPIO15/RXD)
    raspi_serial = RaspberryPiSerial(
        port='/dev/ttyAMA0',  # Primary UART on Pi
        baudrate=9600,
        timeout=1
    )

    try:
        # Connect to serial port
        if raspi_serial.connect():
            # Check connection
            raspi_serial.check_connection()

            # Start listening for incoming data
            raspi_serial.start_listening()

            # Interactive loop for sending data
            print("\nSerial communication ready!")
            print("Type 'quit' to exit, or enter data to send:")

            while True:
                user_input = input("> ")

                if user_input.lower() in ['quit', 'exit', 'q']:
                    break

                if user_input:
                    raspi_serial.write_data(user_input + '\r\n')

                time.sleep(0.1)

        else:
            print("Failed to establish serial connection")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nInterrupted by user")

    except Exception as e:
        print(f"Unexpected error: {e}")

    finally:
        raspi_serial.disconnect()
        print("Program ended")

if __name__ == "__main__":
    main()
