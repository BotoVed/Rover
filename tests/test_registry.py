"""Tests for registry.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.rover.registry import RoverRegistry
from custom_components.rover.const import ROLE_OWNER, ROLE_REGULAR, MAX_PENDING_REMOTES


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    return hass


@pytest.fixture
async def registry(mock_hass):
    with patch("custom_components.rover.registry.Store") as MockStore:
        store = AsyncMock()
        store.async_load = AsyncMock(return_value=None)
        store.async_save = AsyncMock(return_value=None)
        MockStore.return_value = store

        reg = RoverRegistry(mock_hass)
        await reg.async_load()
        yield reg


@pytest.mark.asyncio
async def test_load_default(registry):
    assert registry.get_meta()["server_name"] == "Rover Hub"
    assert registry.all_devices() == []
    assert registry.all_users() == []
    assert registry.all_pending() == []
    assert registry.all_areas() == []


@pytest.mark.asyncio
async def test_add_device(registry):
    sid = await registry.add_device("switch.lamp", "Lamp", "SW")
    assert sid == 1
    dev = registry.get_device(1)
    assert dev["entity_id"] == "switch.lamp"
    assert dev["name"] == "Lamp"
    assert dev["type"] == "SW"
    assert dev["enabled"] is True


@pytest.mark.asyncio
async def test_short_id_sequential(registry):
    await registry.add_device("switch.a", "A", "SW")
    await registry.add_device("switch.b", "B", "SW")
    assert registry.get_device(1)["entity_id"] == "switch.a"
    assert registry.get_device(2)["entity_id"] == "switch.b"


@pytest.mark.asyncio
async def test_remove_device(registry):
    await registry.add_device("switch.a", "A", "SW")
    assert await registry.remove_device(1) is True
    assert registry.get_device(1) is None
    assert await registry.remove_device(999) is False


@pytest.mark.asyncio
async def test_update_device(registry):
    await registry.add_device("switch.a", "A", "SW", area_id=1)
    assert await registry.update_device(1, name="New A", area_id=2, enabled=False) is True
    dev = registry.get_device(1)
    assert dev["name"] == "New A"
    assert dev["area_id"] == 2
    assert dev["enabled"] is False


@pytest.mark.asyncio
async def test_add_area(registry):
    aid = await registry.add_area("Kitchen")
    assert aid == 1
    assert registry.get_area(1)["name"] == "Kitchen"


@pytest.mark.asyncio
async def test_pending_and_approve(registry):
    # First user becomes owner automatically
    result = await registry.add_pending("aabbccdd" * 4, "Phone1")
    assert result is True
    assert len(registry.all_pending()) == 1

    approved = await registry.approve_pending("aabbccdd" * 4)
    assert approved is True
    assert len(registry.all_pending()) == 0
    assert len(registry.all_users()) == 1
    assert registry.all_users()[0]["role"] == ROLE_OWNER
    assert registry.is_approved("aabbccdd" * 4) is True


@pytest.mark.asyncio
async def test_approve_second_regular(registry):
    await registry.add_pending("aabbccdd" * 4, "Owner")
    await registry.approve_pending("aabbccdd" * 4)

    await registry.add_pending("11223344" * 4, "Regular")
    await registry.approve_pending("11223344" * 4)
    assert registry.all_users()[1]["role"] == ROLE_REGULAR


@pytest.mark.asyncio
async def test_revoke_user(registry):
    await registry.add_pending("aabbccdd" * 4, "Phone")
    await registry.approve_pending("aabbccdd" * 4)
    assert await registry.revoke_user("aabbccdd" * 4) is True
    assert registry.is_approved("aabbccdd" * 4) is False


@pytest.mark.asyncio
async def test_pending_queue_full(registry):
    for i in range(MAX_PENDING_REMOTES + 1):
        result = await registry.add_pending(f"{i:032x}", f"Phone{i}")
    assert result is False  # last one rejected


@pytest.mark.asyncio
async def test_duplicate_pending(registry):
    await registry.add_pending("aabbccdd" * 4, "Phone")
    result = await registry.add_pending("aabbccdd" * 4, "Phone")
    assert result is False


@pytest.mark.asyncio
async def test_hash_changes(registry):
    old_hashes = registry.get_hashes().copy()
    await registry.add_device("switch.a", "A", "SW")
    new_hashes = registry.get_hashes()
    assert new_hashes["d"] != old_hashes["d"]
    assert new_hashes["m"] == old_hashes["m"]


@pytest.mark.asyncio
async def test_hash_stable(registry):
    await registry.add_device("switch.a", "A", "SW")
    h1 = registry.get_hashes()["d"]
    # read again without mutation
    h2 = registry.get_hashes()["d"]
    assert h1 == h2


@pytest.mark.asyncio
async def test_invalid_type(registry):
    with pytest.raises(ValueError):
        await registry.add_device("switch.a", "A", "XX")


@pytest.mark.asyncio
async def test_duplicate_entity_id(registry):
    await registry.add_device("switch.a", "A", "SW")
    with pytest.raises(ValueError):
        await registry.add_device("switch.a", "B", "SW")


@pytest.mark.asyncio
async def test_short_id_wraparound(registry):
    # Fill up to near max
    for i in range(1, 5):
        await registry.add_device(f"switch.{i}", f"D{i}", "SW")
    # Manually set counter to max
    registry._data["_next_short_id"] = 65535
    await registry.add_device("switch.last", "Last", "SW")
    # Next should wrap to 1 (since 1-4 are taken, 5 is free)
    sid = await registry.add_device("switch.wrap", "Wrap", "SW")
    assert sid == 5


@pytest.mark.asyncio
async def test_callback_on_mutation(registry):
    mutations = []
    registry.set_on_changed(lambda section: mutations.append(section))
    await registry.add_device("switch.a", "A", "SW")
    assert "d" in mutations
    await registry.set_server_name("New")
    assert "m" in mutations
