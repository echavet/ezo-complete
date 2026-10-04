"""Select entities: operating mode and filter type."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_FILTER_TYPE,
    FILTER_MEAN,
    FILTER_MEDIAN,
    FILTER_NONE,
    MODE_CALIBRATION,
    MODE_EXPLOITATION,
)
from .coordinator import EzoCoordinator
from .entity import EzoEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([
        EzoModeSelect(coordinator),
        EzoFilterTypeSelect(coordinator),
    ])


class EzoModeSelect(EzoEntity, SelectEntity):
    """Select entity for operating mode (Exploitation / Calibration)."""

    entity_description = SelectEntityDescription(
        key="mode",
        translation_key="mode",
        entity_category=EntityCategory.CONFIG,
        options=[MODE_EXPLOITATION, MODE_CALIBRATION],
    )

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    @property
    def icon(self) -> str:
        if self.coordinator.mode == MODE_CALIBRATION:
            return "mdi:flask"
        return "mdi:tune-vertical"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)


class EzoFilterTypeSelect(EzoEntity, SelectEntity):
    """Select entity for reading filter type."""

    entity_description = SelectEntityDescription(
        key="filter_type",
        translation_key="filter_type",
        entity_category=EntityCategory.CONFIG,
        options=[FILTER_NONE, FILTER_MEDIAN, FILTER_MEAN],
    )

    @property
    def current_option(self) -> str:
        return self.coordinator.filter_type

    async def async_select_option(self, option: str) -> None:
        await self.coordinator._update_options({CONF_FILTER_TYPE: option})
