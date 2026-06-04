"""Tests for services.py."""
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.rover.services import (
    DEFAULT_LEVELS,
    SERVICE_DUMP_REGISTRY,
    SERVICE_SEND_TEST_MESSAGE,
    SERVICE_SET_LOGLEVEL,
    SERVICE_SIMULATE_INBOUND,
    _coerce_payload,
    async_register_services,
    async_unregister_services,
)


# ---------- _coerce_payload ----------
def test_coerce_dict_returns_dict():
    assert _coerce_payload({"a": 1}) == {"a": 1}


def test_coerce_empty_string_returns_empty():
    assert _coerce_payload("") == {}
    assert _coerce_payload("   ") == {}


def test_coerce_json_string_returns_dict():
    assert _coerce_payload('{"id": 1, "s": true}') == {"id": 1, "s": True}


def test_coerce_invalid_json_returns_none():
    assert _coerce_payload("not json") is None


def test_coerce_json_array_returns_none():
    assert _coerce_payload("[1, 2, 3]") is None


def test_coerce_unknown_type_returns_none():
    assert _coerce_payload(123) is None
    assert _coerce_payload(None) is None


# ---------- fixtures ----------
def _make_service_call(data):
    call = MagicMock()
    call.data = data
    return call


@pytest.fixture
def runtime():
    rt = MagicMock()
    rt.identity_hash = "fa3ee51762b59a587da700b64b75b0bf"
    rt.transport = MagicMock()
    rt.transport.send = AsyncMock()
    rt.dispatcher = MagicMock()
    rt.dispatcher.dispatch = AsyncMock()
    rt.registry = MagicMock()
    rt.registry.is_approved = MagicMock(return_value=False)
    rt.registry.add_pending = AsyncMock(return_value=True)
    rt.registry.approve_pending = AsyncMock(return_value=True)
    rt.registry.revoke_user = AsyncMock(return_value=True)
    rt.registry.get_meta = MagicMock(return_value={"server_name": "Rover Hub", "version": "0.3.0"})
    rt.registry.get_hashes = MagicMock(return_value={"m": "0000", "u": "0000", "a": "0000", "d": "0000"})
    rt.registry.all_users = MagicMock(return_value=[])
    rt.registry.all_areas = MagicMock(return_value=[])
    rt.registry.all_devices = MagicMock(return_value=[])
    rt.registry.all_pending = MagicMock(return_value=[])
    return rt


@pytest.fixture
def hass():
    h = MagicMock()
    registered = {}

    def reg(domain, name, handler, schema=None):
        registered[name] = handler

    h.services.async_register = MagicMock(side_effect=reg)
    h.services.has_service = MagicMock(return_value=False)
    h.services.async_remove = MagicMock()
    h.loop.call_later = MagicMock()
    h._registered = registered
    return h


# ---------- registration ----------
@pytest.mark.asyncio
async def test_register_all_services(hass, runtime):
    await async_register_services(hass, runtime)
    assert SERVICE_SET_LOGLEVEL in hass._registered
    assert SERVICE_SEND_TEST_MESSAGE in hass._registered
    assert SERVICE_SIMULATE_INBOUND in hass._registered
    assert SERVICE_DUMP_REGISTRY in hass._registered


@pytest.mark.asyncio
async def test_register_idempotent(hass, runtime):
    hass.services.has_service = MagicMock(return_value=True)
    await async_register_services(hass, runtime)
    hass.services.async_register.assert_not_called()


def test_unregister_removes_all(hass):
    hass.services.has_service = MagicMock(return_value=True)
    async_unregister_services(hass)
    assert hass.services.async_remove.call_count == 4


# ---------- set_loglevel ----------
@pytest.mark.asyncio
async def test_set_loglevel_changes_levels(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SET_LOGLEVEL]

    await handler(_make_service_call({"level": "debug", "duration_minutes": 5}))

    for name in DEFAULT_LEVELS:
        assert logging.getLogger(name).level == logging.DEBUG

    hass.loop.call_later.assert_called_once()
    args = hass.loop.call_later.call_args[0]
    assert args[0] == 5 * 60


@pytest.mark.asyncio
async def test_set_loglevel_invalid_level_silent(hass, runtime, caplog):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SET_LOGLEVEL]

    await handler(_make_service_call({"level": "verbose"}))
    hass.loop.call_later.assert_not_called()


# ---------- send_test_message ----------
@pytest.mark.asyncio
async def test_send_test_self_uses_identity(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SEND_TEST_MESSAGE]

    await handler(_make_service_call({"destination_hash": "self", "tp": 6, "payload": {"h": {}}}))

    runtime.transport.send.assert_awaited_once()
    dst, fields = runtime.transport.send.call_args[0]
    assert dst == runtime.identity_hash
    assert fields == {"tp": 6, "h": {}}


@pytest.mark.asyncio
async def test_send_test_hex_destination(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SEND_TEST_MESSAGE]

    dst_hex = "aabbccdd11223344556677889900aabb"
    await handler(_make_service_call({"destination_hash": dst_hex, "tp": 3, "payload": {"id": 1, "v": "on"}}))

    runtime.transport.send.assert_awaited_once()
    dst, fields = runtime.transport.send.call_args[0]
    assert dst == dst_hex
    assert fields == {"tp": 3, "id": 1, "v": "on"}


@pytest.mark.asyncio
async def test_send_test_invalid_destination(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SEND_TEST_MESSAGE]

    await handler(_make_service_call({"destination_hash": "not-hex", "tp": 6, "payload": {}}))
    runtime.transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_test_payload_as_json_string(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SEND_TEST_MESSAGE]

    dst_hex = "aabbccdd11223344556677889900aabb"
    await handler(_make_service_call({"destination_hash": dst_hex, "tp": 5, "payload": '{"id": 7, "s": true}'}))

    runtime.transport.send.assert_awaited_once()
    fields = runtime.transport.send.call_args[0][1]
    assert fields == {"tp": 5, "id": 7, "s": True}


@pytest.mark.asyncio
async def test_send_test_no_transport(hass, runtime):
    runtime.transport = None
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SEND_TEST_MESSAGE]
    await handler(_make_service_call({"destination_hash": "self", "tp": 6}))


# ---------- simulate_inbound ----------
@pytest.mark.asyncio
async def test_simulate_inbound_dispatches(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SIMULATE_INBOUND]

    src = "aabbccdd11223344556677889900aabb"
    await handler(_make_service_call({"source_hash": src, "tp": 5, "payload": {"id": 1, "s": True}}))

    runtime.dispatcher.dispatch.assert_awaited_once()
    src_bytes, fields = runtime.dispatcher.dispatch.call_args[0]
    assert src_bytes == bytes.fromhex(src)
    assert fields == {"tp": 5, "id": 1, "s": True}


@pytest.mark.asyncio
async def test_simulate_inbound_authorized_adds_and_revokes(hass, runtime):
    runtime.registry.is_approved.return_value = False
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SIMULATE_INBOUND]

    src = "11" * 16
    await handler(_make_service_call({
        "source_hash": src, "tp": 5, "payload": {"id": 1, "s": True}, "authorized": True
    }))

    runtime.registry.add_pending.assert_awaited_once_with(src, "_test_sim")
    runtime.registry.approve_pending.assert_awaited_once_with(src)
    runtime.dispatcher.dispatch.assert_awaited_once()
    runtime.registry.revoke_user.assert_awaited_once_with(src)


@pytest.mark.asyncio
async def test_simulate_inbound_already_authorized_no_cleanup(hass, runtime):
    runtime.registry.is_approved.return_value = True
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SIMULATE_INBOUND]

    src = "22" * 16
    await handler(_make_service_call({
        "source_hash": src, "tp": 5, "payload": {"id": 1, "s": True}, "authorized": True
    }))

    runtime.registry.add_pending.assert_not_awaited()
    runtime.registry.approve_pending.assert_not_awaited()
    runtime.registry.revoke_user.assert_not_awaited()
    runtime.dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_simulate_inbound_invalid_source(hass, runtime):
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SIMULATE_INBOUND]

    await handler(_make_service_call({"source_hash": "short", "tp": 5, "payload": {}}))
    runtime.dispatcher.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_simulate_inbound_no_dispatcher(hass, runtime):
    runtime.dispatcher = None
    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_SIMULATE_INBOUND]
    await handler(_make_service_call({"source_hash": "aa" * 16, "tp": 5, "payload": {}}))


# ---------- dump_registry ----------
@pytest.mark.asyncio
async def test_dump_registry_logs_state(hass, runtime, caplog):
    runtime.registry.all_users.return_value = [
        {"hash": "ab" * 16, "name": "Ivan", "role": "owner"},
    ]
    runtime.registry.all_devices.return_value = [
        {"short_id": 1, "name": "Lamp", "type": "SW", "entity_id": "switch.lamp",
         "area_id": 1, "enabled": True},
    ]
    runtime.registry.all_pending.return_value = [
        {"hash": "cd" * 16, "name": "Petr"},
    ]

    await async_register_services(hass, runtime)
    handler = hass._registered[SERVICE_DUMP_REGISTRY]

    with caplog.at_level(logging.INFO, logger="custom_components.rover"):
        await handler(_make_service_call({}))

    text = caplog.text
    assert "REG DUMP" in text
    assert "Ivan" in text
    assert "Lamp" in text
    assert "Petr" in text
