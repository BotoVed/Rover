"""Rover — Remote Over Radio for Home Assistant."""
from __future__ import annotations

__version__ = "0.3.5"

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER_ROOT
from .registry import RoverRegistry
from .rns_transport import RoverTransport

_LOGGER = logging.getLogger(LOGGER_ROOT)


class RoverRuntimeData:
    """Runtime data for Rover integration."""

    def __init__(self) -> None:
        self.registry: RoverRegistry | None = None
        self.transport: RoverTransport | None = None
        self.identity_hash: str | None = None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Rover component (no YAML config)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rover from a config entry."""
    runtime = RoverRuntimeData()

    # 1. Initialize registry
    runtime.registry = RoverRegistry(hass)
    await runtime.registry.async_load()

    # 2. Prepare RNS config directory inside integration's storage
    config_dir = os.path.join(
        hass.config.config_dir, "custom_components", DOMAIN, ".reticulum"
    )
    await hass.async_add_executor_job(os.makedirs, config_dir, True)

    # 3. Stub callback for incoming messages.
    # In Phase 2 this will be replaced by handlers.dispatcher.
    def _on_message_stub(source_hash: bytes | None, fields: dict) -> None:
        src = source_hash.hex()[:8] if source_hash else "?"
        tp = fields.get("tp", "?") if isinstance(fields, dict) else "?"
        _LOGGER.info(
            "INBOUND src=%s... tp=%s (handler not implemented in 0.3.5)",
            src, tp
        )

    # 4. Initialize and start transport (RNS + LXMF)
    runtime.transport = RoverTransport(
        hass=hass,
        config_dir=config_dir,
        on_message=_on_message_stub,
    )

    try:
        identity_hash = await runtime.transport.async_start()
        runtime.identity_hash = identity_hash
        _LOGGER.info(
            "Rover server identity hash: %s (full hex — share via QR in Phase 2)",
            identity_hash
        )
    except Exception:
        _LOGGER.exception("Rover transport failed to start; integration will not work")
        return False

    entry.runtime_data = runtime
    _LOGGER.info("Rover %s setup complete", __version__)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Rover config entry."""
    runtime: RoverRuntimeData = entry.runtime_data
    if runtime is None:
        return True
    if runtime.transport:
        try:
            await runtime.transport.shutdown()
        except Exception:
            _LOGGER.exception("Error during transport shutdown")
    _LOGGER.info("Rover unloaded")
    return True
