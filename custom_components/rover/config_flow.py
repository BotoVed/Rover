"""Config flow для Rover.

Единственный шаг при первой установке: все базовые параметры на одном экране.
После установки настройка устройств, пользователей и просмотр конфига —
через OptionsFlow.

См. SPEC.md §5, DECISIONS.md SB-034, SB-042, SB-043.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

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

CONN_TYPES = ["serial", "tcp"]
DEFAULT_ACK_TIMEOUT_VALUE = 10


class RoverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow для Rover — только базовая установка."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        from .options_flow import RoverOptionsFlow
        return RoverOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Единственный шаг: общие настройки."""
        try:
            if user_input is not None:
                user_input[CONF_PASSWORD_SALT] = secrets.token_hex(DEFAULT_PASSWORD_SALT_BYTES)
                return self.async_create_entry(
                    title=user_input[CONF_HOME_NAME],
                    data=user_input,
                )

            schema = vol.Schema({
                vol.Required(CONF_HOME_NAME, default=DEFAULT_HOME_NAME): str,
                vol.Required(CONF_CONN_TYPE, default=DEFAULT_CONN_TYPE): vol.In(CONN_TYPES),
                vol.Required(CONF_PORT): str,
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
            })
            return self.async_show_form(step_id="user", data_schema=schema)
        except Exception:
            _LOGGER.exception("Rover config_flow async_step_user failed")
            raise
