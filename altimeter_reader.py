import serial

class AltimeterReader:
    def __init__(self, port, baudrate):
        # Initialize UART serial connection
        # port: Serial port (e.g., '/dev/ttyUSB0')
        # baudrate: Baud rate for serial communication (common values are 9600 or 115200)
        self.ser = serial.Serial(port, baudrate)
        self.altitude = 0.0  # Initialize altitude variable
        self.vertical_velocity = 0.0  # Initialize vertical velocity variable

    def read_data(self):
        # Read a line from the serial port
        try:
            line = self.ser.readline().decode('utf-8').strip()  # Read data from the altimeter
            return line
        except Exception as e:
            print(f'Error reading from serial: {e}')
            return None

    def parse_altitude(self, data):
        # Placeholder for parsing altitude data in feet from the received data
        # Example format: "ALT: 1500 ft"
        try:
            # Extract altitude from data string
            altitude_str = data.split(' ')[1]  # Assuming the data comes in format "ALT: 1500 ft"
            self.altitude = float(altitude_str)  # Convert altitude to float
        except Exception as e:
            print(f'Error parsing altitude data: {e}')

    def close(self):
        # Close the serial connection gracefully
        self.ser.close()
