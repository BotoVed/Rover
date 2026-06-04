"""Rover — Remote Over Radio for Home Assistant."""
from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER_ROOT
from .registry import RoverRegistry

_LOGGER = logging.getLogger(LOGGER_ROOT)


class RoverRuntimeData:
    """Runtime data for Rover integration."""

    def __init__(self) -> None:
        self.registry: RoverRegistry | None = None
        self.transport = None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Rover component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rover from a config entry."""
    runtime = RoverRuntimeData()

    # Initialize registry
    runtime.registry = RoverRegistry(hass)
    await runtime.registry.async_load()

    # Ensure .reticulum directory exists for later transport init
    config_dir = os.path.join(
        hass.config.config_dir, "custom_components", DOMAIN, ".reticulum"
    )
    await hass.async_add_executor_job(os.makedirs, config_dir, True)

    entry.runtime_data = runtime

    _LOGGER.info("Rover %s setup complete", entry.version)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Rover config entry."""
    runtime: RoverRuntimeData = entry.runtime_data
    if runtime.transport:
        await runtime.transport.shutdown()
    return True
