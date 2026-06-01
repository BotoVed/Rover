from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rover.handlers import Handlers


@pytest.fixture
def registry():
    return MagicMock()


@pytest.fixture
def ha_bridge():
    hb = MagicMock()
    hb.get_state = AsyncMock()
    hb.call_service = AsyncMock()
    return hb


@pytest.fixture
def outbox():
    return MagicMock()


@pytest.fixture
def config():
    return {"max_retries": 3, "queue_period": 10, "ack_timeout": 8}


@pytest.fixture
def handlers(registry, ha_bridge, outbox, config):
    return Handlers(registry, ha_bridge, outbox, config)


@pytest.fixture
def mock_time():
    with patch("rover.handlers.time.time", return_value=1000.0) as m:
        yield m


# =====================================================================
# on_ping
# =====================================================================


@pytest.mark.asyncio
class TestOnPing:
    async def test_sends_pong_with_hashes(
        self, handlers, registry, outbox, mock_time
    ):
        registry.compute_section_hashes.return_value = {
            "u": "aaaa", "a": "bbbb", "d": "cccc"
        }
        handlers._meta_hash = "meta1"

        await handlers.on_ping({"tp": 6, "ts": 500}, 42)

        mock_time.assert_called()
        outbox.enqueue.assert_called_once()
        args = outbox.enqueue.call_args[0]
        assert args[0] == "pong"
        assert args[1] == {
            "tp": 6, "ts": 500, "h": {"u": "aaaa", "a": "bbbb", "d": "cccc", "m": "meta1"}
        }
        assert args[2] == 3
        assert args[3] == 10
        outbox.wake_suspended.assert_called_once_with()


    async def test_updates_online_nodes(
        self, handlers, registry, outbox, mock_time
    ):
        mock_time.return_value = 1000.0
        await handlers.on_ping({"tp": 6}, 99)
        assert handlers._online_nodes.get(99) == 1000.0


# =====================================================================
# on_command
# =====================================================================


@pytest.mark.asyncio
class TestOnCommand:
    async def test_executes_command_and_sends_push(
        self, handlers, registry, ha_bridge, outbox
    ):
        device = MagicMock()
        device.short_id = 1
        device.entity_id = "light.salon"
        registry.get_by_short_id.return_value = device

        service_call = MagicMock()
        service_call.domain = "light"
        service_call.service = "turn_on"
        service_call.data = {"entity_id": "light.salon"}

        ha_state = MagicMock()
        ha_bridge.get_state.return_value = ha_state

        with (
            patch("rover.handlers.build_service_calls", return_value=[service_call]),
            patch("rover.handlers.extract_state", return_value={"s": 1, "bri": 50}),
            patch("rover.handlers.asyncio.sleep") as mock_sleep,
        ):
            await handlers.on_command({"tp": 5, "id": 1, "s": 1}, 42)

        registry.get_by_short_id.assert_called_once_with(1)
        mock_sleep.assert_called_once()
        ha_bridge.call_service.assert_awaited_once_with(
            "light", "turn_on", {"entity_id": "light.salon"}
        )
        ha_bridge.get_state.assert_awaited_once_with("light.salon")
        outbox.enqueue.assert_called_once_with(
            1, {"tp": 3, "id": 1, "s": 1, "bri": 50}, 3, 10
        )

    async def test_unknown_device_is_ignored(
        self, handlers, registry, ha_bridge, outbox
    ):
        registry.get_by_short_id.return_value = None

        await handlers.on_command({"tp": 5, "id": 999}, 42)

        ha_bridge.call_service.assert_not_called()
        ha_bridge.get_state.assert_not_called()
        outbox.enqueue.assert_not_called()

    async def test_no_service_calls_returns_early(
        self, handlers, registry, ha_bridge, outbox
    ):
        device = MagicMock()
        device.short_id = 1
        registry.get_by_short_id.return_value = device

        with patch("rover.handlers.build_service_calls", return_value=[]):
            await handlers.on_command({"tp": 5, "id": 1}, 42)

        ha_bridge.call_service.assert_not_called()
        outbox.enqueue.assert_not_called()


# =====================================================================
# on_req_one
# =====================================================================


@pytest.mark.asyncio
class TestOnReqOne:
    async def test_sends_status_for_single_id(
        self, handlers, registry, ha_bridge, outbox
    ):
        device = MagicMock()
        device.short_id = 1
        device.entity_id = "light.salon"
        registry.get_by_short_id.return_value = device
        ha_state = MagicMock()
        ha_bridge.get_state.return_value = ha_state

        with patch("rover.handlers.extract_state", return_value={"s": 1}):
            await handlers.on_req_one({"tp": 5, "req": 1}, 42)

        outbox.enqueue.assert_called_once_with(
            1, {"tp": 2, "id": 1, "s": 1}, 3, 10
        )

    async def test_sends_status_for_list_of_ids(
        self, handlers, registry, ha_bridge, outbox
    ):
        dev1 = MagicMock()
        dev1.short_id = 1
        dev1.entity_id = "light.a"
        dev2 = MagicMock()
        dev2.short_id = 2
        dev2.entity_id = "switch.b"

        def get_by_short_id(sid):
            return {1: dev1, 2: dev2}.get(sid)

        registry.get_by_short_id.side_effect = get_by_short_id
        ha_bridge.get_state.return_value = MagicMock()

        with patch("rover.handlers.extract_state", return_value={"s": 1}):
            await handlers.on_req_one({"tp": 5, "req": [1, 2]}, 42)

        assert outbox.enqueue.call_count == 2

    async def test_unknown_id_skipped(
        self, handlers, registry, ha_bridge, outbox
    ):
        registry.get_by_short_id.return_value = None

        await handlers.on_req_one({"tp": 5, "req": 999}, 42)

        ha_bridge.get_state.assert_not_called()
        outbox.enqueue.assert_not_called()


# =====================================================================
# on_req_all
# =====================================================================


@pytest.mark.asyncio
class TestOnReqAll:
    async def test_sends_status_for_all_devices(
        self, handlers, registry, ha_bridge, outbox
    ):
        dev1 = MagicMock()
        dev1.short_id = 1
        dev1.entity_id = "light.a"
        dev2 = MagicMock()
        dev2.short_id = 2
        dev2.entity_id = "switch.b"
        registry.all_devices.return_value = [dev1, dev2]
        ha_bridge.get_state.return_value = MagicMock()

        with patch("rover.handlers.extract_state", return_value={"s": 1}):
            await handlers.on_req_all(42)

        assert outbox.enqueue.call_count == 2
        outbox.enqueue.assert_any_call(1, {"tp": 2, "id": 1, "s": 1}, 3, 10)
        outbox.enqueue.assert_any_call(2, {"tp": 2, "id": 2, "s": 1}, 3, 10)

    async def test_skips_devices_without_state(
        self, handlers, registry, ha_bridge, outbox
    ):
        dev = MagicMock()
        dev.short_id = 1
        dev.entity_id = "light.a"
        registry.all_devices.return_value = [dev]
        ha_bridge.get_state.return_value = None

        await handlers.on_req_all(42)

        outbox.enqueue.assert_not_called()


# =====================================================================
# on_req_config
# =====================================================================


@pytest.mark.asyncio
class TestOnReqConfig:
    async def test_section_m_sends_meta(
        self, handlers, registry, outbox
    ):
        handlers._meta_dict = {"n": "Home"}
        await handlers.on_req_config({"tp": 8, "s": "m"}, 42)

        outbox.enqueue.assert_called_once_with(
            ("config", "m", 1),
            {"tp": 4, "s": "m", "pg": 1, "pgt": 1, "d": {"n": "Home"}},
            3, 10,
        )

    async def test_section_u_sends_users(
        self, handlers, registry, outbox
    ):
        registry.export_users.return_value = [{"id": "user1", "hash": "abc"}]

        await handlers.on_req_config({"tp": 8, "s": "u"}, 42)

        outbox.enqueue.assert_called_once_with(
            ("config", "u", 1),
            {"tp": 4, "s": "u", "pg": 1, "pgt": 1, "d": [{"id": "user1", "hash": "abc"}]},
            3, 10,
        )

    async def test_section_d_paginates_by_5(
        self, handlers, registry, outbox
    ):
        devices = [{"id": i} for i in range(12)]
        registry.export_devices.return_value = devices

        await handlers.on_req_config({"tp": 8, "s": "d"}, 42)

        assert outbox.enqueue.call_count == 3
        pages = {call[0][1]["pg"]: call[0][1] for call in outbox.enqueue.call_args_list}
        assert set(pages.keys()) == {1, 2, 3}
        assert len(pages[1]["d"]) == 5
        assert len(pages[2]["d"]) == 5
        assert len(pages[3]["d"]) == 2

    async def test_section_d_with_requested_page(
        self, handlers, registry, outbox
    ):
        devices = [{"id": i} for i in range(12)]
        registry.export_devices.return_value = devices

        await handlers.on_req_config({"tp": 8, "s": "d", "pg": 2}, 42)

        assert outbox.enqueue.call_count == 1
        page = outbox.enqueue.call_args[0][1]
        assert page["pg"] == 2
        assert page["pgt"] == 3
        assert len(page["d"]) == 5

    async def test_section_a_sends_areas(
        self, handlers, registry, outbox
    ):
        registry.export_areas.return_value = [{"id": "area1", "n": "Salon"}]

        await handlers.on_req_config({"tp": 8, "s": "a"}, 42)

        outbox.enqueue.assert_called_once()


# =====================================================================
# on_ha_state_changed
# =====================================================================


@pytest.mark.asyncio
class TestOnHaStateChanged:
    async def test_sends_push(
        self, handlers, registry, ha_bridge, outbox
    ):
        device = MagicMock()
        device.short_id = 1
        device.entity_id = "light.salon"
        registry.get_by_entity_id.return_value = device

        ha_state = MagicMock()
        with patch("rover.handlers.extract_state", return_value={"s": 1}):
            await handlers.on_ha_state_changed("light.salon", ha_state)

        outbox.enqueue.assert_called_once_with(
            1, {"tp": 3, "id": 1, "s": 1}, 3, 10
        )

    async def test_ignores_unknown_entity(
        self, handlers, registry, outbox
    ):
        registry.get_by_entity_id.return_value = None

        await handlers.on_ha_state_changed("unknown.entity", MagicMock())

        outbox.enqueue.assert_not_called()


# =====================================================================
# on_ha_registry_changed
# =====================================================================


@pytest.mark.asyncio
class TestOnHaRegistryChanged:
    async def test_sends_pong_when_hashes_changed(
        self, handlers, registry, outbox
    ):
        registry.compute_section_hashes.return_value = {
            "u": "old", "a": "old", "d": "old"
        }
        handlers._meta_hash = "old"

        registry.compute_section_hashes.return_value = {
            "u": "new", "a": "new", "d": "new"
        }
        handlers._meta_hash = "new"

        with patch("rover.handlers.time.time", return_value=2000):
            handlers.on_ha_registry_changed()

        outbox.enqueue.assert_called_once()
        pong = outbox.enqueue.call_args[0][1]
        assert pong["tp"] == 6
        assert pong["h"] == {"u": "new", "a": "new", "d": "new", "m": "new"}
        assert pong["ts"] == 2000

    async def test_noop_when_hashes_unchanged(
        self, handlers, registry, outbox
    ):
        registry.compute_section_hashes.return_value = {
            "u": "same", "a": "same", "d": "same"
        }
        handlers._meta_hash = "same"
        handlers._last_hashes = {"u": "same", "a": "same", "d": "same", "m": "same"}

        handlers.on_ha_registry_changed()

        outbox.enqueue.assert_not_called()


# =====================================================================
# mark_node_online
# =====================================================================


class TestMarkNodeOnline:
    def test_updates_timestamp_and_wakes(
        self, handlers, registry, outbox
    ):
        with patch("rover.handlers.time.time", return_value=5000):
            handlers.mark_node_online(42)

        assert handlers._online_nodes[42] == 5000
        outbox.wake_suspended.assert_called_once_with()


# =====================================================================
# is_anyone_online
# =====================================================================


class TestIsAnyoneOnline:
    def test_returns_true_when_node_recent(self, handlers, registry, outbox):
        now = 1000.0
        handlers._online_nodes = {1: 950.0}
        with patch("rover.handlers.time.time", return_value=now):
            assert handlers.is_anyone_online() is True

    def test_returns_false_when_node_old(self, handlers, registry, outbox):
        now = 2000.0
        handlers._online_nodes = {1: 500.0}
        with patch("rover.handlers.time.time", return_value=now):
            assert handlers.is_anyone_online() is False

    def test_returns_false_when_no_nodes(self, handlers, registry, outbox):
        assert handlers.is_anyone_online() is False


# =====================================================================
# set_meta_dict / get_section_hashes
# =====================================================================


class TestMeta:
    def test_set_meta_dict_updates_hash(self, handlers, registry):
        handlers.set_meta_dict({"n": "Home"})
        assert handlers._meta_dict == {"n": "Home"}
        assert isinstance(handlers._meta_hash, str)
        assert len(handlers._meta_hash) == 4

    def test_get_section_hashes_includes_meta(self, handlers, registry):
        registry.compute_section_hashes.return_value = {"u": "a", "a": "b", "d": "c"}
        handlers._meta_hash = "mhash"

        hashes = handlers.get_section_hashes()
        assert hashes == {"u": "a", "a": "b", "d": "c", "m": "mhash"}


# =====================================================================
# _paginate
# =====================================================================


class TestPaginate:
    def test_empty_list_returns_single_empty_page(self):
        assert Handlers._paginate([], 5) == [[]]

    def test_less_than_per_page(self):
        assert Handlers._paginate([1, 2], 5) == [[1, 2]]

    def test_exact_multiple(self):
        assert Handlers._paginate([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_with_remainder(self):
        pages = Handlers._paginate(list(range(12)), 5)
        assert len(pages) == 3
        assert len(pages[0]) == 5
        assert len(pages[1]) == 5
        assert len(pages[2]) == 2
