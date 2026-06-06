"""Tests for options_flow.py — logic of step handlers."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

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
    f.handler = "test_entry_id"
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
    assert "test_device" in result["menu_options"]


@pytest.mark.asyncio
async def test_init_no_registry_aborts(flow):
    flow._config_entry.runtime_data.registry = None
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
    result = await flow.async_step_test_device()
    assert result["type"] == "form"
    assert result["step_id"] == "test_device"


@pytest.mark.asyncio
async def test_test_device_filters_to_testable(flow, registry):
    registry.all_devices.return_value = [
        {"short_id": 1, "name": "Lamp", "type": "SW", "entity_id": "switch.lamp", "enabled": True},
        {"short_id": 2, "name": "Temp", "type": "SE", "entity_id": "sensor.t", "enabled": True},
        {"short_id": 3, "name": "Disabled", "type": "SW", "entity_id": "switch.d", "enabled": False},
    ]
    result = await flow.async_step_test_device()
    assert result["type"] == "form"
    assert result["step_id"] == "test_device"
    # Verify filtering via description (Lamp should be listed, disabled/SE not)
    dl = result.get("description_placeholders", {}).get("device_list", "")
    assert "#1 Lamp [SW] switch.lamp" in dl, f"expected SW device in list, got: {dl}"
    assert "Temp" not in dl, "SE device should be filtered out"
    assert "Disabled" not in dl, "disabled device should be filtered out"


@pytest.mark.asyncio
async def test_test_device_picks_then_action_on(flow, registry, runtime):
    dev = {"short_id": 5, "name": "Pump", "type": "SW", "entity_id": "switch.pump", "enabled": True}
    registry.all_devices.return_value = [dev]
    registry.get_device.return_value = dev
    registry.is_approved.return_value = False
    registry.add_pending = AsyncMock(return_value=True)
    registry.approve_pending = AsyncMock(return_value=True)
    registry.revoke_user = AsyncMock(return_value=True)
    runtime.handlers = MagicMock()
    runtime.handlers.handle_cmd = AsyncMock()

    result1 = await flow.async_step_test_device({"device_id": "5"})
    assert flow._test_short_id == 5

    result2 = await flow.async_step_test_action({"action": "on"})

    runtime.handlers.handle_cmd.assert_awaited_once()
    src_bytes, payload = runtime.handlers.handle_cmd.call_args[0]
    assert payload == {"tp": 5, "id": 5, "s": True}
    registry.add_pending.assert_awaited_once()
    registry.approve_pending.assert_awaited_once()
    registry.revoke_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_test_action_off(flow, registry, runtime):
    dev = {"short_id": 5, "name": "Pump", "type": "SW", "entity_id": "switch.pump", "enabled": True}
    registry.get_device.return_value = dev
    registry.is_approved.return_value = True
    runtime.handlers = MagicMock()
    runtime.handlers.handle_cmd = AsyncMock()

    flow._test_short_id = 5
    await flow.async_step_test_action({"action": "off"})

    runtime.handlers.handle_cmd.assert_awaited_once()
    payload = runtime.handlers.handle_cmd.call_args[0][1]
    assert payload == {"tp": 5, "id": 5, "s": False}
    registry.add_pending.assert_not_called()


@pytest.mark.asyncio
async def test_test_action_activate_scene(flow, registry, runtime):
    dev = {"short_id": 7, "name": "Evening", "type": "SC", "entity_id": "scene.evening", "enabled": True}
    registry.get_device.return_value = dev
    registry.is_approved.return_value = True
    runtime.handlers = MagicMock()
    runtime.handlers.handle_cmd = AsyncMock()

    flow._test_short_id = 7
    await flow.async_step_test_action({"action": "activate"})

    runtime.handlers.handle_cmd.assert_awaited_once()
    payload = runtime.handlers.handle_cmd.call_args[0][1]
    assert payload == {"tp": 5, "id": 7}


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
    qr = json.loads(ph["qr_payload"])
    assert qr["rvr"]["dst"] == runtime.identity_hash
    assert qr["rvr"]["fmt"] == 1
    assert "qr_url" in ph


@pytest.mark.asyncio
async def test_config_submit_returns_to_menu(flow):
    result = await flow.async_step_config({})
    assert result["type"] == "menu"


# ---------- device list rendering ----------
@pytest.mark.asyncio
async def test_devices_form_lists_existing(flow, registry):
    registry.all_devices.return_value = [
        {"short_id": 1, "name": "Lamp", "type": "SW", "entity_id": "switch.lamp", "enabled": True},
        {"short_id": 2, "name": "Sensor", "type": "SE", "entity_id": "sensor.t", "enabled": True},
    ]
    result = await flow.async_step_devices()
    ph = result["description_placeholders"]
    assert ph["count"] == "2"
    assert "Lamp" in ph["device_list"]
    assert "switch.lamp" in ph["device_list"]
    assert "Sensor" in ph["device_list"]


# ---------- QR URL (external API) ----------
def test_build_qr_image_url():
    from custom_components.rover.options_flow import _build_qr_image_url
    url = _build_qr_image_url('{"hello":"world"}')
    assert url.startswith("https://api.qrserver.com/v1/create-qr-code/")
    assert "size=300x300" in url
    assert "data=" in url


@pytest.mark.asyncio
async def test_config_includes_qr_url(flow, runtime):
    result = await flow.async_step_config()
    ph = result["description_placeholders"]
    assert "qr_url" in ph
    assert ph["qr_url"].startswith("https://api.qrserver.com/v1/create-qr-code/")
    assert "data=" in ph["qr_url"]
