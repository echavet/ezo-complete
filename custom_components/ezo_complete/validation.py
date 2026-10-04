"""Strict validation for sensor values to prevent corrupted history graphs.

All numeric sensor values MUST pass through validation before being published.
Out-of-range or unparseable values are rejected (sensor keeps last valid value).

Reading format requirements (Atlas EZO):
- pH: exactly 3 decimal places (e.g., 7.012)
- ORP: exactly 1 decimal place (e.g., 754.7)
- No leading zeros (e.g., reject 0013, 007.012)
- Normalize -0.0 to 0.0
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T", int, float)

# Reading format patterns (Atlas EZO format)
# pH: optional sign, digits, 2 or 3 decimal places (datasheet shows both)
_PH_READING_RE = re.compile(r"^-?(?:0|[1-9]\d*)\.(\d{2,3})$")
# ORP: optional sign, digits, exactly 1 decimal place
_ORP_READING_RE = re.compile(r"^-?(?:0|[1-9]\d*)\.(\d)$")


class ValueType(Enum):
    """Types of values with their validation ranges."""
    
    PH_READING = "ph_reading"
    ORP_READING = "orp_reading"
    ORP_READING_EXTENDED = "orp_reading_extended"
    TEMPERATURE = "temperature"
    SLOPE_PERCENT = "slope_percent"
    SLOPE_OFFSET_MV = "slope_offset_mv"
    VOLTAGE = "voltage"
    SPAN_MV = "span_mv"


@dataclass(frozen=True, slots=True)
class ValueRange:
    """Validation range for a value type."""
    
    min_value: float
    max_value: float
    description: str


VALIDATION_RANGES: dict[ValueType, ValueRange] = {
    # pH: 0-14 ALWAYS (even with extended scale enabled)
    ValueType.PH_READING: ValueRange(0.0, 14.0, "pH reading"),
    # ORP: standard range
    ValueType.ORP_READING: ValueRange(-1019.9, 1019.9, "ORP reading (mV)"),
    # ORP: extended range (per Atlas datasheet)
    ValueType.ORP_READING_EXTENDED: ValueRange(-2000.0, 2000.0, "ORP reading extended (mV)"),
    ValueType.TEMPERATURE: ValueRange(-5.0, 60.0, "temperature (°C)"),
    ValueType.SLOPE_PERCENT: ValueRange(0.0, 200.0, "slope (%)"),
    # Slope offset: ±60 mV (typical probe offset range)
    ValueType.SLOPE_OFFSET_MV: ValueRange(-60.0, 60.0, "slope offset (mV)"),
    ValueType.VOLTAGE: ValueRange(0.0, 6.0, "voltage (V)"),
    ValueType.SPAN_MV: ValueRange(0.0, 2000.0, "span (mV)"),
}


def is_valid_reading_format(raw: str, kind: str) -> bool:
    """Check if a reading string has the correct Atlas EZO format.
    
    Args:
        raw: The raw reading string
        kind: "ph" or "orp"
        
    Returns:
        True if format matches expected Atlas EZO output
    """
    if kind == "ph":
        return bool(_PH_READING_RE.match(raw))
    elif kind == "orp":
        return bool(_ORP_READING_RE.match(raw))
    return False


def normalize_reading(value: float) -> float:
    """Normalize a reading value (e.g., -0.0 -> 0.0)."""
    if value == 0.0:
        return 0.0
    return value


def is_valid_reading(value: float | None, kind: str, *, extended_scale: bool = False) -> bool:
    """Check if a reading value is within physically coherent range.
    
    Args:
        value: The reading value to validate
        kind: "ph" or "orp"
        extended_scale: If True, use extended ORP range (pH always 0-14)
        
    Returns:
        True if value is valid and in range, False otherwise
    """
    if value is None:
        return False
    
    if kind == "ph":
        # pH: ALWAYS 0-14, regardless of extended scale
        range_spec = VALIDATION_RANGES[ValueType.PH_READING]
    elif kind == "orp":
        if extended_scale:
            range_spec = VALIDATION_RANGES[ValueType.ORP_READING_EXTENDED]
        else:
            range_spec = VALIDATION_RANGES[ValueType.ORP_READING]
    else:
        return False
    
    return range_spec.min_value <= value <= range_spec.max_value


def validate_reading(
    raw: str,
    kind: str,
    *,
    extended_scale: bool = False,
    context: str = "",
) -> tuple[float | None, str | None]:
    """Parse and validate a reading string with full format checking.
    
    Args:
        raw: The raw reading string from UART
        kind: "ph" or "orp"
        extended_scale: If True, use extended ORP range
        context: Additional context for logging
        
    Returns:
        Tuple of (normalized value or None, rejection reason or None)
    """
    raw = raw.strip()
    
    # Check format (pH: 3 decimals, ORP: 1 decimal, no leading zeros)
    if not is_valid_reading_format(raw, kind):
        reason = f"invalid {kind} format '{raw}' (expected Atlas EZO format)"
        if context:
            reason = f"{reason} ({context})"
        _LOGGER.debug("Validation rejected: %s", reason)
        return None, reason
    
    try:
        value = float(raw)
    except ValueError:
        reason = f"unparseable value '{raw}'"
        if context:
            reason = f"{reason} ({context})"
        _LOGGER.debug("Validation rejected: %s", reason)
        return None, reason
    
    # Normalize -0.0 to 0.0
    value = normalize_reading(value)
    
    # Check range
    if not is_valid_reading(value, kind, extended_scale=extended_scale):
        if kind == "ph":
            range_desc = "[0, 14]"
        elif kind == "orp" and extended_scale:
            range_desc = "[-2000, 2000]"
        else:
            range_desc = "[-1019.9, 1019.9]"
        reason = f"{kind} reading {value} out of range {range_desc}"
        if context:
            reason = f"{reason} ({context})"
        _LOGGER.debug("Validation rejected: %s", reason)
        return None, reason
    
    return value, None


def is_valid_temperature(value: float | None) -> bool:
    """Check if a temperature value is within sane bounds (-5 to 60°C)."""
    if value is None:
        return False
    range_spec = VALIDATION_RANGES[ValueType.TEMPERATURE]
    return range_spec.min_value <= value <= range_spec.max_value


def is_valid_slope(value: float | None) -> bool:
    """Check if a slope percentage is within valid bounds (0-200%)."""
    if value is None:
        return False
    range_spec = VALIDATION_RANGES[ValueType.SLOPE_PERCENT]
    return range_spec.min_value <= value <= range_spec.max_value


def is_valid_slope_offset(value: float | None) -> bool:
    """Check if a slope offset is within valid bounds (±60 mV)."""
    if value is None:
        return False
    range_spec = VALIDATION_RANGES[ValueType.SLOPE_OFFSET_MV]
    return range_spec.min_value <= value <= range_spec.max_value


def is_valid_voltage(value: float | None) -> bool:
    """Check if a voltage value is within valid bounds (0-6V for USB)."""
    if value is None:
        return False
    range_spec = VALIDATION_RANGES[ValueType.VOLTAGE]
    return range_spec.min_value <= value <= range_spec.max_value


def is_valid_span(value: float | None) -> bool:
    """Check if a span value is within valid bounds."""
    if value is None:
        return False
    range_spec = VALIDATION_RANGES[ValueType.SPAN_MV]
    return range_spec.min_value <= value <= range_spec.max_value


def validate_and_log(
    value: float | None,
    value_type: ValueType,
    context: str = "",
) -> tuple[bool, str | None]:
    """Validate a value and return (is_valid, rejection_reason).
    
    Args:
        value: The value to validate
        value_type: The type of value for range lookup
        context: Additional context for logging (e.g., "from Export reply")
        
    Returns:
        Tuple of (is_valid, rejection_reason or None)
    """
    if value is None:
        return False, "null value"
    
    range_spec = VALIDATION_RANGES.get(value_type)
    if range_spec is None:
        return False, f"unknown value type {value_type}"
    
    if not (range_spec.min_value <= value <= range_spec.max_value):
        reason = (
            f"{range_spec.description} {value} out of range "
            f"[{range_spec.min_value}, {range_spec.max_value}]"
        )
        if context:
            reason = f"{reason} ({context})"
        _LOGGER.debug("Validation rejected: %s", reason)
        return False, reason
    
    return True, None


def parse_and_validate_float(
    raw: str,
    value_type: ValueType,
    context: str = "",
) -> tuple[float | None, str | None]:
    """Parse a string to float and validate it.
    
    Args:
        raw: The raw string to parse
        value_type: The type of value for range lookup
        context: Additional context for logging
        
    Returns:
        Tuple of (value or None if invalid, rejection_reason or None)
    """
    try:
        value = float(raw.strip())
    except (ValueError, TypeError, AttributeError):
        reason = f"unparseable value '{raw}'"
        if context:
            reason = f"{reason} ({context})"
        _LOGGER.debug("Validation rejected: %s", reason)
        return None, reason
    
    is_valid, reason = validate_and_log(value, value_type, context)
    if not is_valid:
        return None, reason
    
    return value, None


def get_reading_value_type(kind: str, *, extended_scale: bool = False) -> ValueType | None:
    """Get the ValueType for a reading based on probe kind."""
    if kind == "ph":
        return ValueType.PH_READING
    elif kind == "orp":
        return ValueType.ORP_READING_EXTENDED if extended_scale else ValueType.ORP_READING
    return None
