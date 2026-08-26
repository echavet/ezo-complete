"""Constants for the EZO Complete integration (pH + ORP)."""

from __future__ import annotations

DOMAIN = "ezo_complete"
MANUFACTURER = "Atlas Scientific"
DEFAULT_NAME = "EZO Complete"
DEFAULT_BAUDRATE = 9600
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
    "sensor",
    "switch",
    "text",
]

STABILITY_WINDOW_S = 10.0
STABILITY_MIN_SAMPLES = 5
PH_STABLE_SPAN = 0.05
ORP_STABLE_SPAN = 5.0

CONF_SERIAL_NUMBER = "serial_number"
CONF_BAUDRATE = "baudrate"
CONF_DEVICE_TYPE = "device_type"
CONF_FIRMWARE = "firmware"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CONTINUOUS_ON_START = "continuous_on_start"
CONF_CONTINUOUS_INTERVAL = "continuous_interval"
CONF_TEMPERATURE_ENTITY = "temperature_entity"

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

RESPONSE_CODE_ENABLE_COMMANDS: tuple[str, ...] = ("RESPONSE,1", "O,1", "OK,1")
ATTRIBUTION = "Data provided by Atlas Scientific EZO Complete"
