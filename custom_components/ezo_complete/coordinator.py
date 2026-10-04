"""Coordinator: one stick, one profile, two operating modes."""

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
    is_reading_in_range,
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
    CONF_CALIBRATION_AUTO_RETURN,
    CONF_CONTINUOUS_INTERVAL,
    CONF_DEVICE_TYPE,
    CONF_FILTER_TYPE,
    CONF_FILTER_WINDOW,
    CONF_MEASUREMENT_INTERVAL,
    CONF_MODE,
    CONF_SERIAL_NUMBER,
    CONF_SLEEP,
    CONF_STABILITY_MAX_SPAN,
    CONF_STABILITY_WINDOW,
    CONF_TEMPERATURE_ENTITY,
    DEFAULT_BAUDRATE,
    DEFAULT_CALIBRATION_AUTO_RETURN,
    DEFAULT_CALIBRATION_INTERVAL,
    DEFAULT_FILTER_TYPE,
    DEFAULT_FILTER_WINDOW,
    DEFAULT_MEASUREMENT_INTERVAL,
    DEFAULT_MODE,
    DEFAULT_ORP_STABILITY_SPAN,
    DEFAULT_PH_STABILITY_SPAN_MV,
    DEFAULT_SLEEP,
    DEFAULT_STABILITY_WINDOW,
    DOMAIN,
    FACTORY_ARM_SECONDS,
    FILTER_NONE,
    MODE_CALIBRATION,
    MODE_EXPLOITATION,
    NERNST_MV_PER_PH,
    RAW_LINE_HISTORY,
    RECONNECT_DELAY,
    RESPONSE_CODE_ENABLE_COMMANDS,
    STABILITY_MIN_SAMPLES,
    STABILITY_MIN_SAMPLES_CEILING,
    STABILITY_MIN_SAMPLES_FLOOR,
    STALE_WAKE_SECONDS,
    TEMPERATURE_PUSH_DELTA,
)
from .export_store import ExportStore
from .filter import ReadingFilter
from .models import EzoDeviceState
from .profiles import ProbeProfile, profile_for
from .registry import async_get_entry_device
from .session import EzoClientError, EzoUnsupportedError, SerialSession
from .stability import StabilityWindow

_LOGGER = logging.getLogger(__name__)


class EzoCoordinator(DataUpdateCoordinator[EzoDeviceState]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = entry.options
        interval = int(options.get(CONF_MEASUREMENT_INTERVAL, DEFAULT_MEASUREMENT_INTERVAL))
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
        self._options_unsub = None
        self._prev_options: dict = dict(entry.options)
        self._unavailable_logged = False
        self._factory_armed_until = 0.0
        self._raw_history: deque[str] = deque(maxlen=RAW_LINE_HISTORY)
        self._pause_listen = False
        self._hold_lock = asyncio.Lock()
        self._hold_owner: asyncio.Task[object] | None = None
        self._last_diag_at = 0.0
        self._last_pushed_t: float | None = None
        self._auto_return_task: asyncio.Task[None] | None = None
        self._auto_return_deadline: float = 0.0
        self._next_poll_time: float = 0.0
        self.cal_setpoints: dict[str, float] = {
            slot.key: slot.default for slot in self.profile.cal_slots if slot.has_number
        }
        stability_window = float(options.get(CONF_STABILITY_WINDOW, DEFAULT_STABILITY_WINDOW))
        stability_span_mv = float(options.get(
            CONF_STABILITY_MAX_SPAN,
            DEFAULT_PH_STABILITY_SPAN_MV if kind == "ph" else DEFAULT_ORP_STABILITY_SPAN
        ))
        self._slope_percent: float = 100.0
        self._stability = StabilityWindow(
            window_s=stability_window,
            min_samples=STABILITY_MIN_SAMPLES,
            span_threshold_mv=stability_span_mv,
            interval_s=float(self.calibration_interval),
            min_samples_floor=STABILITY_MIN_SAMPLES_FLOOR,
            min_samples_ceiling=STABILITY_MIN_SAMPLES_CEILING,
            to_mv_fn=self._ph_span_to_mv if kind == "ph" else None,
        )
        filter_type = options.get(CONF_FILTER_TYPE, DEFAULT_FILTER_TYPE)
        filter_window = int(options.get(CONF_FILTER_WINDOW, DEFAULT_FILTER_WINDOW))
        self._filter = ReadingFilter(filter_type, filter_window)
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
    def mode(self) -> str:
        return self.entry.options.get(CONF_MODE, DEFAULT_MODE)

    @property
    def measurement_interval(self) -> int:
        return int(self.entry.options.get(CONF_MEASUREMENT_INTERVAL, DEFAULT_MEASUREMENT_INTERVAL))

    @property
    def calibration_interval(self) -> int:
        return int(self.entry.options.get(CONF_CONTINUOUS_INTERVAL, DEFAULT_CALIBRATION_INTERVAL))

    @property
    def calibration_auto_return(self) -> int:
        return int(self.entry.options.get(CONF_CALIBRATION_AUTO_RETURN, DEFAULT_CALIBRATION_AUTO_RETURN))

    @property
    def filter_type(self) -> str:
        return self.entry.options.get(CONF_FILTER_TYPE, DEFAULT_FILTER_TYPE)

    @property
    def filter_window(self) -> int:
        return int(self.entry.options.get(CONF_FILTER_WINDOW, DEFAULT_FILTER_WINDOW))

    @property
    def stability_window(self) -> float:
        return float(self.entry.options.get(CONF_STABILITY_WINDOW, DEFAULT_STABILITY_WINDOW))

    @property
    def stability_max_span(self) -> float:
        """Stability threshold in mV (for both pH and ORP)."""
        default = DEFAULT_PH_STABILITY_SPAN_MV if self.profile.kind == "ph" else DEFAULT_ORP_STABILITY_SPAN
        return float(self.entry.options.get(CONF_STABILITY_MAX_SPAN, default))

    @property
    def persisted_sleep(self) -> bool:
        return bool(self.entry.options.get(CONF_SLEEP, DEFAULT_SLEEP))

    @callback
    def _schedule_refresh(self) -> None:
        """Schedule next refresh at fixed rate (start-to-start interval).
        
        Override parent to ensure consistent polling intervals regardless of
        how long each poll takes. Standard DataUpdateCoordinator schedules
        next poll after completion, causing drift.
        """
        if self._update_interval_seconds is None:
            return
        if self.config_entry and self.config_entry.pref_disable_polling:
            return

        self._async_unsub_refresh()

        loop = self.hass.loop
        now = loop.time()

        if self._next_poll_time <= now:
            self._next_poll_time = now + self._update_interval_seconds
        else:
            pass

        delay = max(0.0, self._next_poll_time - now)
        self._unsub_refresh = loop.call_at(
            now + delay, self.__wrap_handle_refresh_interval
        ).cancel
        self._next_poll_time += self._update_interval_seconds

    def _ph_span_to_mv(self, span_ph: float) -> float:
        """Convert pH span to mV-equivalent using current slope.

        Formula: mV = pH * NERNST_MV_PER_PH * (slope% / 100)
        At 100% slope (ideal probe), 1 pH = 59.16 mV.
        A low slope (e.g. 80%) means less mV per pH, so the same pH span
        represents fewer mV, and the probe is actually less stable than it appears.
        """
        return span_ph * NERNST_MV_PER_PH * (self._slope_percent / 100.0)

    def _maybe_update_slope(self, state: EzoDeviceState) -> None:
        """Update slope conversion based on calibration state (pH probes only).

        Logic:
        - If factory calibration (cal_points == 0): use 100% (ideal Nernst)
        - If both acid and base slopes are known: use acid below pH 7, base above,
          or average if current reading is unknown
        - Otherwise: use whichever slope is available, or 100% as fallback
        """
        if self.profile.kind != "ph":
            return

        cal_points = state.cal_points or 0
        if cal_points == 0:
            if self._slope_percent != 100.0:
                self._slope_percent = 100.0
                _LOGGER.debug("Factory calibration: using ideal slope 100%%")
            return

        acid_str = state.slope_acid
        base_str = state.slope_base

        try:
            acid = float(acid_str) if acid_str else None
            base = float(base_str) if base_str else None
        except ValueError:
            return

        if acid is None and base is None:
            return

        current_ph = state.reading
        if acid is not None and base is not None:
            if current_ph is not None and current_ph < 7.0:
                new_slope = acid
            elif current_ph is not None and current_ph >= 7.0:
                new_slope = base
            else:
                new_slope = (acid + base) / 2.0
        elif acid is not None:
            new_slope = acid
        else:
            new_slope = base

        if new_slope is not None and new_slope > 0 and new_slope != self._slope_percent:
            self._slope_percent = new_slope
            _LOGGER.debug("Updated slope_percent to %.1f%% (pH=%.2f)", new_slope, current_ph or 0)

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
        self._options_unsub = self.entry.add_update_listener(self._async_options_updated)
        self._mark_available()

    async def _async_options_updated(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle options update - apply changes immediately without reload.

        Only reacts to relevant option changes (not data-only changes like port/title).
        """
        new_opts = entry.options
        old_opts = getattr(self, "_prev_options", {})

        relevant_keys = {
            CONF_MODE, CONF_MEASUREMENT_INTERVAL, CONF_FILTER_TYPE, CONF_FILTER_WINDOW,
            CONF_CONTINUOUS_INTERVAL, CONF_STABILITY_WINDOW, CONF_STABILITY_MAX_SPAN,
            CONF_CALIBRATION_AUTO_RETURN, CONF_SLEEP, CONF_TEMPERATURE_ENTITY,
        }
        changed = {k for k in relevant_keys if new_opts.get(k) != old_opts.get(k)}
        self._prev_options = dict(new_opts)

        if not changed:
            return

        if CONF_FILTER_TYPE in changed or CONF_FILTER_WINDOW in changed:
            self._filter.configure(self.filter_type, self.filter_window)

        stability_changed = changed & {
            CONF_STABILITY_WINDOW, CONF_STABILITY_MAX_SPAN, CONF_CONTINUOUS_INTERVAL,
            CONF_MEASUREMENT_INTERVAL,
        }
        if stability_changed:
            active_interval = (
                float(self.calibration_interval)
                if self.mode == MODE_CALIBRATION
                else float(self.measurement_interval)
            )
            self._stability = StabilityWindow(
                window_s=self.stability_window,
                min_samples=STABILITY_MIN_SAMPLES,
                span_threshold_mv=self.stability_max_span,
                interval_s=active_interval,
                min_samples_floor=STABILITY_MIN_SAMPLES_FLOOR,
                min_samples_ceiling=STABILITY_MIN_SAMPLES_CEILING,
                to_mv_fn=self._ph_span_to_mv if self.profile.kind == "ph" else None,
            )

        if CONF_MEASUREMENT_INTERVAL in changed and self.mode == MODE_EXPLOITATION:
            self.update_interval = timedelta(seconds=self.measurement_interval)

        if CONF_CONTINUOUS_INTERVAL in changed and self.mode == MODE_CALIBRATION:
            await self._command(f"C,{self.calibration_interval}", ignore_error=True)
            await self._command("C,?", ignore_error=True)

        if CONF_CALIBRATION_AUTO_RETURN in changed:
            self._reset_auto_return_timer()

        if CONF_TEMPERATURE_ENTITY in changed:
            self._retrack_temperature()

        self.async_update_listeners()

    def _retrack_temperature(self) -> None:
        """Re-subscribe to temperature entity if it changed."""
        if self._temp_unsub is not None:
            self._temp_unsub()
            self._temp_unsub = None
        self._async_track_temperature()

    async def async_shutdown(self) -> None:
        if self._temp_unsub is not None:
            self._temp_unsub()
            self._temp_unsub = None
        if self._options_unsub is not None:
            self._options_unsub()
            self._options_unsub = None
        for task in (self._listen_task, self._reconnect_task, self._auto_return_task):
            if task is not None:
                task.cancel()
        self._listen_task = None
        self._reconnect_task = None
        self._auto_return_task = None
        await self.session.disconnect()

    async def async_set_mode(self, mode: str) -> None:
        """Switch between exploitation and calibration modes."""
        if mode == self.mode:
            self._reset_auto_return_timer()
            return

        await self._update_options({CONF_MODE: mode})

        if mode == MODE_CALIBRATION:
            self._filter.reset()
            self._stability.reset()
            interval = self.calibration_interval
            await self._command(f"C,{interval}", ignore_error=True)
            await self._command("C,?", ignore_error=True)
            self._start_auto_return_timer()
            _LOGGER.info("Switched to calibration mode (C,%d)", interval)
        else:
            await self._do_switch_to_exploitation(from_auto_return=False)

    async def _do_switch_to_exploitation(self, *, from_auto_return: bool) -> None:
        """Internal helper to switch to exploitation mode.

        When called from auto-return loop, we must not cancel the current task.
        """
        if not from_auto_return:
            self._cancel_auto_return_timer()
        else:
            self._auto_return_task = None
            self._auto_return_deadline = 0.0

        await self._update_options({CONF_MODE: MODE_EXPLOITATION})
        await self._command("C,0", ignore_error=True)
        await self._command("C,?", ignore_error=True)
        self.update_interval = timedelta(seconds=self.measurement_interval)
        _LOGGER.info("Switched to exploitation mode (polling %d s)", self.measurement_interval)

    async def _update_options(self, updates: dict) -> None:
        """Update entry.options and trigger listeners."""
        new_options = {**self.entry.options, **updates}
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    def _start_auto_return_timer(self) -> None:
        """Start or restart the auto-return timer for calibration mode."""
        self._cancel_auto_return_timer()
        minutes = self.calibration_auto_return
        if minutes <= 0:
            return
        self._auto_return_deadline = time.monotonic() + minutes * 60
        self._auto_return_task = self.entry.async_create_background_task(
            self.hass, self._auto_return_loop(), name=f"{DOMAIN}_auto_return"
        )

    def _cancel_auto_return_timer(self) -> None:
        """Cancel the auto-return timer."""
        if self._auto_return_task is not None:
            self._auto_return_task.cancel()
            self._auto_return_task = None
        self._auto_return_deadline = 0.0

    def _reset_auto_return_timer(self) -> None:
        """Reset the auto-return timer (called on calibration actions)."""
        if self.mode == MODE_CALIBRATION and self.calibration_auto_return > 0:
            self._start_auto_return_timer()

    async def _auto_return_loop(self) -> None:
        """Background task that returns to exploitation mode after timeout."""
        try:
            while True:
                remaining = self._auto_return_deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(remaining, 10))
            if self.mode == MODE_CALIBRATION:
                _LOGGER.info("Auto-return: switching back to exploitation mode")
                await self._do_switch_to_exploitation(from_auto_return=True)
        except asyncio.CancelledError:
            pass

    async def _async_update_data(self) -> EzoDeviceState:
        if not self.session.connected:
            raise UpdateFailed("EZO Complete is disconnected")
        if self.persisted_sleep:
            return self.data
        try:
            if self.mode == MODE_EXPLOITATION:
                await self._async_push_temperature(hold_stream=False)
                await self._command("R")
            elif time.monotonic() - self._last_diag_at >= 60:
                async with self._hold_stream():
                    await self._refresh_diagnostics()
                self._last_diag_at = time.monotonic()
        except EzoClientError as err:
            self._schedule_reconnect()
            raise UpdateFailed(str(err)) from err
        return self.data

    async def async_set_calibration_interval(self, seconds: int) -> None:
        """Update calibration interval setting."""
        await self._update_options({CONF_CONTINUOUS_INTERVAL: int(seconds)})
        if self.mode == MODE_CALIBRATION:
            await self._command(f"C,{int(seconds)}")
            await self._command("C,?")
        self._reset_auto_return_timer()

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
        self._reset_auto_return_timer()

    async def async_calibrate(self, slot: str) -> None:
        value = self.cal_setpoint(slot)
        command = self.profile.cal_set_command(slot, value)
        if (
            slot == "mid"
            and self.profile.kind == "ph"
            and (self.data.cal_points or 0) >= 2
        ):
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_cal_mid_warning",
                "EZO Complete — pH calibration",
                "Attention : Cal,mid sur une sonde pH déjà calibrée 2+ points "
                "efface les points low/high (comportement Atlas). "
                "La calibration continue.",
            )
        self._reset_auto_return_timer()
        await self._async_run_calibration(command)

    async def async_calibrate_clear(self) -> None:
        self._reset_auto_return_timer()
        await self._async_run_calibration("Cal,clear")

    @asynccontextmanager
    async def _hold_stream(self, *, restore: bool = True) -> AsyncIterator[None]:
        is_calibration = self.mode == MODE_CALIBRATION
        if not is_calibration or self._hold_owner is asyncio.current_task():
            yield
            return
        interval = self.calibration_interval
        async with self._hold_lock:
            self._hold_owner = asyncio.current_task()
            self._pause_listen = True
            try:
                await self._command("C,0", ignore_error=True)
                await asyncio.sleep(0.2)
                yield
            finally:
                try:
                    if restore and is_calibration:
                        await self._command(f"C,{interval}", ignore_error=True)
                        await self._command("C,?", ignore_error=True)
                finally:
                    self._hold_owner = None
                    self._pause_listen = False

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
                await self._refresh_diagnostics()
                reading = await self._command("R", ignore_error=True)
                value = reading.first_reading() if reading is not None else self.data.reading
                state = self.data.copy()
                if value is not None:
                    state.reading = value
                self.async_set_updated_data(state)
                _LOGGER.info(
                    "Calibration %s done: Cal,?=%s reading=%s",
                    cal_command,
                    state.cal_points,
                    value,
                )
                self._notify(
                    f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                    "EZO Complete — calibration",
                    f"{cal_command} OK — Cal,?={state.cal_points}, {self.profile.reading_key}={value}",
                )
        except HomeAssistantError as err:
            self._notify(
                f"{DOMAIN}_{self.entry.entry_id}_calibrate",
                "EZO Complete — calibration",
                f"{cal_command} failed: {err}",
            )
            raise

    async def async_set_sleeping(self, enabled: bool) -> None:
        """Sleep is persisted in options and restored on startup/reconnect."""
        await self._update_options({CONF_SLEEP: enabled})
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
        if self.mode == MODE_EXPLOITATION:
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
        _LOGGER.warning(
            "Restoring calibration from %s without confirmation — "
            "this overwrites the current device calibration",
            path,
        )
        await self.async_import_calibration(payload)
        state = self.data.copy()
        state.restore_path = str(path)
        self.async_set_updated_data(state)
        export_timestamp = self.data.export_at or "unknown"
        self._notify(
            f"{DOMAIN}_{self.entry.entry_id}_restore",
            "EZO Complete — restore",
            f"Calibration réécrite depuis {path}\n"
            f"Export d'origine : {export_timestamp}",
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
            pass

        self._temp_unsub = async_track_state_change_event(
            self.hass, [entity_id], _on_temp
        )

    async def _async_push_temperature(self, *, hold_stream: bool = True) -> None:
        """Push temperature compensation value to the probe.
        
        Args:
            hold_stream: If True, pause continuous mode during push. In exploitation
                mode, this should be False since we're polling, not streaming.
        """
        if not self.profile.supports_temperature:
            return
        if self.persisted_sleep:
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
        if hold_stream:
            async with self._hold_stream():
                await self._command(f"T,{value:.2f}", ignore_error=True)
                self._last_pushed_t = value
                await self._command("T,?", ignore_error=True)
        else:
            await self._command(f"T,{value:.2f}", ignore_error=True)
            self._last_pushed_t = value

    async def _initialize_device(self) -> None:
        info = await self.session.identify()
        profile = profile_for(info.kind)
        if profile.kind != self.profile.kind:
            self.cal_setpoints = {
                slot.key: slot.default for slot in profile.cal_slots if slot.has_number
            }
        self.profile = profile
        self._stability = StabilityWindow(
            window_s=self.stability_window,
            min_samples=STABILITY_MIN_SAMPLES,
            span_threshold_mv=self.stability_max_span,
            interval_s=float(self.calibration_interval),
            min_samples_floor=STABILITY_MIN_SAMPLES_FLOOR,
            min_samples_ceiling=STABILITY_MIN_SAMPLES_CEILING,
            to_mv_fn=self._ph_span_to_mv if profile.kind == "ph" else None,
        )
        self._filter.configure(self.filter_type, self.filter_window)
        self._last_pushed_t = None
        state = self.data.copy()
        state.kind = self.profile.kind
        state.device_type = info.device_type
        state.firmware = info.firmware
        state.sleeping = False
        state.factory_armed = False
        state.filter_type = self.filter_type
        state.filter_window = self.filter_window

        restore_path, export_dt = await self.hass.async_add_executor_job(
            self._exports.get_latest_export_info
        )
        if export_dt is not None:
            state.export_at = export_dt.isoformat()
            state.restore_path = restore_path
            _LOGGER.debug("Restored export_at from disk: %s", state.export_at)

        self.async_set_updated_data(state)
        await self._command("C,0", ignore_error=True)
        await self._enable_response_codes()

        if self.mode == MODE_CALIBRATION:
            await self._command(f"C,{self.calibration_interval}", ignore_error=True)
            self._start_auto_return_timer()
        else:
            self.update_interval = timedelta(seconds=self.measurement_interval)

        await self._command("C,?", ignore_error=True)
        await self._refresh_diagnostics()
        self._last_diag_at = time.monotonic()

        if self.persisted_sleep:
            _LOGGER.info("Restoring sleep state from options")
            await self._command("Sleep", ignore_error=True)
            state = self.data.copy()
            state.sleeping = True
            self.async_set_updated_data(state)
        elif self.mode == MODE_EXPLOITATION:
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
                if not is_reading_in_range(line.value, self.profile.kind):
                    _LOGGER.debug(
                        "EZO reading %s out of range for %s, ignoring",
                        line.value,
                        self.profile.kind,
                    )
                    continue
                raw_value = line.value
                state.reading_raw = raw_value
                if self.mode == MODE_EXPLOITATION:
                    filtered = self._filter.push(raw_value)
                    state.reading = filtered
                    state.reading_filtered = filtered
                else:
                    state.reading = raw_value
                    state.reading_filtered = None
                state.sleeping = False
                self._update_stability(state, raw_value)
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
        state.filter_type = self.filter_type
        state.filter_window = self._filter.sample_count
        if last_command and last_command.split(",", 1)[0].lower() != "sleep":
            state.sleeping = False
        self.async_set_updated_data(state)

    def _update_stability(self, state: EzoDeviceState, value: float) -> None:
        snap = self._stability.push(value, time.monotonic())
        state.reading_min = snap.minimum
        state.reading_max = snap.maximum
        state.reading_span = snap.span
        state.reading_stable = snap.stable
        state.stability_samples = snap.sample_count
        state.stability_required = snap.required_samples
        state.stability_span_threshold = snap.span_threshold
        state.stability_span_mv = snap.span_mv
        state.stability_effective_window = snap.effective_window

    def _apply_query(self, state: EzoDeviceState, line: ParsedLine) -> None:
        if self.profile.apply_query(state, line):
            self._maybe_update_slope(state)
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
                was_continuous = state.continuous
                state.continuous = cont.enabled
                state.continuous_interval = cont.interval or state.continuous_interval
                if cont.enabled and cont.interval:
                    self._stability.set_interval(float(cont.interval))
                elif not cont.enabled:
                    self._stability.set_interval(self.update_interval.total_seconds())
                    # Reset stability only when transitioning FROM continuous (True),
                    # not on first init (None) when the window is already empty.
                    if was_continuous is True:
                        self._stability.reset()
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
        from homeassistant.components import usb

        stored_serial = self.entry.data.get(CONF_SERIAL_NUMBER)
        attempt = 0
        while True:
            try:
                await self.session.disconnect()
                await asyncio.sleep(RECONNECT_DELAY)
                new_port = await self._find_device_port(stored_serial)
                if new_port and new_port != self.session.port:
                    _LOGGER.info(
                        "USB device moved: %s -> %s", self.session.port, new_port
                    )
                    self.session = SerialSession(
                        port=new_port, baudrate=self.session.baudrate
                    )
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={**self.entry.data, CONF_PORT: new_port},
                    )
                await self.session.connect()
                await self._initialize_device()
            except asyncio.CancelledError:
                raise
            except (EzoClientError, OSError, TimeoutError) as err:
                attempt += 1
                if attempt % 12 == 1:
                    _LOGGER.debug("Reconnect to %s failed: %s", self.session.port, err)
                continue
            self._mark_available()
            return

    async def _find_device_port(self, serial: str | None) -> str | None:
        """Try to find the current port for a USB device by its serial number."""
        if not serial or serial == "unknown":
            return None
        try:
            from homeassistant.components import usb

            usb_list = usb.async_get_usb(self.hass)
            for device in usb_list:
                if device.serial_number == serial:
                    port = await self.hass.async_add_executor_job(
                        usb.get_serial_by_id, device.device
                    )
                    return port
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not scan USB devices for serial %s", serial)
        return None

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
        device = async_get_entry_device(self.hass, self.entry.entry_id, self.unique_id)
        if device is not None and device.name_by_user is None and device.name != name:
            registry = dr.async_get(self.hass)
            registry.async_update_device(device.id, name=name)
