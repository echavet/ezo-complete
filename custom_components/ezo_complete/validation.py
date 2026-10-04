"""Strict validation for sensor values to prevent corrupted history graphs.

All numeric sensor values MUST pass through validation before being published.
Out-of-range or unparseable values are rejected (sensor keeps last valid value).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T", int, float)


class ValueType(Enum):
    """Types of values with their validation ranges."""
    
    PH_READING = "ph_reading"
    ORP_READING = "orp_reading"
    TEMPERATURE = "temperature"
    SLOPE_PERCENT = "slope_percent"
    VOLTAGE = "voltage"
    SPAN_MV = "span_mv"


@dataclass(frozen=True, slots=True)
class ValueRange:
    """Validation range for a value type."""
    
    min_value: float
    max_value: float
    description: str


VALIDATION_RANGES: dict[ValueType, ValueRange] = {
    ValueType.PH_READING: ValueRange(0.0, 14.0, "pH reading"),
    ValueType.ORP_READING: ValueRange(-1019.9, 1019.9, "ORP reading (mV)"),
    ValueType.TEMPERATURE: ValueRange(-5.0, 60.0, "temperature (°C)"),
    ValueType.SLOPE_PERCENT: ValueRange(0.0, 200.0, "slope (%)"),
    ValueType.VOLTAGE: ValueRange(0.0, 6.0, "voltage (V)"),
    ValueType.SPAN_MV: ValueRange(0.0, 2000.0, "span (mV)"),
}


def is_valid_reading(value: float | None, kind: str) -> bool:
    """Check if a reading value is within physically coherent range.
    
    Args:
        value: The reading value to validate
        kind: "ph" or "orp"
        
    Returns:
        True if value is valid and in range, False otherwise
    """
    if value is None:
        return False
    
    if kind == "ph":
        range_spec = VALIDATION_RANGES[ValueType.PH_READING]
    elif kind == "orp":
        range_spec = VALIDATION_RANGES[ValueType.ORP_READING]
    else:
        return False
    
    return range_spec.min_value <= value <= range_spec.max_value


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


def get_reading_value_type(kind: str) -> ValueType | None:
    """Get the ValueType for a reading based on probe kind."""
    if kind == "ph":
        return ValueType.PH_READING
    elif kind == "orp":
        return ValueType.ORP_READING
    return None
