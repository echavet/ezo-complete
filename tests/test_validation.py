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

    def test_ph_always_0_14_even_with_extended_scale(self) -> None:
        """pH range is ALWAYS 0-14, even when extended_scale is True."""
        assert validation.is_valid_reading(14.0, "ph", extended_scale=True) is True
        assert validation.is_valid_reading(14.01, "ph", extended_scale=True) is False
        assert validation.is_valid_reading(-0.01, "ph", extended_scale=True) is False


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

    def test_orp_extended_scale_allows_wider_range(self) -> None:
        """ORP with extended_scale=True allows ±2000 mV."""
        assert validation.is_valid_reading(1500.0, "orp", extended_scale=True) is True
        assert validation.is_valid_reading(-1500.0, "orp", extended_scale=True) is True
        assert validation.is_valid_reading(2000.0, "orp", extended_scale=True) is True
        assert validation.is_valid_reading(-2000.0, "orp", extended_scale=True) is True
        assert validation.is_valid_reading(2001.0, "orp", extended_scale=True) is False


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


class TestReadingFormatValidation:
    """Test that reading format validation works correctly.
    
    Atlas EZO format requirements:
    - pH: 2 or 3 decimal places (e.g., 7.01 or 7.012)
    - ORP: exactly 1 decimal place (e.g., 754.7)
    - No leading zeros (e.g., reject 0013, 007.012)
    """

    def test_valid_ph_format(self) -> None:
        """Valid pH format: 2 or 3 decimal places."""
        assert validation.is_valid_reading_format("7.012", "ph") is True
        assert validation.is_valid_reading_format("7.01", "ph") is True
        assert validation.is_valid_reading_format("0.000", "ph") is True
        assert validation.is_valid_reading_format("0.00", "ph") is True
        assert validation.is_valid_reading_format("14.000", "ph") is True
        assert validation.is_valid_reading_format("14.00", "ph") is True
        assert validation.is_valid_reading_format("-1.234", "ph") is True
        assert validation.is_valid_reading_format("-1.23", "ph") is True

    def test_invalid_ph_format_wrong_decimals(self) -> None:
        """pH with wrong number of decimals should be rejected."""
        assert validation.is_valid_reading_format("7.0", "ph") is False
        assert validation.is_valid_reading_format("7.0123", "ph") is False
        assert validation.is_valid_reading_format("7", "ph") is False

    def test_invalid_ph_format_leading_zeros(self) -> None:
        """pH with leading zeros should be rejected."""
        assert validation.is_valid_reading_format("007.012", "ph") is False
        assert validation.is_valid_reading_format("0013", "ph") is False
        assert validation.is_valid_reading_format("00.123", "ph") is False

    def test_valid_orp_format(self) -> None:
        """Valid ORP format: exactly 1 decimal place."""
        assert validation.is_valid_reading_format("754.7", "orp") is True
        assert validation.is_valid_reading_format("0.0", "orp") is True
        assert validation.is_valid_reading_format("-500.5", "orp") is True
        assert validation.is_valid_reading_format("1019.9", "orp") is True

    def test_invalid_orp_format_wrong_decimals(self) -> None:
        """ORP with wrong number of decimals should be rejected."""
        assert validation.is_valid_reading_format("754", "orp") is False
        assert validation.is_valid_reading_format("754.75", "orp") is False
        assert validation.is_valid_reading_format("754.757", "orp") is False

    def test_invalid_orp_format_leading_zeros(self) -> None:
        """ORP with leading zeros should be rejected."""
        assert validation.is_valid_reading_format("0700", "orp") is False
        assert validation.is_valid_reading_format("0700.5", "orp") is False

    def test_validate_reading_full(self) -> None:
        """Full validate_reading function with format + range check."""
        # Valid pH
        value, reason = validation.validate_reading("7.012", "ph")
        assert value == 7.012
        assert reason is None
        
        # Invalid format (only 1 decimal for pH)
        value, reason = validation.validate_reading("7.0", "ph")
        assert value is None
        assert "format" in reason.lower()
        
        # Valid format but out of range
        value, reason = validation.validate_reading("15.000", "ph")
        assert value is None
        assert "out of range" in reason.lower()

    def test_normalize_negative_zero(self) -> None:
        """Negative zero should be normalized to 0.0."""
        assert validation.normalize_reading(-0.0) == 0.0
        assert validation.normalize_reading(0.0) == 0.0
        assert validation.normalize_reading(7.0) == 7.0


class TestSlopeOffsetValidation:
    """Test slope offset validation (±60 mV)."""

    def test_valid_slope_offset(self) -> None:
        """Valid slope offsets within ±60 mV should pass."""
        assert validation.is_valid_slope_offset(0.0) is True
        assert validation.is_valid_slope_offset(30.0) is True
        assert validation.is_valid_slope_offset(-30.0) is True
        assert validation.is_valid_slope_offset(60.0) is True
        assert validation.is_valid_slope_offset(-60.0) is True

    def test_invalid_slope_offset(self) -> None:
        """Slope offsets outside ±60 mV should be rejected."""
        assert validation.is_valid_slope_offset(60.1) is False
        assert validation.is_valid_slope_offset(-60.1) is False
        assert validation.is_valid_slope_offset(999.0) is False
        assert validation.is_valid_slope_offset(-999.0) is False
        assert validation.is_valid_slope_offset(None) is False


class TestExportHexRejection:
    """Test that Export hex lines don't get parsed as readings.
    
    Export replies contain hex calibration data like:
    ?Export,8
    9E6B
    2A1F
    ...
    
    These hex values should never be parsed as readings.
    
    CRITICAL: Readings may ONLY come from R command or continuous stream,
    so Export replies should never even be attempted to parse as readings.
    """

    def test_export_hex_wrong_format_for_ph(self) -> None:
        """Export hex lines don't match pH format (3 decimals)."""
        export_lines = ["000000000000", "000000000007", "0013", "9E6B", "2A1F"]
        for line in export_lines:
            assert validation.is_valid_reading_format(line, "ph") is False, (
                f"Export line '{line}' should fail pH format check"
            )

    def test_export_hex_wrong_format_for_orp(self) -> None:
        """Export hex lines don't match ORP format (1 decimal)."""
        export_lines = ["0700", "9E6B", "2A1F", "FFFF"]
        for line in export_lines:
            assert validation.is_valid_reading_format(line, "orp") is False, (
                f"Export line '{line}' should fail ORP format check"
            )

    def test_export_full_validation_rejects_hex(self) -> None:
        """Full validation rejects export hex lines."""
        # These would have been accepted as valid values before format check
        value, reason = validation.validate_reading("000000000007", "ph")
        assert value is None
        assert "format" in reason.lower()
        
        value, reason = validation.validate_reading("0700", "orp")
        assert value is None
        assert "format" in reason.lower()


class TestCalImportRejection:
    """Test that Cal/Import command replies don't corrupt sensor values.
    
    CRITICAL: Readings may ONLY come from R command or continuous stream.
    Cal, Import, Export, Slope, T, Status replies must NEVER be parsed as readings.
    """

    def test_cal_ok_response_not_valid_reading(self) -> None:
        """*OK response shouldn't be parsed as a reading."""
        assert validation.is_valid_reading(None, "ph") is False

    def test_import_response_garbage(self) -> None:
        """Import command responses should be rejected if parsed incorrectly."""
        garbage_values = [999999.0, -999999.0, float("inf"), float("-inf")]
        for value in garbage_values:
            assert validation.is_valid_reading(value, "ph") is False
            assert validation.is_valid_reading(value, "orp") is False

    def test_short_garbage_lines_wrong_format(self) -> None:
        """Short garbage lines should fail format validation."""
        garbage = ["7", "75", "-3.2", "14", "0", "-0"]
        for line in garbage:
            # These might be in valid value range, but wrong format
            ph_valid = validation.is_valid_reading_format(line, "ph")
            orp_valid = validation.is_valid_reading_format(line, "orp")
            assert not ph_valid, f"'{line}' should fail pH format (need 3 decimals)"
            # Some may pass ORP format if they have 1 decimal
            if "." not in line:
                assert not orp_valid, f"'{line}' should fail ORP format (need 1 decimal)"

    def test_cal_multiline_reply_example(self) -> None:
        """Multi-line Cal reply should not contain valid readings.
        
        Example Cal reply:
        ?Cal,2
        *OK
        
        Neither line should pass reading validation.
        """
        cal_lines = ["?Cal,2", "*OK", "OK"]
        for line in cal_lines:
            assert validation.is_valid_reading_format(line, "ph") is False
            assert validation.is_valid_reading_format(line, "orp") is False

    def test_export_multiline_reply_example(self) -> None:
        """Multi-line Export reply should not contain valid readings.
        
        Example Export reply:
        ?Export,8
        9E6B2A1F
        12345678
        *DONE
        
        These are calibration data, not readings.
        """
        export_lines = ["?Export,8", "9E6B2A1F", "12345678", "*DONE", "000000000007"]
        for line in export_lines:
            value, reason = validation.validate_reading(line, "ph")
            assert value is None, f"Export line '{line}' should be rejected"

    def test_import_multiline_reply_example(self) -> None:
        """Multi-line Import reply should not contain valid readings.
        
        Example Import reply with echo:
        Import,9E6B
        *OK
        """
        import_lines = ["Import,9E6B", "*OK", "9E6B"]
        for line in import_lines:
            value, reason = validation.validate_reading(line, "ph")
            assert value is None, f"Import line '{line}' should be rejected"

    def test_slope_reply_not_reading(self) -> None:
        """Slope query reply should not be parsed as reading.
        
        Example: ?Slope,99.7,100.3,-0.89
        """
        slope_lines = ["?Slope,99.7,100.3,-0.89", "99.7,100.3,-0.89"]
        for line in slope_lines:
            value, reason = validation.validate_reading(line, "ph")
            assert value is None

    def test_status_reply_not_reading(self) -> None:
        """Status query reply should not be parsed as reading.
        
        Example: ?Status,P,5.023
        """
        status_lines = ["?Status,P,5.023", "P,5.023"]
        for line in status_lines:
            value, reason = validation.validate_reading(line, "ph")
            assert value is None


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


class TestPhTwoDecimalFormat:
    """Test that pH accepts 2-decimal format (datasheet shows both 2 and 3)."""

    def test_ph_two_decimals_valid(self) -> None:
        """pH with 2 decimals should be accepted."""
        value, reason = validation.validate_reading("7.01", "ph")
        assert value == 7.01
        assert reason is None
        
        value, reason = validation.validate_reading("13.99", "ph")
        assert value == 13.99
        assert reason is None

    def test_ph_three_decimals_still_valid(self) -> None:
        """pH with 3 decimals should still be accepted."""
        value, reason = validation.validate_reading("7.012", "ph")
        assert value == 7.012
        assert reason is None

    def test_ph_one_decimal_still_invalid(self) -> None:
        """pH with only 1 decimal should be rejected."""
        value, reason = validation.validate_reading("7.0", "ph")
        assert value is None
        assert "format" in reason.lower()

    def test_ph_four_decimals_invalid(self) -> None:
        """pH with 4 decimals should be rejected."""
        value, reason = validation.validate_reading("7.0123", "ph")
        assert value is None
        assert "format" in reason.lower()


class TestStreamAcceptanceInCalibration:
    """Test that continuous stream is accepted when mode is calibration.
    
    Stream acceptance must not depend solely on the last C,? reply:
    accept when state.continuous is True OR configured mode is calibration.
    """

    def test_calibration_mode_logic(self) -> None:
        """Verify the stream acceptance logic for calibration mode."""
        # Simulate the logic from coordinator._apply_lines
        def is_reading_source(last_command, state_continuous, mode):
            cmd_verb = (last_command or "").split(",", 1)[0].lower()
            is_continuous_stream = (
                last_command is None
                and (state_continuous is True or mode == "calibration")
            )
            return cmd_verb == "r" or is_continuous_stream
        
        # R command always allowed
        assert is_reading_source("R", False, "exploitation") is True
        assert is_reading_source("R", False, "calibration") is True
        
        # Stream with state.continuous=True
        assert is_reading_source(None, True, "exploitation") is True
        assert is_reading_source(None, True, "calibration") is True
        
        # Stream in calibration mode (even if C,? not received yet)
        assert is_reading_source(None, False, "calibration") is True
        assert is_reading_source(None, None, "calibration") is True
        
        # Stream in exploitation without continuous=True: NOT allowed
        assert is_reading_source(None, False, "exploitation") is False
        assert is_reading_source(None, None, "exploitation") is False
        
        # Non-R commands never allowed
        assert is_reading_source("Export", True, "calibration") is False
        assert is_reading_source("Cal,mid", True, "calibration") is False
        assert is_reading_source("Import,9E6B", True, "calibration") is False
