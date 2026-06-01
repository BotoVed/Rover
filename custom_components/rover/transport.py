from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .const import MESHTASTIC_BROADCAST_ADDR, MESHTASTIC_PRIVATE_APP_PORT

_LOGGER = logging.getLogger(__name__)


class Transport:
    def __init__(self) -> None:
        self._interface: Any = None
        self._on_packet: Callable | None = None
        self._on_ack: Callable | None = None
        self._on_disconnect: Callable | None = None
        self._on_reconnect: Callable | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection_type: str | None = None
        self._port: str | None = None
        self._connected: bool = False
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_interval: float = 30.0

    def set_callbacks(
        self,
        on_packet: Callable | None = None,
        on_ack: Callable | None = None,
        on_disconnect: Callable | None = None,
        on_reconnect: Callable | None = None,
    ) -> None:
        self._on_packet = on_packet
        self._on_ack = on_ack
        self._on_disconnect = on_disconnect
        self._on_reconnect = on_reconnect

    async def connect(self, connection_type: str, port: str) -> None:
        self._connection_type = connection_type
        self._port = port
        await self._do_connect()

    async def _do_connect(self) -> bool:
        try:
            loop = asyncio.get_running_loop()

            def _connect() -> None:
                from meshtastic import serial_interface, tcp_interface
                if self._connection_type == "serial":
                    self._interface = serial_interface.SerialInterface(self._port)
                elif self._connection_type == "tcp":
                    self._interface = tcp_interface.TCPInterface(hostname=self._port)
                self._interface.onReceive = self._handle_receive
                self._loop = loop

            await loop.run_in_executor(None, _connect)
            self._connected = True
            self._stop_reconnect_loop()
            if self._on_reconnect:
                self._on_reconnect()
            return True
        except Exception:
            _LOGGER.exception("Connection failed")
            self._connected = False
            self._interface = None
            self._start_reconnect_loop()
            return False

    def _handle_receive(self, packet: Any) -> None:
        if not self._connected:
            return

        from meshtastic.protobuf import portnums_pb2

        from_port = packet.decoded.portnum if packet.decoded else 0
        from_node = packet.fromId if hasattr(packet, "fromId") else 0

        if from_port == portnums_pb2.ROUTING_APP:
            if hasattr(packet.decoded, "routing") and packet.decoded.routing:
                routing = packet.decoded.routing
                request_id = getattr(routing, "requestId", 0)
                if request_id and self._on_ack:
                    success = not getattr(routing, "error", None)
                    self._loop.call_soon_threadsafe(self._on_ack, request_id, success)
        else:
            if from_port == MESHTASTIC_PRIVATE_APP_PORT:
                payload = (
                    bytes(packet.decoded.data)
                    if packet.decoded and packet.decoded.data
                    else b""
                )
                if payload and self._on_packet:
                    self._loop.call_soon_threadsafe(self._on_packet, payload, from_node)

    async def send(self, payload: bytes, want_ack: bool = True) -> int | None:
        if not self._connected or not self._interface:
            return None

        def _send() -> None:
            self._interface.sendData(
                payload,
                destinationId=MESHTASTIC_BROADCAST_ADDR,
                portNum=MESHTASTIC_PRIVATE_APP_PORT,
                wantAck=want_ack,
            )

        await asyncio.get_running_loop().run_in_executor(None, _send)
        return 0

    async def disconnect(self) -> None:
        self._stop_reconnect_loop()
        if self._interface:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._interface.close
                )
            except Exception:
                pass
            self._interface = None
        self._connected = False

    def check_alive(self) -> None:
        if not self._connected or not self._interface:
            return
        try:
            if hasattr(self._interface, "isConnected"):
                if not self._interface.isConnected:
                    self._mark_disconnected()
        except Exception:
            self._mark_disconnected()

    def _mark_disconnected(self) -> None:
        if not self._connected:
            return
        self._connected = False
        if self._interface:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None
        if self._on_disconnect:
            self._on_disconnect()
        self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    def _stop_reconnect_loop(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    async def _reconnect_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reconnect_interval)
            _LOGGER.info(
                "Attempting reconnect to %s %s...", self._connection_type, self._port
            )
            if await self._do_connect():
                _LOGGER.info("Reconnected successfully")
                return
            _LOGGER.warning(
                "Reconnect failed, will retry in %ss", self._reconnect_interval
            )

    @property
    def is_connected(self) -> bool:
        return self._connected
