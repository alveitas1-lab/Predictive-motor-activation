import RPi.GPIO as GPIO
import time

class MotorController:
    def __init__(self, step_pin=17, dir_pin=27, enable_pin=22):
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        
        self.initialize_pins()  # Initialize GPIO pins

    def initialize_pins(self):
        GPIO.setmode(GPIO.BCM)  # Use BCM GPIO numbering
        GPIO.setup(self.step_pin, GPIO.OUT)  # Set step pin as output
        GPIO.setup(self.dir_pin, GPIO.OUT)  # Set direction pin as output
        GPIO.setup(self.enable_pin, GPIO.OUT)  # Set enable pin as output
        GPIO.output(self.enable_pin, GPIO.LOW)  # Enable the motor

    def rotate_to_0_degrees(self):
        self.rotate(0)  # Rotate to 0 degrees (0 steps)

    def rotate_to_90_degrees(self):
        self.rotate(100)  # Rotate to 90 degrees (100 steps)

    def rotate(self, steps):
        GPIO.output(self.dir_pin, GPIO.HIGH)  # Set direction
        for _ in range(steps):
            GPIO.output(self.step_pin, GPIO.HIGH)
            time.sleep(0.01)  # Adjust the speed as necessary
            GPIO.output(self.step_pin, GPIO.LOW)
            time.sleep(0.01)

    def cleanup(self):
        GPIO.cleanup()  # Cleanup GPIO settings

if __name__ == '__main__':
    motor = MotorController()  # Create an instance of MotorController
    try:
        motor.rotate_to_90_degrees()  # Rotate to 90 degrees as a test
        time.sleep(2)  # Delay to observe the motor movement
        motor.rotate_to_0_degrees()  # Rotate back to 0 degrees
    finally:
        motor.cleanup()  # Ensure GPIO cleanup on exit
