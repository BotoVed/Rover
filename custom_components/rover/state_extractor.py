"""State extractor — преобразование HA state в dict состояния протокола.

Симметричный к commands.py: чистая функция, на вход Device + HA state object,
на выход — dict с полями состояния для STATUS/PUSH-пакетов.

HA state объект ожидается в виде, совместимом с homeassistant.core.State:
- атрибут .state — строка (например, "on", "off", "23.5", "armed_home")
- атрибут .attributes — dict (например, {"brightness": 200, "color_temp": 350})

Если state == None или state.state in ("unknown", "unavailable") — возвращаем
пустой dict (нечего обновлять).

Сам HA не вызывается. Применение — в ha_bridge.py.

См. SPEC.md §5.5, §9.2 и DECISIONS.md SB-028, SB-030, SB-033.
"""

from __future__ import annotations

from typing import Any

from .const import (
    DEV_ALARM,
    DEV_BINARY_SENSOR,
    DEV_BUTTON,
    DEV_CLIMATE,
    DEV_COVER,
    DEV_FAN,
    DEV_HUMIDIFIER,
    DEV_LIGHT,
    DEV_LOCK,
    DEV_SENSOR,
    DEV_SIREN,
    DEV_SWITCH,
    DEV_WATER_HEATER,
)
from .registry import Device

# Cостояния HA, при которых не выгружаем поля (см. п.1 обсуждения)
_INVALID_STATES = {"unknown", "unavailable", None}


def extract_state(device: Device, ha_state: Any) -> dict:
    """Извлечь dict состояния из HA state-объекта для STATUS/PUSH.

    ha_state — объект с атрибутами .state (str) и .attributes (dict),
    либо None. В тестах используется FakeState с теми же атрибутами.
    """
    if ha_state is None:
        return {}
    if getattr(ha_state, "state", None) in _INVALID_STATES:
        return {}

    t = device.t
    if t == DEV_LIGHT:
        return _light(ha_state)
    if t == DEV_SWITCH:
        return _on_off(ha_state)
    if t == DEV_SIREN:
        return _on_off(ha_state)
    if t == DEV_BINARY_SENSOR:
        return _on_off(ha_state)
    if t == DEV_CLIMATE:
        return _climate(ha_state)
    if t == DEV_WATER_HEATER:
        return _water_heater(ha_state)
    if t == DEV_FAN:
        return _fan(ha_state)
    if t == DEV_COVER:
        return _cover(ha_state)
    if t == DEV_LOCK:
        return _lock(ha_state)
    if t == DEV_ALARM:
        return _alarm(ha_state)
    if t == DEV_HUMIDIFIER:
        return _humidifier(ha_state)
    if t == DEV_SENSOR:
        return _sensor(ha_state)
    if t == DEV_BUTTON:
        return {}  # у button/scene нет состояния
    return {}


def _is_on(state: str) -> int:
    """HA 'on' / 'off' / специальные → 1 / 0."""
    return 1 if state == "on" else 0


def _attr(ha_state: Any, key: str) -> Any:
    """Достать атрибут безопасно (без AttributeError, если attributes пуст)."""
    attrs = getattr(ha_state, "attributes", None) or {}
    return attrs.get(key)


# ---------- LIGHT ----------

def _light(ha_state: Any) -> dict:
    """L: s, bri (HA 0..255 → 0..100), ct."""
    result: dict = {"s": _is_on(ha_state.state)}
    if result["s"] == 1:
        bri = _attr(ha_state, "brightness")
        if bri is not None:
            # SB-030: HA 0..255 → 0..100
            result["bri"] = round(int(bri) / 2.55)
        ct = _attr(ha_state, "color_temp")
        if ct is not None:
            result["ct"] = int(ct)
    return result


# ---------- SWITCH / SIREN / BINARY_SENSOR ----------

def _on_off(ha_state: Any) -> dict:
    return {"s": _is_on(ha_state.state)}


# ---------- CLIMATE ----------

def _climate(ha_state: Any) -> dict:
    """C: s, th (target), tc (current), md (hvac_mode), fn (fan_mode)."""
    state = ha_state.state
    result: dict = {"s": 0 if state == "off" else 1, "md": str(state)}

    th = _attr(ha_state, "temperature")
    if th is not None:
        result["th"] = float(th)
    tc = _attr(ha_state, "current_temperature")
    if tc is not None:
        result["tc"] = float(tc)
    fn = _attr(ha_state, "fan_mode")
    if fn is not None:
        result["fn"] = str(fn)
    return result


# ---------- WATER_HEATER ----------

def _water_heater(ha_state: Any) -> dict:
    """WH: s, th, tc, md."""
    state = ha_state.state
    result: dict = {"s": 0 if state == "off" else 1, "md": str(state)}

    th = _attr(ha_state, "temperature")
    if th is not None:
        result["th"] = float(th)
    tc = _attr(ha_state, "current_temperature")
    if tc is not None:
        result["tc"] = float(tc)
    return result


# ---------- FAN ----------

def _fan(ha_state: Any) -> dict:
    """F: s, sp (percentage)."""
    result: dict = {"s": _is_on(ha_state.state)}
    sp = _attr(ha_state, "percentage")
    if sp is not None:
        result["sp"] = int(sp)
    return result


# ---------- COVER ----------

def _cover(ha_state: Any) -> dict:
    """CV: st (open/closed/opening/closing), pos (current_position)."""
    result: dict = {"st": str(ha_state.state)}
    pos = _attr(ha_state, "current_position")
    if pos is not None:
        result["pos"] = int(pos)
    return result


# ---------- LOCK ----------

def _lock(ha_state: Any) -> dict:
    """LK: st (locked/unlocked/locking/unlocking/jammed)."""
    return {"st": str(ha_state.state)}


# ---------- ALARM ----------

def _alarm(ha_state: Any) -> dict:
    """A: st (armed_home/armed_away/armed_night/disarmed/triggered/pending/arming)."""
    return {"st": str(ha_state.state)}


# ---------- HUMIDIFIER ----------

def _humidifier(ha_state: Any) -> dict:
    """H: s, th (target humidity), tc (current humidity)."""
    result: dict = {"s": _is_on(ha_state.state)}
    th = _attr(ha_state, "humidity")
    if th is not None:
        result["th"] = int(th)
    tc = _attr(ha_state, "current_humidity")
    if tc is not None:
        result["tc"] = int(tc)
    return result


# ---------- SENSOR ----------

def _sensor(ha_state: Any) -> dict:
    """S: v (всегда строка, SB-033), u (если есть в attributes)."""
    result: dict = {"v": str(ha_state.state)}
    unit = _attr(ha_state, "unit_of_measurement")
    if unit is not None:
        result["u"] = str(unit)
    return result
