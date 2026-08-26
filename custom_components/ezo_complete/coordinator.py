"""Coordinator: one stick, one profile, no pH/ORP if/else in I/O."""

from __future__ import annotations

import asyncio
from collections import deque
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
    is_usb_product_name,
    parse_cal_points,
    parse_continuous,
    parse_device_info,
    compact_export_dump,
    is_export_data_line,
    parse_export_count,
    parse_flag,
    parse_led,
    parse_name,
    parse_slope,
    parse_status,
    parse_temperature,
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
    DEFAULT_ORP_CALIBRATION,
    DEFAULT_PH_HIGH,
    DEFAULT_PH_LOW,
    DEFAULT_PH_MID,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FACTORY_ARM_SECONDS,
    IMPORT_CALIBRATION_SUFFIX,
    ORP_STABLE_SPAN,
    PH_STABLE_SPAN,
    RAW_LINE_HISTORY,
    STABILITY_MIN_SAMPLES,
    STABILITY_WINDOW_S,
    RECONNECT_DELAY,
    RESPONSE_CODE_ENABLE_COMMANDS,
    STALE_WAKE_SECONDS,
)
from .models import EzoDeviceState
from .profiles import ProbeProfile, profile_for
from .session import EzoClientError, EzoUnsupportedError, SerialSession

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
        self.pending_orp_cal = DEFAULT_ORP_CALIBRATION
        self.pending_ph_mid = DEFAULT_PH_MID
        self.pending_ph_low = DEFAULT_PH_LOW
        self.pending_ph_high = DEFAULT_PH_HIGH
        self._reading_window: deque[tuple[float, float]] = deque()

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

    async def async_calibrate(self, slot: str, value: float) -> None:
        command = self.profile.cal_set_command(slot, value)
        await self._async_run_calibration(command, expect_points=True)

    async def async_calibrate_clear(self) -> None:
        await self._async_run_calibration("Cal,clear", expect_points=False)

    async def _async_run_calibration(self, cal_command: str, *, expect_points: bool) -> None:
        resume = self.data.continuous is not False
        interval = self.data.continuous_interval or self.configured_continuous_interval
        try:
            await self._command("C,0", ignore_error=True)
            await asyncio.sleep(0.2)
            await self._async_push_temperature()
            cal = await self._command(cal_command)
            if not cal.ok and cal.error_code:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"command": cal_command, "error": cal.error_code},
                )
            query = await self._command("Cal,?")
            points = parse_cal_points(query)
            if points is None:
                points = 1 if expect_points else 0
            reading = await self._command("R", ignore_error=True)
            orp_or_ph = reading.first_reading() if reading is not None else self.data.reading
            state = self.data.copy()
            state.cal_points = points
            if orp_or_ph is not None:
                state.reading = orp_or_ph
            self.async_set_updated_data(state)
            _LOGGER.info(
                "Calibration %s done: Cal,?=%s reading=%s",
                cal_command,
                points,
                orp_or_ph,
            )
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                "EZO Complete — calibration",
                f"{cal_command} OK — Cal,?={points}, {self.profile.reading_key}={orp_or_ph}",
            )
        except HomeAssistantError as err:
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                "EZO Complete — calibration",
                f"{cal_command} failed: {err}",
            )
            raise
        finally:
            if resume:
                await self._command(f"C,{interval}", ignore_error=True)
                await self._command("C,?", ignore_error=True)

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
            await self._command("C,0", ignore_error=True)
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
        resume = self.data.continuous is not False
        interval = self.data.continuous_interval or self.configured_continuous_interval
        try:
            await self._command("C,0", ignore_error=True)
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
                    # Wrapped: first hex line appeared again.
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
            exported_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            archive, restore = await self.hass.async_add_executor_job(
                self._write_export_file, payload
            )
            state = self.data.copy()
            state.export_data = payload
            state.export_at = exported_at
            state.export_path = archive
            state.restore_path = restore
            self.async_set_updated_data(state)
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_export",
                "EZO Complete — export calibration",
                f"Archive : {archive}\nRestore : {restore}\n\n{payload}",
            )
            return payload
        finally:
            if resume:
                await self._command(f"C,{interval}", ignore_error=True)

    def _export_folder(self) -> Path:
        return Path(self.hass.config.path(DOMAIN))

    def _restore_file(self) -> Path:
        slug = (self.unique_id or "probe").replace("/", "_")
        return self._export_folder() / f"{slug}.{IMPORT_CALIBRATION_SUFFIX}"

    def _write_export_file(self, payload: str) -> tuple[str, str]:
        folder = self._export_folder()
        folder.mkdir(parents=True, exist_ok=True)
        slug = (self.unique_id or "probe").replace("/", "_")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        archive = folder / f"{slug}_calibration_{stamp}.txt"
        restore = self._restore_file()
        text = payload.rstrip() + "\n"
        archive.write_text(text, encoding="ascii")
        restore.write_text(text, encoding="ascii")
        return str(archive), str(restore)

    async def async_import_calibration(self, payload: str) -> None:
        lines = compact_export_dump(payload.splitlines())
        if not lines:
            lines = [line.strip() for line in payload.splitlines() if line.strip()]
        if not lines:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="import_empty"
            )
        resume = self.data.continuous is not False
        interval = self.data.continuous_interval or self.configured_continuous_interval
        try:
            await self._command("C,0", ignore_error=True)
            for line in lines:
                cmd = line if line.lower().startswith("import") else f"Import,{line}"
                await self._command(cmd)
            await self._command("Cal,?")
        finally:
            if resume:
                await self._command(f"C,{interval}", ignore_error=True)

    async def async_restore_calibration(self) -> str:
        path = self._restore_file()

        def _read() -> str | None:
            if not path.is_file():
                return None
            text = path.read_text(encoding="ascii", errors="ignore").strip()
            return text or None

        payload = await self.hass.async_add_executor_job(_read)
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
        await self._command(f"T,{value:.2f}", ignore_error=True)
        await self._command("T,?", ignore_error=True)

    async def _initialize_device(self) -> None:
        info = await self.session.identify()
        self.profile = profile_for(info.kind)
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
        now = time.monotonic()
        self._reading_window.append((now, value))
        cutoff = now - STABILITY_WINDOW_S
        while self._reading_window and self._reading_window[0][0] < cutoff:
            self._reading_window.popleft()
        values = [sample for _, sample in self._reading_window]
        if not values:
            state.reading_min = None
            state.reading_max = None
            state.reading_span = None
            state.reading_stable = False
            return
        state.reading_min = min(values)
        state.reading_max = max(values)
        state.reading_span = state.reading_max - state.reading_min
        threshold = PH_STABLE_SPAN if self.profile.kind == "ph" else ORP_STABLE_SPAN
        state.reading_stable = (
            len(values) >= STABILITY_MIN_SAMPLES and state.reading_span <= threshold
        )

    def _apply_query(self, state: EzoDeviceState, line: ParsedLine) -> None:
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
        elif key in {"orpext", "phext"}:
            flag = parse_flag(raw, key)
            if flag is not None:
                state.extended_scale = flag
        elif key == "t":
            temp = parse_temperature(raw)
            if temp is not None:
                state.temperature = temp
        elif key == "slope":
            slope = parse_slope(raw)
            if slope:
                state.slope_acid = slope[0] if slope else None
                state.slope_base = slope[1] if len(slope) > 1 else None

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
