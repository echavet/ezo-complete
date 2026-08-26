"""pH EZO Complete profile."""

from __future__ import annotations

from ..const import (
    DEFAULT_PH_HIGH,
    DEFAULT_PH_LOW,
    DEFAULT_PH_MID,
    PH_RANGE_EXTENDED,
    PH_STABLE_SPAN,
)
from .base import CalSlot, ProbeProfile


class PhProfile(ProbeProfile):
    kind = "ph"
    model = "EZO Complete-pH"
    default_name = "EZO pH"
    reading_key = "ph"
    reading_unit = "pH"
    reading_precision = 3
    extended_command = "pHext"
    supports_temperature = True
    extra_diagnostics = ("temperature", "slope")
    max_cal_points = 3
    stability_span = PH_STABLE_SPAN
    cal_slots = (
        CalSlot(
            key="mid",
            button_key="calibrate_mid",
            button_translation_key="calibrate_mid",
            default=DEFAULT_PH_MID,
            unit="pH",
            minimum=PH_RANGE_EXTENDED[0],
            maximum=PH_RANGE_EXTENDED[1],
            step=0.01,
            number_key="ph_mid",
            number_translation_key="ph_mid",
        ),
        CalSlot(
            key="low",
            button_key="calibrate_low",
            button_translation_key="calibrate_low",
            default=DEFAULT_PH_LOW,
            unit="pH",
            minimum=PH_RANGE_EXTENDED[0],
            maximum=PH_RANGE_EXTENDED[1],
            step=0.01,
            requires_points=1,
            number_key="ph_low",
            number_translation_key="ph_low",
        ),
        CalSlot(
            key="high",
            button_key="calibrate_high",
            button_translation_key="calibrate_high",
            default=DEFAULT_PH_HIGH,
            unit="pH",
            minimum=PH_RANGE_EXTENDED[0],
            maximum=PH_RANGE_EXTENDED[1],
            step=0.01,
            requires_points=1,
            number_key="ph_high",
            number_translation_key="ph_high",
        ),
    )

    def cal_set_command(self, slot: str, value: float) -> str:
        point = slot.lower()
        if point not in {"mid", "low", "high"}:
            raise ValueError(f"pH calibration slot must be mid/low/high, not {slot}")
        return f"Cal,{point},{value:.2f}"

    def cal_label(self, cal_points: int | None) -> str | None:
        if cal_points is None:
            return None
        return {0: "none", 1: "one_point", 2: "two_point", 3: "three_point"}.get(
            cal_points, str(cal_points)
        )
