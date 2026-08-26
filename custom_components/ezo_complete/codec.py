"""Pure Atlas EZO UART codec (no I/O, no Home Assistant)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re

from .const import STATUS_REASON_MAP, SUPPORTED_KINDS

CR = b"\r"
CMD_TERMINATOR = "\r"
_READING_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


class LineKind(StrEnum):
    READING = "reading"
    QUERY = "query"
    STATUS = "status"
    OTHER = "other"


class EzoStatusCode(StrEnum):
    OK = "OK"
    ER = "ER"
    OV = "OV"
    UV = "UV"
    RS = "RS"
    RE = "RE"
    SL = "SL"
    WA = "WA"


@dataclass(slots=True)
class ParsedLine:
    kind: LineKind
    raw: str
    value: float | None = None
    query_key: str | None = None
    query_args: tuple[str, ...] = ()
    status_code: str | None = None


@dataclass(slots=True)
class DeviceInfoResponse:
    device_type: str
    firmware: str
    raw: str

    @property
    def kind(self) -> str:
        token = (self.device_type or "").strip().lower()
        if token in {"ph", "orp"}:
            return token
        blob = self.raw.upper()
        if ",PH," in blob or blob.endswith("PH") or "PH," in blob:
            return "ph"
        if "ORP" in blob:
            return "orp"
        return token

    @property
    def is_supported(self) -> bool:
        return self.kind in SUPPORTED_KINDS


@dataclass(slots=True)
class StatusResponse:
    reason_code: str
    reason: str
    voltage: float | None
    raw: str


@dataclass(slots=True)
class ContinuousResponse:
    enabled: bool
    interval: int
    raw: str


@dataclass(slots=True)
class EzoResponse:
    command: str
    lines: list[ParsedLine] = field(default_factory=list)

    @property
    def raw_lines(self) -> list[str]:
        return [line.raw for line in self.lines]

    @property
    def ok(self) -> bool:
        codes = [line.status_code for line in self.lines if line.kind is LineKind.STATUS]
        if EzoStatusCode.ER in codes or EzoStatusCode.OV in codes:
            return False
        if EzoStatusCode.OK in codes:
            return True
        return any(line.kind in (LineKind.READING, LineKind.QUERY) for line in self.lines)

    @property
    def error_code(self) -> str | None:
        for line in self.lines:
            if line.status_code in {EzoStatusCode.ER, EzoStatusCode.OV, EzoStatusCode.UV}:
                return line.status_code
        return None

    def first_reading(self) -> float | None:
        for line in self.lines:
            if line.kind is LineKind.READING and line.value is not None:
                return line.value
        return None

    def query(self, key: str | None = None) -> ParsedLine | None:
        for line in self.lines:
            if line.kind is not LineKind.QUERY:
                continue
            if key is None or (line.query_key or "").lower() == key.lower():
                return line
        return None


_ACK_ONLY_VERBS = frozenset(
    {
        "c",
        "l",
        "find",
        "sleep",
        "factory",
        "name",
        "ok",
        "o",
        "response",
        "orpext",
        "phext",
        "cal",
        "t",
    }
)


def command_succeeded(response: EzoResponse) -> bool:
    if response.error_code:
        return False
    if response.ok:
        return True
    verb, _, arg = response.command.partition(",")
    if arg.strip() == "?":
        return False
    return verb.strip().lower() in _ACK_ONLY_VERBS


def encode_command(command: str) -> bytes:
    return f"{command.strip()}{CMD_TERMINATOR}".encode("ascii")


def parse_line(raw: str) -> ParsedLine:
    text = raw.strip().strip("\x00")
    if not text:
        return ParsedLine(kind=LineKind.OTHER, raw=text)
    if text.startswith("*"):
        code = text[1:].split(",", 1)[0].strip().upper()
        return ParsedLine(kind=LineKind.STATUS, raw=text, status_code=code)
    if text.startswith("?"):
        body = text[1:]
        parts = [part.strip() for part in body.split(",")]
        return ParsedLine(
            kind=LineKind.QUERY,
            raw=text,
            query_key=parts[0] if parts else "",
            query_args=tuple(parts[1:]),
        )
    if _READING_RE.match(text):
        return ParsedLine(kind=LineKind.READING, raw=text, value=float(text))
    return ParsedLine(kind=LineKind.OTHER, raw=text)


def parse_device_info(response: EzoResponse | str) -> DeviceInfoResponse | None:
    line = _query_line(response, "i")
    if line is None:
        raw = _raw_blob(response)
        upper = raw.upper()
        if "ORP" in upper:
            return DeviceInfoResponse(device_type="ORP", firmware="", raw=raw)
        if re.search(r"\bPH\b", upper):
            return DeviceInfoResponse(device_type="pH", firmware="", raw=raw)
        return None
    device_type = line.query_args[0] if line.query_args else ""
    firmware = line.query_args[1] if len(line.query_args) > 1 else ""
    info = DeviceInfoResponse(device_type=device_type, firmware=firmware, raw=line.raw)
    return info if info.is_supported else None


def parse_status(response: EzoResponse | str) -> StatusResponse | None:
    line = _query_line(response, "status")
    if line is None:
        return None
    reason_code = (line.query_args[0] if line.query_args else "U").upper()
    voltage: float | None = None
    if len(line.query_args) > 1:
        try:
            voltage = float(line.query_args[1])
        except ValueError:
            voltage = None
    return StatusResponse(
        reason_code=reason_code,
        reason=STATUS_REASON_MAP.get(reason_code, "unknown"),
        voltage=voltage,
        raw=line.raw,
    )


def parse_continuous(response: EzoResponse | str) -> ContinuousResponse | None:
    line = _query_line(response, "c")
    if line is None:
        return None
    interval = 0
    if line.query_args:
        try:
            interval = int(float(line.query_args[0]))
        except ValueError:
            interval = 0
    return ContinuousResponse(enabled=interval > 0, interval=max(interval, 0), raw=line.raw)


def parse_cal_points(response: EzoResponse | str) -> int | None:
    """``?Cal,0`` … ``?Cal,3`` (ORP uses 0/1, pH uses 0–3)."""
    line = _query_line(response, "cal")
    if line is not None and line.query_args:
        try:
            return int(float(line.query_args[0]))
        except ValueError:
            pass
    match = re.search(r"\?Cal\s*,\s*(\d+)", _raw_blob(response), flags=re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def parse_led(response: EzoResponse | str) -> bool | None:
    line = _query_line(response, "l")
    if line is None or not line.query_args:
        return None
    return line.query_args[0] not in {"0", "0.0"}


def parse_name(response: EzoResponse | str) -> str | None:
    line = _query_line(response, "name")
    if line is None:
        return None
    return ",".join(line.query_args)


def parse_flag(response: EzoResponse | str, key: str) -> bool | None:
    line = _query_line(response, key)
    if line is None or not line.query_args:
        return None
    return line.query_args[0] not in {"0", "0.0"}


def parse_temperature(response: EzoResponse | str) -> float | None:
    line = _query_line(response, "t")
    if line is None or not line.query_args:
        return None
    try:
        return float(line.query_args[0])
    except ValueError:
        return None


def parse_slope(response: EzoResponse | str) -> tuple[str, ...] | None:
    """``?Slope,99.7,100.3`` acid%, base% (optional offset)."""
    line = _query_line(response, "slope")
    if line is None:
        return None
    return line.query_args


def parse_export_count(response: EzoResponse | str) -> int | None:
    line = _query_line(response, "export")
    if line is None or not line.query_args:
        return None
    try:
        return int(float(line.query_args[0]))
    except ValueError:
        return None


_USB_PRODUCT_MARKERS = (
    "FT230X",
    "FT232",
    "FT2232",
    "FT4232",
    "BASIC UART",
    "USB SERIAL",
    "USB-SERIAL",
)


def is_usb_product_name(name: str | None) -> bool:
    if not name or not name.strip():
        return True
    upper = name.upper()
    return any(marker in upper for marker in _USB_PRODUCT_MARKERS)


def resolve_display_name(
    *,
    ezo_name: str | None = None,
    configured: str | None = None,
    fallback: str = "EZO Complete",
) -> str:
    if ezo_name and ezo_name.strip():
        return ezo_name.strip()
    if configured and not is_usb_product_name(configured):
        return configured.strip()
    return fallback


def unique_id_from_serial(serial_number: str | None, device_type: str) -> str:
    serial = (serial_number or "unknown").strip() or "unknown"
    kind = (device_type or "unknown").strip().lower() or "unknown"
    if kind == "ph":
        kind = "ph"
    return f"{serial}_{kind}"


def _query_line(response: EzoResponse | str, key: str) -> ParsedLine | None:
    if isinstance(response, EzoResponse):
        return response.query(key)
    for raw in _split_raw(response):
        parsed = parse_line(raw)
        if parsed.kind is LineKind.QUERY and (parsed.query_key or "").lower() == key.lower():
            return parsed
    return None


def _split_raw(raw: str) -> list[str]:
    return [part for part in re.split(r"[\r\n]+", raw) if part.strip()]


def _raw_blob(response: EzoResponse | str) -> str:
    if isinstance(response, EzoResponse):
        return "\n".join(response.raw_lines)
    return response
