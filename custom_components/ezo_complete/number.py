"""Number entities: cal setpoints from the probe profile, continuous interval."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONTINUOUS_INTERVAL_MAX, CONTINUOUS_INTERVAL_MIN
from .coordinator import EzoCoordinator
from .entity import EzoEntity
from .profiles import CalSlot

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [EzoContinuousIntervalNumber(coordinator)]
    entities.extend(
        EzoCalSetpointNumber(coordinator, slot)
        for slot in coordinator.profile.cal_slots
        if slot.has_number
    )
    async_add_entities(entities)


class EzoCalSetpointNumber(EzoEntity, RestoreEntity, NumberEntity):
    """HA-side buffer setpoint, sent only when the matching Cal button is pressed."""

    def __init__(self, coordinator: EzoCoordinator, slot: CalSlot) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key=slot.number_key or slot.key,
                translation_key=slot.number_translation_key or slot.key,
                native_min_value=slot.minimum,
                native_max_value=slot.maximum,
                native_step=slot.step,
                native_unit_of_measurement=slot.unit,
                mode=NumberMode.BOX,
            ),
        )
        self._slot = slot.key
        self._attr_native_value = coordinator.cal_setpoint(slot.key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._attr_native_value = float(last.state)
            except (TypeError, ValueError):
                pass
        if self._attr_native_value is not None:
            self.coordinator.set_cal_setpoint(self._slot, float(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.coordinator.set_cal_setpoint(self._slot, value)
        self.async_write_ha_state()


class EzoContinuousIntervalNumber(EzoEntity, NumberEntity):
    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="continuous_interval",
                translation_key="continuous_interval",
                entity_category=EntityCategory.CONFIG,
                native_min_value=CONTINUOUS_INTERVAL_MIN,
                native_max_value=CONTINUOUS_INTERVAL_MAX,
                native_step=1,
                native_unit_of_measurement="s",
                mode=NumberMode.BOX,
            ),
        )

    @property
    def native_value(self) -> float | None:
        interval = self.coordinator.data.continuous_interval
        return float(interval) if interval is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_continuous_interval(int(value))
