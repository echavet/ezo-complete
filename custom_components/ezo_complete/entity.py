"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import EzoCoordinator


class EzoEntity(CoordinatorEntity[EzoCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: EzoCoordinator,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.unique_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.profile.model,
            name=coordinator.device_name,
            sw_version=coordinator.data.firmware,
            serial_number=coordinator.entry.data.get("serial_number"),
            configuration_url="https://atlas-scientific.com/",
        )

    @property
    def suggested_object_id(self) -> str:
        """Return consistent object_id independent of device name.
        
        This ensures entity_ids like `sensor.ezo_ph_ph` instead of
        `sensor.piscine_ezo_ph_ph` when the device is renamed.
        """
        kind = self.coordinator.profile.kind
        key = self.entity_description.key
        return f"ezo_{kind}_{key}"
