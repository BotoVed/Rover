"""Pytest fixtures for Rover tests."""
import sys
from unittest.mock import MagicMock

# Mock RNS/LXMF before any rover module imports trigger rns_transport.
# rns_transport imports LXMF and RNS at module level; they are not
# installed in the CI/test environment (only on HAOS via HACS deps).
RNSMock = MagicMock()
RNSMock.Identity.recall = MagicMock(return_value=None)
RNSMock.Transport.request_path = MagicMock()
RNSMock.Destination.OUT = 0
RNSMock.Destination.SINGLE = 0

sys.modules["RNS"] = RNSMock

LXMFMock = MagicMock()
LXMFMock.LXMRouter = MagicMock()
LXMFMock.LXMessage = MagicMock()
LXMFMock.LXMessage.DIRECT = 0

sys.modules["LXMF"] = LXMFMock

# Mock homeassistant.helpers.config_validation for local test env.
# On CI homeassistant is installed and the real module is used.
cv_mock = MagicMock()
cv_mock.config_entry_only_config_schema = MagicMock(return_value={})
cv_mock.positive_int = MagicMock(return_value=None)
sys.modules["homeassistant.helpers.config_validation"] = cv_mock

# Mock voluptuous (not installed in local test env, only on HAOS)
vol_mock = MagicMock()
vol_mock.Schema = MagicMock(return_value=None)
vol_mock.In = MagicMock(return_value=MagicMock())
vol_mock.All = MagicMock(return_value=MagicMock())
vol_mock.Range = MagicMock(return_value=MagicMock())
vol_mock.Optional = MagicMock(return_value="optional-key")
vol_mock.Required = MagicMock(return_value="required-key")
vol_mock.Any = MagicMock(return_value=MagicMock())
sys.modules["voluptuous"] = vol_mock
sys.modules["voluptuous.schema_builder"] = vol_mock
sys.modules["voluptuous.validators"] = vol_mock

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
