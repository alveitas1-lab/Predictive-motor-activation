# =============================================================================
# data_logger.py
# =============================================================================
# Writes all flight data to a CSV file on the SD card every loop cycle.
#
# WHAT THIS MODULE DOES:
#   1. Opens (or creates) the log file on the SD card at startup.
#   2. Writes the column header row once.
#   3. Accepts a log_row() call every loop cycle with all current data.
#   4. Writes each row immediately and flushes to disk.
#   5. Closes the file cleanly on shutdown.
#
# WHY FLUSH EVERY CYCLE?
#   On a hard landing, ejection charge firing, or power loss, there is
#   no guarantee the program gets to run a clean shutdown sequence.
#   By flushing after every write, the worst case is losing the last
#   single row of data rather than the entire flight log.
#   The performance cost at 50 Hz is acceptable on the SD card.
#
# CSV FORMAT:
#   The column order is defined in config.LOG_COLUMNS and must match
#   the order of values passed to log_row() exactly.
#   After the flight, open the file in Excel, Google Sheets, or Python
#   (pandas) and plot any column against pi_time_s.
#
# SD CARD SETUP (CircuitPython):
#   CircuitPython mounts the SD card as /sd/ when using the
#   adafruit_sdcard library with busio.SPI.
#   The log file will appear at /sd/flight_01.csv (or whatever
#   SD_LOG_FILENAME is set to in config.py).
#
#   CIRCUITPYTHON LIBRARIES REQUIRED:
#     adafruit_sdcard
#     storage (built into CircuitPython)
#   Install via: circup install adafruit_sdcard
#
# POST-FLIGHT DATA ANALYSIS:
#   Pull the SD card, open the CSV in Python with:
#
#     import pandas as pd
#     import matplotlib.pyplot as plt
#
#     df = pd.read_csv("flight_01.csv")
#     df.plot(x="pi_time_s", y="altitude_ft")
#     plt.show()
#
#   You can overlay this against your other avionics bay flight computers
#   by aligning on launch time (time_since_launch_s == 0).
# =============================================================================

import os
import board
import busio
import digitalio
import storage

from telemetry_types import TelemetrySample, DerivedState, ActuatorStatus
import config


class DataLogger:

    def __init__(self):
        """
        Initialize the SD card and open the log file.

        Mounts the SD card over SPI using the pins defined in config.py,
        then opens (or creates) the log file and writes the header row.

        If SD card initialization fails, a RuntimeError is raised and
        the program stops. Flying without a data logger is not acceptable
        for a competition flight — the logs are your primary record of
        what the system did.

        Called once at startup in main.py.
        """
        # --- Initialize SPI bus for SD card ---
        spi = busio.SPI(
            clock=getattr(board, f"GP{config.SD_SCK_PIN}"),
            MOSI=getattr(board, f"GP{config.SD_MOSI_PIN}"),
            MISO=getattr(board, f"GP{config.SD_MISO_PIN}")
        )

        # Chip select pin for SD card
        cs = digitalio.DigitalInOut(
            getattr(board, f"GP{config.SD_CS_PIN}")
        )
        cs.direction = digitalio.Direction.OUTPUT

        # Mount the SD card
        try:
            import adafruit_sdcard
            sdcard = adafruit_sdcard.SDCard(spi, cs)
            vfs = storage.VfsFat(sdcard)
            storage.mount(vfs, "/sd")
        except Exception as e:
            raise RuntimeError(f"SD card mount failed: {e}")

        # --- Open log file ---
        # "a" mode = append. If the file already exists (e.g. power
        # cycled on the pad), new data is added after existing rows
        # rather than overwriting. Change SD_LOG_FILENAME in config.py
        # between flights to keep logs separate.
        log_path = f"/sd/{config.SD_LOG_FILENAME}"
        try:
            self._file = open(log_path, "a")
        except Exception as e:
            raise RuntimeError(f"Log file open failed: {e}")

        # Write header row only if the file is empty (new file).
        # If we are appending to an existing file, skip the header
        # so it doesn't appear mid-file after a power cycle.
        if self._file.seek(0, 2) == 0:   # seek to end, check position
            self._write_header()

        self._row_count: int = 0

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def log_row(
        self,
        sample: TelemetrySample,
        derived: DerivedState,
        predicted_apogee_ft: float,
        flight_phase: str,
        actuator: ActuatorStatus,
    ) -> None:
        """
        Write one row of flight data to the CSV file.

        Called once per loop cycle in main.py.
        The column order here must match config.LOG_COLUMNS exactly.

        Args:
            sample:             Latest TelemetrySample from SensorReader.
            derived:            Latest DerivedState from DerivedStateCalculator.
            predicted_apogee_ft: Latest ML model prediction (0.0 if not yet run).
            flight_phase:       Current FlightPhase string.
            actuator:           Current ActuatorStatus from Actuator.

        HOW TO ADD A NEW COLUMN:
          1. Add the column name to LOG_COLUMNS in config.py.
          2. Add the corresponding value to the row list below
             in the same position.
          That is all — the header and data stay in sync automatically.
        """
        if derived is None:
            # Derived state not yet available (buffer still filling).
            # Write a partial row with zeros for derived fields.
            vert_accel     = 0.0
            time_launch    = 0.0
            alt_error      = 0.0
            avg_vel        = 0.0
            avg_accel      = 0.0
        else:
            vert_accel     = derived.vertical_acceleration_ft_s2
            time_launch    = derived.time_since_launch_s
            alt_error      = derived.altitude_error_ft
            avg_vel        = derived.avg_velocity_ft_s
            avg_accel      = derived.avg_acceleration_ft_s2

        # Build the row in the exact order of config.LOG_COLUMNS
        row = [
            f"{sample.pi_time:.4f}",                    # pi_time_s
            f"{sample.altitude_ft:.2f}",                # altitude_ft
            f"{sample.vertical_velocity_ft_s:.3f}",     # vertical_velocity_ft_s
            f"{vert_accel:.3f}",                        # vert_accel_ft_s2
            f"{avg_vel:.3f}",                           # avg_velocity_ft_s
            f"{avg_accel:.3f}",                         # avg_accel_ft_s2
            f"{time_launch:.4f}",                       # time_since_launch_s
            f"{alt_error:.2f}",                         # altitude_error_ft
            f"{predicted_apogee_ft:.1f}",               # predicted_apogee_ft
            flight_phase,                               # flight_phase
            str(actuator.is_deployed),                  # brakes_deployed
            f"{sample.accel_x_g:.4f}",                 # raw_accel_x_g
            f"{sample.accel_y_g:.4f}",                  # raw_accel_y_g
            f"{sample.accel_z_g:.4f}",                  # raw_accel_z_g
            f"{sample.gyro_x_dps:.3f}",                 # raw_gyro_x_dps
            f"{sample.gyro_y_dps:.3f}",                 # raw_gyro_y_dps
            f"{sample.gyro_z_dps:.3f}",                 # raw_gyro_z_dps
            f"{sample.pressure_hpa:.4f}",               # pressure_hpa
            f"{sample.temperature_c:.2f}",              # temperature_c
            str(sample.telemetry_valid),                # telemetry_valid
        ]

        self._file.write(",".join(row) + "\n")

        # Flush to disk every cycle.
        # This ensures data survives a hard landing or power loss.
        self._file.flush()
        self._row_count += 1

    def close(self) -> None:
        """
        Flush and close the log file cleanly.

        Called by main.py during the SAFE/shutdown phase.
        After this, no more rows can be written.
        """
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass   # Best effort — if close fails, the data is still flushed

    @property
    def row_count(self) -> int:
        """Total number of data rows written so far."""
        return self._row_count

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _write_header(self) -> None:
        """
        Write the CSV column header row.

        Only called once, when a new (empty) log file is created.
        Uses the column list from config.LOG_COLUMNS so the header
        always matches the data rows automatically.
        """
        self._file.write(",".join(config.LOG_COLUMNS) + "\n")
        self._file.flush()
