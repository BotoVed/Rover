"""Rover message dispatcher — routes inbound messages by tp to handlers."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    LOGGER_HND,
    TP_CMD,
    TP_PING_PONG,
    TP_REQ,
    TP_REGISTER,
)

if TYPE_CHECKING:
    from .handlers import RoverHandlers

_LOGGER = logging.getLogger(LOGGER_HND)

# Wire protocol: Android uses compact integer keys over msgpack
# Map them to the string keys used internally by handlers.
# Key meaning varies by message type; key 0 is always tp.

# General mapping (used as fallback)
_GENERAL_MAP: dict[int, str] = {
    0: "tp",
    1: "h",
    2: "s",
    3: "name",
    4: "ver",
    5: "section",
    6: "target",
    7: "service",
    8: "type",
    9: "id",
    10: "uid",
}

# Per-type overrides for keys that differ by message type
_TP_MAPS: dict[int, dict[int, str]] = {
    TP_REGISTER: {1: "uid"},
    TP_CMD: {3: "b", 10: "rgb", 11: "ct", 12: "ef"},
}


def _normalize(fields: dict) -> dict:
    """Convert integer keys to string keys for handler compatibility."""
    if not fields:
        return fields
    if not any(isinstance(k, int) for k in fields):
        return fields

    result: dict = {}
    tp = fields.get(0) if isinstance(fields.get(0), int) else None
    type_map = _TP_MAPS.get(tp, {})
    for k, v in fields.items():
        if isinstance(k, int):
            mapped = type_map.get(k, _GENERAL_MAP.get(k))
            result[mapped] = v
        else:
            result[k] = v
    return result


class RoverDispatcher:
    """Routes incoming LXMF messages to typed handlers."""

    def __init__(self, handlers: "RoverHandlers") -> None:
        self._handlers = handlers

    async def dispatch(self, source_hash: bytes | None, fields: dict) -> None:
        """Entry point — called from transport on every inbound message."""
        if not isinstance(fields, dict):
            _LOGGER.warning("DISPATCH reject: fields not dict, got %s", type(fields).__name__)
            return

        fields = _normalize(fields)

        tp = fields.get("tp")
        if not isinstance(tp, int):
            _LOGGER.warning("DISPATCH reject: missing or invalid tp=%r", tp)
            return

        src_hex = source_hash.hex() if source_hash else "?"
        _LOGGER.debug("DISPATCH src=%s... tp=%d", src_hex[:8], tp)

        if tp == TP_CMD:
            await self._handlers.handle_cmd(source_hash, fields)
        elif tp == TP_PING_PONG:
            await self._handlers.handle_ping(source_hash, fields)
        elif tp == TP_REQ:
            await self._handlers.handle_req(source_hash, fields)
        elif tp == TP_REGISTER:
            await self._handlers.handle_register(source_hash, fields)
        else:
            _LOGGER.warning("DISPATCH reject: unsupported tp=%d (inbound types only: 5,6,8,9)", tp)
