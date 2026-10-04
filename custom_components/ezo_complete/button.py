"""Buttons: calibration slots come from the probe profile.

Cal buttons are only available in Calibration mode and when stable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MODE_CALIBRATION
from .coordinator import EzoCoordinator
from .entity import EzoEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoButtonEntityDescription(ButtonEntityDescription):
    press_fn: Callable[[EzoCoordinator], Awaitable[None]]
    available_fn: Callable[[EzoCoordinator], bool] | None = None


def _cal_press(slot: str) -> Callable[[EzoCoordinator], Awaitable[None]]:
    async def _press(coordinator: EzoCoordinator) -> None:
        await coordinator.async_calibrate(slot)

    return _press


def _cal_available(slot: str) -> Callable[[EzoCoordinator], bool]:
    """Cal buttons require Calibration mode AND stable reading AND slot prerequisites."""

    def _available(coordinator: EzoCoordinator) -> bool:
        if coordinator.mode != MODE_CALIBRATION:
            return False
        return coordinator.profile.can_calibrate(
            slot,
            stable=bool(coordinator.data.reading_stable),
            cal_points=coordinator.data.cal_points,
        )

    return _available


SHARED_BUTTONS: tuple[EzoButtonEntityDescription, ...] = (
    EzoButtonEntityDescription(
        key="calibrate_clear",
        translation_key="calibrate_clear",
        press_fn=lambda c: c.async_calibrate_clear(),
        available_fn=lambda c: c.mode == MODE_CALIBRATION,
    ),
    EzoButtonEntityDescription(
        key="find",
        translation_key="find",
        press_fn=lambda c: c.async_find(),
    ),
    EzoButtonEntityDescription(
        key="export_calibration",
        translation_key="export_calibration",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.async_export_calibration(),
    ),
    EzoButtonEntityDescription(
        key="restore_calibration",
        translation_key="restore_calibration",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.async_restore_calibration(),
    ),
    EzoButtonEntityDescription(
        key="factory_reset",
        translation_key="factory_reset",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        press_fn=lambda c: c.async_factory_reset(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities = [
        EzoButton(
            coordinator,
            EzoButtonEntityDescription(
                key=slot.button_key,
                translation_key=slot.button_translation_key,
                press_fn=_cal_press(slot.key),
                available_fn=_cal_available(slot.key),
            ),
        )
        for slot in coordinator.profile.cal_slots
    ]
    entities.extend(EzoButton(coordinator, desc) for desc in SHARED_BUTTONS)
    async_add_entities(entities)


class EzoButton(EzoEntity, ButtonEntity):
    entity_description: EzoButtonEntityDescription

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        fn = self.entity_description.available_fn
        return True if fn is None else fn(self.coordinator)

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
