"""Pytest fixtures for Rover tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


@pytest.fixture
def mock_hass():
    """Return a mock HomeAssistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config.config_dir = "/config"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    hass.add_job = MagicMock()
    return hass


@pytest.fixture
def mock_store():
    """Patch homeassistant.helpers.storage.Store."""
    with patch("custom_components.rover.registry.Store") as MockStore:
        store_instance = AsyncMock(spec=Store)
        store_instance.async_load = AsyncMock(return_value=None)
        store_instance.async_save = AsyncMock(return_value=None)
        MockStore.return_value = store_instance
        yield MockStore, store_instance
