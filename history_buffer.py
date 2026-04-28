# =============================================================================
# history_buffer.py
# =============================================================================
# A rolling time-window buffer that stores recent TelemetrySample objects.
#
# WHY DO WE NEED THIS?
#   The flight computer runs in a loop at 50 Hz. Each cycle produces a new
#   telemetry sample. To compute things like average velocity or acceleration
#   trends, we need to look at the last ~1 second of data, not just the
#   most recent single sample.
#
#   This buffer automatically:
#     1. Only stores genuinely new samples (ignores duplicates).
#     2. Discards samples older than the configured time window.
#     3. Provides helper methods for downstream calculations.
#
# KEY BEHAVIOR:
#   - TIME-BASED window, not count-based. At 50 Hz with a 1.0s window,
#     you get up to ~50 samples. If the loop slows down, you still get
#     1 second of history.
#   - Uses a deque (double-ended queue) internally. This lets us add to
#     the right and remove from the left in O(1) time — very efficient.
#
# CHANGES FROM ORIGINAL VERSION:
#   - Added clock-jump guard: if pi_time goes backward (e.g. after a
#     reset or NTP correction), the buffer clears itself rather than
#     producing negative time deltas that would corrupt calculations.
# =============================================================================

from collections import deque
from typing import Deque, List, Optional

from telemetry_types import TelemetrySample


class HistoryBuffer:

    def __init__(self, window_seconds: float = 1.0):
        """
        Args:
            window_seconds: How many seconds of history to retain.
                            Configured in config.py as HISTORY_WINDOW_SECONDS.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.window_seconds = window_seconds
        self._samples: Deque[TelemetrySample] = deque()
        self._last_appended_pi_time: Optional[float] = None

        # Maximum number of samples to retain regardless of time window.
        # At 40 Hz with a 1-second window we get up to 40 samples, but
        # averaging over 20 is statistically equivalent for our purposes
        # and halves the computation cost of average velocity/acceleration.
        self._max_samples: int = 20

    def append(self, sample: TelemetrySample) -> bool:
        """
        Add a sample to the buffer ONLY if it is genuinely new.

        Returns True if the sample was added, False if it was ignored.

        WHY DUPLICATE CHECKING?
          The main loop may run faster than the sensors update. If we
          called append() on every loop tick with the same sensor reading,
          we would artificially inflate our sample count and corrupt
          average velocity/acceleration calculations.
        """
        if sample is None:
            return False

        if sample.pi_time is None:
            return False

        # --- Clock-jump guard ---
        # If pi_time goes backward, something unexpected happened
        # (e.g. the Pico's clock was reset). Clear the buffer and start
        # fresh rather than producing nonsensical negative dt values.
        if self._last_appended_pi_time is not None:
            if sample.pi_time < self._last_appended_pi_time:
                self.clear()

        # --- Duplicate guard ---
        # Ignore samples with the same or older timestamp than the
        # last one we stored.
        if self._last_appended_pi_time is not None:
            if sample.pi_time <= self._last_appended_pi_time:
                return False

        self._samples.append(sample)
        self._last_appended_pi_time = sample.pi_time
        self._prune_old_samples(reference_time=sample.pi_time)

        # Enforce the maximum sample cap — remove oldest if over limit.
        # This runs after time-based pruning so the cap only ever trims
        # samples that are already within the time window.
        while len(self._samples) > self._max_samples:
            self._samples.popleft()

        return True

    def _prune_old_samples(self, reference_time: float) -> None:
        """
        Remove samples that have fallen outside the time window.

        This is called automatically after every successful append.
        We remove from the LEFT (oldest end) of the deque.

        Example: window = 1.0s, current time = 10.5s
          → cutoff = 9.5s
          → any sample with pi_time < 9.5 is removed
        """
        cutoff_time = reference_time - self.window_seconds
        while self._samples and self._samples[0].pi_time < cutoff_time:
            self._samples.popleft()

    # -------------------------------------------------------------------------
    # Query methods — used by DerivedStateCalculator and other modules
    # -------------------------------------------------------------------------

    def get_samples(self) -> List[TelemetrySample]:
        """All retained samples in chronological order (oldest first)."""
        return list(self._samples)

    def latest(self) -> Optional[TelemetrySample]:
        """Most recent sample, or None if buffer is empty."""
        return self._samples[-1] if self._samples else None

    def oldest(self) -> Optional[TelemetrySample]:
        """Oldest retained sample, or None if buffer is empty."""
        return self._samples[0] if self._samples else None

    def size(self) -> int:
        """Number of samples currently stored."""
        return len(self._samples)

    def is_empty(self) -> bool:
        return len(self._samples) == 0

    def clear(self) -> None:
        """Remove all samples. Called on clock jump or system reset."""
        self._samples.clear()
        self._last_appended_pi_time = None

    def time_span(self) -> float:
        """
        The actual time range covered by the stored samples, in seconds.

        Example: if oldest sample is at t=9.5 and newest at t=10.5,
        time_span() returns 1.0.

        Returns 0.0 if fewer than 2 samples exist.
        """
        if len(self._samples) < 2:
            return 0.0
        return self._samples[-1].pi_time - self._samples[0].pi_time

    def has_minimum_samples(self, minimum_count: int = 2) -> bool:
        """
        True if at least minimum_count samples are stored.

        Why 2 minimum?
          You need at least 2 data points to compute a rate of change
          (velocity from position, acceleration from velocity).
          A buffer with 1 sample cannot tell you how anything is changing.
        """
        return len(self._samples) >= minimum_count

    def valid_samples_only(self) -> List[TelemetrySample]:
        """
        Return only samples where telemetry_valid is True.

        Use this in calculations where a bad sensor reading would
        corrupt the result (e.g. acceleration estimates).
        Logging should use get_samples() to record everything including
        invalid samples — they are useful for diagnosing sensor issues.
        """
        return [s for s in self._samples if s.telemetry_valid]

    def summary(self) -> dict:
        """Lightweight debug summary. Useful for logging system state."""
        latest = self.latest()
        oldest = self.oldest()
        return {
            "window_seconds": self.window_seconds,
            "sample_count": self.size(),
            "time_span": self.time_span(),
            "latest_pi_time": latest.pi_time if latest else None,
            "oldest_pi_time": oldest.pi_time if oldest else None,
        }
