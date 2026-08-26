"""Config Flow: USB discovery, identify pH vs ORP, options including T entity."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import usb
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    SOURCE_RECONFIGURE,
    SOURCE_USB,
)
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
    TextSelector,
)
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from .codec import unique_id_from_serial
from .const import (
    BAUDRATES,
    CONF_BAUDRATE,
    CONF_CONTINUOUS_INTERVAL,
    CONF_CONTINUOUS_ON_START,
    CONF_DEVICE_TYPE,
    CONF_FIRMWARE,
    CONF_SERIAL_NUMBER,
    CONF_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL,
    CONTINUOUS_INTERVAL_MAX,
    CONTINUOUS_INTERVAL_MIN,
    DEFAULT_BAUDRATE,
    DEFAULT_CONTINUOUS_INTERVAL,
    DEFAULT_CONTINUOUS_ON_START,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .profiles import profile_for
from .session import EzoClientError, EzoUnsupportedError, probe_ezo

_LOGGER = logging.getLogger(__name__)


class EzoCompleteConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._port: str | None = None
        self._serial_number: str | None = None
        self._firmware: str | None = None
        self._device_type: str = "orp"
        self._discovery_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT].strip()
            baudrate = int(user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
            error = await self._async_validate_and_set_unique_id(port, baudrate)
            if error:
                errors["base"] = error
            else:
                profile = profile_for(self._device_type)
                name = (
                    (user_input.get(CONF_NAME) or profile.default_name).strip()
                    or profile.default_name
                )
                return self._async_build_entry(port, baudrate, name)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PORT): SerialPortSelector(),
                        vol.Optional(
                            CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[str(rate) for rate in BAUDRATES],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Optional(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                    }
                ),
                user_input or {},
            ),
            errors=errors,
        )

    async def async_step_usb(self, discovery_info: UsbServiceInfo) -> ConfigFlowResult:
        device = await self.hass.async_add_executor_job(
            usb.get_serial_by_id, discovery_info.device
        )
        self._port = device
        self._serial_number = discovery_info.serial_number
        error = await self._async_validate_and_set_unique_id(
            device, DEFAULT_BAUDRATE, serial_number=discovery_info.serial_number
        )
        if error:
            return self.async_abort(reason=error)
        self._discovery_name = profile_for(self._device_type).default_name
        self._abort_if_unique_id_configured(
            updates={CONF_PORT: device, CONF_SERIAL_NUMBER: self._serial_number}
        )
        self.context["title_placeholders"] = {CONF_NAME: self._discovery_name}
        return await self.async_step_usb_confirm()

    async def async_step_usb_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            assert self._port is not None
            name = (
                user_input.get(CONF_NAME) or self._discovery_name or DEFAULT_NAME
            ).strip() or DEFAULT_NAME
            return self._async_build_entry(self._port, DEFAULT_BAUDRATE, name)
        return self.async_show_form(
            step_id="usb_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME, default=self._discovery_name or DEFAULT_NAME
                    ): TextSelector()
                }
            ),
            description_placeholders={
                "port": self._port or "",
                "serial": self._serial_number or "",
                "kind": self._device_type,
                "firmware": self._firmware or "",
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT].strip()
            baudrate = int(user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
            name = (user_input.get(CONF_NAME) or entry.title).strip() or entry.title
            error = await self._async_validate_and_set_unique_id(
                port, baudrate, serial_number=entry.data.get(CONF_SERIAL_NUMBER)
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    title=name,
                    data={
                        **entry.data,
                        CONF_PORT: port,
                        CONF_BAUDRATE: baudrate,
                        CONF_NAME: name,
                        CONF_SERIAL_NUMBER: self._serial_number
                        or entry.data.get(CONF_SERIAL_NUMBER),
                        CONF_FIRMWARE: self._firmware or entry.data.get(CONF_FIRMWARE),
                        CONF_DEVICE_TYPE: self._device_type,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PORT): SerialPortSelector(),
                        vol.Optional(CONF_BAUDRATE): SelectSelector(
                            SelectSelectorConfig(
                                options=[str(rate) for rate in BAUDRATES],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Optional(CONF_NAME): TextSelector(),
                    }
                ),
                {
                    CONF_PORT: entry.data.get(CONF_PORT),
                    CONF_BAUDRATE: str(entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
                    CONF_NAME: entry.data.get(CONF_NAME, entry.title),
                },
            ),
            errors=errors,
        )

    async def _async_validate_and_set_unique_id(
        self,
        port: str,
        baudrate: int,
        serial_number: str | None = None,
    ) -> str | None:
        try:
            info = await probe_ezo(port, baudrate=baudrate)
        except EzoUnsupportedError:
            return "not_supported"
        except (EzoClientError, OSError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Cannot probe %s: %s", port, err)
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error probing %s", port)
            return "unknown"
        self._firmware = info.firmware
        self._device_type = info.kind
        if serial_number:
            self._serial_number = serial_number
        unique_id = unique_id_from_serial(self._serial_number, self._device_type)
        await self.async_set_unique_id(unique_id)
        if self.source not in (SOURCE_RECONFIGURE, SOURCE_USB):
            self._abort_if_unique_id_configured()
        elif self.source == SOURCE_RECONFIGURE:
            abort_mismatch = getattr(self, "_abort_if_unique_id_mismatch", None)
            if abort_mismatch is not None:
                abort_mismatch()
        return None

    def _async_build_entry(self, port: str, baudrate: int, name: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={
                CONF_PORT: port,
                CONF_BAUDRATE: baudrate,
                CONF_NAME: name,
                CONF_SERIAL_NUMBER: self._serial_number,
                CONF_DEVICE_TYPE: self._device_type,
                CONF_FIRMWARE: self._firmware,
            },
            options={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_CONTINUOUS_ON_START: DEFAULT_CONTINUOUS_ON_START,
                CONF_CONTINUOUS_INTERVAL: DEFAULT_CONTINUOUS_INTERVAL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EzoCompleteOptionsFlow()


class EzoCompleteOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {
                CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                CONF_CONTINUOUS_ON_START: bool(user_input[CONF_CONTINUOUS_ON_START]),
                CONF_CONTINUOUS_INTERVAL: int(user_input[CONF_CONTINUOUS_INTERVAL]),
            }
            if CONF_TEMPERATURE_ENTITY in user_input:
                data[CONF_TEMPERATURE_ENTITY] = user_input.get(CONF_TEMPERATURE_ENTITY)
            return self.async_create_entry(title="", data=data)

        options = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=300, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_CONTINUOUS_ON_START,
                default=options.get(CONF_CONTINUOUS_ON_START, DEFAULT_CONTINUOUS_ON_START),
            ): BooleanSelector(),
            vol.Required(
                CONF_CONTINUOUS_INTERVAL,
                default=options.get(CONF_CONTINUOUS_INTERVAL, DEFAULT_CONTINUOUS_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=CONTINUOUS_INTERVAL_MIN,
                    max=CONTINUOUS_INTERVAL_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
        kind = (self.config_entry.data.get(CONF_DEVICE_TYPE) or "").lower()
        try:
            profile = profile_for(kind)
        except ValueError:
            profile = None
        if profile is not None and profile.supports_temperature:
            schema[
                vol.Optional(
                    CONF_TEMPERATURE_ENTITY,
                    default=options.get(CONF_TEMPERATURE_ENTITY),
                )
            ] = EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
