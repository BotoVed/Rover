"""Tests for ha_bridge.py."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.rover.ha_bridge import RoverHABridge
from custom_components.rover.const import TP_PUSH, PUSH_THROTTLE_MS, SENSOR_PUSH_INTERVAL


def make_state(state_value, attributes=None):
    s = MagicMock()
    s.state = state_value
    s.attributes = attributes or {}
    return s


def make_event(entity_id, new_state):
    e = MagicMock()
    e.data = {"entity_id": entity_id, "new_state": new_state}
    return e


@pytest.fixture
async def hass():
    loop = asyncio.get_running_loop()
    h = MagicMock()
    h.bus.async_listen = MagicMock(return_value=lambda: None)
    h.loop = loop
    h.async_create_task = lambda coro: loop.create_task(coro)
    return h


@pytest.fixture
def registry():
    r = MagicMock()
    r.get_device_by_entity_id = MagicMock(return_value=None)
    r.get_device = MagicMock(return_value=None)
    r.all_users = MagicMock(return_value=[
        {"hash": "aa" * 16, "name": "Owner", "role": "owner"},
    ])
    r.get_hashes = MagicMock(return_value={"m": "0000", "u": "0000", "a": "0000", "d": "0000"})
    return r


@pytest.fixture
def transport():
    t = MagicMock()
    t.send = AsyncMock()
    return t


@pytest.fixture
def bridge(hass, registry, transport):
    return RoverHABridge(hass, registry, transport)


# ---------- start / stop ----------
@pytest.mark.asyncio
async def test_start_subscribes(bridge, hass):
    await bridge.async_start()
    hass.bus.async_listen.assert_called_once()
    args = hass.bus.async_listen.call_args[0]
    assert args[0] == "state_changed"


@pytest.mark.asyncio
async def test_stop_unsubscribes(bridge, hass):
    unsub = MagicMock()
    hass.bus.async_listen.return_value = unsub
    await bridge.async_start()
    await bridge.async_stop()
    unsub.assert_called_once()


# ---------- filtering ----------
@pytest.mark.asyncio
async def test_event_unknown_entity_ignored(bridge, registry, transport):
    registry.get_device_by_entity_id.return_value = None
    bridge._on_event(make_event("switch.unknown", make_state("on")))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_disabled_device_ignored(bridge, registry, transport):
    registry.get_device_by_entity_id.return_value = {
        "short_id": 1, "entity_id": "switch.a", "type": "SW", "enabled": False
    }
    bridge._on_event(make_event("switch.a", make_state("on")))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_no_new_state_ignored(bridge, transport):
    e = MagicMock()
    e.data = {"entity_id": "switch.a", "new_state": None}
    bridge._on_event(e)
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    transport.send.assert_not_awaited()


# ---------- basic push ----------
@pytest.mark.asyncio
async def test_sw_push_after_throttle(bridge, registry, transport):
    dev = {"short_id": 1, "entity_id": "switch.a", "type": "SW", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev

    bridge._on_event(make_event("switch.a", make_state("on")))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 / 2)
    transport.send.assert_not_awaited()

    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    transport.send.assert_awaited_once()
    args = transport.send.call_args[0]
    assert args[0] == "aa" * 16
    assert args[1] == {"tp": TP_PUSH, "id": 1, "v": "on"}


@pytest.mark.asyncio
async def test_push_to_multiple_users(bridge, registry, transport):
    dev = {"short_id": 1, "entity_id": "switch.a", "type": "SW", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev
    registry.all_users.return_value = [
        {"hash": "aa" * 16, "name": "A", "role": "owner"},
        {"hash": "bb" * 16, "name": "B", "role": "regular"},
        {"hash": "cc" * 16, "name": "C", "role": "regular"},
    ]

    bridge._on_event(make_event("switch.a", make_state("off")))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    assert transport.send.await_count == 3


@pytest.mark.asyncio
async def test_no_users_no_send(bridge, registry, transport):
    dev = {"short_id": 1, "entity_id": "switch.a", "type": "SW", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev
    registry.all_users.return_value = []

    bridge._on_event(make_event("switch.a", make_state("on")))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)
    transport.send.assert_not_awaited()


# ---------- throttle / coalescing ----------
@pytest.mark.asyncio
async def test_rapid_changes_coalesce(bridge, registry, transport):
    dev = {"short_id": 1, "entity_id": "switch.a", "type": "SW", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev

    for v in ["on", "off", "on", "off", "on"]:
        bridge._on_event(make_event("switch.a", make_state(v)))

    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.1)

    transport.send.assert_awaited_once()
    msg = transport.send.call_args[0][1]
    assert msg["v"] == "on"


# ---------- SE rate limit ----------
@pytest.mark.asyncio
async def test_se_first_push_immediate_after_throttle(bridge, registry, transport):
    dev = {"short_id": 7, "entity_id": "sensor.t", "type": "SE", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev

    bridge._on_event(make_event("sensor.t", make_state("21.5", {"unit_of_measurement": "°C"})))
    await asyncio.sleep(PUSH_THROTTLE_MS / 1000 + 0.2)

    transport.send.assert_awaited_once()
    msg = transport.send.call_args[0][1]
    assert msg["v"] == "21.5"
    assert msg["u"] == "°C"


@pytest.mark.asyncio
async def test_se_second_push_delayed_by_cooldown(bridge, registry, transport):
    dev = {"short_id": 7, "entity_id": "sensor.t", "type": "SE", "enabled": True}
    registry.get_device_by_entity_id.return_value = dev
    registry.get_device.return_value = dev

    bridge._last_sent[7] = time.monotonic() - 1.0

    bridge._on_event(make_event("sensor.t", make_state("22.0")))

    await asyncio.sleep(0.6)
    transport.send.assert_not_awaited()

    await asyncio.sleep(4.5)
    transport.send.assert_awaited_once()


# ---------- pong broadcast ----------
@pytest.mark.asyncio
async def test_broadcast_pong_to_all_users(bridge, registry, transport):
    registry.all_users.return_value = [
        {"hash": "aa" * 16, "name": "A", "role": "owner"},
        {"hash": "bb" * 16, "name": "B", "role": "regular"},
    ]
    registry.get_hashes.return_value = {"m": "ab12", "u": "cd34", "a": "ef56", "d": "78ab"}

    await bridge.broadcast_pong()

    assert transport.send.await_count == 2
    for call in transport.send.await_args_list:
        msg = call[0][1]
        assert msg["tp"] == 6
        assert msg["h"] == {"m": "ab12", "u": "cd34", "a": "ef56", "d": "78ab"}


@pytest.mark.asyncio
async def test_broadcast_pong_no_users(bridge, registry, transport):
    registry.all_users.return_value = []
    await bridge.broadcast_pong()
    transport.send.assert_not_awaited()
