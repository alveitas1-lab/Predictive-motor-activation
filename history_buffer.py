from collections import deque
from typing import Deque, List, Optional

from telemetry_types import TelemetrySample


class HistoryBuffer:
    """
    Time-based rolling buffer for recent telemetry history.

    Design purpose:
    - Store only genuinely new telemetry samples
    - Keep a rolling history over a fixed time window
    - Support downstream calculations such as:
        - derived acceleration
        - average velocity
        - velocity trends
        - launch detection inputs
        - ML feature generation

    Important behavior:
    - This buffer is TIME-BASED, not fixed-count-based
    - Only append when a truly new telemetry sample arrives
    - Old samples are automatically pruned once outside the window
    """

    def __init__(self, window_seconds: float = 1.0):
        """
        Initialize the history buffer.

        Args:
            window_seconds:
                Length of time history to retain, in seconds.
                We are using 1.0 s because Blue Raven live status updates
                arrive at about 5 Hz, so 1 second gives ~5 fresh samples.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.window_seconds = window_seconds
        self._samples: Deque[TelemetrySample] = deque()
        self._last_appended_pi_time: Optional[float] = None

    def append(self, sample: TelemetrySample) -> bool:
        """
        Append a telemetry sample ONLY if it is genuinely new.

        Args:
            sample:
                A TelemetrySample object.

        Returns:
            True if the sample was appended.
            False if it was ignored (duplicate / invalid for append).

        Notes:
        - We only want fresh telemetry in this history buffer.
        - Since the controller may run faster than the Blue Raven update rate,
          repeated reuse of the latest telemetry should NOT repeatedly append
          duplicates into the history.
        """
        if sample is None:
            return False

        if sample.pi_time is None:
            return False

        # Ignore duplicate timestamps.
        # This is the main protection against stuffing the buffer
        # with repeated copies of the same Blue Raven sample.
        if self._last_appended_pi_time is not None:
            if sample.pi_time <= self._last_appended_pi_time:
                return False

        self._samples.append(sample)
        self._last_appended_pi_time = sample.pi_time

        self._prune_old_samples(reference_time=sample.pi_time)
        return True

    def _prune_old_samples(self, reference_time: float) -> None:
        """
        Remove samples older than the rolling window.

        Args:
            reference_time:
                Usually the pi_time of the most recently appended sample.
        """
        cutoff_time = reference_time - self.window_seconds

        while self._samples and self._samples[0].pi_time < cutoff_time:
            self._samples.popleft()

    def get_samples(self) -> List[TelemetrySample]:
        """
        Return all retained samples as a list in chronological order.
        """
        return list(self._samples)

    def latest(self) -> Optional[TelemetrySample]:
        """
        Return the most recent telemetry sample, or None if empty.
        """
        if not self._samples:
            return None
        return self._samples[-1]

    def oldest(self) -> Optional[TelemetrySample]:
        """
        Return the oldest retained telemetry sample, or None if empty.
        """
        if not self._samples:
            return None
        return self._samples[0]

    def size(self) -> int:
        """
        Return the number of retained samples.
        """
        return len(self._samples)

    def is_empty(self) -> bool:
        """
        Return True if no samples are stored.
        """
        return len(self._samples) == 0

    def clear(self) -> None:
        """
        Remove all samples from the buffer.
        """
        self._samples.clear()
        self._last_appended_pi_time = None

    def time_span(self) -> float:
        """
        Return the actual time span covered by the retained samples.

        Returns:
            0.0 if fewer than 2 samples exist,
            otherwise latest.pi_time - oldest.pi_time.
        """
        if len(self._samples) < 2:
            return 0.0

        return self._samples[-1].pi_time - self._samples[0].pi_time

    def has_minimum_samples(self, minimum_count: int = 2) -> bool:
        """
        Return True if the buffer contains at least minimum_count samples.

        Why this matters:
        - You need at least 2 samples to estimate acceleration from velocity.
        - Some downstream calculations may want 3 or more points.
        """
        return len(self._samples) >= minimum_count

    def valid_samples_only(self) -> List[TelemetrySample]:
        """
        Return only telemetry samples currently marked valid.

        This gives downstream modules the option to ignore invalid samples
        if they want to operate only on trusted telemetry.
        """
        return [sample for sample in self._samples if sample.telemetry_valid]

    def summary(self) -> dict:
        """
        Return a lightweight summary useful for debugging/logging.
        """
        latest = self.latest()
        oldest = self.oldest()

        return {
            "window_seconds": self.window_seconds,
            "sample_count": self.size(),
            "time_span": self.time_span(),
            "latest_pi_time": latest.pi_time if latest else None,
            "oldest_pi_time": oldest.pi_time if oldest else None,
        }
