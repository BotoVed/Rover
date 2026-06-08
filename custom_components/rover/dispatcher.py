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
# Map them to the string keys used internally by handlers
_KEY_MAP: dict[int, str] = {
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
}


def _normalize(fields: dict) -> dict:
    """Convert integer keys to string keys for handler compatibility."""
    if not fields:
        return fields
    if not any(isinstance(k, int) for k in fields):
        return fields
    result: dict = {}
    for k, v in fields.items():
        if isinstance(k, int):
            result[_KEY_MAP.get(k)] = v
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
