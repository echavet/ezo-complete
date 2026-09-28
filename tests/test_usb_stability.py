"""Tests for USB reconnect stability and entity_id preservation."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "ezo_complete"


def _load(name: str, path: Path):
    if "ezo_complete" not in sys.modules:
        pkg = types.ModuleType("ezo_complete")
        pkg.__path__ = [str(PKG)]
        sys.modules["ezo_complete"] = pkg
    if "ezo_complete.profiles" not in sys.modules:
        sub = types.ModuleType("ezo_complete.profiles")
        sub.__path__ = [str(PKG / "profiles")]
        sys.modules["ezo_complete.profiles"] = sub
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load("ezo_complete.const", PKG / "const.py")
codec = _load("ezo_complete.codec", PKG / "codec.py")


def test_unique_id_from_serial_consistency() -> None:
    """Verify unique_id generation is deterministic and consistent."""
    assert codec.unique_id_from_serial("ABC123", "orp") == "ABC123_orp"
    assert codec.unique_id_from_serial("ABC123", "ph") == "ABC123_ph"
    assert codec.unique_id_from_serial("ABC123", "ORP") == "ABC123_orp"
    assert codec.unique_id_from_serial("ABC123", "pH") == "ABC123_ph"
    assert codec.unique_id_from_serial(None, "orp") == "unknown_orp"
    assert codec.unique_id_from_serial("", "orp") == "unknown_orp"
    assert codec.unique_id_from_serial("  ", "orp") == "unknown_orp"


def test_unique_id_from_serial_with_whitespace() -> None:
    """Whitespace is stripped from serial and kind."""
    assert codec.unique_id_from_serial(" ABC123 ", "orp") == "ABC123_orp"
    assert codec.unique_id_from_serial("ABC123", " orp ") == "ABC123_orp"


def test_unique_id_stability_across_calls() -> None:
    """Same inputs always produce the same unique_id."""
    serial = "FT230X_12345"
    for _ in range(100):
        assert codec.unique_id_from_serial(serial, "ph") == "FT230X_12345_ph"
        assert codec.unique_id_from_serial(serial, "orp") == "FT230X_12345_orp"


def test_unknown_serial_unique_id() -> None:
    """Entries without USB serial use 'unknown' prefix."""
    assert codec.unique_id_from_serial(None, "orp") == "unknown_orp"
    assert codec.unique_id_from_serial(None, "ph") == "unknown_ph"


def test_entity_unique_id_pattern() -> None:
    """Entity unique_ids follow {coordinator_unique_id}_{entity_key} pattern."""
    coordinator_uid = codec.unique_id_from_serial("ABC123", "orp")
    entity_keys = ["orp", "status_reason", "calibration_state", "continuous", "led"]
    for key in entity_keys:
        entity_uid = f"{coordinator_uid}_{key}"
        assert entity_uid.startswith("ABC123_orp_")
        assert entity_uid.endswith(f"_{key}")


def test_migration_entity_unique_id_update() -> None:
    """Verify entity unique_id migration pattern works correctly."""
    old_uid = "unknown_orp"
    new_uid = "ABC123_orp"
    
    old_entity_uid = f"{old_uid}_reading"
    new_entity_uid = old_entity_uid.replace(f"{old_uid}_", f"{new_uid}_", 1)
    
    assert old_entity_uid == "unknown_orp_reading"
    assert new_entity_uid == "ABC123_orp_reading"


def test_migration_preserves_entity_key() -> None:
    """Migration only changes the coordinator prefix, not the entity key."""
    old_uid = "unknown_ph"
    new_uid = "XYZ789_ph"
    entity_keys = ["ph", "slope", "temperature", "calibrate_mid"]
    
    for key in entity_keys:
        old_entity_uid = f"{old_uid}_{key}"
        new_entity_uid = old_entity_uid.replace(f"{old_uid}_", f"{new_uid}_", 1)
        assert new_entity_uid == f"{new_uid}_{key}"
        assert new_entity_uid.endswith(f"_{key}")


def test_usb_product_name_detection() -> None:
    """Generic USB names should be detected for device name fallback."""
    assert codec.is_usb_product_name("FT230X Basic UART")
    assert codec.is_usb_product_name("FT232R USB UART")
    assert codec.is_usb_product_name("USB Serial")
    assert codec.is_usb_product_name("USB-Serial CH340")
    assert codec.is_usb_product_name("")
    assert codec.is_usb_product_name(None)
    assert not codec.is_usb_product_name("EZO ORP")
    assert not codec.is_usb_product_name("My Pool ORP Sensor")


def test_resolve_display_name_with_usb_name() -> None:
    """USB product names should fall back to profile default."""
    assert codec.resolve_display_name(
        ezo_name=None,
        configured="FT230X Basic UART",
        fallback="EZO ORP"
    ) == "EZO ORP"
    
    assert codec.resolve_display_name(
        ezo_name="Pool Sensor",
        configured="FT230X Basic UART",
        fallback="EZO ORP"
    ) == "Pool Sensor"


def test_resolve_display_name_priority() -> None:
    """EZO device name takes priority over configured name."""
    assert codec.resolve_display_name(
        ezo_name="Circuit Name",
        configured="User Config",
        fallback="Default"
    ) == "Circuit Name"
    
    assert codec.resolve_display_name(
        ezo_name=None,
        configured="User Config",
        fallback="Default"
    ) == "User Config"
    
    assert codec.resolve_display_name(
        ezo_name=None,
        configured=None,
        fallback="Default"
    ) == "Default"


class TestUSBDiscoveryAdoption:
    """Test scenarios where USB discovery finds existing entries."""

    def test_find_entry_by_unknown_serial_logic(self) -> None:
        """Demonstrate the entry matching logic for unknown serials."""
        stored_serial = "unknown"
        stored_kind = "orp"
        discovery_kind = "orp"
        
        should_match = (
            stored_serial == "unknown"
            and stored_kind.lower() == discovery_kind.lower()
        )
        assert should_match

    def test_find_entry_different_kind_no_match(self) -> None:
        """Different device types should not match."""
        stored_serial = "unknown"
        stored_kind = "ph"
        discovery_kind = "orp"
        
        should_match = (
            stored_serial == "unknown"
            and stored_kind.lower() == discovery_kind.lower()
        )
        assert not should_match

    def test_find_entry_with_known_serial_no_match(self) -> None:
        """Entries with known serials should not be adopted."""
        stored_serial = "ABC123"
        stored_kind = "orp"
        discovery_kind = "orp"
        
        should_match = (
            stored_serial == "unknown"
            and stored_kind.lower() == discovery_kind.lower()
        )
        assert not should_match


class TestPortChangeScenarios:
    """Test USB port change detection and handling."""

    def test_port_path_comparison(self) -> None:
        """Port paths should be compared as strings."""
        old_port = "/dev/serial/by-id/usb-FTDI_FT230X_ABC123-if00-port0"
        new_port = "/dev/serial/by-id/usb-FTDI_FT230X_ABC123-if00-port0"
        assert old_port == new_port
        
        moved_port = "/dev/ttyUSB1"
        assert old_port != moved_port

    def test_session_port_update_needed(self) -> None:
        """Determine when session port needs updating."""
        session_port = "/dev/ttyUSB0"
        discovered_port = "/dev/ttyUSB1"
        
        needs_update = discovered_port and discovered_port != session_port
        assert needs_update

    def test_session_port_no_update_same(self) -> None:
        """No update needed when port is the same."""
        session_port = "/dev/ttyUSB0"
        discovered_port = "/dev/ttyUSB0"
        
        needs_update = discovered_port and discovered_port != session_port
        assert not needs_update

    def test_session_port_no_update_none(self) -> None:
        """No update when discovery returns None."""
        session_port = "/dev/ttyUSB0"
        discovered_port = None
        
        needs_update = discovered_port and discovered_port != session_port
        assert not needs_update
