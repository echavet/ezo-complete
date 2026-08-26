"""ORP (redox) EZO Complete profile."""

from __future__ import annotations

from .base import ProbeProfile


class OrpProfile(ProbeProfile):
    kind = "orp"
    model = "EZO Complete-ORP"
    default_name = "EZO ORP"
    reading_key = "orp"
    reading_unit = "mV"
    extended_command = "ORPext"
    supports_temperature = False
    max_cal_points = 1

    def cal_set_command(self, slot: str, value: float) -> str:
        return f"Cal,{int(round(value))}"
