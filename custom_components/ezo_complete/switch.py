"""Switches: LED, Sleep, Extended scale (no more continuous - replaced by mode select)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EzoCoordinator
from .entity import EzoEntity
from .models import EzoDeviceState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoSwitchEntityDescription(SwitchEntityDescription):
    is_on_fn: Callable[[EzoDeviceState], bool | None]
    turn_on_fn: Callable[[EzoCoordinator], Awaitable[None]]
    turn_off_fn: Callable[[EzoCoordinator], Awaitable[None]]


SWITCHES: tuple[EzoSwitchEntityDescription, ...] = (
    EzoSwitchEntityDescription(
        key="led",
        translation_key="led",
        is_on_fn=lambda s: s.led,
        turn_on_fn=lambda c: c.async_set_led(True),
        turn_off_fn=lambda c: c.async_set_led(False),
    ),
    EzoSwitchEntityDescription(
        key="sleep",
        translation_key="sleep",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: s.sleeping,
        turn_on_fn=lambda c: c.async_set_sleeping(True),
        turn_off_fn=lambda c: c.async_set_sleeping(False),
    ),
    EzoSwitchEntityDescription(
        key="extended_scale",
        translation_key="extended_scale",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda s: s.extended_scale,
        turn_on_fn=lambda c: c.async_set_extended(True),
        turn_off_fn=lambda c: c.async_set_extended(False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EzoSwitch(coordinator, desc) for desc in SWITCHES)


class EzoSwitch(EzoEntity, SwitchEntity):
    entity_description: EzoSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.entity_description.turn_on_fn(self.coordinator)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.entity_description.turn_off_fn(self.coordinator)
