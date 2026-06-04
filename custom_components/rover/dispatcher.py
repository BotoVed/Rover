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


class RoverDispatcher:
    """Routes incoming LXMF messages to typed handlers."""

    def __init__(self, handlers: "RoverHandlers") -> None:
        self._handlers = handlers

    async def dispatch(self, source_hash: bytes | None, fields: dict) -> None:
        """Entry point — called from transport on every inbound message."""
        if not isinstance(fields, dict):
            _LOGGER.warning("DISPATCH reject: fields not dict, got %s", type(fields).__name__)
            return

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
