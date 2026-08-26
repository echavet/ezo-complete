"""Serial session: one exclusive UART, one lock, no probe semantics."""

from __future__ import annotations

import asyncio
import logging
import time

from .codec import (
    CR,
    DeviceInfoResponse,
    EzoResponse,
    LineKind,
    ParsedLine,
    ReplyKind,
    encode_command,
    expected_reply,
    parse_device_info,
    parse_line,
    reply_is_complete,
)
from .const import (
    COMMAND_TIMEOUT,
    FIND_TIMEOUT,
    OPEN_SETTLE,
    READ_COMMAND_TIMEOUT,
    WAKE_SETTLE,
)

_LOGGER = logging.getLogger(__name__)
_REBOOT = {"factory"}


class EzoClientError(Exception):
    """Serial I/O or unexpected device reply."""


class EzoUnsupportedError(EzoClientError):
    """Circuit is not a supported EZO Complete probe (pH / ORP)."""


class SerialSession:
    """Talk to one EZO Complete stick. Probe type is not this class's job."""

    def __init__(self, port: str, baudrate: int = 9600) -> None:
        self.port = port
        self.baudrate = baudrate
        self._serial: object | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self.last_rx_at: float | None = None

    @property
    def connected(self) -> bool:
        return self._connected and self._serial is not None

    async def connect(self) -> None:
        import serialx

        if self.connected:
            return
        serial = serialx.async_serial_for_url(
            self.port, baudrate=self.baudrate, exclusive=True
        )
        await serial.open()
        self._serial = serial
        self._connected = True
        await asyncio.sleep(OPEN_SETTLE)
        await self._drain_unlocked(0.25)
        _LOGGER.debug("Opened EZO serial %s @ %s", self.port, self.baudrate)

    async def disconnect(self) -> None:
        serial = self._serial
        self._serial = None
        self._connected = False
        if serial is None:
            return
        close = getattr(serial, "close", None)
        if close is None:
            return
        try:
            await close()
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("Error closing %s: %s", self.port, err)

    async def command(self, cmd: str, timeout: float | None = None) -> EzoResponse:
        async with self._lock:
            return await self._command_unlocked(cmd, timeout)

    async def listen(self, timeout: float) -> list[ParsedLine]:
        async with self._lock:
            return await self._read_lines_unlocked(timeout)

    async def wake(self) -> None:
        async with self._lock:
            await self._write_unlocked(b"\r")
            await asyncio.sleep(WAKE_SETTLE)
            await self._drain_unlocked(0.3)

    async def identify(
        self, timeout: float = COMMAND_TIMEOUT, retries: int = 3
    ) -> DeviceInfoResponse:
        """Wake, stop stream, ``i``, accept pH or ORP only."""
        await self.wake()
        last_raw = "<empty>"
        for attempt in range(max(retries, 1)):
            try:
                await self.command("C,0", timeout=timeout)
            except EzoClientError:
                pass
            async with self._lock:
                await self._drain_unlocked(0.6)
            response = await self.command("i", timeout=timeout)
            last_raw = " | ".join(response.raw_lines) or "<empty>"
            info = parse_device_info(response)
            if info is not None and info.is_supported:
                return info
            _LOGGER.info("identify %s/%s: %s", attempt + 1, retries, last_raw)
            await asyncio.sleep(0.4)
        raise EzoUnsupportedError(f"Not an EZO Complete pH/ORP circuit: {last_raw}")

    async def _command_unlocked(
        self, cmd: str, timeout: float | None = None
    ) -> EzoResponse:
        if not self.connected:
            raise EzoClientError("Serial port is not open")
        name = cmd.strip()
        lowered = name.split(",", 1)[0].lower()
        if timeout is None:
            if lowered == "r":
                timeout = READ_COMMAND_TIMEOUT
            elif lowered == "find":
                timeout = FIND_TIMEOUT
            else:
                timeout = COMMAND_TIMEOUT
        drain_s = 0.5 if lowered in {"c", "i", "factory"} else 0.05
        await self._drain_unlocked(drain_s)
        await self._write_unlocked(encode_command(name))
        if expected_reply(name) is ReplyKind.SILENT:
            return EzoResponse(command=name)
        lines = await self._read_lines_unlocked(timeout, command=name)
        if lowered in _REBOOT:
            await asyncio.sleep(OPEN_SETTLE)
            lines.extend(await self._read_lines_unlocked(1.0, command=name))
        return EzoResponse(command=name, lines=lines)

    async def _write_unlocked(self, data: bytes) -> None:
        serial = self._require_serial()
        try:
            await serial.write(data)
            flush = getattr(serial, "flush", None)
            if flush is not None:
                await flush()
        except (OSError, TimeoutError) as err:
            self._connected = False
            raise EzoClientError(f"Write failed on {self.port}: {err}") from err

    async def _read_lines_unlocked(
        self, timeout: float, command: str | None = None
    ) -> list[ParsedLine]:
        serial = self._require_serial()
        lines: list[ParsedLine] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(timeout, 0.05)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(serial.readuntil(CR), timeout=remaining)
            except TimeoutError:
                break
            except asyncio.CancelledError:
                raise
            except (OSError, EOFError) as err:
                self._connected = False
                raise EzoClientError(f"Read failed on {self.port}: {err}") from err
            text = raw.decode("ascii", errors="ignore").strip("\r\n\x00 ").strip()
            if not text:
                continue
            parsed = parse_line(text)
            lines.append(parsed)
            self.last_rx_at = time.monotonic()
            _LOGGER.debug("EZO %s << %s", self.port, text)
            if reply_is_complete(lines, command):
                if parsed.kind is not LineKind.STATUS:
                    extra = await self._read_one_unlocked(0.15)
                    if extra is not None:
                        lines.append(extra)
                break
        return lines

    async def _read_one_unlocked(self, timeout: float) -> ParsedLine | None:
        serial = self._require_serial()
        try:
            raw = await asyncio.wait_for(serial.readuntil(CR), timeout=timeout)
        except (TimeoutError, OSError):
            return None
        text = raw.decode("ascii", errors="ignore").strip("\r\n\x00 ").strip()
        return parse_line(text) if text else None

    async def _drain_unlocked(self, timeout: float) -> None:
        try:
            await self._read_lines_unlocked(timeout)
        except EzoClientError:
            return

    def _require_serial(self):
        serial = self._serial
        if serial is None:
            self._connected = False
            raise EzoClientError("Serial port is not open")
        return serial


async def probe_ezo(
    port: str, baudrate: int = 9600, timeout: float = COMMAND_TIMEOUT
) -> DeviceInfoResponse:
    session = SerialSession(port, baudrate=baudrate)
    try:
        await session.connect()
        return await session.identify(timeout=timeout)
    finally:
        await session.disconnect()
