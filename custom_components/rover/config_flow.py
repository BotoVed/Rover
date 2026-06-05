"""Config flow for Rover integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, LOGGER_ROOT

if TYPE_CHECKING:
    from .options_flow import RoverOptionsFlow

_LOGGER = logging.getLogger(LOGGER_ROOT)


class RoverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rover."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Rover Hub", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={"name": "Rover Hub"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "RoverOptionsFlow":
        """Return options flow handler."""
        from .options_flow import RoverOptionsFlow

        return RoverOptionsFlow(config_entry)
