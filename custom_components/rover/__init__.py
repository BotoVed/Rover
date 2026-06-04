"""Rover — Remote Over Radio for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER_ROOT

_LOGGER = logging.getLogger(LOGGER_ROOT)


class RoverRuntimeData:
    def __init__(self) -> None:
        self.transport = None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    runtime = RoverRuntimeData()
    hass.data[DOMAIN][entry.entry_id] = runtime

    _LOGGER.info("Rover %s setup started", entry.version)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
    if runtime and runtime.transport:
        await runtime.transport.shutdown()
    return True
