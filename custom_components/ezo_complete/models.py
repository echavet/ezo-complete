"""Runtime snapshot for one EZO Complete stick."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(slots=True)
class EzoDeviceState:
    kind: str | None = None  # "orp" | "ph"
    reading: float | None = None
    continuous: bool | None = None
    continuous_interval: int | None = None
    led: bool | None = None
    cal_points: int | None = None
    firmware: str | None = None
    device_type: str | None = None
    device_name: str | None = None
    status_reason: str | None = None
    status_reason_code: str | None = None
    status_voltage: float | None = None
    extended_scale: bool | None = None
    temperature: float | None = None
    slope_acid: str | None = None
    slope_base: str | None = None
    sleeping: bool = False
    last_raw: str | None = None
    last_lines: list[str] = field(default_factory=list)
    export_data: str | None = None
    export_at: str | None = None
    export_path: str | None = None
    restore_path: str | None = None
    factory_armed: bool = False
    port: str | None = None
    baudrate: int | None = None
    serial_number: str | None = None
    reading_min: float | None = None
    reading_max: float | None = None
    reading_span: float | None = None
    reading_stable: bool = False
    reading_source: str | None = None  # "factory" | "calibrated"

    def copy(self) -> EzoDeviceState:
        return replace(self, last_lines=list(self.last_lines))
