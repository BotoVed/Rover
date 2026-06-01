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
        _LOGGER.info("Transport connecting to %s %s...", connection_type, port)
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
            _LOGGER.info("Transport connected to %s %s", self._connection_type, self._port)
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

    def _handle_receive(self, packet: Any, interface: Any = None) -> None:
        if not self._connected:
            return

        from meshtastic.protobuf import portnums_pb2

        try:
            if isinstance(packet, dict):
                decoded = packet.get("decoded", {})
                if isinstance(decoded, dict):
                    from_port = decoded.get("portnum", 0)
                    from_node = packet.get("from", 0)
                else:
                    from_port = getattr(decoded, "portnum", 0)
                    from_node = packet.get("from", 0)
            else:
                decoded = getattr(packet, "decoded", None)
                from_port = getattr(decoded, "portnum", 0) if decoded else 0
                from_node = getattr(packet, "fromId", getattr(packet, "from", 0))

            _LOGGER.debug("Raw packet: port=%s from=%s", from_port, from_node)

            if from_port == portnums_pb2.ROUTING_APP:
                if isinstance(decoded, dict):
                    routing = decoded.get("routing", {})
                else:
                    routing = getattr(decoded, "routing", None) if decoded else {}
                if isinstance(routing, dict):
                    request_id = routing.get("requestId", 0)
                    error_reason = routing.get("errorReason", routing.get("error"))
                    success = error_reason is None or error_reason == "NONE" or error_reason == 0
                else:
                    request_id = getattr(routing, "requestId", 0)
                    error_reason = getattr(routing, "errorReason", getattr(routing, "error", None))
                    success = not error_reason or str(error_reason) == "NONE"

                if request_id and self._on_ack and self._loop:
                    _LOGGER.debug("Routing: request_id=%s success=%s error=%s",
                                 request_id, success, error_reason)
                    self._loop.call_soon_threadsafe(self._on_ack, request_id, success)
                return

            if from_port == MESHTASTIC_PRIVATE_APP_PORT:
                if isinstance(decoded, dict):
                    payload = decoded.get("payload", b"")
                else:
                    payload = getattr(decoded, "payload", getattr(decoded, "data", b"")) if decoded else b""
                if isinstance(payload, str):
                    payload = payload.encode("latin-1")
                if payload and self._on_packet and self._loop:
                    _LOGGER.info("Rover packet from %s, %d bytes", from_node, len(payload))
                    self._loop.call_soon_threadsafe(self._on_packet, payload, from_node)
        except Exception:
            _LOGGER.exception("Error handling received packet: %s", packet)

    async def send(self, payload: bytes, want_ack: bool = True) -> int | None:
        if not self._connected or not self._interface:
            _LOGGER.warning("Transport: cannot send, not connected")
            return None

        def _send() -> int | None:
            try:
                result = self._interface.sendData(
                    payload,
                    destinationId=MESHTASTIC_BROADCAST_ADDR,
                    portNum=MESHTASTIC_PRIVATE_APP_PORT,
                    wantAck=want_ack,
                )
                if result is None:
                    return None
                if isinstance(result, int):
                    return result
                packet_id = getattr(result, "id", None)
                if packet_id is None and isinstance(result, dict):
                    packet_id = result.get("id")
                _LOGGER.debug("Sent %d bytes, packet_id=%s", len(payload), packet_id)
                return packet_id
            except Exception:
                _LOGGER.exception("Transport: send failed")
                return None

        return await asyncio.get_running_loop().run_in_executor(None, _send)

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
