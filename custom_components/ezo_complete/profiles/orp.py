"""ORP (redox) EZO Complete profile."""

from __future__ import annotations

from ..const import DEFAULT_ORP_CALIBRATION, ORP_RANGE_EXTENDED, ORP_STABLE_SPAN
from .base import CalSlot, ProbeProfile


class OrpProfile(ProbeProfile):
    kind = "orp"
    model = "EZO Complete-ORP"
    default_name = "EZO ORP"
    reading_key = "orp"
    reading_unit = "mV"
    reading_precision = 1
    extended_command = "ORPext"
    supports_temperature = False
    max_cal_points = 1
    stability_span = ORP_STABLE_SPAN
    cal_slots = (
        CalSlot(
            key="225",
            button_key="calibrate_225",
            button_translation_key="calibrate_225",
            default=DEFAULT_ORP_CALIBRATION,
            unit="mV",
            minimum=ORP_RANGE_EXTENDED[0],
            maximum=ORP_RANGE_EXTENDED[1],
            step=1,
            fixed_value=DEFAULT_ORP_CALIBRATION,
        ),
        CalSlot(
            key="custom",
            button_key="calibrate_custom",
            button_translation_key="calibrate_custom",
            default=DEFAULT_ORP_CALIBRATION,
            unit="mV",
            minimum=ORP_RANGE_EXTENDED[0],
            maximum=ORP_RANGE_EXTENDED[1],
            step=1,
            number_key="calibration_value",
            number_translation_key="calibration_value",
        ),
    )

    def cal_set_command(self, slot: str, value: float) -> str:
        return f"Cal,{int(round(value))}"
