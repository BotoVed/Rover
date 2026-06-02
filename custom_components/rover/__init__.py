from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from .codec import FragmentBuffer, decode
from .const import (
    CONF_ACK_TIMEOUT,
    CONF_CONN_TYPE,
    CONF_MAX_RETRIES,
    CONF_PORT,
    CONF_QUEUE_PERIOD,
    DEFAULT_ACK_TIMEOUT,
    DEFAULT_CONN_TYPE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_PERIOD,
    DOMAIN,
    TP_FRAGMENT,
)
from .dispatcher import Dispatcher
from .handlers import Handlers
from .ha_bridge import HaBridge
from .queue import Batcher, InDedup, OutQueue
from .registry import Registry
from .transport import Transport

from homeassistant.config_entries import ConfigEntryNotReady

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.event import async_track_time_interval

__version__ = "0.2.11"

_LOGGER = logging.getLogger(__name__)


def _make_on_packet(
    dispatcher: Dispatcher,
    fragment_buffer: FragmentBuffer,
    dedup: InDedup,
):

    def _on_packet(payload: bytes, from_node: int) -> None:
        try:
            packet = decode(payload)
        except Exception:
            _LOGGER.exception("Failed to decode incoming packet")
            return

        _LOGGER.info("Packet from node %s: %s", from_node, packet)

        tp = packet.get("tp")

        if tp == TP_FRAGMENT:
            assembled = fragment_buffer.feed(packet)
            if assembled is not None:
                cmid = assembled.get("cmid")
                if cmid and dedup.seen(cmid):
                    return
                asyncio.create_task(dispatcher.dispatch(assembled, from_node))
            return

        cmid = packet.get("cmid")
        if cmid and dedup.seen(cmid):
            return

        asyncio.create_task(dispatcher.dispatch(packet, from_node))

    return _on_packet


def _make_on_ack(out_queue: OutQueue, handlers: Handlers):

    def _on_ack(packet_id: int, success: bool) -> None:
        if success:
            out_queue.on_ack(packet_id)
        else:
            out_queue.on_nak(packet_id)
        handlers.mark_node_online(0)

    return _on_ack


async def _send_cycle(
    out_queue: OutQueue,
    batcher: Batcher,
    transport: Transport,
) -> None:
    """Один цикл отправки: собрать пачку → отправить → пометить."""
    now = time.monotonic()
    batch = batcher.build_batch(out_queue, now=now)
    if not batch.packets:
        return

    last_packet_id = None
    for raw_bytes in batch.packets:
        packet_id = await transport.send(raw_bytes)
        if packet_id is None:
            _LOGGER.warning("Send cycle: transport.send returned None, aborting batch")
            return
        last_packet_id = packet_id

    if last_packet_id is not None:
        now = time.monotonic()
        for key in batch.sent_keys:
            out_queue.mark_sent(key, last_packet_id, now=now)


async def _check_ack_timeouts(
    out_queue: OutQueue,
    ack_timeout: float,
    queue_period: float,
) -> None:
    now = time.monotonic()
    out_queue.check_ack_timeouts(ack_timeout=ack_timeout, period=queue_period, now=now)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.helpers.event import async_track_time_interval

    _LOGGER.info("Rover: setting up entry %s (title=%s)", entry.entry_id, entry.title)

    config = {**entry.data, **entry.options}

    registry = Registry()
    registry_path = hass.config.path(f"{DOMAIN}_registry.json")
    await registry.load(registry_path)

    ha_bridge = HaBridge(hass)
    out_queue = OutQueue()
    batcher = Batcher()
    dedup = InDedup()
    fragment_buffer = FragmentBuffer()
    transport = Transport()
    handlers = Handlers(registry, ha_bridge, out_queue, config)
    dispatcher = Dispatcher(handlers)

    transport.set_callbacks(
        on_packet=_make_on_packet(dispatcher, fragment_buffer, dedup),
        on_ack=_make_on_ack(out_queue, handlers),
    )

    ha_bridge.set_callbacks(
        on_state_changed=handlers.on_ha_state_changed,
        on_registry_changed=handlers.on_ha_registry_changed,
    )

    conn_type = config.get(CONF_CONN_TYPE, DEFAULT_CONN_TYPE)
    port = config.get(CONF_PORT)
    try:
        async with asyncio.timeout(30):
            await transport.connect(conn_type, port)
    except (asyncio.TimeoutError, Exception) as e:
        _LOGGER.warning("Connection failed: %s, will retry", e)
        raise ConfigEntryNotReady(
            f"Failed to connect to {conn_type} {port}: {e}"
        ) from e

    # Реестр пуст — пользователь добавляет устройства через options_flow
    ha_bridge.start_tracking([])
    await ha_bridge.start_registry_listeners()

    home_name = config.get("home_name", "Rover")
    handlers.set_meta_dict({"n": home_name})

    queue_period = config.get(CONF_QUEUE_PERIOD, DEFAULT_QUEUE_PERIOD)
    ack_timeout = config.get(CONF_ACK_TIMEOUT, DEFAULT_ACK_TIMEOUT)

    def _schedule(coro):
        """Запускает корутину в event loop из любого треда."""
        hass.loop.call_soon_threadsafe(
            asyncio.create_task, coro
        )

    unsub_send = async_track_time_interval(
        hass,
        lambda now: _schedule(
            _send_cycle(out_queue, batcher, transport)
        ),
        timedelta(seconds=queue_period),
    )
    unsub_ack = async_track_time_interval(
        hass,
        lambda now: _schedule(
            _check_ack_timeouts(out_queue, ack_timeout, queue_period)
        ),
        timedelta(seconds=max(1, min(ack_timeout, queue_period) // 2)),
    )
    unsub_alive = async_track_time_interval(
        hass,
        lambda _: transport.check_alive(),
        timedelta(seconds=30),
    )

    entry.runtime_data = RoverRuntimeData(
        registry=registry,
        transport=transport,
        out_queue=out_queue,
        dispatcher=dispatcher,
        handlers=handlers,
        ha_bridge=ha_bridge,
        unsub_send=unsub_send,
        unsub_ack=unsub_ack,
        unsub_alive=unsub_alive,
    )

    _LOGGER.info("Rover: entry %s ready", entry.entry_id)

    await _async_register_test_services(hass, entry)

    return True


async def _async_register_test_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register rover.test_ping and rover.test_cmd. Idempotent."""
    if hass.services.has_service(DOMAIN, "test_ping"):
        return

    from homeassistant.core import ServiceCall

    async def handle_test_ping(call: ServiceCall) -> None:
        from .test_e2e import simulate_ping
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.warning("[TEST PING] No Rover entries configured")
            return
        rt = entries[0].runtime_data
        await simulate_ping(hass, rt.dispatcher)

    async def handle_test_cmd(call: ServiceCall) -> None:
        from .test_e2e import simulate_cmd
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.warning("[TEST CMD] No Rover entries configured")
            return
        rt = entries[0].runtime_data
        device_id = call.data["device_id"]
        value = call.data.get("value")
        await simulate_cmd(hass, rt.dispatcher, rt.registry, device_id, value)

    hass.services.async_register(DOMAIN, "test_ping", handle_test_ping)
    hass.services.async_register(DOMAIN, "test_cmd", handle_test_cmd)
    _LOGGER.info("Rover test services registered")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Rover: unloading entry %s", entry.entry_id)

    data: RoverRuntimeData = entry.runtime_data

    if data.unsub_send:
        data.unsub_send()
    if data.unsub_ack:
        data.unsub_ack()
    if data.unsub_alive:
        data.unsub_alive()

    if data.ha_bridge:
        data.ha_bridge.stop_tracking()

    if data.transport:
        await data.transport.disconnect()

    registry_path = hass.config.path(f"{DOMAIN}_registry.json")
    await data.registry.save(registry_path)

    if not hass.config_entries.async_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, "test_ping")
        hass.services.async_remove(DOMAIN, "test_cmd")

    return True


@dataclass
class RoverRuntimeData:
    registry: Registry
    transport: Transport | None = None
    out_queue: OutQueue | None = None
    dispatcher: Dispatcher | None = None
    handlers: Handlers | None = None
    ha_bridge: HaBridge | None = None
    unsub_send: object | None = None
    unsub_ack: object | None = None
    unsub_alive: object | None = None


type RoverConfigEntry = ConfigEntry[RoverRuntimeData]
