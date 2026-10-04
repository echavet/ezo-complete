"""Binary sensors: live-reading stability for calibration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EzoCoordinator
from .entity import EzoEntity
from .models import EzoDeviceState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoBinarySensorEntityDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[EzoDeviceState], bool]


SENSORS: tuple[EzoBinarySensorEntityDescription, ...] = (
    EzoBinarySensorEntityDescription(
        key="reading_stable",
        translation_key="reading_stable",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: s.reading_stable,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EzoBinarySensor(coordinator, desc) for desc in SENSORS)


class EzoBinarySensor(EzoEntity, BinarySensorEntity):
    entity_description: EzoBinarySensorEntityDescription

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, float | int | None]:
        data = self.coordinator.data
        return {
            "min": data.reading_min,
            "max": data.reading_max,
            "span": data.reading_span,
            "span_mv": data.stability_span_mv,
            "samples": data.stability_samples,
            "required_samples": data.stability_required,
            "span_threshold": data.stability_span_threshold,
            "threshold_mv": data.stability_span_threshold,
            "effective_window": data.stability_effective_window,
        }
