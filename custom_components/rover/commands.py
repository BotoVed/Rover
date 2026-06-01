"""Commands — преобразование Rover-команды в вызов HA-сервиса.

Чистый модуль: Device + packet → list[ServiceCall].
Ничего не вызывает, не знает про транспорт, очередь, HA API.

См. SPEC.md §5, DECISIONS.md SB-028, SB-030, SB-031.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    DEV_ALARM,
    DEV_BUTTON,
    DEV_CLIMATE,
    DEV_COVER,
    DEV_FAN,
    DEV_HUMIDIFIER,
    DEV_LIGHT,
    DEV_LOCK,
    DEV_SIREN,
    DEV_SWITCH,
    DEV_WATER_HEATER,
)
from .registry import Device


@dataclass
class ServiceCall:
    """Описание вызова одного HA-сервиса."""
    domain: str
    service: str
    data: dict = field(default_factory=dict)


# ---------- helpers ----------

def _entity(entity_id: str) -> dict:
    return {"entity_id": entity_id}


def _make(domain: str, service: str, entity_id: str, **kw) -> ServiceCall:
    data = _entity(entity_id)
    data.update(kw)
    return ServiceCall(domain=domain, service=service, data=data)


# ---------- device-type handlers ----------

def _on_off(domain: str, packet: dict, entity_id: str) -> list[ServiceCall]:
    s = packet.get("s")
    if s == 1:
        return [_make(domain, "turn_on", entity_id)]
    if s == 0:
        return [_make(domain, "turn_off", entity_id)]
    return []


def _handle_light(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    s = packet.get("s")
    if s == 0:
        return [_make("light", "turn_off", eid)]
    if s != 1:
        return []

    data: dict = {"entity_id": eid}
    bri = packet.get("bri")
    if bri is not None:
        data["brightness"] = round(bri * 2.55)
    ct = packet.get("ct")
    if ct is not None:
        data["color_temp"] = ct
    return [ServiceCall("light", "turn_on", data)]


def _handle_switch(packet: dict, device: Device) -> list[ServiceCall]:
    return _on_off("switch", packet, device.entity_id)


def _handle_siren(packet: dict, device: Device) -> list[ServiceCall]:
    return _on_off("siren", packet, device.entity_id)


def _handle_climate(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    result: list[ServiceCall] = []

    s = packet.get("s")
    if s == 1:
        result.append(_make("climate", "turn_on", eid))
    elif s == 0:
        return [_make("climate", "turn_off", eid)]

    th = packet.get("th")
    if th is not None:
        result.append(_make("climate", "set_temperature", eid, temperature=th))

    md = packet.get("md")
    if md is not None:
        result.append(_make("climate", "set_hvac_mode", eid, hvac_mode=md))

    fn = packet.get("fn")
    if fn is not None:
        result.append(_make("climate", "set_fan_mode", eid, fan_mode=fn))

    return result


def _handle_water_heater(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    result: list[ServiceCall] = []

    if packet.get("s") == 1:
        result.append(_make("water_heater", "turn_on", eid))

    th = packet.get("th")
    if th is not None:
        result.append(_make("water_heater", "set_temperature", eid, temperature=th))

    return result


def _handle_fan(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    result: list[ServiceCall] = []

    if packet.get("s") == 1:
        result.append(_make("fan", "turn_on", eid))

    sp = packet.get("sp")
    if sp is not None:
        result.append(_make("fan", "set_percentage", eid, percentage=sp))

    return result


_COVER_CMDS = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}


def _handle_cover(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    cmd = packet.get("cmd")
    if cmd is not None and cmd in _COVER_CMDS:
        return [_make("cover", _COVER_CMDS[cmd], eid)]

    pos = packet.get("pos")
    if pos is not None:
        return [_make("cover", "set_cover_position", eid, position=pos)]

    return []


_LOCK_CMDS = {"lock": "lock", "unlock": "unlock"}


def _handle_lock(packet: dict, device: Device) -> list[ServiceCall]:
    cmd = packet.get("cmd")
    if cmd in _LOCK_CMDS:
        return [_make("lock", _LOCK_CMDS[cmd], device.entity_id)]
    return []


_ALARM_CMDS = {
    "arm_home": "alarm_arm_home",
    "arm_away": "alarm_arm_away",
    "arm_night": "alarm_arm_night",
    "disarm": "alarm_disarm",
}


def _handle_alarm(packet: dict, device: Device) -> list[ServiceCall]:
    cmd = packet.get("cmd")
    if cmd not in _ALARM_CMDS:
        return []

    data: dict = {"entity_id": device.entity_id}
    pin = packet.get("pin")
    if pin is not None:
        data["code"] = pin
    return [ServiceCall("alarm_control_panel", _ALARM_CMDS[cmd], data)]


def _handle_humidifier(packet: dict, device: Device) -> list[ServiceCall]:
    eid = device.entity_id
    result: list[ServiceCall] = []

    if packet.get("s") == 1:
        result.append(_make("humidifier", "turn_on", eid))

    th = packet.get("th")
    if th is not None:
        result.append(_make("humidifier", "set_humidity", eid, humidity=th))

    return result


def _handle_button(packet: dict, device: Device) -> list[ServiceCall]:
    if packet.get("cmd") != "press":
        return []

    domain = device.entity_id.split(".")[0]
    if domain == "scene":
        return [_make("scene", "turn_on", device.entity_id)]
    return [_make("button", "press", device.entity_id)]


# ---------- dispatch ----------

_HANDLERS: dict[str, callable] = {
    DEV_LIGHT: _handle_light,
    DEV_SWITCH: _handle_switch,
    DEV_SIREN: _handle_siren,
    DEV_CLIMATE: _handle_climate,
    DEV_WATER_HEATER: _handle_water_heater,
    DEV_FAN: _handle_fan,
    DEV_COVER: _handle_cover,
    DEV_LOCK: _handle_lock,
    DEV_ALARM: _handle_alarm,
    DEV_HUMIDIFIER: _handle_humidifier,
    DEV_BUTTON: _handle_button,
}


def build_service_calls(device: Device, packet: dict) -> list[ServiceCall]:
    """Преобразовать Rover-пакет в список вызовов HA-сервисов.

    Если для типа устройства нет обработчика или в пакете нет осмысленных
    полей — возвращается пустой список.
    """
    handler = _HANDLERS.get(device.t)
    if handler is None:
        return []
    return handler(packet, device)
