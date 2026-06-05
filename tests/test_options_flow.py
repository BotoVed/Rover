"""Tests for options_flow.py — logic of step handlers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.rover.options_flow import RoverOptionsFlow


def _state(friendly=None):
    s = MagicMock()
    s.attributes = {"friendly_name": friendly} if friendly else {}
    return s


@pytest.fixture
def registry():
    r = MagicMock()
    r.get_meta = MagicMock(return_value={"server_name": "Rover Hub", "version": "0.3.0"})
    r.set_server_name = AsyncMock()
    r.all_devices = MagicMock(return_value=[])
    r.get_device_by_entity_id = MagicMock(return_value=None)
    r.add_device = AsyncMock(return_value=1)
    r.remove_device = AsyncMock(return_value=True)
    r.all_users = MagicMock(return_value=[])
    r.revoke_user = AsyncMock(return_value=True)
    r.all_pending = MagicMock(return_value=[])
    r.approve_pending = AsyncMock(return_value=True)
    return r


@pytest.fixture
def runtime(registry):
    rt = MagicMock()
    rt.registry = registry
    rt.identity_hash = "fa3ee51762b59a587da700b64b75b0bf"
    return rt


@pytest.fixture
def entry(runtime):
    e = MagicMock()
    e.runtime_data = runtime
    return e


@pytest.fixture
def flow(entry):
    f = RoverOptionsFlow(entry)
    f.hass = MagicMock()
    f.hass.states.get = MagicMock(return_value=_state("Lamp"))
    f.async_show_menu = MagicMock(side_effect=lambda **kwargs: {"type": "menu", **kwargs})
    f.async_show_form = MagicMock(side_effect=lambda **kwargs: {"type": "form", **kwargs})
    f.async_abort = MagicMock(side_effect=lambda **kwargs: {"type": "abort", **kwargs})
    return f


@pytest.mark.asyncio
async def test_init_shows_menu(flow):
    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert "general" in result["menu_options"]
    assert "devices" in result["menu_options"]
    assert "device_remove" in result["menu_options"]
    assert "users" in result["menu_options"]
    assert "pending" in result["menu_options"]
    assert "config" in result["menu_options"]
    assert "device_test" in result["menu_options"]


@pytest.mark.asyncio
async def test_init_no_registry_aborts(flow):
    flow.config_entry.runtime_data.registry = None
    result = await flow.async_step_init()
    assert result["type"] == "abort"


@pytest.mark.asyncio
async def test_general_form_shown(flow):
    result = await flow.async_step_general()
    assert result["type"] == "form"
    assert result["step_id"] == "general"


@pytest.mark.asyncio
async def test_general_submit_sets_name(flow, registry):
    await flow.async_step_general({"server_name": "Камиль RV"})
    registry.set_server_name.assert_awaited_once_with("Камиль RV")


@pytest.mark.asyncio
async def test_general_submit_empty_ignored(flow, registry):
    await flow.async_step_general({"server_name": "   "})
    registry.set_server_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_devices_form_shown(flow):
    result = await flow.async_step_devices()
    assert result["type"] == "form"
    assert result["step_id"] == "devices"


@pytest.mark.asyncio
async def test_devices_submit_adds_new(flow, registry):
    registry.get_device_by_entity_id.return_value = None
    await flow.async_step_devices({"entities": ["switch.lamp", "sensor.temp"]})
    assert registry.add_device.await_count == 2


@pytest.mark.asyncio
async def test_devices_skips_existing(flow, registry):
    registry.get_device_by_entity_id.side_effect = [None, {"short_id": 1}]
    await flow.async_step_devices({"entities": ["switch.a", "switch.b"]})
    assert registry.add_device.await_count == 1


@pytest.mark.asyncio
async def test_devices_skips_unsupported_domain(flow, registry):
    await flow.async_step_devices({"entities": ["zone.home"]})
    registry.add_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_remove_empty_list(flow, registry):
    registry.all_devices.return_value = []
    result = await flow.async_step_device_remove()
    assert result["type"] == "form"
    assert result["description_placeholders"]["count"] == "0"


@pytest.mark.asyncio
async def test_device_remove_submit_removes(flow, registry):
    registry.all_devices.return_value = [
        {"short_id": 1, "name": "A", "type": "SW"},
        {"short_id": 2, "name": "B", "type": "LT"},
    ]
    await flow.async_step_device_remove({"device_ids": ["1", "2"]})
    assert registry.remove_device.await_count == 2
    registry.remove_device.assert_any_await(1)
    registry.remove_device.assert_any_await(2)


@pytest.mark.asyncio
async def test_device_remove_ignores_invalid_id(flow, registry):
    registry.all_devices.return_value = [{"short_id": 1, "name": "A", "type": "SW"}]
    await flow.async_step_device_remove({"device_ids": ["not_int"]})
    registry.remove_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_test_empty_list(flow, registry):
    registry.all_devices.return_value = []
    result = await flow.async_step_device_test()
    assert result["type"] == "form"
    assert result["description_placeholders"]["count"] == "0"


@pytest.mark.asyncio
async def test_device_test_submit_calls_service(flow, registry):
    registry.all_devices.return_value = [
        {"short_id": 1, "name": "Lamp", "type": "SW", "entity_id": "switch.lamp"},
    ]
    registry.get_device = MagicMock(return_value={"short_id": 1, "name": "Lamp", "type": "SW", "entity_id": "switch.lamp"})
    flow.hass.services.async_call = AsyncMock()
    await flow.async_step_device_test({"device_id": "1", "action": "toggle"})
    flow.hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "toggle", {"entity_id": "switch.lamp"}, blocking=True
    )


@pytest.mark.asyncio
async def test_users_empty_list_form(flow, registry):
    registry.all_users.return_value = []
    result = await flow.async_step_users()
    assert result["type"] == "form"
    assert result["description_placeholders"]["active"] == "0"


@pytest.mark.asyncio
async def test_users_revoke(flow, registry):
    registry.all_users.return_value = [
        {"hash": "ab" * 16, "name": "X", "role": "regular"},
    ]
    await flow.async_step_users({"user_hashes": ["ab" * 16]})
    registry.revoke_user.assert_awaited_once_with("ab" * 16)


@pytest.mark.asyncio
async def test_pending_empty_form(flow, registry):
    registry.all_pending.return_value = []
    result = await flow.async_step_pending()
    assert result["type"] == "form"
    assert result["description_placeholders"]["count"] == "0"


@pytest.mark.asyncio
async def test_pending_approve(flow, registry):
    h = "cd" * 16
    await flow.async_step_pending({"pending_hash": h, "action": "approve"})
    registry.approve_pending.assert_awaited_once_with(h)


@pytest.mark.asyncio
async def test_pending_reject_no_op(flow, registry):
    h = "cd" * 16
    await flow.async_step_pending({"pending_hash": h, "action": "reject"})
    registry.approve_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_shows_identity_and_qr(flow, runtime):
    result = await flow.async_step_config()
    assert result["type"] == "form"
    ph = result["description_placeholders"]
    assert ph["identity"] == runtime.identity_hash
    assert ph["server_name"] == "Rover Hub"
    import json
    qr = json.loads(ph["qr_payload"])
    assert qr["rvr"]["dst"] == runtime.identity_hash
    assert qr["rvr"]["fmt"] == 1


@pytest.mark.asyncio
async def test_config_submit_returns_to_menu(flow):
    result = await flow.async_step_config({})
    assert result["type"] == "menu"
