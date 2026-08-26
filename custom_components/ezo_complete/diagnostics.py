"""Diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import EzoCoordinator

TO_REDACT = {"serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[EzoCoordinator]
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    state = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connected": coordinator.session.connected,
        "profile": coordinator.profile.kind,
        "last_update_success": coordinator.last_update_success,
        "device": {
            "port": state.port,
            "kind": state.kind,
            "reading": state.reading,
            "firmware": state.firmware,
            "cal_points": state.cal_points,
            "temperature": state.temperature,
            "export_path": state.export_path,
            "restore_path": state.restore_path,
            "export_data": state.export_data,
        },
        "last_raw_lines": list(state.last_lines),
    }
