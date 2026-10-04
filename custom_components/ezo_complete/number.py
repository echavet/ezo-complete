"""Number entities: cal setpoints, calibration interval, and other config parameters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CALIBRATION_AUTO_RETURN_MAX,
    CALIBRATION_AUTO_RETURN_MIN,
    CONF_CALIBRATION_AUTO_RETURN,
    CONF_CONTINUOUS_INTERVAL,
    CONF_FILTER_WINDOW,
    CONF_MEASUREMENT_INTERVAL,
    CONF_STABILITY_MAX_SPAN,
    CONF_STABILITY_WINDOW,
    CONTINUOUS_INTERVAL_MAX,
    CONTINUOUS_INTERVAL_MIN,
    DEFAULT_CALIBRATION_AUTO_RETURN,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_FILTER_WINDOW,
    DEFAULT_MEASUREMENT_INTERVAL,
    DEFAULT_ORP_STABILITY_SPAN,
    DEFAULT_PH_STABILITY_SPAN_MV,
    DEFAULT_STABILITY_WINDOW,
    FILTER_WINDOW_MAX,
    FILTER_WINDOW_MIN,
    MEASUREMENT_INTERVAL_MAX,
    MEASUREMENT_INTERVAL_MIN,
    ORP_STABILITY_SPAN_MAX,
    ORP_STABILITY_SPAN_MIN,
    PH_STABILITY_SPAN_MV_MAX,
    PH_STABILITY_SPAN_MV_MIN,
    STABILITY_WINDOW_MAX,
    STABILITY_WINDOW_MIN,
)
from .coordinator import EzoCoordinator
from .entity import EzoEntity
from .profiles import CalSlot

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzoConfigNumberDescription(NumberEntityDescription):
    """Description for config-backed number entities."""

    option_key: str
    default_value: float
    set_fn: Callable[[EzoCoordinator, float], Awaitable[None]] | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EzoCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = []

    for slot in coordinator.profile.cal_slots:
        if slot.has_number:
            entities.append(EzoCalSetpointNumber(coordinator, slot))

    entities.append(EzoCalibrationIntervalNumber(coordinator))
    entities.append(EzoMeasurementIntervalNumber(coordinator))
    entities.append(EzoFilterWindowNumber(coordinator))
    entities.append(EzoStabilityWindowNumber(coordinator))
    entities.append(EzoStabilityMaxSpanNumber(coordinator))
    entities.append(EzoAutoReturnNumber(coordinator))

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


class EzoCalibrationIntervalNumber(EzoEntity, NumberEntity):
    """Calibration mode continuous interval (C,n seconds).

    NOTE: Entity key is 'continuous_interval' for unique_id stability.
    Display name uses translation_key 'calibration_interval'.
    """

    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="continuous_interval",
                translation_key="calibration_interval",
                entity_category=EntityCategory.CONFIG,
                native_min_value=CONTINUOUS_INTERVAL_MIN,
                native_max_value=CONTINUOUS_INTERVAL_MAX,
                native_step=1,
                native_unit_of_measurement="s",
                mode=NumberMode.BOX,
            ),
        )

    @property
    def native_value(self) -> float:
        return float(self.coordinator.calibration_interval)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_calibration_interval(int(value))


class EzoMeasurementIntervalNumber(EzoEntity, NumberEntity):
    """Exploitation mode polling interval."""

    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="measurement_interval",
                translation_key="measurement_interval",
                entity_category=EntityCategory.CONFIG,
                native_min_value=MEASUREMENT_INTERVAL_MIN,
                native_max_value=MEASUREMENT_INTERVAL_MAX,
                native_step=1,
                native_unit_of_measurement="s",
                mode=NumberMode.SLIDER,
            ),
        )

    @property
    def native_value(self) -> float:
        return float(self.coordinator.measurement_interval)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._update_options({CONF_MEASUREMENT_INTERVAL: int(value)})


class EzoFilterWindowNumber(EzoEntity, NumberEntity):
    """Filter window size (number of samples for median/mean)."""

    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="filter_window",
                translation_key="filter_window",
                entity_category=EntityCategory.CONFIG,
                native_min_value=FILTER_WINDOW_MIN,
                native_max_value=FILTER_WINDOW_MAX,
                native_step=1,
                mode=NumberMode.BOX,
            ),
        )

    @property
    def native_value(self) -> float:
        return float(self.coordinator.filter_window)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._update_options({CONF_FILTER_WINDOW: int(value)})


class EzoStabilityWindowNumber(EzoEntity, NumberEntity):
    """Stability window duration (seconds)."""

    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="stability_window",
                translation_key="stability_window",
                entity_category=EntityCategory.CONFIG,
                native_min_value=STABILITY_WINDOW_MIN,
                native_max_value=STABILITY_WINDOW_MAX,
                native_step=1,
                native_unit_of_measurement="s",
                mode=NumberMode.SLIDER,
            ),
        )

    @property
    def native_value(self) -> float:
        return float(self.coordinator.stability_window)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._update_options({CONF_STABILITY_WINDOW: float(value)})


class EzoStabilityMaxSpanNumber(EzoEntity, NumberEntity):
    """Stability max span threshold (mV)."""

    def __init__(self, coordinator: EzoCoordinator) -> None:
        kind = coordinator.profile.kind
        if kind == "ph":
            min_val = PH_STABILITY_SPAN_MV_MIN
            max_val = PH_STABILITY_SPAN_MV_MAX
            default = DEFAULT_PH_STABILITY_SPAN_MV
        else:
            min_val = ORP_STABILITY_SPAN_MIN
            max_val = ORP_STABILITY_SPAN_MAX
            default = DEFAULT_ORP_STABILITY_SPAN

        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="stability_max_span",
                translation_key="stability_max_span",
                entity_category=EntityCategory.CONFIG,
                native_min_value=min_val,
                native_max_value=max_val,
                native_step=0.1,
                native_unit_of_measurement="mV",
                mode=NumberMode.BOX,
            ),
        )
        self._default = default

    @property
    def native_value(self) -> float:
        return float(self.coordinator.stability_max_span)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._update_options({CONF_STABILITY_MAX_SPAN: float(value)})


class EzoAutoReturnNumber(EzoEntity, NumberEntity):
    """Auto-return timer (minutes, 0 = disabled)."""

    def __init__(self, coordinator: EzoCoordinator) -> None:
        super().__init__(
            coordinator,
            NumberEntityDescription(
                key="calibration_auto_return",
                translation_key="calibration_auto_return",
                entity_category=EntityCategory.CONFIG,
                native_min_value=CALIBRATION_AUTO_RETURN_MIN,
                native_max_value=CALIBRATION_AUTO_RETURN_MAX,
                native_step=1,
                native_unit_of_measurement="min",
                mode=NumberMode.BOX,
            ),
        )

    @property
    def native_value(self) -> float:
        return float(self.coordinator.calibration_auto_return)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator._update_options({CONF_CALIBRATION_AUTO_RETURN: int(value)})
