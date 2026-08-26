"""Coordinator: one stick, one profile, no pH/ORP if/else in I/O."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
import time

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PORT, UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.unit_conversion import TemperatureConverter

from .codec import (
    LineKind,
    ParsedLine,
    command_succeeded,
    compact_export_dump,
    is_export_data_line,
    is_usb_product_name,
    parse_cal_points,
    parse_continuous,
    parse_device_info,
    parse_export_count,
    parse_led,
    parse_name,
    parse_status,
    resolve_display_name,
)
from .const import (
    CONF_BAUDRATE,
    CONF_CONTINUOUS_INTERVAL,
    CONF_CONTINUOUS_ON_START,
    CONF_DEVICE_TYPE,
    CONF_SERIAL_NUMBER,
    CONF_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_BAUDRATE,
    DEFAULT_CONTINUOUS_INTERVAL,
    DEFAULT_CONTINUOUS_ON_START,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FACTORY_ARM_SECONDS,
    RAW_LINE_HISTORY,
    RECONNECT_DELAY,
    RESPONSE_CODE_ENABLE_COMMANDS,
    STABILITY_MIN_SAMPLES,
    STABILITY_WINDOW_S,
    STALE_WAKE_SECONDS,
    TEMPERATURE_PUSH_DELTA,
)
from .export_store import ExportStore
from .models import EzoDeviceState
from .profiles import ProbeProfile, profile_for
from .session import EzoClientError, EzoUnsupportedError, SerialSession
from .stability import StabilityWindow

_LOGGER = logging.getLogger(__name__)


class EzoCoordinator(DataUpdateCoordinator[EzoDeviceState]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = entry.options
        interval = int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.data.get(CONF_NAME) or entry.title or DOMAIN,
            update_interval=timedelta(seconds=max(interval, 1)),
        )
        kind = (entry.data.get(CONF_DEVICE_TYPE) or "orp").lower()
        self.profile: ProbeProfile = profile_for(kind)
        self.entry = entry
        self.session = SerialSession(
            port=entry.data[CONF_PORT],
            baudrate=int(entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
        )
        self.data = EzoDeviceState(
            kind=self.profile.kind,
            port=self.session.port,
            baudrate=self.session.baudrate,
            serial_number=entry.data.get(CONF_SERIAL_NUMBER),
        )
        self._listen_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._temp_unsub = None
        self._unavailable_logged = False
        self._factory_armed_until = 0.0
        self._raw_history: deque[str] = deque(maxlen=RAW_LINE_HISTORY)
        self._pause_listen = False
        self._last_diag_at = 0.0
        self._last_pushed_t: float | None = None
        self.cal_setpoints: dict[str, float] = {
            slot.key: slot.default for slot in self.profile.cal_slots if slot.has_number
        }
        self._stability = StabilityWindow(
            window_s=STABILITY_WINDOW_S,
            min_samples=STABILITY_MIN_SAMPLES,
            span=self.profile.stability_span,
        )
        slug = (self.unique_id or "probe").replace("/", "_")
        self._exports = ExportStore(Path(hass.config.path(DOMAIN)), slug)

    @property
    def unique_id(self) -> str:
        return self.entry.unique_id or self.entry.entry_id

    @property
    def device_name(self) -> str:
        return resolve_display_name(
            ezo_name=self.data.device_name,
            configured=self.entry.data.get(CONF_NAME) or self.entry.title,
            fallback=self.profile.default_name,
        )

    @property
    def continuous_on_start(self) -> bool:
        return bool(
            self.entry.options.get(CONF_CONTINUOUS_ON_START, DEFAULT_CONTINUOUS_ON_START)
        )

    @property
    def configured_continuous_interval(self) -> int:
        return int(
            self.entry.options.get(CONF_CONTINUOUS_INTERVAL, DEFAULT_CONTINUOUS_INTERVAL)
        )

    async def async_setup(self) -> None:
        try:
            await self.session.connect()
            await self._initialize_device()
        except (EzoClientError, OSError, TimeoutError) as err:
            await self.session.disconnect()
            raise ConfigEntryNotReady(f"Cannot open {self.session.port}: {err}") from err
        self._listen_task = self.entry.async_create_background_task(
            self.hass, self._listen_loop(), name=f"{DOMAIN}_listen"
        )
        self._async_track_temperature()
        self._mark_available()

    async def async_shutdown(self) -> None:
        if self._temp_unsub is not None:
            self._temp_unsub()
            self._temp_unsub = None
        for task in (self._listen_task, self._reconnect_task):
            if task is not None:
                task.cancel()
        self._listen_task = None
        self._reconnect_task = None
        await self.session.disconnect()

    async def _async_update_data(self) -> EzoDeviceState:
        if not self.session.connected:
            raise UpdateFailed("EZO Complete is disconnected")
        try:
            if not self.data.continuous:
                await self._async_push_temperature()
                await self._command("R")
            elif time.monotonic() - self._last_diag_at >= 60:
                await self._refresh_diagnostics()
        except EzoClientError as err:
            self._schedule_reconnect()
            raise UpdateFailed(str(err)) from err
        return self.data

    async def async_set_continuous(self, enabled: bool) -> None:
        if enabled:
            interval = self.data.continuous_interval or self.configured_continuous_interval
            await self._command(f"C,{interval}")
        else:
            await self._command("C,0")
        await self._command("C,?", ignore_error=True)
        if self.data.continuous is None:
            state = self.data.copy()
            state.continuous = enabled
            self.async_set_updated_data(state)

    async def async_set_continuous_interval(self, seconds: int) -> None:
        await self._command(f"C,{int(seconds)}")
        await self._command("C,?")

    async def async_set_led(self, enabled: bool) -> None:
        await self._command("L,1" if enabled else "L,0")
        await self._command("L,?", ignore_error=True)
        if self.data.led is None:
            state = self.data.copy()
            state.led = enabled
            self.async_set_updated_data(state)

    async def async_set_extended(self, enabled: bool) -> None:
        cmd = self.profile.extended_command
        await self._command(f"{cmd},1" if enabled else f"{cmd},0")
        await self._command(f"{cmd},?", ignore_error=True)

    def cal_setpoint(self, slot: str) -> float:
        spec = self.profile.slot(slot)
        if spec is not None and spec.fixed_value is not None:
            return spec.fixed_value
        if slot in self.cal_setpoints:
            return self.cal_setpoints[slot]
        if spec is not None:
            return spec.default
        raise KeyError(slot)

    def set_cal_setpoint(self, slot: str, value: float) -> None:
        self.cal_setpoints[slot] = value

    async def async_calibrate(self, slot: str) -> None:
        value = self.cal_setpoint(slot)
        command = self.profile.cal_set_command(slot, value)
        await self._async_run_calibration(command)

    async def async_calibrate_clear(self) -> None:
        await self._async_run_calibration("Cal,clear")

    @asynccontextmanager
    async def _hold_stream(self, *, restore: bool = True) -> AsyncIterator[None]:
        resume = restore and self.data.continuous is not False
        interval = self.data.continuous_interval or self.configured_continuous_interval
        held = self._pause_listen
        self._pause_listen = True
        try:
            await self._command("C,0", ignore_error=True)
            await asyncio.sleep(0.2)
            yield
        finally:
            try:
                if resume:
                    await self._command(f"C,{interval}", ignore_error=True)
                    await self._command("C,?", ignore_error=True)
            finally:
                self._pause_listen = held

    async def _async_run_calibration(self, cal_command: str) -> None:
        try:
            async with self._hold_stream():
                await self._async_push_temperature()
                cal = await self._command(cal_command)
                if cal.error_code:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="command_failed",
                        translation_placeholders={
                            "command": cal_command,
                            "error": cal.error_code,
                        },
                    )
                query = await self._command("Cal,?")
                points = parse_cal_points(query)
                reading = await self._command("R", ignore_error=True)
                value = reading.first_reading() if reading is not None else self.data.reading
                state = self.data.copy()
                if points is not None:
                    state.cal_points = points
                if value is not None:
                    state.reading = value
                self.async_set_updated_data(state)
                _LOGGER.info(
                    "Calibration %s done: Cal,?=%s reading=%s",
                    cal_command,
                    points,
                    value,
                )
                self._notify(
                    f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                    "EZO Complete — calibration",
                    f"{cal_command} OK — Cal,?={points}, {self.profile.reading_key}={value}",
                )
        except HomeAssistantError as err:
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                "EZO Complete — calibration",
                f"{cal_command} failed: {err}",
            )
            raise

    async def async_set_sleeping(self, enabled: bool) -> None:
        """Sleep is assumed-state: Atlas has no Sleep,? query."""
        if enabled:
            await self._command("Sleep")
            state = self.data.copy()
            state.sleeping = True
            self.async_set_updated_data(state)
            return
        await self.session.wake()
        state = self.data.copy()
        state.sleeping = False
        self.async_set_updated_data(state)
        await self._command("Status", ignore_error=True)
        if not self.data.continuous:
            await self._command("R", ignore_error=True)

    async def async_find(self) -> None:
        await self._command("Find")

    async def async_set_device_name(self, name: str) -> None:
        cleaned = name.strip()[:16]
        await self._command(f"Name,{cleaned}" if cleaned else "Name,")
        await self._command("Name,?")

    async def async_factory_reset(self, *, confirm: bool = False) -> None:
        now = time.monotonic()
        if not confirm and now > self._factory_armed_until:
            self._factory_armed_until = now + FACTORY_ARM_SECONDS
            state = self.data.copy()
            state.factory_armed = True
            self.async_set_updated_data(state)
            _LOGGER.warning("Factory reset armed for %s s", FACTORY_ARM_SECONDS)
            return
        self._factory_armed_until = 0.0
        try:
            async with self._hold_stream(restore=False):
                await self._command("Factory", ignore_error=True)
                await asyncio.sleep(2.5)
                await self._command("C,0", ignore_error=True)
                await asyncio.sleep(0.3)
                await self._initialize_device()
        except (EzoUnsupportedError, EzoClientError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"command": "Factory", "error": str(err)},
            ) from err
        self._notify(
            f"{DOMAIN}_{self.entry.entry_id}_factory",
            "EZO Complete",
            "Factory reset OK — circuit réidentifié.",
        )

    async def async_export_calibration(self) -> str:
        async with self._hold_stream():
            first = await self._command("Export")
            count = parse_export_count(first)
            raw_chunks: list[str] = list(first.raw_lines)
            remaining = count if count is not None else 8
            for _ in range(max(remaining, 0) + 1):
                response = await self._command("Export", ignore_error=True)
                if not response.raw_lines:
                    break
                raw_chunks.extend(response.raw_lines)
                if response.query("export") and parse_export_count(response) == 0:
                    break
                cycle = compact_export_dump(raw_chunks)
                if count is not None and len(cycle) >= count:
                    break
                if count is None and len(cycle) >= 2:
                    data_lines = [
                        line.strip()
                        for line in raw_chunks
                        if is_export_data_line(line)
                    ]
                    if data_lines.count(cycle[0]) > 1:
                        break
            payload = "\n".join(compact_export_dump(raw_chunks)).strip()
            if not payload:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"command": "Export", "error": "empty"},
                )
            now = datetime.now(UTC).replace(microsecond=0)

            def _write() -> tuple[str, str]:
                return self._exports.write(payload, now=now)

            archive, restore = await self.hass.async_add_executor_job(_write)
            state = self.data.copy()
            state.export_data = payload
            state.export_at = now.isoformat()
            state.export_path = archive
            state.restore_path = restore
            self.async_set_updated_data(state)
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_export",
                "EZO Complete — export calibration",
                f"Archive : {archive}\nRestore : {restore}\n\n{payload}",
            )
            return payload

    async def async_import_calibration(self, payload: str) -> None:
        lines = compact_export_dump(payload.splitlines())
        if not lines:
            lines = [line.strip() for line in payload.splitlines() if line.strip()]
        if not lines:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="import_empty"
            )
        async with self._hold_stream():
            for line in lines:
                cmd = line if line.lower().startswith("import") else f"Import,{line}"
                await self._command(cmd)
            await self._command("Cal,?")

    async def async_restore_calibration(self) -> str:
        path = self._exports.restore_path
        payload = await self.hass.async_add_executor_job(self._exports.read_restore)
        if payload is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restore_missing",
                translation_placeholders={"path": str(path)},
            )
        await self.async_import_calibration(payload)
        state = self.data.copy()
        state.restore_path = str(path)
        self.async_set_updated_data(state)
        self._notify(
            f"{DOMAIN}_{self.entry.entry_id}_restore",
            "EZO Complete — restore",
            f"Calibration réécrite depuis {path}",
        )
        return payload

    async def async_send_raw(self, command: str) -> str:
        response = await self._command(command)
        return "\n".join(response.raw_lines)

    def _async_track_temperature(self) -> None:
        if not self.profile.supports_temperature:
            return
        entity_id = self.entry.options.get(CONF_TEMPERATURE_ENTITY)
        if not entity_id:
            return

        @callback
        def _on_temp(event: Event) -> None:
            self.hass.async_create_task(self._async_push_temperature())

        self._temp_unsub = async_track_state_change_event(
            self.hass, [entity_id], _on_temp
        )
        self.hass.async_create_task(self._async_push_temperature())

    async def _async_push_temperature(self) -> None:
        if not self.profile.supports_temperature:
            return
        entity_id = self.entry.options.get(CONF_TEMPERATURE_ENTITY)
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable", ""}:
            return
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return
        unit = state.attributes.get("unit_of_measurement")
        if unit and unit != UnitOfTemperature.CELSIUS:
            try:
                value = TemperatureConverter.convert(
                    value, unit, UnitOfTemperature.CELSIUS
                )
            except Exception:  # noqa: BLE001
                return
        if (
            self._last_pushed_t is not None
            and abs(value - self._last_pushed_t) < TEMPERATURE_PUSH_DELTA
        ):
            return
        await self._command(f"T,{value:.2f}", ignore_error=True)
        self._last_pushed_t = value
        await self._command("T,?", ignore_error=True)

    async def _initialize_device(self) -> None:
        info = await self.session.identify()
        profile = profile_for(info.kind)
        if profile.kind != self.profile.kind:
            self.cal_setpoints = {
                slot.key: slot.default for slot in profile.cal_slots if slot.has_number
            }
        self.profile = profile
        self._stability = StabilityWindow(
            window_s=STABILITY_WINDOW_S,
            min_samples=STABILITY_MIN_SAMPLES,
            span=profile.stability_span,
        )
        self._last_pushed_t = None
        state = self.data.copy()
        state.kind = self.profile.kind
        state.device_type = info.device_type
        state.firmware = info.firmware
        state.sleeping = False
        state.factory_armed = False
        self.async_set_updated_data(state)
        await self._command("C,0", ignore_error=True)
        await self._enable_response_codes()
        if self.continuous_on_start:
            await self._command(
                f"C,{self.configured_continuous_interval}", ignore_error=True
            )
        await self._refresh_diagnostics()
        self._last_diag_at = time.monotonic()
        if not self.data.continuous:
            await self._async_push_temperature()
            await self._command("R", ignore_error=True)

    async def _enable_response_codes(self) -> None:
        for cmd in RESPONSE_CODE_ENABLE_COMMANDS:
            response = await self._command(cmd, ignore_error=True)
            if response is not None and response.ok:
                return

    async def _refresh_diagnostics(self) -> None:
        for cmd in self.profile.diagnostic_queries():
            await self._command(cmd, ignore_error=True)

    async def _command(self, cmd: str, *, ignore_error: bool = False):
        if not self.session.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            )
        held = self._pause_listen
        self._pause_listen = True
        try:
            if cmd.split(",", 1)[0].lower() != "sleep" and self._needs_wake():
                _LOGGER.info("EZO UART idle — waking before %s", cmd)
                await self.session.wake()
            verb = cmd.split(",", 1)[0].lower()
            log = (
                _LOGGER.info
                if verb in {"cal", "c", "factory", "l", "find", "export", "t"}
                else _LOGGER.debug
            )
            log("EZO >> %s", cmd)
            response = await self.session.command(cmd)
            if not command_succeeded(response) and not response.error_code:
                _LOGGER.info("EZO %s empty — wake and retry", cmd)
                await self.session.wake()
                response = await self.session.command(cmd)
            log("EZO << %s", " | ".join(response.raw_lines) if response.raw_lines else "<empty>")
        except EzoClientError as err:
            self._schedule_reconnect()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"command": cmd, "error": str(err)},
            ) from err
        finally:
            if not held:
                self._pause_listen = False

        if cmd.split(",", 1)[0].lower() == "sleep":
            return response
        self._apply_lines(response.lines, last_command=cmd)
        if command_succeeded(response):
            return response
        if ignore_error:
            return response
        if not response.raw_lines:
            self._schedule_reconnect()
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={
                "command": cmd,
                "error": response.error_code or "timeout",
            },
        )

    def _needs_wake(self) -> bool:
        if self.data.sleeping:
            return True
        last = self.session.last_rx_at
        if last is None:
            return True
        return (time.monotonic() - last) >= STALE_WAKE_SECONDS

    async def _listen_loop(self) -> None:
        while True:
            try:
                if self._pause_listen or not self.session.connected:
                    await asyncio.sleep(0.2)
                    continue
                if self.data.sleeping or self.data.continuous is False:
                    await asyncio.sleep(0.5)
                    continue
                lines = await self.session.listen(0.4)
                if lines:
                    self._apply_lines(lines)
                    self._mark_available()
            except asyncio.CancelledError:
                raise
            except (EzoClientError, OSError, TimeoutError) as err:
                _LOGGER.debug("Listen loop error: %s", err)
                self._schedule_reconnect()
                await asyncio.sleep(RECONNECT_DELAY)

    def _apply_lines(
        self, lines: list[ParsedLine], last_command: str | None = None
    ) -> None:
        if not lines:
            return
        state = self.data.copy()
        for line in lines:
            self._raw_history.append(line.raw)
            if line.kind is LineKind.READING and line.value is not None:
                state.reading = line.value
                state.sleeping = False
                self._update_stability(state, line.value)
            elif line.kind is LineKind.QUERY:
                self._apply_query(state, line)
            elif line.status_code == "SL":
                state.sleeping = True
            elif line.status_code == "WA":
                state.sleeping = False
        state.reading_source = "calibrated" if state.cal_points else "factory"
        state.last_raw = lines[-1].raw
        state.last_lines = list(self._raw_history)
        state.factory_armed = time.monotonic() <= self._factory_armed_until
        if last_command and last_command.split(",", 1)[0].lower() != "sleep":
            state.sleeping = False
        self.async_set_updated_data(state)

    def _update_stability(self, state: EzoDeviceState, value: float) -> None:
        snap = self._stability.push(value, time.monotonic())
        state.reading_min = snap.minimum
        state.reading_max = snap.maximum
        state.reading_span = snap.span
        state.reading_stable = snap.stable

    def _apply_query(self, state: EzoDeviceState, line: ParsedLine) -> None:
        if self.profile.apply_query(state, line):
            return
        key = (line.query_key or "").lower()
        raw = line.raw
        if key == "i":
            info = parse_device_info(raw)
            if info:
                state.device_type = info.device_type
                state.firmware = info.firmware
                state.kind = info.kind
        elif key == "c":
            cont = parse_continuous(raw)
            if cont:
                state.continuous = cont.enabled
                state.continuous_interval = cont.interval or state.continuous_interval
        elif key == "cal":
            points = parse_cal_points(raw)
            if points is not None:
                state.cal_points = points
        elif key == "l":
            led = parse_led(raw)
            if led is not None:
                state.led = led
        elif key == "status":
            status = parse_status(raw)
            if status:
                state.status_reason = status.reason
                state.status_reason_code = status.reason_code
                state.status_voltage = status.voltage
        elif key == "name":
            name = parse_name(raw)
            if name is not None:
                state.device_name = name

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._mark_unavailable()
        self._reconnect_task = self.entry.async_create_background_task(
            self.hass, self._reconnect_loop(), name=f"{DOMAIN}_reconnect"
        )

    async def _reconnect_loop(self) -> None:
        while True:
            try:
                await self.session.disconnect()
                await asyncio.sleep(RECONNECT_DELAY)
                await self.session.connect()
                await self._initialize_device()
            except asyncio.CancelledError:
                raise
            except (EzoClientError, OSError, TimeoutError) as err:
                _LOGGER.debug("Reconnect to %s failed: %s", self.session.port, err)
                continue
            self._mark_available()
            return

    def _mark_unavailable(self) -> None:
        if not self._unavailable_logged:
            _LOGGER.warning("EZO Complete disconnected (%s)", self.session.port)
            self._unavailable_logged = True
        self.last_update_success = False
        self.async_update_listeners()

    def _mark_available(self) -> None:
        if self._unavailable_logged:
            _LOGGER.info("EZO Complete reconnected (%s)", self.session.port)
            self._unavailable_logged = False
        self.last_update_success = True
        self.async_update_listeners()

    def _notify(self, nid: str, title: str, message: str) -> None:
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=nid
        )

    def async_sync_device_name(self) -> None:
        name = self.device_name
        configured = self.entry.data.get(CONF_NAME) or self.entry.title
        if is_usb_product_name(configured) or is_usb_product_name(self.entry.title):
            self.hass.config_entries.async_update_entry(
                self.entry, title=name, data={**self.entry.data, CONF_NAME: name}
            )
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.unique_id)})
        if device is not None and device.name_by_user is None and device.name != name:
            registry.async_update_device(device.id, name=name)
