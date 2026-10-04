"""Constants for the EZO Complete integration (pH + ORP)."""

from __future__ import annotations

DOMAIN = "ezo_complete"
MANUFACTURER = "Atlas Scientific"
DEFAULT_NAME = "EZO Complete"
DEFAULT_BAUDRATE = 9600

# Mode constants
MODE_EXPLOITATION = "exploitation"
MODE_CALIBRATION = "calibration"

# Filter constants
FILTER_NONE = "none"
FILTER_MEDIAN = "median"
FILTER_MEAN = "mean"

# Defaults for new settings
DEFAULT_MODE = MODE_EXPLOITATION
DEFAULT_MEASUREMENT_INTERVAL = 60
DEFAULT_FILTER_TYPE = FILTER_MEDIAN
DEFAULT_FILTER_WINDOW = 5
DEFAULT_CALIBRATION_INTERVAL = 1
DEFAULT_CALIBRATION_AUTO_RETURN = 15
DEFAULT_STABILITY_WINDOW = 10.0
DEFAULT_PH_STABILITY_SPAN_MV = 3.0  # ~0.05 pH at 100% slope
DEFAULT_ORP_STABILITY_SPAN = 5.0   # mV (direct measurement)
DEFAULT_SLEEP = False

# Legacy defaults (for migration)
DEFAULT_UPDATE_INTERVAL = 5
DEFAULT_CONTINUOUS_ON_START = True
DEFAULT_CONTINUOUS_INTERVAL = 1

DEFAULT_ORP_CALIBRATION = 225.0
DEFAULT_PH_MID = 7.0
DEFAULT_PH_LOW = 4.0
DEFAULT_PH_HIGH = 10.0

PLATFORMS: list[str] = [
    "binary_sensor",
    "button",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
]

# Stability defaults (used if not configured)
STABILITY_WINDOW_S = 10.0
STABILITY_MIN_SAMPLES = 5
STABILITY_MIN_SAMPLES_FLOOR = 3
STABILITY_MIN_SAMPLES_CEILING = 5
PH_STABLE_SPAN = 0.05
ORP_STABLE_SPAN = 5.0
TEMPERATURE_PUSH_DELTA = 0.1

# Configuration keys
CONF_SERIAL_NUMBER = "serial_number"
CONF_BAUDRATE = "baudrate"
CONF_DEVICE_TYPE = "device_type"
CONF_FIRMWARE = "firmware"
CONF_TEMPERATURE_ENTITY = "temperature_entity"

# New configuration keys (entry.options)
CONF_MODE = "mode"
CONF_MEASUREMENT_INTERVAL = "measurement_interval"
CONF_FILTER_TYPE = "filter_type"
CONF_FILTER_WINDOW = "filter_window"
# NOTE: continuous_interval key kept for entity unique_id stability (approved design)
CONF_CONTINUOUS_INTERVAL = "continuous_interval"
CONF_CALIBRATION_AUTO_RETURN = "calibration_auto_return"
CONF_STABILITY_WINDOW = "stability_window"
CONF_STABILITY_MAX_SPAN = "stability_max_span"
CONF_SLEEP = "sleep"

# Legacy keys (for migration only)
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CONTINUOUS_ON_START = "continuous_on_start"

# Ranges
MEASUREMENT_INTERVAL_MIN = 5
MEASUREMENT_INTERVAL_MAX = 3600
FILTER_WINDOW_MIN = 1
FILTER_WINDOW_MAX = 20
CALIBRATION_AUTO_RETURN_MIN = 0
CALIBRATION_AUTO_RETURN_MAX = 120
STABILITY_WINDOW_MIN = 5.0
STABILITY_WINDOW_MAX = 60.0

# Stability thresholds are in mV for both pH and ORP (calibration-independent)
# pH: ~3 mV ≈ 0.05 pH at 100% slope (59.16 mV/pH at 25°C)
# ORP: direct mV measurement
PH_STABILITY_SPAN_MV_MIN = 0.5
PH_STABILITY_SPAN_MV_MAX = 30.0
PH_STABILITY_SPAN_MV_DEFAULT = 3.0
ORP_STABILITY_SPAN_MIN = 1.0
ORP_STABILITY_SPAN_MAX = 20.0

# Nernst constant: ideal mV per pH unit at 25°C
NERNST_MV_PER_PH = 59.16

BAUDRATES: tuple[int, ...] = (300, 1200, 2400, 9600, 19200, 38400, 57600, 115200)

SUPPORTED_KINDS: frozenset[str] = frozenset({"orp", "ph"})

IMPORT_CALIBRATION_SUFFIX = "import_calibration"

COMMAND_TIMEOUT = 2.0
READ_COMMAND_TIMEOUT = 3.0
FIND_TIMEOUT = 4.0
WAKE_SETTLE = 1.0
OPEN_SETTLE = 0.6
STALE_WAKE_SECONDS = 15.0
RECONNECT_DELAY = 5.0
RAW_LINE_HISTORY = 20
FACTORY_ARM_SECONDS = 30
CONTINUOUS_INTERVAL_MIN = 1
CONTINUOUS_INTERVAL_MAX = 99

ORP_RANGE_STANDARD = (-1020.0, 1020.0)
ORP_RANGE_EXTENDED = (-2000.0, 2000.0)
PH_RANGE_STANDARD = (0.001, 14.0)
PH_RANGE_EXTENDED = (-1.6, 15.6)

STATUS_REASON_MAP: dict[str, str] = {
    "P": "power",
    "S": "software",
    "B": "brownout",
    "W": "watchdog",
    "U": "unknown",
}

# Commands to enable UART response codes on Atlas EZO circuits.
# - RESPONSE,1: legacy syntax (older firmware)
# - *OK,1: modern syntax (firmware 2.x+, per pH_EZO_Datasheet.pdf / ORP_EZO_Datasheet.pdf)
# Tried in order; first successful command wins.
RESPONSE_CODE_ENABLE_COMMANDS: tuple[str, ...] = ("*OK,1", "RESPONSE,1")

# Valid reading ranges per Atlas datasheets (values outside are measurement artifacts)
PH_READING_MIN = PH_RANGE_EXTENDED[0]  # -1.6
PH_READING_MAX = PH_RANGE_EXTENDED[1]  # 15.6
ORP_READING_MIN = ORP_RANGE_STANDARD[0]  # -1020.0
ORP_READING_MAX = ORP_RANGE_STANDARD[1]  # 1020.0
ATTRIBUTION = "Data provided by Atlas Scientific EZO Complete"
