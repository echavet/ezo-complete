"""Runtime snapshot for one EZO Complete stick."""

from __future__ import annotations

from dataclasses import dataclass, field


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

    def copy(self) -> EzoDeviceState:
        return EzoDeviceState(
            kind=self.kind,
            reading=self.reading,
            continuous=self.continuous,
            continuous_interval=self.continuous_interval,
            led=self.led,
            cal_points=self.cal_points,
            firmware=self.firmware,
            device_type=self.device_type,
            device_name=self.device_name,
            status_reason=self.status_reason,
            status_reason_code=self.status_reason_code,
            status_voltage=self.status_voltage,
            extended_scale=self.extended_scale,
            temperature=self.temperature,
            slope_acid=self.slope_acid,
            slope_base=self.slope_base,
            sleeping=self.sleeping,
            last_raw=self.last_raw,
            last_lines=list(self.last_lines),
            export_data=self.export_data,
            export_at=self.export_at,
            export_path=self.export_path,
            restore_path=self.restore_path,
            factory_armed=self.factory_armed,
            port=self.port,
            baudrate=self.baudrate,
            serial_number=self.serial_number,
        )
