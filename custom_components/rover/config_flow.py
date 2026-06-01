from __future__ import annotations

import logging
import os
import secrets
from typing import Any

import voluptuous as vol
from serial.tools import list_ports

_LOGGER = logging.getLogger(__name__)
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ACK_TIMEOUT,
    CONF_CHANNEL,
    CONF_CONN_TYPE,
    CONF_HOME_NAME,
    CONF_HOP_LIMIT,
    CONF_MAX_RETRIES,
    CONF_PASSWORD_SALT,
    CONF_PORT,
    CONF_PSK,
    CONF_PUSH_ENABLED,
    CONF_QUEUE_PERIOD,
    DEFAULT_CHANNEL,
    DEFAULT_CONN_TYPE,
    DEFAULT_HOME_NAME,
    DEFAULT_HOP_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PASSWORD_SALT_BYTES,
    DEFAULT_PSK,
    DEFAULT_PUSH_ENABLED,
    DEFAULT_QUEUE_PERIOD,
    DOMAIN,
)

DEFAULT_ACK_TIMEOUT_VALUE = 10

_BASE_FIELDS = {
    vol.Required(CONF_HOME_NAME, default=DEFAULT_HOME_NAME): str,
    vol.Required(CONF_CHANNEL, default=DEFAULT_CHANNEL): str,
    vol.Required(CONF_PSK, default=DEFAULT_PSK): str,
    vol.Required(CONF_HOP_LIMIT, default=DEFAULT_HOP_LIMIT):
        vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
    vol.Required(CONF_QUEUE_PERIOD, default=DEFAULT_QUEUE_PERIOD):
        vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
    vol.Required(CONF_MAX_RETRIES, default=DEFAULT_MAX_RETRIES):
        vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Required(CONF_ACK_TIMEOUT, default=DEFAULT_ACK_TIMEOUT_VALUE):
        vol.All(vol.Coerce(int), vol.Range(min=5, max=30)),
    vol.Required(CONF_PUSH_ENABLED, default=DEFAULT_PUSH_ENABLED): bool,
}

def _get_serial_ports() -> list[str]:
    ports = []
    for p in list_ports.comports():
        device = p.device
        if not (device.startswith("/dev/ttyACM") or device.startswith("/dev/ttyUSB")):
            continue
        real = os.path.realpath(device)
        by_id_dir = "/dev/serial/by-id/"
        if os.path.isdir(by_id_dir):
            for entry in sorted(os.listdir(by_id_dir)):
                if os.path.realpath(os.path.join(by_id_dir, entry)) == real:
                    ports.append(os.path.join(by_id_dir, entry))
                    break
            else:
                ports.append(device)
        else:
            ports.append(device)
    if not ports:
        ports = ["/dev/ttyACM0"]
    return ports


class RoverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._conn_type: str = DEFAULT_CONN_TYPE

    @staticmethod
    def async_get_options_flow(config_entry):
        from .options_flow import RoverOptionsFlow
        return RoverOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                self._conn_type = user_input[CONF_CONN_TYPE]
                if self._conn_type == "serial":
                    return await self.async_step_serial()
                return await self.async_step_tcp()

            schema = vol.Schema({
                vol.Required(CONF_CONN_TYPE, default=DEFAULT_CONN_TYPE): SelectSelector(
                    SelectSelectorConfig(options=[
                        {"value": "serial", "label": "Serial (USB)"},
                        {"value": "tcp", "label": "TCP"},
                    ])
                ),
            })
            return self.async_show_form(step_id="user", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover config_flow async_step_user failed")
            raise

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                user_input[CONF_CONN_TYPE] = self._conn_type
                user_input[CONF_PASSWORD_SALT] = secrets.token_hex(DEFAULT_PASSWORD_SALT_BYTES)
                return self.async_create_entry(
                    title=user_input[CONF_HOME_NAME],
                    data=user_input,
                )

            ports = _get_serial_ports()
            schema = vol.Schema({
                vol.Required(CONF_PORT): SelectSelector(
                    SelectSelectorConfig(options=[
                        {"value": p, "label": os.path.basename(p)} for p in ports
                    ])
                ),
                **_BASE_FIELDS,
            })
            return self.async_show_form(step_id="serial", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover config_flow async_step_serial failed")
            raise

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        try:
            if user_input is not None:
                user_input[CONF_CONN_TYPE] = self._conn_type
                user_input[CONF_PASSWORD_SALT] = secrets.token_hex(DEFAULT_PASSWORD_SALT_BYTES)
                return self.async_create_entry(
                    title=user_input[CONF_HOME_NAME],
                    data=user_input,
                )

            schema = vol.Schema({
                vol.Required(CONF_PORT): TextSelector(TextSelectorConfig()),
                **_BASE_FIELDS,
            })
            return self.async_show_form(step_id="tcp", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover config_flow async_step_tcp failed")
            raise
