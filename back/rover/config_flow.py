"""Config flow для Rover.

Пошаговая настройка через Settings → Integrations.
Шаг 1 (user): тип подключения, порт/адрес шлюза, имя дома.
Шаг 2 (advanced): канал, PSK, hop limit, период повторов, ретраи.

См. SPEC.md §8.1, DECISIONS.md SB-034.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import (
    CONF_CHANNEL,
    CONF_CONN_TYPE,
    CONF_HOME_NAME,
    CONF_HOP_LIMIT,
    CONF_MAX_RETRIES,
    CONF_PORT,
    CONF_PSK,
    CONF_PUSH_ENABLED,
    CONF_QUEUE_PERIOD,
    DEFAULT_CHANNEL,
    DEFAULT_CONN_TYPE,
    DEFAULT_HOME_NAME,
    DEFAULT_HOP_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PSK,
    DEFAULT_PUSH_ENABLED,
    DEFAULT_QUEUE_PERIOD,
    DOMAIN,
)

CONN_TYPES = ["serial", "tcp"]


class RoverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow для Rover."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Шаг 1: основные параметры подключения."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced()

        schema = vol.Schema({
            vol.Required(CONF_HOME_NAME, default=DEFAULT_HOME_NAME): str,
            vol.Required(CONF_CONN_TYPE, default=DEFAULT_CONN_TYPE): vol.In(CONN_TYPES),
            vol.Required(CONF_PORT): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Шаг 2: расширенные параметры Meshtastic и очереди."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title=self._data[CONF_HOME_NAME],
                data=self._data,
            )

        schema = vol.Schema({
            vol.Required(CONF_CHANNEL, default=DEFAULT_CHANNEL): str,
            vol.Required(CONF_PSK, default=DEFAULT_PSK): str,
            vol.Required(CONF_HOP_LIMIT, default=DEFAULT_HOP_LIMIT):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
            vol.Required(CONF_QUEUE_PERIOD, default=DEFAULT_QUEUE_PERIOD):
                vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
            vol.Required(CONF_MAX_RETRIES, default=DEFAULT_MAX_RETRIES):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            vol.Required(CONF_PUSH_ENABLED, default=DEFAULT_PUSH_ENABLED): bool,
        })
        return self.async_show_form(step_id="advanced", data_schema=schema)
