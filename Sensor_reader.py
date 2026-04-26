# =============================================================================
# sensor_reader.py
# =============================================================================
# Reads the LSM6DSOX (IMU) and DPS310 (barometer) over I2C and produces
# a TelemetrySample every loop cycle.
#
# WHAT THIS MODULE DOES:
#   1. Initializes both sensors on the shared I2C bus at startup.
#   2. Every loop cycle, reads raw acceleration, gyro, pressure, temperature.
#   3. Converts pressure → altitude using the barometric formula.
#   4. Estimates vertical velocity by differentiating altitude over time.
#   5. Packages everything into a TelemetrySample for downstream modules.
#
# ALTITUDE CALCULATION:
#   The DPS310 gives us atmospheric pressure in hPa. We convert this to
#   altitude using the international barometric formula:
#
#     altitude = 44307.7 × (1 − (pressure / sea_level_pressure)^0.190284)
#
#   This gives altitude in meters above sea level. We then:
#     - Convert to feet (× 3.28084)
#     - Subtract the ground pressure altitude recorded at startup
#       so that the reading is AGL (above ground level), not ASL.
#
# VERTICAL VELOCITY CALCULATION:
#   We differentiate altitude over time:
#     velocity = (current_altitude − previous_altitude) / dt
#
#   This is simple and effective for a barometric sensor. The DPS310
#   updates at ~25 Hz in our configuration, so dt ≈ 0.04s between
#   fresh baro readings. At 50 Hz loop rate, some cycles will reuse
#   the previous baro reading — the HistoryBuffer's duplicate guard
#   handles that correctly.
#
# SENSOR ADDRESSES (I2C):
#   LSM6DSOX default: 0x6A (SDO/SA0 pin low) or 0x6B (SDO high)
#   DPS310 default:   0x77 (SDO pin low)     or 0x76 (SDO high)
#   Both use the same I2C bus (I2C0, GP4/GP5).
#
# CIRCUITPYTHON LIBRARIES REQUIRED:
#   adafruit_lsm6ds   — for LSM6DSOX
#   adafruit_dps310   — for DPS310
#   Install via: circup install adafruit_lsm6ds adafruit_dps310
# =============================================================================

import time
import board
import busio

from telemetry_types import TelemetrySample
import config


# Conversion constants
_METERS_TO_FEET = 3.28084
_MS2_TO_G = 1.0 / 9.80665          # m/s² → g
_FT_TO_METERS = 0.3048


class SensorReader:

    def __init__(self):
        """
        Initialize I2C bus and both sensors.

        This is called ONCE at system startup in main.py before the
        flight loop begins. If a sensor fails to initialize, an
        exception is raised and the program stops — we do not want
        to fly with a missing sensor.

        After initialization, _zero_altitude() is called to record
        the ground-level pressure so all altitude readings are AGL.
        """
        # --- Set up I2C bus ---
        # board.GP4 and board.GP5 are the SDA and SCL pins defined
        # in config.py (I2C_SDA_PIN = 4, I2C_SCL_PIN = 5).
        # We use busio.I2C for explicit control over frequency.
        self._i2c = busio.I2C(
            scl=board.GP5,
            sda=board.GP4,
            frequency=config.I2C_FREQUENCY_HZ
        )

        # --- Initialize LSM6DSOX ---
        # Import here so the rest of the file is importable on a PC
        # for unit testing without CircuitPython hardware libraries.
        try:
            from adafruit_lsm6ds.lsm6dsox import LSM6DSOX
            from adafruit_lsm6ds import Rate, AccelRange, GyroRange

            self._imu = LSM6DSOX(self._i2c)

            # Set accelerometer range to ±16g (handles high-thrust motors)
            # AccelRange options: RANGE_2G, RANGE_4G, RANGE_8G, RANGE_16G
            self._imu.accelerometer_range = AccelRange.RANGE_16G

            # Set accelerometer output data rate to 104 Hz
            # Rate options: RATE_12_5_HZ, RATE_26_HZ, RATE_52_HZ,
            #               RATE_104_HZ, RATE_208_HZ, RATE_416_HZ
            self._imu.accelerometer_data_rate = Rate.RATE_104_HZ

            # Set gyro range to ±2000 dps (widest range for stability logging)
            self._imu.gyro_range = GyroRange.RANGE_2000_DPS
            self._imu.gyro_data_rate = Rate.RATE_104_HZ

        except Exception as e:
            raise RuntimeError(f"LSM6DSOX init failed: {e}")

        # --- Initialize DPS310 ---
        try:
            import adafruit_dps310

            self._baro = adafruit_dps310.DPS310(self._i2c)

            # Configure oversampling for pressure and temperature.
            # Higher oversampling = lower noise, slightly slower update rate.
            # 16x oversampling gives ~25 Hz update rate, which is fine.
            self._baro.pressure_oversample_count = (
                adafruit_dps310.SampleCount.COUNT_16
            )
            self._baro.temperature_oversample_count = (
                adafruit_dps310.SampleCount.COUNT_16
            )
            self._baro.mode = adafruit_dps310.Mode.CONT_PRESTEMP

        except Exception as e:
            raise RuntimeError(f"DPS310 init failed: {e}")

        # --- State for velocity estimation ---
        # We track the previous altitude and timestamp so we can
        # differentiate altitude → velocity each cycle.
        self._prev_altitude_ft: float = 0.0
        self._prev_time_s: float = time.monotonic()

        # --- Ground reference ---
        # Set during _zero_altitude(). All altitude readings are
        # reported relative to this baseline.
        self._ground_altitude_ft: float = 0.0

        # Zero the altitude reference now.
        self._zero_altitude()

    def _zero_altitude(self, samples: int = 20) -> None:
        """
        Record the ground-level altitude baseline.

        Reads the barometer multiple times and averages the result.
        This average becomes our AGL zero reference for the entire flight.

        WHY AVERAGE?
          A single baro reading is noisy. Averaging 20 samples over
          ~0.8 seconds gives a stable baseline. This is called on the
          pad before flight — make sure the rocket is stationary and
          the barometer has warmed up for at least 5 seconds first.

        Args:
            samples: Number of readings to average. 20 is a good default.
        """
        readings = []
        for _ in range(samples):
            try:
                pressure = self._baro.pressure
                alt_ft = self._pressure_to_altitude_ft(pressure)
                readings.append(alt_ft)
            except Exception:
                pass
            time.sleep(0.04)

        if readings:
            self._ground_altitude_ft = sum(readings) / len(readings)
        else:
            # If all readings failed, assume ground = 0.
            # This will be obvious in the log as all altitudes being
            # offset by the actual ground pressure altitude.
            self._ground_altitude_ft = 0.0

    def read(self) -> TelemetrySample:
        """
        Read both sensors and return a TelemetrySample.

        This is called once per loop cycle in main.py.
        If either sensor read fails, telemetry_valid is set to False
        and the last known good values are used where possible.
        The HistoryBuffer and downstream modules handle invalid samples
        gracefully — they skip them for physics calculations but the
        DataLogger still records them so you can see when failures occurred.

        Returns:
            A TelemetrySample with current sensor data.
        """
        now = time.monotonic()
        valid = True

        # --- Read IMU ---
        try:
            # acceleration returns (x, y, z) in m/s²
            # We convert to g for logging and burnout detection.
            ax_ms2, ay_ms2, az_ms2 = self._imu.acceleration
            gx_dps, gy_dps, gz_dps = self._imu.gyro

            ax_g = ax_ms2 * _MS2_TO_G
            ay_g = ay_ms2 * _MS2_TO_G
            az_g = az_ms2 * _MS2_TO_G

            # gyro comes back in rad/s from some library versions —
            # check your adafruit_lsm6ds version. If gyro values look
            # like 0.01–0.1 instead of 1–360, multiply by 57.2958.
            # The library used here returns degrees/s natively.

        except Exception as e:
            # Sensor read failed. Use zeros and flag invalid.
            ax_g = ay_g = az_g = 0.0
            gx_dps = gy_dps = gz_dps = 0.0
            valid = False

        # --- Read barometer ---
        try:
            pressure_hpa = self._baro.pressure
            temperature_c = self._baro.temperature

            altitude_asl_ft = self._pressure_to_altitude_ft(pressure_hpa)
            altitude_agl_ft = altitude_asl_ft - self._ground_altitude_ft

        except Exception as e:
            pressure_hpa = 0.0
            temperature_c = 0.0
            altitude_agl_ft = self._prev_altitude_ft
            valid = False

        # --- Compute vertical velocity ---
        # Simple finite difference: Δaltitude / Δtime
        # dt is clamped to a minimum of 0.001s to prevent division
        # by zero if two reads happen almost simultaneously.
        dt = max(now - self._prev_time_s, 0.001)
        vertical_velocity_ft_s = (altitude_agl_ft - self._prev_altitude_ft) / dt

        # Update previous values for next cycle
        self._prev_altitude_ft = altitude_agl_ft
        self._prev_time_s = now

        return TelemetrySample(
            pi_time=now,
            altitude_ft=altitude_agl_ft,
            vertical_velocity_ft_s=vertical_velocity_ft_s,
            accel_x_g=ax_g,
            accel_y_g=ay_g,
            accel_z_g=az_g,
            gyro_x_dps=gx_dps,
            gyro_y_dps=gy_dps,
            gyro_z_dps=gz_dps,
            pressure_hpa=pressure_hpa,
            temperature_c=temperature_c,
            telemetry_valid=valid
        )

    @staticmethod
    def _pressure_to_altitude_ft(pressure_hpa: float) -> float:
        """
        Convert barometric pressure to altitude using the international
        barometric formula.

        Formula:
            altitude_m = 44307.7 × (1 − (P / P0)^0.190284)

        Where:
            P  = measured pressure in hPa
            P0 = sea-level reference pressure in hPa (from config)

        This assumes a standard atmosphere temperature lapse rate.
        For competition altitudes up to 10,000 ft AGL the error is
        typically less than 0.1% — well within acceptable range.

        Args:
            pressure_hpa: Current pressure reading from DPS310.

        Returns:
            Altitude in feet above the sea-level reference pressure.
            Subtract ground_altitude_ft to get AGL.
        """
        if pressure_hpa <= 0:
            return 0.0

        ratio = pressure_hpa / config.BARO_SEA_LEVEL_PRESSURE_HPA
        altitude_m = 44307.7 * (1.0 - (ratio ** 0.190284))
        return altitude_m * _METERS_TO_FEET
