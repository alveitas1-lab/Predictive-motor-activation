from typing import Optional, List

from telemetry_types import TelemetrySample, DerivedState
from history_buffer import HistoryBuffer


class DerivedStateCalculator:
    """
    Computes derived state values from recent telemetry history
    and controller context.

    Purpose:
    - Estimate vertical acceleration from velocity history
    - Compute time since launch
    - Compute altitude error relative to target apogee
    - Compute average velocity over the history window
    - Compute average acceleration over the history window

    This module does NOT:
    - read telemetry directly
    - detect launch by itself
    - make deployment decisions
    - run the ML model

    It only computes useful state quantities for downstream modules.
    """

    def __init__(self, target_apogee_ft: float):
        """
        Initialize the derived state calculator.

        Args:
            target_apogee_ft:
                User-entered target apogee in feet.
        """
        self.target_apogee_ft = target_apogee_ft

    def compute(
        self,
        history: HistoryBuffer,
        launch_time_s: Optional[float]
    ) -> Optional[DerivedState]:
        """
        Compute a DerivedState object from telemetry history.

        Args:
            history:
                Rolling history buffer of TelemetrySample objects.
            launch_time_s:
                Pi timestamp when launch was detected.
                If None, time_since_launch_s will be 0.0.

        Returns:
            A DerivedState object if at least one telemetry sample exists,
            otherwise None.
        """
        latest_sample = history.latest()
        if latest_sample is None:
            return None

        samples = history.get_samples()

        vertical_acceleration_ft_s2 = self._estimate_current_acceleration(samples)
        time_since_launch_s = self._compute_time_since_launch(
            current_time_s=latest_sample.pi_time,
            launch_time_s=launch_time_s
        )
        altitude_error_ft = self.target_apogee_ft - latest_sample.altitude_ft
        avg_velocity_ft_s = self._compute_average_velocity(samples)
        avg_acceleration_ft_s2 = self._compute_average_acceleration(samples)

        return DerivedState(
            vertical_acceleration_ft_s2=vertical_acceleration_ft_s2,
            time_since_launch_s=time_since_launch_s,
            altitude_error_ft=altitude_error_ft,
            avg_velocity_ft_s=avg_velocity_ft_s,
            avg_acceleration_ft_s2=avg_acceleration_ft_s2
        )

    def _compute_time_since_launch(
        self,
        current_time_s: float,
        launch_time_s: Optional[float]
    ) -> float:
        """
        Compute time since launch.

        If launch has not yet been detected, return 0.0.
        """
        if launch_time_s is None:
            return 0.0

        elapsed = current_time_s - launch_time_s
        return max(0.0, elapsed)

    def _compute_average_velocity(self, samples: List[TelemetrySample]) -> float:
        """
        Compute average vertical velocity over all samples in the buffer.

        Returns:
            0.0 if no samples are available.
        """
        if not samples:
            return 0.0

        total = 0.0
        count = 0

        for sample in samples:
            total += sample.vertical_velocity_ft_s
            count += 1

        if count == 0:
            return 0.0

        return total / count

    def _estimate_current_acceleration(self, samples: List[TelemetrySample]) -> float:
        """
        Estimate the most recent vertical acceleration using the last two samples.

        Uses:
            a ≈ Δv / Δt

        Returns:
            0.0 if fewer than 2 samples are available or if time difference is invalid.
        """
        if len(samples) < 2:
            return 0.0

        s1 = samples[-2]
        s2 = samples[-1]

        dt = s2.pi_time - s1.pi_time
        if dt <= 0:
            return 0.0

        dv = s2.vertical_velocity_ft_s - s1.vertical_velocity_ft_s
        return dv / dt

    def _compute_average_acceleration(self, samples: List[TelemetrySample]) -> float:
        """
        Compute average vertical acceleration across the entire buffer.

        This is done by estimating acceleration between each adjacent sample pair
        and averaging those segment accelerations.

        Returns:
            0.0 if fewer than 2 samples are available.
        """
        if len(samples) < 2:
            return 0.0

        acceleration_estimates = []

        for i in range(1, len(samples)):
            s1 = samples[i - 1]
            s2 = samples[i]

            dt = s2.pi_time - s1.pi_time
            if dt <= 0:
                continue

            dv = s2.vertical_velocity_ft_s - s1.vertical_velocity_ft_s
            acceleration_estimates.append(dv / dt)

        if not acceleration_estimates:
            return 0.0

        return sum(acceleration_estimates) / len(acceleration_estimates)
