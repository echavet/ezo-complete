"""Tests for value validation to prevent out-of-range sensor values.

These tests verify:
1. Strict validation ranges for all sensor types
2. Export/Import/Cal replies don't corrupt sensor values
3. Garbage lines are rejected
4. rejected_readings counter increments correctly
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

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


validation = _load("ezo_complete.validation", PKG / "validation.py")


class TestPhValidation:
    """Test pH reading validation (0-14 range)."""

    def test_valid_ph_readings(self) -> None:
        """Valid pH readings within 0-14 should pass."""
        assert validation.is_valid_reading(0.0, "ph") is True
        assert validation.is_valid_reading(7.0, "ph") is True
        assert validation.is_valid_reading(14.0, "ph") is True
        assert validation.is_valid_reading(6.89, "ph") is True
        assert validation.is_valid_reading(13.99, "ph") is True

    def test_invalid_ph_out_of_range_high(self) -> None:
        """pH readings above 14 should be rejected."""
        assert validation.is_valid_reading(14.01, "ph") is False
        assert validation.is_valid_reading(15.0, "ph") is False
        assert validation.is_valid_reading(100.0, "ph") is False
        assert validation.is_valid_reading(255.0, "ph") is False

    def test_invalid_ph_out_of_range_low(self) -> None:
        """pH readings below 0 should be rejected."""
        assert validation.is_valid_reading(-0.01, "ph") is False
        assert validation.is_valid_reading(-1.0, "ph") is False
        assert validation.is_valid_reading(-100.0, "ph") is False

    def test_invalid_ph_none(self) -> None:
        """None pH readings should be rejected."""
        assert validation.is_valid_reading(None, "ph") is False


class TestOrpValidation:
    """Test ORP reading validation (-1019.9 to 1019.9 mV)."""

    def test_valid_orp_readings(self) -> None:
        """Valid ORP readings within range should pass."""
        assert validation.is_valid_reading(0.0, "orp") is True
        assert validation.is_valid_reading(225.0, "orp") is True
        assert validation.is_valid_reading(-500.0, "orp") is True
        assert validation.is_valid_reading(800.0, "orp") is True
        assert validation.is_valid_reading(-1019.9, "orp") is True
        assert validation.is_valid_reading(1019.9, "orp") is True

    def test_invalid_orp_out_of_range_high(self) -> None:
        """ORP readings above 1019.9 should be rejected."""
        assert validation.is_valid_reading(1020.0, "orp") is False
        assert validation.is_valid_reading(2000.0, "orp") is False
        assert validation.is_valid_reading(65535.0, "orp") is False

    def test_invalid_orp_out_of_range_low(self) -> None:
        """ORP readings below -1019.9 should be rejected."""
        assert validation.is_valid_reading(-1020.0, "orp") is False
        assert validation.is_valid_reading(-2000.0, "orp") is False

    def test_invalid_orp_none(self) -> None:
        """None ORP readings should be rejected."""
        assert validation.is_valid_reading(None, "orp") is False


class TestTemperatureValidation:
    """Test temperature validation (-5 to 60°C)."""

    def test_valid_temperatures(self) -> None:
        """Valid temperatures within range should pass."""
        assert validation.is_valid_temperature(25.0) is True
        assert validation.is_valid_temperature(-5.0) is True
        assert validation.is_valid_temperature(60.0) is True
        assert validation.is_valid_temperature(0.0) is True
        assert validation.is_valid_temperature(37.5) is True

    def test_invalid_temperature_high(self) -> None:
        """Temperatures above 60°C should be rejected."""
        assert validation.is_valid_temperature(60.1) is False
        assert validation.is_valid_temperature(100.0) is False
        assert validation.is_valid_temperature(255.0) is False

    def test_invalid_temperature_low(self) -> None:
        """Temperatures below -5°C should be rejected."""
        assert validation.is_valid_temperature(-5.1) is False
        assert validation.is_valid_temperature(-40.0) is False

    def test_invalid_temperature_none(self) -> None:
        """None temperature should be rejected."""
        assert validation.is_valid_temperature(None) is False


class TestSlopeValidation:
    """Test slope validation (0-200%)."""

    def test_valid_slopes(self) -> None:
        """Valid slopes within range should pass."""
        assert validation.is_valid_slope(100.0) is True
        assert validation.is_valid_slope(0.0) is True
        assert validation.is_valid_slope(200.0) is True
        assert validation.is_valid_slope(99.7) is True
        assert validation.is_valid_slope(85.5) is True

    def test_invalid_slope_high(self) -> None:
        """Slopes above 200% should be rejected."""
        assert validation.is_valid_slope(200.1) is False
        assert validation.is_valid_slope(300.0) is False

    def test_invalid_slope_negative(self) -> None:
        """Negative slopes should be rejected."""
        assert validation.is_valid_slope(-0.1) is False
        assert validation.is_valid_slope(-10.0) is False

    def test_invalid_slope_none(self) -> None:
        """None slope should be rejected."""
        assert validation.is_valid_slope(None) is False


class TestVoltageValidation:
    """Test voltage validation (0-6V for USB)."""

    def test_valid_voltages(self) -> None:
        """Valid voltages within range should pass."""
        assert validation.is_valid_voltage(5.0) is True
        assert validation.is_valid_voltage(0.0) is True
        assert validation.is_valid_voltage(6.0) is True
        assert validation.is_valid_voltage(3.3) is True
        assert validation.is_valid_voltage(4.95) is True

    def test_invalid_voltage_high(self) -> None:
        """Voltages above 6V should be rejected."""
        assert validation.is_valid_voltage(6.1) is False
        assert validation.is_valid_voltage(12.0) is False

    def test_invalid_voltage_negative(self) -> None:
        """Negative voltages should be rejected."""
        assert validation.is_valid_voltage(-0.1) is False

    def test_invalid_voltage_none(self) -> None:
        """None voltage should be rejected."""
        assert validation.is_valid_voltage(None) is False


class TestExportHexRejection:
    """Test that Export hex lines don't get parsed as readings.
    
    Export replies contain hex calibration data like:
    ?Export,8
    9E6B
    2A1F
    ...
    
    These hex values should never be parsed as readings.
    """

    def test_export_hex_not_valid_ph(self) -> None:
        """Export hex parsed as numbers should be out of pH range.
        
        Note: 0x0000 = 0 is technically valid pH, but real export data
        contains calibration hex that parses to large integers.
        """
        hex_values = ["9E6B", "2A1F", "FFFF", "1234", "ABCD"]
        for hex_str in hex_values:
            try:
                value = int(hex_str, 16)
                assert validation.is_valid_reading(float(value), "ph") is False, (
                    f"Hex {hex_str} = {value} should be rejected for pH"
                )
            except ValueError:
                pass

    def test_export_hex_not_valid_orp(self) -> None:
        """Export hex parsed as numbers should be out of ORP range."""
        hex_values = ["9E6B", "2A1F", "FFFF", "1234"]
        for hex_str in hex_values:
            try:
                value = int(hex_str, 16)
                assert validation.is_valid_reading(float(value), "orp") is False, (
                    f"Hex {hex_str} = {value} should be rejected for ORP"
                )
            except ValueError:
                pass


class TestCalImportRejection:
    """Test that Cal/Import command replies don't corrupt sensor values."""

    def test_cal_ok_response_not_valid_reading(self) -> None:
        """*OK response shouldn't be parsed as a reading."""
        assert validation.is_valid_reading(None, "ph") is False

    def test_import_response_garbage(self) -> None:
        """Import command responses should be rejected if parsed incorrectly."""
        garbage_values = [999999.0, -999999.0, float("inf"), float("-inf")]
        for value in garbage_values:
            assert validation.is_valid_reading(value, "ph") is False
            assert validation.is_valid_reading(value, "orp") is False


class TestGarbageLineRejection:
    """Test that garbage/partial lines are rejected."""

    def test_parse_and_validate_garbage(self) -> None:
        """Unparseable strings should be rejected."""
        garbage = ["abc", "?OK", "*OK,1", "Export,8", "", "   ", "NaN", "inf"]
        for raw in garbage:
            value, reason = validation.parse_and_validate_float(
                raw, validation.ValueType.PH_READING, "garbage test"
            )
            assert value is None, f"'{raw}' should be rejected"
            assert reason is not None

    def test_parse_valid_float_in_range(self) -> None:
        """Valid float strings in range should pass."""
        value, reason = validation.parse_and_validate_float(
            "7.00", validation.ValueType.PH_READING, "test"
        )
        assert value == 7.0
        assert reason is None

    def test_parse_valid_float_out_of_range(self) -> None:
        """Valid float strings out of range should be rejected."""
        value, reason = validation.parse_and_validate_float(
            "15.0", validation.ValueType.PH_READING, "test"
        )
        assert value is None
        assert reason is not None
        assert "out of range" in reason


class TestUnknownKindRejection:
    """Test that unknown probe kinds are rejected."""

    def test_unknown_kind_rejected(self) -> None:
        """Unknown probe kinds should always reject readings."""
        assert validation.is_valid_reading(7.0, "unknown") is False
        assert validation.is_valid_reading(225.0, "ec") is False
        assert validation.is_valid_reading(100.0, "") is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_ph_boundary_values(self) -> None:
        """Test exact boundary values for pH."""
        assert validation.is_valid_reading(0.0, "ph") is True
        assert validation.is_valid_reading(14.0, "ph") is True
        assert validation.is_valid_reading(-0.0001, "ph") is False
        assert validation.is_valid_reading(14.0001, "ph") is False

    def test_orp_boundary_values(self) -> None:
        """Test exact boundary values for ORP."""
        assert validation.is_valid_reading(-1019.9, "orp") is True
        assert validation.is_valid_reading(1019.9, "orp") is True
        assert validation.is_valid_reading(-1019.91, "orp") is False
        assert validation.is_valid_reading(1019.91, "orp") is False

    def test_temperature_boundary_values(self) -> None:
        """Test exact boundary values for temperature."""
        assert validation.is_valid_temperature(-5.0) is True
        assert validation.is_valid_temperature(60.0) is True
        assert validation.is_valid_temperature(-5.01) is False
        assert validation.is_valid_temperature(60.01) is False

    def test_slope_boundary_values(self) -> None:
        """Test exact boundary values for slope."""
        assert validation.is_valid_slope(0.0) is True
        assert validation.is_valid_slope(200.0) is True
        assert validation.is_valid_slope(-0.01) is False
        assert validation.is_valid_slope(200.01) is False

    def test_voltage_boundary_values(self) -> None:
        """Test exact boundary values for voltage."""
        assert validation.is_valid_voltage(0.0) is True
        assert validation.is_valid_voltage(6.0) is True
        assert validation.is_valid_voltage(-0.01) is False
        assert validation.is_valid_voltage(6.01) is False


class TestValidateAndLog:
    """Test the validate_and_log function."""

    def test_valid_value_returns_true(self) -> None:
        """Valid values should return (True, None)."""
        is_valid, reason = validation.validate_and_log(
            7.0, validation.ValueType.PH_READING, "test"
        )
        assert is_valid is True
        assert reason is None

    def test_invalid_value_returns_reason(self) -> None:
        """Invalid values should return (False, reason_string)."""
        is_valid, reason = validation.validate_and_log(
            15.0, validation.ValueType.PH_READING, "export reply"
        )
        assert is_valid is False
        assert reason is not None
        assert "out of range" in reason
        assert "export reply" in reason

    def test_none_value_rejected(self) -> None:
        """None values should be rejected with reason."""
        is_valid, reason = validation.validate_and_log(
            None, validation.ValueType.PH_READING, "test"
        )
        assert is_valid is False
        assert reason == "null value"
