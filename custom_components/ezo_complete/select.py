"""Select entities: operating mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODE,
    DEFAULT_MODE,
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
    async_add_entities([EzoModeSelect(coordinator)])


class EzoModeSelect(EzoEntity, SelectEntity):
    """Select entity for operating mode (Exploitation / Calibration)."""

    entity_description = SelectEntityDescription(
        key="mode",
        translation_key="mode",
        entity_category=EntityCategory.CONFIG,
        options=[MODE_EXPLOITATION, MODE_CALIBRATION],
    )

    _attr_icon = "mdi:tune-vertical"

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option)
        self._update_icon()

    def _update_icon(self) -> None:
        if self.coordinator.mode == MODE_CALIBRATION:
            self._attr_icon = "mdi:flask"
        else:
            self._attr_icon = "mdi:tune-vertical"

    @property
    def icon(self) -> str:
        if self.coordinator.mode == MODE_CALIBRATION:
            return "mdi:flask"
        return "mdi:tune-vertical"
