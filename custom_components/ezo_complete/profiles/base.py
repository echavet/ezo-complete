"""Abstract probe profile."""

from __future__ import annotations

from abc import ABC


class ProbeProfile(ABC):
    """Strategy: everything that differs between pH and ORP."""

    kind: str
    model: str
    default_name: str
    reading_key: str
    reading_unit: str
    extended_command: str
    supports_temperature: bool = False
    max_cal_points: int = 1

    def cal_set_command(self, slot: str, value: float) -> str:
        """UART command to store one calibration point."""
        raise NotImplementedError

    def diagnostic_queries(self) -> tuple[str, ...]:
        extra = (f"{self.extended_command},?",)
        if self.supports_temperature:
            extra = extra + ("T,?", "Slope,?")
        return ("C,?", "Cal,?", "L,?", "Status", "Name,?", "i") + extra
