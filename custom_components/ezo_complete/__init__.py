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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .codec import unique_id_from_serial
from .const import CONF_DEVICE_TYPE, CONF_SERIAL_NUMBER, DOMAIN, PLATFORMS
from .coordinator import EzoCoordinator

_LOGGER = logging.getLogger(__name__)

type EzoConfigEntry = ConfigEntry[EzoCoordinator]

_DEVICE_SCHEMA = {vol.Required(CONF_DEVICE_ID): cv.string}


def async_migrate_unique_id(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    old_unique_id: str,
    new_unique_id: str,
) -> None:
    """Migrate device and entity registry entries when unique_id changes.

    This updates:
    - Device registry: changes device identifiers from old to new unique_id
    - Entity registry: updates entity unique_ids that start with old_unique_id

    Used by both config entry migration and USB discovery adoption.
    """
    if old_unique_id == new_unique_id:
        return

    _LOGGER.info(
        "Entry %s: migrating unique_id %s -> %s",
        config_entry.entry_id,
        old_unique_id,
        new_unique_id,
    )

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    old_device = dev_reg.async_get_device(identifiers={(DOMAIN, old_unique_id)})
    if old_device:
        _LOGGER.debug(
            "Updating device %s identifiers: %s -> %s",
            old_device.id,
            old_unique_id,
            new_unique_id,
        )
        dev_reg.async_update_device(
            old_device.id,
            new_identifiers={(DOMAIN, new_unique_id)},
        )

    for entity in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id):
        if entity.unique_id.startswith(f"{old_unique_id}_"):
            new_entity_unique_id = entity.unique_id.replace(
                f"{old_unique_id}_", f"{new_unique_id}_", 1
            )
            _LOGGER.info(
                "Migrating entity %s: %s -> %s",
                entity.entity_id,
                entity.unique_id,
                new_entity_unique_id,
            )
            ent_reg.async_update_entity(
                entity.entity_id, new_unique_id=new_entity_unique_id
            )


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to new version.

    Version 2.1: unique_id normalization for USB serial stability.
    - Ensures unique_id matches the pattern {serial}_{kind}
    - Migrates entity unique_ids if the entry unique_id changes
    """
    if config_entry.version > 2:
        _LOGGER.warning(
            "Cannot downgrade entry %s from version %s.%s",
            config_entry.entry_id,
            config_entry.version,
            config_entry.minor_version,
        )
        return False

    if config_entry.version == 1:
        _LOGGER.info("Migrating entry %s from version 1 to 2.1", config_entry.entry_id)
        serial = config_entry.data.get(CONF_SERIAL_NUMBER) or "unknown"
        kind = (config_entry.data.get(CONF_DEVICE_TYPE) or "orp").lower()
        new_unique_id = unique_id_from_serial(serial, kind)
        old_unique_id = config_entry.unique_id

        if old_unique_id and old_unique_id != new_unique_id:
            async_migrate_unique_id(hass, config_entry, old_unique_id, new_unique_id)

        hass.config_entries.async_update_entry(
            config_entry,
            unique_id=new_unique_id,
            version=2,
            minor_version=1,
        )

    return True


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
