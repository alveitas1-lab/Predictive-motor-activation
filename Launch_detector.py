# =============================================================================
# launch_detector.py
# =============================================================================
# Detects launch and motor burnout from accelerometer data.
#
# WHY TWO DETECTORS IN ONE MODULE?
#   Launch and burnout are both acceleration threshold events detected
#   from the same sensor (LSM6DSOX Z-axis). They are sequential stages
#   of the same physical event — motor ignition → motor burnout — so
#   it makes sense to manage them together in one state machine.
#
# HOW LAUNCH DETECTION WORKS:
#   The rocket sits on the pad reading ~1g (gravity).
#   When the motor ignites, acceleration jumps to several g.
#   We require LAUNCH_DETECT_CONSECUTIVE_SAMPLES samples in a row
#   above LAUNCH_DETECT_ACCEL_THRESHOLD_G before declaring launch.
#   This prevents a bump, a gust, or a handling event from triggering
#   a false launch.
#
# HOW BURNOUT DETECTION WORKS:
#   During motor burn, the sensor reads high (e.g. 8–15g).
#   At burnout, thrust drops to zero and the reading falls sharply.
#   We require BURNOUT_CONSECUTIVE_SAMPLES readings in a row
#   below BURNOUT_ACCEL_THRESHOLD_G before declaring burnout.
#   This prevents a brief thrust dip mid-burn from ending the lockout early.
#
# WHICH AXIS IS "VERTICAL"?
#   We use the Z-axis of the LSM6DSOX. This assumes the sensor is mounted
#   with its Z-axis pointing along the rocket's long axis (up = positive Z
#   when the rocket is on the pad). If your sensor is mounted differently,
#   you may need to change _get_vertical_accel_g() to use a different axis
#   or compute the vector magnitude instead.
#
#   VECTOR MAGNITUDE OPTION:
#   If you are not sure of your sensor orientation, you can use total
#   acceleration magnitude instead: sqrt(ax² + ay² + az²).
#   This is rotation-independent but slightly slower to compute.
#   A commented-out version is provided below.
#
# STATE MACHINE:
#   WAITING_FOR_LAUNCH → (accel > threshold × N samples) → LAUNCHED
#   LAUNCHED           → (accel < threshold × N samples) → BURNT_OUT
#   BURNT_OUT          → terminal state (no further transitions here)
# =============================================================================

import math
from typing import Optional

from telemetry_types import TelemetrySample
import config


class LaunchDetector:

    # Internal state names (not exposed outside this module)
    _STATE_WAITING   = "WAITING_FOR_LAUNCH"
    _STATE_LAUNCHED  = "LAUNCHED"
    _STATE_BURNT_OUT = "BURNT_OUT"

    def __init__(self):
        """
        Initialize the launch detector.

        All counters start at zero and state starts at WAITING_FOR_LAUNCH.
        This is called once at startup in main.py.
        """
        self._state = self._STATE_WAITING

        # Consecutive sample counters.
        # These count how many samples IN A ROW have met the threshold.
        # Any sample that breaks the streak resets the counter to zero.
        self._launch_consecutive_count: int = 0
        self._burnout_consecutive_count: int = 0

        # Timestamps set when each event is confirmed.
        # None means the event has not occurred yet.
        self.launch_time_s: Optional[float] = None
        self.burnout_time_s: Optional[float] = None

    # -------------------------------------------------------------------------
    # Public interface — called every loop cycle from main.py
    # -------------------------------------------------------------------------

    def update(self, sample: TelemetrySample) -> None:
        """
        Feed a new telemetry sample into the detector.

        This must be called every loop cycle while in IDLE or ASCENDING
        flight phases. Once BURNT_OUT is confirmed, it can still be
        called safely — it will just return immediately.

        Args:
            sample: The latest TelemetrySample from SensorReader.
        """
        if not sample.telemetry_valid:
            # Don't let bad sensor data affect our consecutive counters.
            # We simply skip this sample without resetting anything.
            return

        if self._state == self._STATE_WAITING:
            self._check_for_launch(sample)

        elif self._state == self._STATE_LAUNCHED:
            self._check_for_burnout(sample)

        # If _STATE_BURNT_OUT: nothing to do, fall through.

    @property
    def launched(self) -> bool:
        """True once launch has been confirmed."""
        return self._state in (self._STATE_LAUNCHED, self._STATE_BURNT_OUT)

    @property
    def burnt_out(self) -> bool:
        """True once motor burnout has been confirmed."""
        return self._state == self._STATE_BURNT_OUT

    # -------------------------------------------------------------------------
    # Private detection logic
    # -------------------------------------------------------------------------

    def _check_for_launch(self, sample: TelemetrySample) -> None:
        """
        Check whether this sample contributes to a launch confirmation.

        HOW THE CONSECUTIVE COUNTER WORKS:
          Think of it as a streak counter.
          If the rocket needs 5 samples in a row above 2.5g:
            Sample 1: 8g  → counter = 1
            Sample 2: 9g  → counter = 2
            Sample 3: 7g  → counter = 3
            Sample 4: 1g  → counter reset to 0  (streak broken)
            Sample 5: 9g  → counter = 1
            Sample 6: 10g → counter = 2
            ...
          Once counter reaches LAUNCH_DETECT_CONSECUTIVE_SAMPLES → launch!

          This means a single spike or bump won't trigger launch.
          The motor must produce sustained thrust for ~50ms (5 × 10ms).
        """
        accel_g = self._get_vertical_accel_g(sample)

        if accel_g >= config.LAUNCH_DETECT_ACCEL_THRESHOLD_G:
            self._launch_consecutive_count += 1
        else:
            # Streak broken — reset and start counting again
            self._launch_consecutive_count = 0

        if self._launch_consecutive_count >= config.LAUNCH_DETECT_CONSECUTIVE_SAMPLES:
            self._state = self._STATE_LAUNCHED
            self.launch_time_s = sample.pi_time
            self._launch_consecutive_count = 0   # clean up

    def _check_for_burnout(self, sample: TelemetrySample) -> None:
        """
        Check whether this sample contributes to a burnout confirmation.

        Same consecutive-counter logic as launch detection, but in reverse:
        we are looking for acceleration FALLING below the threshold.

        PHYSICAL PICTURE:
          High accel (8–15g) = motor burning → keep lockout active
          Low accel (<2g)    = motor done    → start counting toward burnout
          If 10 samples in a row are below 2g → burnout confirmed

        WHY 10 SAMPLES?
          At 104 Hz, 10 samples = ~96ms. This is long enough to confirm
          the thrust is truly gone (not a brief dip in an inconsistent burn)
          but short enough that we don't waste valuable braking time.
          Adjust BURNOUT_CONSECUTIVE_SAMPLES in config.py if needed.
        """
        accel_g = self._get_vertical_accel_g(sample)

        if accel_g <= config.BURNOUT_ACCEL_THRESHOLD_G:
            self._burnout_consecutive_count += 1
        else:
            # Accel went back up — motor is still burning
            self._burnout_consecutive_count = 0

        if self._burnout_consecutive_count >= config.BURNOUT_CONSECUTIVE_SAMPLES:
            self._state = self._STATE_BURNT_OUT
            self.burnout_time_s = sample.pi_time
            self._burnout_consecutive_count = 0   # clean up

    @staticmethod
    def _get_vertical_accel_g(sample: TelemetrySample) -> float:
        """
        Extract the vertical acceleration component in g.

        DEFAULT BEHAVIOR:
          Uses the absolute value of accel_z_g. The Z-axis is assumed
          to point along the rocket's long axis. During boost, this will
          be the dominant axis reading the full thrust + gravity signal.
          We take abs() because the sign depends on which end of the
          sensor you call "up" — this makes the detector orientation-tolerant.

        ALTERNATIVE — use vector magnitude (rotation-independent):
          If your sensor might not be perfectly aligned with the rocket axis,
          uncomment the line below and comment out the abs(accel_z_g) return.
          Magnitude is always positive and doesn't depend on orientation.

            magnitude = math.sqrt(
                sample.accel_x_g**2 +
                sample.accel_y_g**2 +
                sample.accel_z_g**2
            )
            return magnitude

        NOTE: On the pad, magnitude ≈ 1g (gravity vector).
              During burn, magnitude ≈ total thrust/mass (same as Z-axis
              if the rocket flies straight).
        """
        return abs(sample.accel_z_g)
