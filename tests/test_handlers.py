"""Tests for handlers.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.rover.handlers import RoverHandlers
from custom_components.rover.const import TP_CONFIG, TP_PING_PONG, TP_STATUS


SRC_OWNER = "aa" * 16
SRC_REGULAR = "bb" * 16
SRC_UNKNOWN = "cc" * 16


@pytest.fixture
def hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states.get = MagicMock(return_value=None)
    return h


@pytest.fixture
def registry():
    r = MagicMock()
    r.is_approved = MagicMock(side_effect=lambda h: h in (SRC_OWNER, SRC_REGULAR))
    r.get_device = MagicMock(return_value=None)
    r.get_hashes = MagicMock(return_value={"m": "0000", "u": "0000", "a": "0000", "d": "0000"})
    r.get_meta = MagicMock(return_value={"server_name": "Rover Hub", "version": "0.3.0"})
    r.all_users = MagicMock(return_value=[])
    r.all_areas = MagicMock(return_value=[])
    r.all_devices = MagicMock(return_value=[])
    r.add_pending = AsyncMock(return_value=True)
    r.approve_pending = AsyncMock(return_value=True)
    r.consume_qr_token = MagicMock(return_value=True)
    return r


@pytest.fixture
def transport():
    t = MagicMock()
    t.send = AsyncMock()
    return t


@pytest.fixture
def handlers(hass, registry, transport):
    return RoverHandlers(hass, registry, transport)


# ---------- CMD ----------
@pytest.mark.asyncio
async def test_cmd_unknown_source_rejected(handlers, hass, transport):
    await handlers.handle_cmd(bytes.fromhex(SRC_UNKNOWN), {"tp": 5, "id": 1, "s": True})
    hass.services.async_call.assert_not_awaited()
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_unknown_device_rejected(handlers, hass, registry):
    registry.get_device.return_value = None
    await handlers.handle_cmd(bytes.fromhex(SRC_OWNER), {"tp": 5, "id": 999, "s": True})
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_disabled_device_rejected(handlers, hass, registry):
    registry.get_device.return_value = {
        "short_id": 1, "entity_id": "switch.lamp", "type": "SW", "enabled": False
    }
    await handlers.handle_cmd(bytes.fromhex(SRC_OWNER), {"tp": 5, "id": 1, "s": True})
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_sw_turn_on(handlers, hass, registry):
    registry.get_device.return_value = {
        "short_id": 1, "entity_id": "switch.lamp", "type": "SW", "enabled": True
    }
    await handlers.handle_cmd(bytes.fromhex(SRC_OWNER), {"tp": 5, "id": 1, "s": True})
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {"entity_id": "switch.lamp"}, blocking=False
    )


@pytest.mark.asyncio
async def test_cmd_lt_brightness(handlers, hass, registry):
    registry.get_device.return_value = {
        "short_id": 2, "entity_id": "light.kitchen", "type": "LT", "enabled": True
    }
    await handlers.handle_cmd(bytes.fromhex(SRC_OWNER), {"tp": 5, "id": 2, "s": True, "b": 75})
    hass.services.async_call.assert_awaited_once_with(
        "light", "turn_on", {"entity_id": "light.kitchen", "brightness": 191}, blocking=False
    )


@pytest.mark.asyncio
async def test_cmd_invalid_id(handlers, hass):
    await handlers.handle_cmd(bytes.fromhex(SRC_OWNER), {"tp": 5, "s": True})
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cmd_no_source(handlers, hass):
    await handlers.handle_cmd(None, {"tp": 5, "id": 1, "s": True})
    hass.services.async_call.assert_not_awaited()


# ---------- PING ----------
@pytest.mark.asyncio
async def test_ping_approved_sends_pong(handlers, transport, registry):
    registry.get_hashes.return_value = {"m": "ab12", "u": "cd34", "a": "ef56", "d": "78ab"}
    await handlers.handle_ping(bytes.fromhex(SRC_OWNER), {"tp": 6, "h": {}})
    transport.send.assert_awaited_once()
    args = transport.send.call_args[0]
    assert args[0] == SRC_OWNER
    assert args[1]["tp"] == TP_PING_PONG
    assert args[1]["h"] == {"m": "ab12", "u": "cd34", "a": "ef56", "d": "78ab"}


@pytest.mark.asyncio
async def test_ping_unknown_source_silent(handlers, transport):
    await handlers.handle_ping(bytes.fromhex(SRC_UNKNOWN), {"tp": 6, "h": {}})
    transport.send.assert_not_awaited()


# ---------- REQ ----------
@pytest.mark.asyncio
async def test_req_meta(handlers, transport, registry):
    registry.get_meta.return_value = {"server_name": "Hub", "version": "0.3.0"}
    await handlers.handle_req(bytes.fromhex(SRC_OWNER), {"tp": 8, "section": "m"})
    transport.send.assert_awaited()
    msg = transport.send.call_args_list[0][0][1]
    assert msg["tp"] == TP_CONFIG
    assert msg["section"] == "m"
    assert msg["data"] == {"server_name": "Hub", "version": "0.3.0"}


@pytest.mark.asyncio
async def test_req_devices_filters_disabled(handlers, transport, registry):
    registry.all_devices.return_value = [
        {"short_id": 1, "entity_id": "s.a", "name": "A", "type": "SW", "area_id": 1, "enabled": True},
        {"short_id": 2, "entity_id": "s.b", "name": "B", "type": "SW", "area_id": 1, "enabled": False},
    ]
    await handlers.handle_req(bytes.fromhex(SRC_OWNER), {"tp": 8, "section": "d"})
    assert transport.send.await_count == 2
    cfg = transport.send.call_args_list[0][0][1]
    assert cfg["section"] == "d"
    assert len(cfg["data"]) == 1
    assert cfg["data"][0]["id"] == 1


@pytest.mark.asyncio
async def test_req_invalid_section(handlers, transport):
    await handlers.handle_req(bytes.fromhex(SRC_OWNER), {"tp": 8, "section": "x"})
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_req_unauthorized(handlers, transport):
    await handlers.handle_req(bytes.fromhex(SRC_UNKNOWN), {"tp": 8, "section": "m"})
    transport.send.assert_not_awaited()


# ---------- REGISTER ----------
@pytest.mark.asyncio
async def test_register_first_becomes_owner(handlers, registry, transport):
    registry.all_users.return_value = []
    registry.is_approved.side_effect = lambda h: False
    await handlers.handle_register(
        bytes.fromhex("11" * 16), {"tp": 9, "name": "Ivan", "uid": "abcd"},
    )
    registry.add_pending.assert_awaited_once()
    registry.approve_pending.assert_awaited_once()
    registry.consume_qr_token.assert_called_once_with("abcd")
    assert transport.send.await_count == 6  # 4 CONFIG + 1 STATUS + 1 PONG


@pytest.mark.asyncio
async def test_register_auto_approves_with_valid_uid(handlers, registry, transport):
    registry.all_users.return_value = [{"hash": SRC_OWNER, "name": "X", "role": "owner"}]
    registry.is_approved.side_effect = lambda h: h == SRC_OWNER
    await handlers.handle_register(
        bytes.fromhex("22" * 16), {"tp": 9, "name": "Petr", "uid": "xyz"},
    )
    registry.add_pending.assert_awaited_once_with("22" * 16, "Petr")
    registry.approve_pending.assert_awaited_once()
    registry.consume_qr_token.assert_called_once_with("xyz")
    assert transport.send.await_count == 6  # 4 CONFIG + 1 STATUS + 1 PONG


@pytest.mark.asyncio
async def test_register_rejected_when_uid_mismatch(handlers, registry, transport):
    registry.consume_qr_token = MagicMock(return_value=False)
    registry.is_approved.side_effect = lambda h: False
    await handlers.handle_register(
        bytes.fromhex("33" * 16), {"tp": 9, "name": "Badger", "uid": "wrong"},
    )
    registry.add_pending.assert_not_awaited()
    registry.approve_pending.assert_not_awaited()
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_existing_user_resends_config(handlers, registry, transport):
    registry.is_approved.side_effect = lambda h: h == SRC_OWNER
    await handlers.handle_register(
        bytes.fromhex(SRC_OWNER), {"tp": 9, "name": "Owner", "uid": "abcd"},
    )
    assert transport.send.await_count == 6  # 4 CONFIG + 1 STATUS + 1 PONG
    registry.add_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_name_trimmed_to_max(handlers, registry):
    registry.all_users.return_value = []
    registry.is_approved.side_effect = lambda h: False
    long_name = "X" * 100
    await handlers.handle_register(
        bytes.fromhex("44" * 16), {"tp": 9, "name": long_name, "uid": "abcd"},
    )
    call_args = registry.add_pending.await_args
    assert len(call_args[0][1]) <= 32
