"""Probe profile: cal slots, sensors, stability — not UART I/O."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..codec import ParsedLine, parse_flag, parse_slope, parse_temperature
from ..models import EzoDeviceState
from ..validation import is_valid_slope, is_valid_temperature

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalSlot:
    """One calibration action (button) and optional HA number setpoint."""

    key: str
    button_key: str
    button_translation_key: str
    default: float
    unit: str
    minimum: float
    maximum: float
    step: float
    requires_points: int = 0
    number_key: str | None = None
    number_translation_key: str | None = None
    fixed_value: float | None = None

    @property
    def has_number(self) -> bool:
        return self.number_key is not None and self.fixed_value is None


class ProbeProfile(ABC):
    kind: str
    model: str
    default_name: str
    reading_key: str
    reading_unit: str
    reading_precision: int = 1
    extended_command: str
    supports_temperature: bool = False
    extra_diagnostics: tuple[str, ...] = ()
    max_cal_points: int = 1
    stability_span: float = 0.05
    cal_slots: tuple[CalSlot, ...] = ()

    @abstractmethod
    def cal_set_command(self, slot: str, value: float) -> str:
        """UART command to store one calibration point."""

    def slot(self, key: str) -> CalSlot | None:
        for item in self.cal_slots:
            if item.key == key:
                return item
        return None

    def can_calibrate(self, slot: str, *, stable: bool, cal_points: int | None) -> bool:
        spec = self.slot(slot)
        if spec is None or not stable:
            return False
        return (cal_points or 0) >= spec.requires_points

    def cal_label(self, cal_points: int | None) -> str | None:
        if cal_points is None:
            return None
        return "calibrated" if cal_points else "not_calibrated"

    def reading_attributes(self, state: EzoDeviceState) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "source": state.reading_source,
            "stable": state.reading_stable,
            "span": state.reading_span,
            "min": state.reading_min,
            "max": state.reading_max,
            "cal_points": state.cal_points,
            "extended_scale": state.extended_scale,
        }
        if self.supports_temperature:
            attrs["temperature"] = state.temperature
            attrs["slope_acid"] = state.slope_acid
            attrs["slope_base"] = state.slope_base
            attrs["slope_offset"] = state.slope_offset
        return attrs

    def apply_query(self, state: EzoDeviceState, line: ParsedLine) -> bool:
        """Handle a probe-specific `?Key` line. Return True if consumed.
        
        Validates all numeric values; out-of-range values are rejected and
        increment state.rejected_readings.
        """
        key = (line.query_key or "").lower()
        if key == self.extended_command.lower():
            flag = parse_flag(line.raw, key)
            if flag is not None:
                state.extended_scale = flag
            return True
        if not self.supports_temperature:
            return False
        if key == "t":
            temp = parse_temperature(line.raw)
            if temp is not None:
                if is_valid_temperature(temp):
                    state.temperature = temp
                else:
                    _LOGGER.debug(
                        "Temperature %s out of range [-5, 60], rejected (counter=%d)",
                        temp,
                        state.rejected_readings + 1,
                    )
                    state.rejected_readings += 1
            return True
        if key == "slope":
            slope = parse_slope(line.raw)
            if slope:
                try:
                    acid_val = float(slope[0])
                    if is_valid_slope(acid_val):
                        state.slope_acid = slope[0]
                    else:
                        _LOGGER.debug(
                            "Slope acid %s out of range [0, 200], rejected",
                            acid_val,
                        )
                        state.rejected_readings += 1
                except (ValueError, TypeError):
                    state.rejected_readings += 1
                
                if len(slope) > 1:
                    try:
                        base_val = float(slope[1])
                        if is_valid_slope(base_val):
                            state.slope_base = slope[1]
                        else:
                            _LOGGER.debug(
                                "Slope base %s out of range [0, 200], rejected",
                                base_val,
                            )
                            state.rejected_readings += 1
                    except (ValueError, TypeError):
                        state.rejected_readings += 1
                else:
                    state.slope_base = None
                
                state.slope_offset = slope[2] if len(slope) > 2 else None
            return True
        return False

    def diagnostic_queries(self) -> tuple[str, ...]:
        extra = (f"{self.extended_command},?",)
        if self.supports_temperature:
            extra = extra + ("T,?", "Slope,?")
        return ("Cal,?", "L,?", "Status", "Name,?", "i") + extra
