from __future__ import annotations

from .codec import decode
from .const import TP_CMD, TP_PING, TP_REQ
from .queue import InDedup


class Dispatcher:
    def __init__(self, handlers) -> None:
        self._handlers = handlers
        self._dedup = InDedup()

    async def dispatch(self, payload: bytes, from_node: int) -> None:
        packet = decode(payload)
        tp = packet.get("tp")

        cmid = packet.get("cmid")
        if cmid and self._dedup.seen(cmid):
            return

        if tp == TP_CMD:
            if "req" in packet:
                if packet["req"] == "all":
                    await self._handlers.on_req_all(from_node)
                else:
                    await self._handlers.on_req_one(packet, from_node)
            elif "id" in packet:
                await self._handlers.on_command(packet, from_node)
        elif tp == TP_PING:
            await self._handlers.on_ping(packet, from_node)
        elif tp == TP_REQ:
            await self._handlers.on_req_config(packet, from_node)
