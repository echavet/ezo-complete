"""Device registry helpers (compat with HA < 2026.8)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


def async_get_entry_device(
    hass: HomeAssistant, config_entry_id: str, unique_id: str
) -> dr.DeviceEntry | None:
    """Return this config entry's device identified by (DOMAIN, unique_id).

    HA 2026.8 added DeviceRegistry.async_get_device_by_identifier(identifier,
    config_entry_id); HA 2026.9 deprecated async_get_device (removed in 2027.8).
    Fall back to async_get_device on older cores (hacs.json minimum is 2026.5.0).
    """
    registry = dr.async_get(hass)
    identifier = (DOMAIN, unique_id)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, config_entry_id)
    return registry.async_get_device(identifiers={identifier})
