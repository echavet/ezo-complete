"""Rolling window: is the live reading stable enough to calibrate?

For pH sensors, stability is judged in mV-equivalent to be independent of
calibration. The slope (from Cal,?) determines the conversion:
  mV_delta = pH_delta * 59.16 * (slope% / 100)

This ensures that a probe with low slope doesn't appear falsely stable
just because the pH range is compressed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable


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
    span_mv: float | None
    stable: bool
    sample_count: int
    required_samples: int
    span_threshold: float
    effective_window: float | None = None


class StabilityWindow:
    """Rolling window for calibration stability gating.

    Args:
        window_s: Time window to consider (seconds).
        min_samples: Base minimum samples required (used with fast intervals).
        span_threshold_mv: Maximum allowed span in mV to consider readings stable.
        interval_s: Expected reading interval (seconds). When provided, the
            required sample count adapts so that stability is achievable even
            with slow Atlas C,n intervals (e.g. 5 s).
        min_samples_floor: Absolute minimum samples, even for slow intervals.
        min_samples_ceiling: Maximum samples required, even for fast intervals.
        to_mv_fn: Optional function to convert reading values to mV-equivalent.
            For ORP, this is identity (readings are already in mV).
            For pH, this converts pH span to mV using the current slope.
    """

    def __init__(
        self,
        *,
        window_s: float,
        min_samples: int,
        span_threshold_mv: float,
        interval_s: float | None = None,
        min_samples_floor: int = 3,
        min_samples_ceiling: int = 5,
        to_mv_fn: Callable[[float], float] | None = None,
    ) -> None:
        self._window_s = window_s
        self._base_min_samples = min_samples
        self._span_threshold_mv = span_threshold_mv
        self._interval_s = interval_s
        self._min_samples_floor = min_samples_floor
        self._min_samples_ceiling = min_samples_ceiling
        self._to_mv_fn = to_mv_fn or (lambda x: x)
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

    @property
    def span_threshold_mv(self) -> float:
        """Current span threshold in mV."""
        return self._span_threshold_mv

    def set_interval(self, interval_s: float | None) -> None:
        """Update the expected reading interval (e.g. when C,n changes)."""
        self._interval_s = interval_s

    def set_span_threshold(self, threshold_mv: float) -> None:
        """Update the span threshold in mV."""
        self._span_threshold_mv = threshold_mv

    def set_to_mv_fn(self, fn: Callable[[float], float] | None) -> None:
        """Update the mV conversion function (e.g. when slope changes)."""
        self._to_mv_fn = fn or (lambda x: x)

    def reset(self) -> None:
        """Clear accumulated samples (e.g. when switching from continuous to polling)."""
        self._samples.clear()

    @property
    def effective_window_s(self) -> float:
        """Effective window size, expanded if needed to fit required samples.
        
        With slow polling intervals (e.g. 25s in exploitation mode), the
        configured window (e.g. 10s) may be too small to ever accumulate
        enough samples. We expand to fit required_samples × interval.
        """
        if self._interval_s is None or self._interval_s <= 0:
            return self._window_s
        min_window = self.required_samples * self._interval_s
        return max(self._window_s, min_window)

    def push(self, value: float, now: float) -> StabilitySnapshot:
        self._samples.append((now, value))
        cutoff = now - self.effective_window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        values = [sample for _, sample in self._samples]
        required = self.required_samples
        if not values:
            return StabilitySnapshot(
                None, None, None, None, False, 0, required, self._span_threshold_mv,
                self.effective_window_s
            )
        minimum = min(values)
        maximum = max(values)
        span_native = maximum - minimum
        span_mv = self._to_mv_fn(span_native)
        stable = len(values) >= required and span_mv <= self._span_threshold_mv
        return StabilitySnapshot(
            minimum,
            maximum,
            span_native,
            span_mv,
            stable,
            len(values),
            required,
            self._span_threshold_mv,
            self.effective_window_s,
        )
