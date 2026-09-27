"""Rolling window: is the live reading stable enough to calibrate?"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


def compute_min_samples(
    window_s: float, interval_s: float, floor: int = 3, ceiling: int = 5
) -> int:
    """Derive the required sample count from reading interval and window size.

    With fast intervals (e.g. 1 s), we want at least `ceiling` samples to avoid
    reacting to transient glitches.  With slow intervals (e.g. 5 s), we lower
    the bar to the maximum physically attainable within the window, but never
    below `floor` to ensure a meaningful span measurement.
    """
    if interval_s <= 0:
        return ceiling
    possible = int(window_s / interval_s) + 1
    return max(floor, min(ceiling, possible))


@dataclass(frozen=True, slots=True)
class StabilitySnapshot:
    minimum: float | None
    maximum: float | None
    span: float | None
    stable: bool
    sample_count: int
    required_samples: int
    span_threshold: float


class StabilityWindow:
    """Rolling window for calibration stability gating.

    Args:
        window_s: Time window to consider (seconds).
        min_samples: Base minimum samples required (used with fast intervals).
        span: Maximum allowed span (max - min) to consider readings stable.
        interval_s: Expected reading interval (seconds). When provided, the
            required sample count adapts so that stability is achievable even
            with slow Atlas C,n intervals (e.g. 5 s).
        min_samples_floor: Absolute minimum samples, even for slow intervals.
        min_samples_ceiling: Maximum samples required, even for fast intervals.
    """

    def __init__(
        self,
        *,
        window_s: float,
        min_samples: int,
        span: float,
        interval_s: float | None = None,
        min_samples_floor: int = 3,
        min_samples_ceiling: int = 5,
    ) -> None:
        self._window_s = window_s
        self._base_min_samples = min_samples
        self._span = span
        self._interval_s = interval_s
        self._min_samples_floor = min_samples_floor
        self._min_samples_ceiling = min_samples_ceiling
        self._samples: deque[tuple[float, float]] = deque()

    @property
    def required_samples(self) -> int:
        """Current required sample count, adapted to the reading interval."""
        if self._interval_s is None:
            return self._base_min_samples
        return compute_min_samples(
            self._window_s,
            self._interval_s,
            self._min_samples_floor,
            self._min_samples_ceiling,
        )

    def set_interval(self, interval_s: float | None) -> None:
        """Update the expected reading interval (e.g. when C,n changes)."""
        self._interval_s = interval_s

    def push(self, value: float, now: float) -> StabilitySnapshot:
        self._samples.append((now, value))
        cutoff = now - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        values = [sample for _, sample in self._samples]
        required = self.required_samples
        if not values:
            return StabilitySnapshot(None, None, None, False, 0, required, self._span)
        minimum = min(values)
        maximum = max(values)
        current_span = maximum - minimum
        stable = len(values) >= required and current_span <= self._span
        return StabilitySnapshot(
            minimum, maximum, current_span, stable, len(values), required, self._span
        )
