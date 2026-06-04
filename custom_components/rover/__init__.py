"""Rover — Remote Over Radio for Home Assistant."""
from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER_ROOT

_LOGGER = logging.getLogger(LOGGER_ROOT)


class RoverRuntimeData:
    """Runtime data for Rover integration."""
    def __init__(self) -> None:
        self.transport = None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Rover component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rover from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    runtime = RoverRuntimeData()
    hass.data[DOMAIN][entry.entry_id] = runtime

    _LOGGER.info("Rover %s setup started", entry.version)

    # Placeholder: transport initialized in next stage
    # config_dir = os.path.join(hass.config.config_dir, "custom_components", "rover", ".reticulum")
    # from .rns_transport import RoverTransport
    # runtime.transport = RoverTransport(hass, config_dir, lambda src, flds: None)
    # hash_hex = await runtime.transport.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Rover config entry."""
    runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
    if runtime and runtime.transport:
        await runtime.transport.shutdown()
    return True
