"""Rolling window: is the live reading stable enough to calibrate?"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StabilitySnapshot:
    minimum: float | None
    maximum: float | None
    span: float | None
    stable: bool


class StabilityWindow:
    def __init__(self, *, window_s: float, min_samples: int, span: float) -> None:
        self._window_s = window_s
        self._min_samples = min_samples
        self._span = span
        self._samples: deque[tuple[float, float]] = deque()

    def push(self, value: float, now: float) -> StabilitySnapshot:
        self._samples.append((now, value))
        cutoff = now - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        values = [sample for _, sample in self._samples]
        if not values:
            return StabilitySnapshot(None, None, None, False)
        minimum = min(values)
        maximum = max(values)
        span = maximum - minimum
        stable = len(values) >= self._min_samples and span <= self._span
        return StabilitySnapshot(minimum, maximum, span, stable)
