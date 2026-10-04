"""Reading filter for EZO Complete (median, mean, or passthrough)."""

from __future__ import annotations

import statistics
from collections import deque

from .const import FILTER_MEAN, FILTER_MEDIAN, FILTER_NONE


class ReadingFilter:
    """Rolling window filter for pH/ORP readings."""

    def __init__(self, filter_type: str = FILTER_NONE, window: int = 5) -> None:
        self._type = filter_type
        self._window = max(1, window)
        self._buffer: deque[float] = deque(maxlen=self._window)

    @property
    def filter_type(self) -> str:
        return self._type

    @property
    def window_size(self) -> int:
        return self._window

    @property
    def sample_count(self) -> int:
        return len(self._buffer)

    def configure(self, filter_type: str, window: int) -> None:
        """Reconfigure the filter, clearing the buffer if settings change."""
        new_window = max(1, window)
        if self._type != filter_type or self._window != new_window:
            self._type = filter_type
            self._window = new_window
            self._buffer = deque(maxlen=new_window)

    def push(self, value: float) -> float:
        """Add a value and return the filtered result."""
        self._buffer.append(value)
        if self._type == FILTER_NONE or len(self._buffer) < 2:
            return value
        if self._type == FILTER_MEDIAN:
            return statistics.median(self._buffer)
        if self._type == FILTER_MEAN:
            return statistics.mean(self._buffer)
        return value

    def reset(self) -> None:
        """Clear the filter buffer."""
        self._buffer.clear()

    def last_raw(self) -> float | None:
        """Return the most recent raw value, or None if empty."""
        return self._buffer[-1] if self._buffer else None
