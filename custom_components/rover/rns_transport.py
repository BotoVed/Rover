"""RNS/LXMF transport wrapper for Rover."""
from __future__ import annotations

import logging
import os
import signal as signal_module
from typing import Callable

import RNS
import LXMF

from homeassistant.core import HomeAssistant

from .codec import decode
from .const import DEFAULT_TCP_PORT, LOGGER_TRN


class RoverTransport:
    def __init__(
        self,
        hass: HomeAssistant,
        config_dir: str,
        on_message: Callable,
        tcp_port: int = DEFAULT_TCP_PORT,
    ) -> None:
        self._hass = hass
        self._config_dir = config_dir
        self._on_message = on_message
        self._tcp_port = tcp_port
        self._logger = logging.getLogger(LOGGER_TRN)
        self._identity: RNS.Identity | None = None
        self._router: LXMF.LXMRouter | None = None
        self._delivery_dest = None
        self._tcp_interface = None  # TCPServerInterface, lazy import
        self._shutdown = False

    async def async_start(self) -> str:
        def _init():
            os.makedirs(self._config_dir, exist_ok=True)
            os.makedirs(os.path.join(self._config_dir, "lxmf_storage"), exist_ok=True)

            identity_path = os.path.join(self._config_dir, "rover_identity")
            if os.path.exists(identity_path):
                identity = RNS.Identity.from_file(identity_path)
            else:
                identity = RNS.Identity()
                identity.to_file(identity_path)
            identity_hash = identity.hash.hex()
            self._logger.info(
                "RNS init identity=%s...", identity_hash[:16]
            )
            self._identity = identity

            # Both RNS.Reticulum and LXMF.LXMRouter call signal.signal()
            # in their __init__, which raises from a worker thread.
            _orig_signal = signal_module.signal
            signal_module.signal = lambda signum, handler: None
            try:
                try:
                    RNS.Reticulum(configdir=self._config_dir)
                    self._logger.info("RNS init configdir=%s", self._config_dir)
                except OSError:
                    self._logger.warning("RNS already running, reusing")

                router = LXMF.LXMRouter(
                    identity=self._identity,
                    storagepath=os.path.join(self._config_dir, "lxmf_storage"),
                )
            finally:
                signal_module.signal = _orig_signal
            self._logger.info("LXMF router started")
            self._router = router

            dest = router.register_delivery_identity(
                self._identity,
                display_name="Rover Hub",
                stamp_cost=None,
            )
            self._delivery_dest = dest
            self._logger.info("LXMF delivery identity registered")

            router.register_delivery_callback(self._on_lxmf_message)

            # TCP Server Interface для прямых mesh-подключений
            try:
                from RNS.Interfaces.TCPInterface import TCPServerInterface
                self._tcp_interface = TCPServerInterface(
                    RNS.Transport,
                    name="Rover TCP",
                    port=self._tcp_port,
                    bindip="0.0.0.0",
                )
                RNS.Transport.interfaces.append(self._tcp_interface)
                self._logger.info(
                    "TCP interface started on port %s", self._tcp_port
                )
            except Exception as exc:
                self._logger.warning(
                    "TCP interface failed on port %s: %s", self._tcp_port, exc
                )

        await self._hass.async_add_executor_job(_init)
        return self._identity.hash.hex()

    @property
    def identity(self) -> RNS.Identity | None:
        return self._identity

    def _on_lxmf_message(self, message: LXMF.LXMessage) -> None:
        trace = message.hash.hex()[:8] if message.hash else "--------"
        src_hex = message.source_hash.hex() if message.source_hash else ""

        fields: dict | None = None
        if isinstance(message.fields, dict):
            fields = message.fields
        elif isinstance(message.fields, bytes):
            try:
                fields = decode(message.fields)
            except Exception as exc:
                self._logger.error(
                    "IN [%s] src=%s... decode error: %s",
                    trace, src_hex[:8], exc,
                )
                return
        elif isinstance(message.content, bytes):
            try:
                fields = decode(message.content)
            except Exception as exc:
                self._logger.error(
                    "IN [%s] src=%s... content decode error: %s",
                    trace, src_hex[:8], exc,
                )
                return
        else:
            self._logger.error(
                "IN [%s] src=%s... no valid fields or content",
                trace, src_hex[:8],
            )
            return

        self._logger.debug(
            "IN [%s] src=%s... fields_keys=%s",
            trace, src_hex[:8], list(fields.keys()),
        )
        self._hass.add_job(self._on_message, message.source_hash, fields)

    async def send(
        self,
        destination_hash_hex: str,
        fields: dict,
        delivery_callback: Callable | None = None,
        failed_callback: Callable | None = None,
    ) -> bool:
        dst_bytes = bytes.fromhex(destination_hash_hex)
        trace = os.urandom(4).hex()

        remote_identity = RNS.Identity.recall(dst_bytes)
        if remote_identity is None:
            RNS.Transport.request_path(dst_bytes)
            self._logger.warning(
                "OUT [%s] dst=%s... identity not in cache, requested path",
                trace, destination_hash_hex[:8],
            )
            return False

        remote_dest = RNS.Destination(
            remote_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            "lxmf", "delivery",
        )

        def _do_send():
            msg = LXMF.LXMessage(
                destination=remote_dest,
                source=self._delivery_dest,
                content=b"",
                title=b"",
                desired_method=LXMF.LXMessage.DIRECT,
            )
            msg.fields = fields

            msg.register_delivery_callback(
                lambda m: self._on_delivery(m, trace)
            )
            msg.register_failed_callback(
                lambda m: self._on_failed(m, trace)
            )

            self._router.handle_outbound(msg)

            self._logger.debug(
                "OUT [%s] dst=%s... fields_keys=%s",
                trace, destination_hash_hex[:8], list(fields.keys()),
            )

        await self._hass.async_add_executor_job(_do_send)
        return True

    def _on_delivery(self, message: LXMF.LXMessage, trace: str) -> None:
        self._logger.debug("DELIVERY [%s] state=DELIVERED", trace)

    def _on_failed(self, message: LXMF.LXMessage, trace: str) -> None:
        self._logger.warning("FAILED [%s] — LXMF delivery failed", trace)

    async def shutdown(self) -> None:
        self._shutdown = True

        def _do_shutdown():
            if self._tcp_interface is not None:
                try:
                    if self._tcp_interface in RNS.Transport.interfaces:
                        RNS.Transport.interfaces.remove(self._tcp_interface)
                    self._tcp_interface = None
                    self._logger.info("TCP interface removed")
                except Exception:
                    pass
            if self._router:
                try:
                    self._router.stop()
                except Exception:
                    pass
                self._router = None

        await self._hass.async_add_executor_job(_do_shutdown)
        self._logger.info("Transport shutdown complete")
