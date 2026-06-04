"""HA <-> Rover bridge: subscribe to state_changed, throttle, push to remotes."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    LOGGER_HAB,
    PUSH_THROTTLE_MS,
    SENSOR_PUSH_INTERVAL,
    TP_PUSH,
)
from .state_extractor import extract_state

if TYPE_CHECKING:
    from .registry import RoverRegistry
    from .rns_transport import RoverTransport

_LOGGER = logging.getLogger(LOGGER_HAB)


class RoverHABridge:
    """Listens to HA state changes and emits PUSH to all approved remotes.

    Throttling rules (DECISIONS 067):
    - All devices: 500 ms per-device coalescing window. Multiple changes within
      the window are merged: only the latest state is sent after the window.
    - SE (sensors): additionally min 5 s between PUSH for the same device.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        registry: "RoverRegistry",
        transport: "RoverTransport",
    ) -> None:
        self._hass = hass
        self._registry = registry
        self._transport = transport

        self._unsub: callable | None = None
        self._pending: dict[int, dict] = {}
        self._timers: dict[int, asyncio.TimerHandle] = {}
        self._last_sent: dict[int, float] = {}

    async def async_start(self) -> None:
        """Begin listening to HA state changes."""
        self._unsub = self._hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._on_event
        )
        _LOGGER.info("HA bridge started")

    async def async_stop(self) -> None:
        """Stop listening and cancel pending timers."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        for timer in list(self._timers.values()):
            timer.cancel()
        self._timers.clear()
        self._pending.clear()
        _LOGGER.info("HA bridge stopped")

    @callback
    def _on_event(self, event: Event) -> None:
        """Filter state_changed events to registered devices and schedule PUSH."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None:
            return

        device = self._registry.get_device_by_entity_id(entity_id)
        if device is None or not device.get("enabled", True):
            return

        try:
            extracted = extract_state(
                new_state.state, dict(new_state.attributes), device["type"]
            )
        except ValueError:
            _LOGGER.debug("PUSH skip: unknown type for %s", entity_id)
            return

        short_id = device["short_id"]
        push_msg = {"tp": TP_PUSH, "id": short_id, **extracted}

        self._pending[short_id] = push_msg

        if short_id in self._timers:
            _LOGGER.debug("THROTTLE hit id=%d (timer already armed)", short_id)
            return

        delay_s = self._compute_delay(device["type"], short_id)
        _LOGGER.debug(
            "THROTTLE schedule id=%d type=%s delay=%.3fs",
            short_id, device["type"], delay_s,
        )
        self._timers[short_id] = self._hass.loop.call_later(
            delay_s,
            lambda sid=short_id: self._hass.async_create_task(self._flush(sid)),
        )

    def _compute_delay(self, device_type: str, short_id: int) -> float:
        """Return delay in seconds for next flush of this device."""
        base = PUSH_THROTTLE_MS / 1000.0

        if device_type == "SE":
            last = self._last_sent.get(short_id, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < SENSOR_PUSH_INTERVAL:
                return max(base, SENSOR_PUSH_INTERVAL - elapsed)
        return base

    async def _flush(self, short_id: int) -> None:
        """Send the pending PUSH for this device to all approved remotes."""
        self._timers.pop(short_id, None)
        msg = self._pending.pop(short_id, None)
        if msg is None:
            return

        device = self._registry.get_device(short_id)
        if device is None or not device.get("enabled", True):
            _LOGGER.debug("THROTTLE flush drop: id=%d gone or disabled", short_id)
            return

        users = self._registry.all_users()
        if not users:
            _LOGGER.debug("THROTTLE flush drop: id=%d no approved remotes", short_id)
            self._last_sent[short_id] = time.monotonic()
            return

        _LOGGER.info(
            "PUSH id=%d v=%r to %d remote(s)",
            short_id, msg.get("v"), len(users),
        )

        for user in users:
            dst_hex = user["hash"]
            try:
                await self._transport.send(dst_hex, msg)
            except Exception:
                _LOGGER.exception("PUSH send error to %s...", dst_hex[:8])

        self._last_sent[short_id] = time.monotonic()

    async def broadcast_pong(self) -> None:
        """Send an unsolicited PONG to all approved remotes (DECISIONS 038)."""
        users = self._registry.all_users()
        if not users:
            return
        hashes = self._registry.get_hashes()
        pong = {"tp": 6, "h": hashes}
        _LOGGER.info("PONG broadcast h=%s to %d remote(s)", hashes, len(users))
        for user in users:
            try:
                await self._transport.send(user["hash"], pong)
            except Exception:
                _LOGGER.exception("PONG send error to %s...", user["hash"][:8])
