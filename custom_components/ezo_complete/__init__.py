"""EZO Complete (pH + ORP) Home Assistant integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import EzoCoordinator

_LOGGER = logging.getLogger(__name__)

type EzoConfigEntry = ConfigEntry[EzoCoordinator]

_DEVICE_SCHEMA = {vol.Required(CONF_DEVICE_ID): cv.string}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def _coordinator_from_call(call: ServiceCall) -> EzoCoordinator:
        device_id = call.data[CONF_DEVICE_ID]
        registry = dr.async_get(hass)
        device = registry.async_get(device_id)
        if device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_device"
            )
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN:
                return entry.runtime_data
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="unknown_device"
        )

    async def handle_send_command(call: ServiceCall) -> None:
        await (await _coordinator_from_call(call)).async_send_raw(call.data["command"])

    async def handle_factory_reset(call: ServiceCall) -> None:
        if not call.data.get("confirm"):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="factory_not_confirmed"
            )
        await (await _coordinator_from_call(call)).async_factory_reset(confirm=True)

    async def handle_export(call: ServiceCall) -> ServiceResponse:
        coordinator = await _coordinator_from_call(call)
        payload = await coordinator.async_export_calibration()
        return {
            "payload": payload,
            "path": coordinator.data.export_path,
            "restore_path": coordinator.data.restore_path,
            "exported_at": coordinator.data.export_at,
            "lines": payload.splitlines(),
        }

    async def handle_import(call: ServiceCall) -> None:
        await (await _coordinator_from_call(call)).async_import_calibration(
            call.data["payload"]
        )

    async def handle_restore(call: ServiceCall) -> ServiceResponse:
        coordinator = await _coordinator_from_call(call)
        payload = await coordinator.async_restore_calibration()
        return {"payload": payload, "path": coordinator.data.restore_path}

    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command,
        schema=vol.Schema({**_DEVICE_SCHEMA, vol.Required("command"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "factory_reset", handle_factory_reset,
        schema=vol.Schema({**_DEVICE_SCHEMA, vol.Required("confirm"): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, "export_calibration", handle_export,
        schema=vol.Schema(_DEVICE_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "import_calibration", handle_import,
        schema=vol.Schema({**_DEVICE_SCHEMA, vol.Required("payload"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "restore_calibration", handle_restore,
        schema=vol.Schema(_DEVICE_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EzoConfigEntry) -> bool:
    coordinator = EzoCoordinator(hass, entry)
    try:
        await coordinator.async_setup()
        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, Exception):
        await coordinator.async_shutdown()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_sync_device_name()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info(
        "EZO Complete ready: kind=%s port=%s serial=%s fw=%s",
        coordinator.profile.kind,
        coordinator.session.port,
        coordinator.data.serial_number,
        coordinator.data.firmware,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EzoConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
