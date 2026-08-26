"""pH EZO Complete profile."""

from __future__ import annotations

from .base import ProbeProfile


class PhProfile(ProbeProfile):
    kind = "ph"
    model = "EZO Complete-pH"
    default_name = "EZO pH"
    reading_key = "ph"
    reading_unit = "pH"
    extended_command = "pHext"
    supports_temperature = True
    max_cal_points = 3

    def cal_set_command(self, slot: str, value: float) -> str:
        point = slot.lower()
        if point not in {"mid", "low", "high"}:
            raise ValueError(f"pH calibration slot must be mid/low/high, not {slot}")
        return f"Cal,{point},{value:.2f}"
