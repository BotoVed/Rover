"""E2E test simulators for Rover. Triggered via HA services. Remove before release."""
from __future__ import annotations

import logging
import random
import time

_LOGGER = logging.getLogger(__name__)

FAKE_FROM_NODE = 0x99999999


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes", "y")
    return False


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


TYPE_TO_CMD_FIELDS = {
    "SW": lambda v: {"s": _to_bool(v)},
    "L": lambda v: {"s": _to_bool(v)},
    "S": lambda v: {"s": _to_bool(v)},
    "BS": lambda v: {"s": _to_bool(v)},
    "F": lambda v: {"s": _to_bool(v)},
    "H": lambda v: {"s": _to_bool(v), "th": _to_float(v)},
    "C": lambda v: {"th": _to_float(v)},
    "WH": lambda v: {"th": _to_float(v)},
    "CV": lambda v: {"cmd": str(v) if v else "stop"},
    "LK": lambda v: {"cmd": "lock" if _to_bool(v) else "unlock"},
    "A": lambda v: {"cmd": str(v) if v else "disarm"},
    "SI": lambda v: {"s": _to_bool(v)},
    "B": lambda v: {"cmd": "press"},
}


async def simulate_ping(hass, dispatcher) -> None:
    ts = int(time.time())
    ping = {"tp": 6, "ts": ts, "h": {}}
    _LOGGER.info("[TEST PING] Simulating incoming PING from node=0x%x ts=%d",
                 FAKE_FROM_NODE, ts)
    await dispatcher.dispatch(ping, from_node=FAKE_FROM_NODE)


def _parse_device_id(raw: str) -> str | None:
    """Parse device_id input → 4-hex registry key. Returns None if invalid."""
    s = str(raw).strip().lower().strip('"').strip("'")
    if not s:
        return None
    try:
        if s.startswith("0x"):
            short_id = int(s, 16)
        elif s.isdigit():
            short_id = int(s, 10)
        else:
            short_id = int(s, 16)
    except ValueError:
        return None
    if not (0 <= short_id <= 0xFFFF):
        return None
    return f"{short_id:04x}"


async def simulate_cmd(hass, dispatcher, registry, device_id: str, value) -> None:
    sid_str = _parse_device_id(device_id)
    if sid_str is None:
        _LOGGER.warning("[TEST CMD] Invalid device_id=%r. Use decimal (49283) or hex (c083, 0xc083).",
                        device_id)
        return

    sid_int = int(sid_str, 16)
    dev = registry.get_by_short_id(sid_int)

    if dev is None:
        _LOGGER.warning("[TEST CMD] Device id=%s not found. Available: %s",
                        sid_str, [f"0x{d.short_id:04x}={d.t}" for d in registry.all_devices()])
        return

    builder = TYPE_TO_CMD_FIELDS.get(dev.t)
    if builder is None:
        _LOGGER.warning("[TEST CMD] Type %r not supported. Device: id=0x%04x name=%s",
                        dev.t, dev.short_id, dev.n)
        return

    fields = builder(value)
    cmid = random.randint(0, 65535)
    cmd = {"tp": 5, "id": dev.short_id, "cmid": cmid, **fields}

    _LOGGER.info("[TEST CMD] Simulating incoming CMD id=0x%04x type=%s name=%s value=%r → %s",
                 dev.short_id, dev.t, dev.n, value, fields)
    await dispatcher.dispatch(cmd, from_node=FAKE_FROM_NODE)
