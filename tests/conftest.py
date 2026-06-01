from __future__ import annotations

from unittest.mock import MagicMock

import sys

# Mock homeassistant before any rover imports are triggered
_HA_MODULES = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.area_registry": MagicMock(),
    "homeassistant.helpers.entity_registry": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.const": MagicMock(),
}

for mod_name, mock in _HA_MODULES.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mock

# Wire up core types
ha_core = sys.modules["homeassistant.core"]
ha_core.HomeAssistant = MagicMock
ha_core.State = MagicMock
ha_core.callback = lambda x: x
ha_core.Event = MagicMock

# Wire up helpers.event
ha_event = sys.modules["homeassistant.helpers.event"]
ha_event.async_track_time_interval = lambda hass, cb, period: lambda: None
ha_event.Event = MagicMock
ha_event.async_track_state_change_event = MagicMock()

# Wire up registries
ha_ar = sys.modules["homeassistant.helpers.area_registry"]
ha_er = sys.modules["homeassistant.helpers.entity_registry"]
ha_ar.async_get = MagicMock(return_value=MagicMock())
ha_er.async_get = MagicMock(return_value=MagicMock())

# Wire up config_entries
ha_ce = sys.modules["homeassistant.config_entries"]
ha_ce.ConfigEntry = MagicMock

# Wire up const
ha_const = sys.modules["homeassistant.const"]
