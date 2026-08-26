"""Sensors: reading + diagnostics, shaped by the probe profile."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import EzoCoordinator
from .entity import EzoEntity
from .models import EzoDeviceState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[EzoDeviceState], StateType]
    extra_fn: Callable[[EzoDeviceState], dict[str, Any]] | None = None
    kinds: frozenset[str] | None = None


def _cal_label(state: EzoDeviceState) -> str | None:
    if state.cal_points is None:
        return None
    if state.kind == "ph":
        return {0: "none", 1: "one_point", 2: "two_point", 3: "three_point"}.get(
            state.cal_points, str(state.cal_points)
        )
    return "calibrated" if state.cal_points else "not_calibrated"


SENSORS: tuple[EzoSensorEntityDescription, ...] = (
    EzoSensorEntityDescription(
        key="orp",
        translation_key="orp",
        kinds=frozenset({"orp"}),
        native_unit_of_measurement="mV",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.reading,
        extra_fn=lambda s: {
            "source": s.reading_source,
            "stable": s.reading_stable,
            "span": s.reading_span,
            "min": s.reading_min,
            "max": s.reading_max,
            "cal_points": s.cal_points,
            "extended_scale": s.extended_scale,
        },
    ),
    EzoSensorEntityDescription(
        key="ph",
        translation_key="ph",
        kinds=frozenset({"ph"}),
        native_unit_of_measurement="pH",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda s: s.reading,
        extra_fn=lambda s: {
            "source": s.reading_source,
            "stable": s.reading_stable,
            "span": s.reading_span,
            "min": s.reading_min,
            "max": s.reading_max,
            "cal_points": s.cal_points,
            "temperature": s.temperature,
            "slope_acid": s.slope_acid,
            "slope_base": s.slope_base,
        },
    ),
    EzoSensorEntityDescription(
        key="temperature",
        translation_key="compensation_temperature",
        kinds=frozenset({"ph"}),
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s.temperature,
    ),
    EzoSensorEntityDescription(
        key="slope",
        translation_key="slope",
        kinds=frozenset({"ph"}),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            f"{s.slope_acid},{s.slope_base}" if s.slope_acid and s.slope_base else s.slope_acid
        ),
    ),
    EzoSensorEntityDescription(
        key="status_reason",
        translation_key="status_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["power", "software", "brownout", "watchdog", "unknown"],
        value_fn=lambda s: s.status_reason,
        extra_fn=lambda s: {"code": s.status_reason_code},
    ),
    EzoSensorEntityDescription(
        key="status_voltage",
        translation_key="status_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=3,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.status_voltage,
    ),
    EzoSensorEntityDescription(
        key="calibration_state",
        translation_key="calibration_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cal_label,
        extra_fn=lambda s: {"points": s.cal_points, "reading": s.reading},
    ),
    EzoSensorEntityDescription(
        key="calibration_export",
        translation_key="calibration_export",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.export_at,
        extra_fn=lambda s: {
            "payload": s.export_data,
            "archive_path": s.export_path,
            "restore_path": s.restore_path,
        },
    ),
    EzoSensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.firmware,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    kind = coordinator.profile.kind
    async_add_entities(
        EzoSensor(coordinator, desc)
        for desc in SENSORS
        if desc.kinds is None or kind in desc.kinds
    )


class EzoSensor(EzoEntity, SensorEntity):
    entity_description: EzoSensorEntityDescription

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        extra_fn = self.entity_description.extra_fn
        return extra_fn(self.coordinator.data) if extra_fn else None
