# =============================================================================
# config.py
# =============================================================================
# Central configuration for the IREC airbrake flight computer.
#
# HOW TO USE THIS FILE:
#   Every tunable constant in the entire project lives here.
#   No other file should contain "magic numbers."
#   Before each flight, review the sections marked [PRE-FLIGHT CHECK].
#
# WIRING REFERENCE (Raspberry Pi Pico pinout):
# -------------------------------------------------------
#   LSM6DSOX (IMU — accelerometer + gyroscope)
#     SDA  → GP4  (Pico pin 6)
#     SCL  → GP5  (Pico pin 7)
#     VIN  → 3.3V (Pico pin 36)
#     GND  → GND  (Pico pin 38)
#     Note: Both LSM6DSOX and DPS310 share the same I2C bus (I2C0).
#           Ensure pull-up resistors (4.7kΩ) are on SDA and SCL.
#
#   DPS310 (Barometric pressure + temperature → altitude)
#     SDA  → GP4  (shared with LSM6DSOX on I2C0)
#     SCL  → GP5  (shared with LSM6DSOX on I2C0)
#     VIN  → 3.3V
#     GND  → GND
#
#   Stepper motor driver (e.g. A4988, DRV8825 — your choice)
#     STEP → GP10 (Pico pin 14)
#     DIR  → GP11 (Pico pin 15)
#     EN   → GP12 (Pico pin 16)  — active LOW on most drivers
#     VIN  → External motor power (check your driver's rated voltage)
#     GND  → Shared GND with Pico
#     Note: Never power the motor from the Pico's 3.3V or 5V rail.
#           Use the PowerBoost 1000 output for motor supply if needed.
#
#   Micro-SD breakout (SPI)
#     MOSI → GP19 (Pico pin 25)
#     MISO → GP16 (Pico pin 21)
#     SCK  → GP18 (Pico pin 24)
#     CS   → GP17 (Pico pin 22)
#     VIN  → 3.3V (this board is 5V-ready but 3.3V logic safe)
#     GND  → GND
#
#   PowerBoost 1000
#     Provides 5V regulated output from a LiPo cell.
#     Power the Pico via its VSYS pin (pin 39) from the PowerBoost output.
#     Do NOT power via USB at the same time.
# =============================================================================


# -----------------------------------------------------------------------------
# [PRE-FLIGHT CHECK] Mission parameters
# These are the values you set on the launch pad before each flight.
# -----------------------------------------------------------------------------

# Target apogee in feet above ground level (AGL).
# IREC Basic category: 10,000 ft AGL
# Change this to match your competition or test flight target.
TARGET_APOGEE_FT: float = 10000.0

# Ground reference note:
# The DPS310 is zeroed at boot by averaging 20 pressure readings.
# All altitude values throughout the program are AGL relative to
# that boot-time baseline. No manual site altitude entry is needed —
# just power on, let the sensor warm up for 5 seconds, and the
# zero is set automatically before you walk to the pad.


# -----------------------------------------------------------------------------
# I2C bus configuration
# Both sensors share I2C bus 0 on the Pico.
# -----------------------------------------------------------------------------

I2C_BUS_ID: int = 0          # CircuitPython: board.I2C() uses GP4/GP5 by default
I2C_SDA_PIN: int = 4         # GP4
I2C_SCL_PIN: int = 5         # GP5
I2C_FREQUENCY_HZ: int = 400_000   # 400 kHz fast mode — both sensors support this


# -----------------------------------------------------------------------------
# LSM6DSOX — Inertial Measurement Unit
# Measures acceleration (m/s²) and angular rate (°/s) on 3 axes.
# We primarily use the Z-axis (vertical) accelerometer channel.
# -----------------------------------------------------------------------------

# Accelerometer full-scale range.
# Options (in g): 2, 4, 8, 16
# At 10,000 ft on a competition motor, peak acceleration during burn
# can easily exceed 10g. Use ±16g for safety margin.
IMU_ACCEL_RANGE_G: int = 16

# Output data rate for the accelerometer, in Hz.
# 104 Hz gives ~10ms per sample — fast enough for burnout detection
# without overwhelming the Pico's processing budget.
# Options: 12, 26, 52, 104, 208, 416, 833, 1660
IMU_ACCEL_ODR_HZ: int = 104

# Gyroscope range (degrees per second). Not used for flight logic,
# but logged for post-flight analysis of roll/pitch stability.
# Options: 125, 250, 500, 1000, 2000
IMU_GYRO_RANGE_DPS: int = 2000


# -----------------------------------------------------------------------------
# DPS310 — Barometric pressure sensor → altitude
# The DPS310 gives us pressure and temperature, from which we compute
# altitude using the barometric formula. It is the primary altitude source.
# -----------------------------------------------------------------------------

# Oversampling rate for pressure measurement.
# Higher = more accurate, but slower. 16x is a good balance.
BARO_PRESSURE_OVERSAMPLE: int = 16

# Oversampling rate for temperature measurement.
# Temperature is used to correct pressure readings. 16x is fine.
BARO_TEMP_OVERSAMPLE: int = 16

# Sea-level pressure in hPa. This is used to convert pressure → altitude.
# Standard atmosphere is 1013.25 hPa. For best accuracy, enter the
# actual QNH from your local weather service before flight.
# [PRE-FLIGHT CHECK] — update this from the day's weather report.
BARO_SEA_LEVEL_PRESSURE_HPA: float = 1013.25


# -----------------------------------------------------------------------------
# Stepper motor configuration
# Fill these in once you choose your motor and driver.
# The system uses these values to command a 90° rotation.
# -----------------------------------------------------------------------------

# How many steps the driver sends per full 360° revolution of the motor shaft.
# Common values:
#   200  = standard 1.8°/step motor, full-step mode
#   400  = same motor in half-step mode (smoother, quieter)
#   800  = quarter-step mode
#   2048 = 28BYJ-48 gear motor in half-step mode
# SET THIS ONCE YOU KNOW YOUR MOTOR + DRIVER COMBINATION.
STEPPER_STEPS_PER_REV: int = 200

# Steps required to rotate 90° (fully retracted → fully deployed).
# Formula: STEPPER_STEPS_PER_REV / 4
# This is computed automatically — do not change it directly.
# If your mechanical linkage means 90° shaft rotation does not equal
# fully open brakes, adjust STEPPER_STEPS_PER_REV above instead.
STEPPER_STEPS_FOR_90_DEG: int = STEPPER_STEPS_PER_REV // 4

# Step pulse delay in seconds.
# Smaller = faster motor. Too small = motor stalls or misses steps.
# Start at 0.002 (2ms) and reduce carefully if speed is needed.
STEPPER_STEP_DELAY_S: float = 0.002

# GPIO pin assignments for the stepper driver.
STEPPER_STEP_PIN: int = 10    # GP10
STEPPER_DIR_PIN: int = 11     # GP11
STEPPER_ENABLE_PIN: int = 12  # GP12 — pull LOW to enable most drivers

# Direction logic.
# If the brakes move the wrong way on first test, flip this to False.
STEPPER_DEPLOY_DIR_HIGH: bool = True   # True = HIGH on DIR pin = deploy direction


# -----------------------------------------------------------------------------
# Micro-SD SPI pin assignments
# -----------------------------------------------------------------------------

SD_MOSI_PIN: int = 19
SD_MISO_PIN: int = 16
SD_SCK_PIN: int = 18
SD_CS_PIN: int = 17

# Log filename written to SD card root.
# Increment this manually between flights to avoid overwriting logs.
# Format: flight_01.csv, flight_02.csv, etc.
SD_LOG_FILENAME: str = "flight_01.csv"


# -----------------------------------------------------------------------------
# History buffer
# Controls how much recent telemetry is kept in RAM for calculations.
# -----------------------------------------------------------------------------

# Rolling time window in seconds.
# At 104 Hz IMU + ~25 Hz baro fusion, 1.0 s gives ~50–100 samples.
# This feeds derived state (average velocity, acceleration estimates).
HISTORY_WINDOW_SECONDS: float = 1.0


# -----------------------------------------------------------------------------
# Launch detection
# The rocket is considered launched when the vertical acceleration
# exceeds this threshold for a sustained period.
# -----------------------------------------------------------------------------

# Acceleration threshold to declare launch, in g (earth gravities).
# At rest on the pad the sensor reads ~1g (gravity). During motor burn
# it will read much higher. 2.5g means "clearly not sitting still."
# [PRE-FLIGHT CHECK] — verify this is above pad vibration noise.
LAUNCH_DETECT_ACCEL_THRESHOLD_G: float = 2.5

# How many consecutive samples must exceed the threshold to confirm launch.
# At 104 Hz, 5 samples = ~48ms. Prevents a bump from triggering launch.
LAUNCH_DETECT_CONSECUTIVE_SAMPLES: int = 5


# -----------------------------------------------------------------------------
# Burnout detection
# After launch, the motor burn lockout is active. The lockout ends
# when acceleration drops sharply, indicating motor burnout.
#
# Physical explanation:
#   During burn: net acceleration = thrust/mass − g → reads HIGH (e.g. 5–15g)
#   After burnout: only gravity + drag → reads LOW (below ~2g and falling)
# -----------------------------------------------------------------------------

# Acceleration level BELOW which burnout is considered to have occurred, in g.
# The LSM6DSOX measures total acceleration including gravity. At burnout,
# the reading will drop toward 1g (free fall + drag). 2.0g is a safe threshold
# that is clearly above free-fall but clearly below any meaningful motor thrust.
# [PRE-FLIGHT CHECK] — review against your motor's thrust curve.
BURNOUT_ACCEL_THRESHOLD_G: float = 2.0

# How many consecutive samples must be below threshold to confirm burnout.
# At 104 Hz, 10 samples = ~96ms. Prevents a brief thrust dip from
# prematurely ending the lockout.
BURNOUT_CONSECUTIVE_SAMPLES: int = 10


# -----------------------------------------------------------------------------
# Brake retraction triggers
# Once deployed, the brakes retract under these conditions.
# -----------------------------------------------------------------------------

# Duration of continuous negative vertical velocity (ft/s) before
# the brakes retract. "Negative" means descending.
# 3.0 seconds is intentionally conservative — we want to be sure
# we are past apogee and in genuine descent before retracting.
RETRACT_NEGATIVE_VELOCITY_DURATION_S: float = 3.0

# Sudden velocity shift threshold (ft/s change per second).
# If vertical velocity changes by more than this amount in one sample,
# the brakes retract immediately. This catches unexpected events like
# a parachute ejecting or a structural anomaly.
# Example: 50 ft/s/s ≈ a very abrupt, unexpected deceleration.
RETRACT_SUDDEN_SHIFT_FT_S2: float = 50.0


# -----------------------------------------------------------------------------
# Apogee prediction (ML model)
# These values describe the TFLite model's expected input/output format.
# They must match exactly what the model was trained with.
# Update these after training your model.
# -----------------------------------------------------------------------------

# Path to the compiled TFLite model file on the Pico's filesystem.
MODEL_PATH: str = "apogee_model.tflite"

# Number of input features the model expects.
# Must match the feature vector built in apogee_predictor.py.
# Default feature set: [altitude_ft, vertical_velocity_ft_s,
#                       vertical_acceleration_ft_s2, avg_velocity_ft_s,
#                       avg_acceleration_ft_s2, time_since_launch_s,
#                       altitude_error_ft]
MODEL_INPUT_FEATURES: int = 7

# Whether the model uses int8 quantization.
# Float32 is simpler; int8 is faster but requires scale/zero-point handling.
# Set to False until you decide during training.
MODEL_IS_QUANTIZED: bool = False


# -----------------------------------------------------------------------------
# Main loop timing
# -----------------------------------------------------------------------------

# Target loop rate in Hz.
# The main control loop runs at this rate. Sensor reads, derived state,
# prediction, and logging all happen once per loop iteration.
# 50 Hz = 20ms per cycle, which is fast enough for this application.
LOOP_RATE_HZ: int = 50
LOOP_PERIOD_S: float = 1.0 / LOOP_RATE_HZ   # 0.02 s


# -----------------------------------------------------------------------------
# Logging
# Column headers for the CSV log file written to the SD card.
# The order here must match the row written in data_logger.py.
# -----------------------------------------------------------------------------

LOG_COLUMNS: list = [
    "pi_time_s",
    "altitude_ft",
    "vertical_velocity_ft_s",
    "vert_accel_ft_s2",
    "avg_velocity_ft_s",
    "avg_accel_ft_s2",
    "time_since_launch_s",
    "altitude_error_ft",
    "predicted_apogee_ft",
    "flight_phase",
    "brakes_deployed",
    "raw_accel_x_g",
    "raw_accel_y_g",
    "raw_accel_z_g",
    "raw_gyro_x_dps",
    "raw_gyro_y_dps",
    "raw_gyro_z_dps",
    "pressure_hpa",
    "temperature_c",
    "telemetry_valid",
]
