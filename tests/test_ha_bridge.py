from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

mock_core = MagicMock()
mock_core.callback = lambda fn: fn
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = mock_core
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.entity_registry"] = MagicMock()
sys.modules["homeassistant.helpers.area_registry"] = MagicMock()

from rover.ha_bridge import HaBridge

pytestmark = pytest.mark.asyncio


@pytest.fixture
def hass():
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    return h


@pytest.fixture
def bridge(hass):
    return HaBridge(hass)


@pytest.fixture
def mock_track(hass):
    with patch("rover.ha_bridge.async_track_state_change_event") as m:
        yield m


class TestCallService:
    async def test_calls_async_call(self, bridge, hass):
        await bridge.call_service("light", "turn_on", {"entity_id": "light.salon"})
        hass.services.async_call.assert_awaited_once_with(
            "light", "turn_on", {"entity_id": "light.salon"}, blocking=True, limit=5
        )


class TestGetState:
    async def test_returns_hass_states_get(self, bridge, hass):
        mock_state = MagicMock()
        hass.states.get.return_value = mock_state

        result = await bridge.get_state("light.salon")

        hass.states.get.assert_called_once_with("light.salon")
        assert result is mock_state

    async def test_returns_none_when_missing(self, bridge, hass):
        hass.states.get.return_value = None

        result = await bridge.get_state("nonexistent.entity")

        assert result is None


class TestStartTracking:
    async def test_subscribes_via_async_track_state_change_event(
        self, bridge, hass, mock_track
    ):
        bridge.start_tracking(["light.salon", "switch.garage"])

        assert bridge._tracked_entities == {"light.salon", "switch.garage"}
        assert mock_track.call_count == 1
        args, _ = mock_track.call_args
        assert args[0] is hass
        assert set(args[1]) == {"light.salon", "switch.garage"}
        assert args[2] == bridge._handle_state_event

    async def test_adds_new_entities_to_existing_set(
        self, bridge, hass, mock_track
    ):
        bridge.start_tracking(["light.salon"])
        bridge.start_tracking(["switch.garage"])

        assert mock_track.call_count == 2
        assert bridge._tracked_entities == {"light.salon", "switch.garage"}

    async def test_does_not_duplicate_entities(
        self, bridge, hass, mock_track
    ):
        bridge.start_tracking(["light.salon", "light.salon"])

        assert bridge._tracked_entities == {"light.salon"}
        mock_track.assert_called_once()

    async def test_store_unsubscribe(self, bridge, hass, mock_track):
        mock_unsub = MagicMock()
        mock_track.return_value = mock_unsub

        bridge.start_tracking(["light.salon"])

        assert mock_unsub in bridge._unsub_state


class TestHandleStateEvent:
    async def test_calls_on_state_changed(self, bridge, hass, mock_track):
        on_state_changed = MagicMock()
        bridge.set_callbacks(on_state_changed=on_state_changed)
        bridge.start_tracking(["light.salon"])

        new_state = MagicMock()
        event = MagicMock()
        event.data = {"entity_id": "light.salon", "new_state": new_state}
        bridge._handle_state_event(event)

        on_state_changed.assert_called_once_with("light.salon", new_state)

    async def test_ignores_untracked_entity(self, bridge, hass, mock_track):
        on_state_changed = MagicMock()
        bridge.set_callbacks(on_state_changed=on_state_changed)
        bridge.start_tracking(["light.salon"])

        new_state = MagicMock()
        event = MagicMock()
        event.data = {"entity_id": "switch.other", "new_state": new_state}
        bridge._handle_state_event(event)

        on_state_changed.assert_not_called()

    async def test_ignores_when_new_state_is_none(
        self, bridge, hass, mock_track
    ):
        on_state_changed = MagicMock()
        bridge.set_callbacks(on_state_changed=on_state_changed)
        bridge.start_tracking(["light.salon"])

        event = MagicMock()
        event.data = {"entity_id": "light.salon", "new_state": None}
        bridge._handle_state_event(event)

        on_state_changed.assert_not_called()

    async def test_ignores_when_no_callback_set(
        self, bridge, hass, mock_track
    ):
        bridge.start_tracking(["light.salon"])

        new_state = MagicMock()
        event = MagicMock()
        event.data = {"entity_id": "light.salon", "new_state": new_state}
        bridge._handle_state_event(event)

    async def test_handle_state_event_called_by_subscription(
        self, bridge, hass, mock_track
    ):
        handler_spy = MagicMock()
        bridge._handle_state_event = handler_spy
        bridge.start_tracking(["light.salon"])

        handler = mock_track.call_args[0][2]
        event = MagicMock()
        handler(event)

        handler_spy.assert_called_once_with(event)


class TestStopTracking:
    async def test_unsubscribes_all(self, bridge, hass, mock_track):
        unsub = MagicMock()
        mock_track.return_value = unsub
        bridge.start_tracking(["light.salon"])

        bridge.stop_tracking()

        unsub.assert_called_once()
        assert bridge._unsub_state == []

    async def test_clear_tracked_entities_not_affected(self, bridge, hass, mock_track):
        bridge.start_tracking(["light.salon"])

        bridge.stop_tracking()

        assert bridge._tracked_entities == {"light.salon"}


class TestStopTrackingEntity:
    async def test_removes_entity_and_resubscribes(
        self, bridge, hass, mock_track
    ):
        mock_track.return_value = MagicMock()
        bridge.start_tracking(["light.salon", "switch.garage"])
        mock_track.reset_mock()

        bridge.stop_tracking_entity("light.salon")

        assert bridge._tracked_entities == {"switch.garage"}
        assert mock_track.call_count == 1
        args, _ = mock_track.call_args
        assert args[0] is hass
        assert args[1] == ["switch.garage"]
        assert args[2] == bridge._handle_state_event

    async def test_resubscribes_when_entity_not_tracked(
        self, bridge, hass, mock_track
    ):
        mock_track.return_value = MagicMock()
        bridge.start_tracking(["light.salon"])
        mock_track.reset_mock()

        bridge.stop_tracking_entity("switch.unknown")

        assert bridge._tracked_entities == {"light.salon"}
        assert mock_track.call_count == 1
        args, _ = mock_track.call_args
        assert args[1] == ["light.salon"]


class TestRegistryListeners:
    async def test_start_registry_listeners_subscribes(
        self, bridge, hass
    ):
        entity_reg = MagicMock()
        area_reg = MagicMock()
        with (
            patch("rover.ha_bridge.er.async_get", return_value=entity_reg),
            patch("rover.ha_bridge.ar.async_get", return_value=area_reg),
        ):
            await bridge.start_registry_listeners()

        entity_reg.async_subscribe.assert_called_once_with(
            bridge._handle_entity_registry_event
        )
        area_reg.async_subscribe.assert_called_once_with(
            bridge._handle_area_registry_event
        )


class TestRegistryChangedCallback:
    async def test_entity_registry_event_calls_callback(self, bridge, hass):
        callback = MagicMock()
        bridge.set_callbacks(on_registry_changed=callback)

        bridge._handle_entity_registry_event(MagicMock())

        callback.assert_called_once()

    async def test_area_registry_event_calls_callback(self, bridge, hass):
        callback = MagicMock()
        bridge.set_callbacks(on_registry_changed=callback)

        bridge._handle_area_registry_event(MagicMock())

        callback.assert_called_once()

    async def test_no_callback_set(self, bridge, hass):
        bridge._handle_entity_registry_event(MagicMock())
        bridge._handle_area_registry_event(MagicMock())


class TestRegistryProperties:
    async def test_entity_registry_property(self, bridge, hass):
        mock_reg = MagicMock()
        with patch("rover.ha_bridge.er.async_get", return_value=mock_reg):
            assert bridge.entity_registry is mock_reg

    async def test_area_registry_property(self, bridge, hass):
        mock_reg = MagicMock()
        with patch("rover.ha_bridge.ar.async_get", return_value=mock_reg):
            assert bridge.area_registry is mock_reg
