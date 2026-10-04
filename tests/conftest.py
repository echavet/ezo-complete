"""Pytest fixtures for EZO Complete unit tests.

This file contains only pure Python fixtures that don't require Home Assistant.
It avoids importing from custom_components to keep CI simple.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class LineKind(Enum):
    """Line kind enum for fake responses."""
    STATUS = auto()
    QUERY = auto()
    READING = auto()


@dataclass(slots=True)
class ParsedLine:
    """Parsed line from EZO response."""
    raw: str
    kind: LineKind
    value: float | None = None
    query_key: str | None = None
    status_code: str | None = None


@dataclass(slots=True)
class EzoResponse:
    """EZO command response."""
    command: str
    lines: list[ParsedLine]

    @property
    def ok(self) -> bool:
        return any(
            line.kind is LineKind.STATUS and line.status_code == "OK"
            for line in self.lines
        )

    @property
    def raw_lines(self) -> list[str]:
        return [line.raw for line in self.lines]


@dataclass(slots=True)
class DeviceInfoResponse:
    """Device info response."""
    device_type: str
    firmware: str
    raw: str

    @property
    def kind(self) -> str:
        token = (self.device_type or "").strip().lower()
        if token in {"ph", "orp"}:
            return token
        return "unknown"


class FakeSerialSession:
    """Fake serial session for testing without real hardware."""

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 9600) -> None:
        self.port = port
        self.baudrate = baudrate
        self._connected = False
        self.last_rx_at: float | None = None
        self.commands_sent: list[str] = []
        self._readings: list[float] = [7.00, 7.01, 7.02]
        self._reading_idx = 0
        self._device_type = "pH"
        self._firmware = "2.15"
        self._continuous = False
        self._continuous_interval = 1
        self._cal_points = 0
        self._led = True

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def command(self, cmd: str, timeout: float | None = None) -> EzoResponse:
        self.commands_sent.append(cmd)
        lowered = cmd.lower().strip()

        if lowered == "i":
            return self._info_response()
        elif lowered.startswith("c,"):
            return self._continuous_response(cmd)
        elif lowered == "c,?":
            return self._continuous_query_response()
        elif lowered == "r":
            return self._reading_response()
        elif lowered == "cal,?":
            return self._cal_query_response()
        elif lowered.startswith("cal,"):
            return self._cal_response(cmd)
        elif lowered == "l,?":
            return self._led_query_response()
        elif lowered.startswith("l,"):
            return self._led_response(cmd)
        elif lowered == "*ok,1" or lowered == "response,1":
            return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])
        elif lowered == "status":
            return self._status_response()
        elif lowered.startswith("t,"):
            return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])
        elif lowered == "slope,?":
            return self._slope_response()
        else:
            return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])

    async def listen(self, timeout: float) -> list[ParsedLine]:
        if self._continuous:
            reading = self._next_reading()
            return [ParsedLine(f"{reading:.2f}", LineKind.READING, value=reading)]
        return []

    async def wake(self) -> None:
        pass

    async def identify(
        self, timeout: float = 2.0, retries: int = 3
    ) -> DeviceInfoResponse:
        return DeviceInfoResponse(
            device_type=self._device_type,
            firmware=self._firmware,
            raw=f"?I,{self._device_type},{self._firmware}",
        )

    def _next_reading(self) -> float:
        reading = self._readings[self._reading_idx % len(self._readings)]
        self._reading_idx += 1
        return reading

    def _info_response(self) -> EzoResponse:
        return EzoResponse(
            command="i",
            lines=[ParsedLine(f"?I,{self._device_type},{self._firmware}", LineKind.QUERY, query_key="I")],
        )

    def _continuous_response(self, cmd: str) -> EzoResponse:
        parts = cmd.split(",")
        if len(parts) >= 2:
            val = parts[1].strip()
            if val == "0":
                self._continuous = False
            else:
                self._continuous = True
                try:
                    self._continuous_interval = int(val)
                except ValueError:
                    pass
        return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])

    def _continuous_query_response(self) -> EzoResponse:
        if self._continuous:
            return EzoResponse(
                command="C,?",
                lines=[ParsedLine(f"?C,{self._continuous_interval}", LineKind.QUERY, query_key="C")],
            )
        return EzoResponse(
            command="C,?",
            lines=[ParsedLine("?C,0", LineKind.QUERY, query_key="C")],
        )

    def _reading_response(self) -> EzoResponse:
        reading = self._next_reading()
        return EzoResponse(
            command="R",
            lines=[ParsedLine(f"{reading:.2f}", LineKind.READING, value=reading)],
        )

    def _cal_query_response(self) -> EzoResponse:
        return EzoResponse(
            command="Cal,?",
            lines=[ParsedLine(f"?Cal,{self._cal_points}", LineKind.QUERY, query_key="Cal")],
        )

    def _cal_response(self, cmd: str) -> EzoResponse:
        if "mid" in cmd.lower():
            self._cal_points = max(1, self._cal_points)
        elif "low" in cmd.lower() or "high" in cmd.lower():
            self._cal_points = min(3, self._cal_points + 1)
        elif "clear" in cmd.lower():
            self._cal_points = 0
        return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])

    def _led_query_response(self) -> EzoResponse:
        return EzoResponse(
            command="L,?",
            lines=[ParsedLine(f"?L,{1 if self._led else 0}", LineKind.QUERY, query_key="L")],
        )

    def _led_response(self, cmd: str) -> EzoResponse:
        self._led = "1" in cmd
        return EzoResponse(command=cmd, lines=[ParsedLine("*OK", LineKind.STATUS, status_code="OK")])

    def _status_response(self) -> EzoResponse:
        return EzoResponse(
            command="Status",
            lines=[ParsedLine("?Status,P,5.0", LineKind.QUERY, query_key="Status")],
        )

    def _slope_response(self) -> EzoResponse:
        return EzoResponse(
            command="Slope,?",
            lines=[ParsedLine("?Slope,99.7,100.3,0.0", LineKind.QUERY, query_key="Slope")],
        )

    def set_readings(self, readings: list[float]) -> None:
        self._readings = readings
        self._reading_idx = 0


@pytest.fixture
def fake_serial_session() -> FakeSerialSession:
    """Create a fake serial session."""
    return FakeSerialSession()
