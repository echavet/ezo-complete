"""Number entities: cal setpoints, continuous interval."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONTINUOUS_INTERVAL_MAX,
    CONTINUOUS_INTERVAL_MIN,
    DEFAULT_ORP_CALIBRATION,
    DEFAULT_PH_HIGH,
    DEFAULT_PH_LOW,
    DEFAULT_PH_MID,
    ORP_RANGE_EXTENDED,
    PH_RANGE_EXTENDED,
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
    kind = coordinator.profile.kind
    entities: list[NumberEntity] = [EzoContinuousIntervalNumber(coordinator)]
    if kind == "orp":
        entities.append(
            EzoLocalNumber(
                coordinator,
                NumberEntityDescription(
                    key="calibration_value",
                    translation_key="calibration_value",
                    native_min_value=ORP_RANGE_EXTENDED[0],
                    native_max_value=ORP_RANGE_EXTENDED[1],
                    native_step=1,
                    native_unit_of_measurement="mV",
                    mode=NumberMode.BOX,
                ),
                default=DEFAULT_ORP_CALIBRATION,
                attr="pending_orp_cal",
            )
        )
    else:
        entities.extend(
            [
                EzoLocalNumber(
                    coordinator,
                    NumberEntityDescription(
                        key="ph_mid",
                        translation_key="ph_mid",
                        native_min_value=PH_RANGE_EXTENDED[0],
                        native_max_value=PH_RANGE_EXTENDED[1],
                        native_step=0.01,
                        native_unit_of_measurement="pH",
                        mode=NumberMode.BOX,
                    ),
                    default=DEFAULT_PH_MID,
                    attr="pending_ph_mid",
                ),
                EzoLocalNumber(
                    coordinator,
                    NumberEntityDescription(
                        key="ph_low",
                        translation_key="ph_low",
                        native_min_value=PH_RANGE_EXTENDED[0],
                        native_max_value=PH_RANGE_EXTENDED[1],
                        native_step=0.01,
                        native_unit_of_measurement="pH",
                        mode=NumberMode.BOX,
                    ),
                    default=DEFAULT_PH_LOW,
                    attr="pending_ph_low",
                ),
                EzoLocalNumber(
                    coordinator,
                    NumberEntityDescription(
                        key="ph_high",
                        translation_key="ph_high",
                        native_min_value=PH_RANGE_EXTENDED[0],
                        native_max_value=PH_RANGE_EXTENDED[1],
                        native_step=0.01,
                        native_unit_of_measurement="pH",
                        mode=NumberMode.BOX,
                    ),
                    default=DEFAULT_PH_HIGH,
                    attr="pending_ph_high",
                ),
            ]
        )
    async_add_entities(entities)


class EzoLocalNumber(EzoEntity, RestoreEntity, NumberEntity):
    """HA-side setpoint, sent only when the matching Cal button is pressed."""

    def __init__(
        self,
        coordinator: EzoCoordinator,
        description: NumberEntityDescription,
        *,
        default: float,
        attr: str,
    ) -> None:
        super().__init__(coordinator, description)
        self._attr_native_value = default
        self._attr_name_key = attr
        self._store_attr = attr

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._attr_native_value = float(last.state)
            except (TypeError, ValueError):
                pass
        if self._attr_native_value is not None:
            setattr(self.coordinator, self._store_attr, float(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        setattr(self.coordinator, self._store_attr, value)
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
