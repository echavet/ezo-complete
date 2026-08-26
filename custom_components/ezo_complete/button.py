"""Buttons."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_ORP_CALIBRATION
from .coordinator import EzoCoordinator
from .entity import EzoEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoButtonEntityDescription(ButtonEntityDescription):
    press_fn: Callable[[EzoCoordinator], Awaitable[None]]
    kinds: frozenset[str] | None = None
    available_fn: Callable[[EzoCoordinator], bool] | None = None


BUTTONS: tuple[EzoButtonEntityDescription, ...] = (
    EzoButtonEntityDescription(
        key="calibrate_225",
        translation_key="calibrate_225",
        kinds=frozenset({"orp"}),
        press_fn=lambda c: c.async_calibrate("custom", DEFAULT_ORP_CALIBRATION),
    ),
    EzoButtonEntityDescription(
        key="calibrate_custom",
        translation_key="calibrate_custom",
        kinds=frozenset({"orp"}),
        press_fn=lambda c: c.async_calibrate("custom", c.pending_orp_cal),
    ),
    EzoButtonEntityDescription(
        key="calibrate_mid",
        translation_key="calibrate_mid",
        kinds=frozenset({"ph"}),
        press_fn=lambda c: c.async_calibrate("mid", c.pending_ph_mid),
    ),
    EzoButtonEntityDescription(
        key="calibrate_low",
        translation_key="calibrate_low",
        kinds=frozenset({"ph"}),
        press_fn=lambda c: c.async_calibrate("low", c.pending_ph_low),
        available_fn=lambda c: (c.data.cal_points or 0) >= 1,
    ),
    EzoButtonEntityDescription(
        key="calibrate_high",
        translation_key="calibrate_high",
        kinds=frozenset({"ph"}),
        press_fn=lambda c: c.async_calibrate("high", c.pending_ph_high),
        available_fn=lambda c: (c.data.cal_points or 0) >= 1,
    ),
    EzoButtonEntityDescription(
        key="calibrate_clear",
        translation_key="calibrate_clear",
        press_fn=lambda c: c.async_calibrate_clear(),
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
    kind = coordinator.profile.kind
    async_add_entities(
        EzoButton(coordinator, desc)
        for desc in BUTTONS
        if desc.kinds is None or kind in desc.kinds
    )


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
