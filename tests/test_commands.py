"""Юнит-тесты для commands.py."""

from __future__ import annotations

from rover.commands import ServiceCall, build_service_calls
from rover.const import (
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
from rover.registry import Device


def _dev(t: str, entity_id: str) -> Device:
    return Device(short_id=1, entity_id=entity_id, t=t, n="x")


# ---------- LIGHT ----------

def test_light_off():
    calls = build_service_calls(_dev(DEV_LIGHT, "light.salon"), {"tp": 5, "id": 1, "s": 0})
    assert calls == [ServiceCall("light", "turn_off", {"entity_id": "light.salon"})]


def test_light_on_simple():
    calls = build_service_calls(_dev(DEV_LIGHT, "light.salon"), {"tp": 5, "id": 1, "s": 1})
    assert calls == [ServiceCall("light", "turn_on", {"entity_id": "light.salon"})]


def test_light_on_with_brightness_converted_to_255_scale():
    """SB-030: bri 0..100 → HA brightness 0..255."""
    calls = build_service_calls(_dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1, "s": 1, "bri": 50})
    assert calls[0].data["brightness"] == round(50 * 2.55)


def test_light_on_with_bri_zero():
    calls = build_service_calls(_dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1, "s": 1, "bri": 0})
    assert calls[0].data["brightness"] == 0


def test_light_on_with_bri_100():
    calls = build_service_calls(_dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1, "s": 1, "bri": 100})
    assert calls[0].data["brightness"] == 255


def test_light_with_color_temp():
    calls = build_service_calls(_dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1, "s": 1, "ct": 350})
    assert calls[0].data["color_temp"] == 350


def test_light_off_ignores_bri_ct():
    calls = build_service_calls(
        _dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1, "s": 0, "bri": 50, "ct": 300}
    )
    assert calls == [ServiceCall("light", "turn_off", {"entity_id": "light.x"})]


def test_light_empty_packet_returns_no_calls():
    assert build_service_calls(_dev(DEV_LIGHT, "light.x"), {"tp": 5, "id": 1}) == []


# ---------- SWITCH / SIREN ----------

def test_switch_on():
    calls = build_service_calls(_dev(DEV_SWITCH, "switch.x"), {"tp": 5, "id": 1, "s": 1})
    assert calls == [ServiceCall("switch", "turn_on", {"entity_id": "switch.x"})]


def test_switch_off():
    calls = build_service_calls(_dev(DEV_SWITCH, "switch.x"), {"tp": 5, "id": 1, "s": 0})
    assert calls == [ServiceCall("switch", "turn_off", {"entity_id": "switch.x"})]


def test_siren_on():
    calls = build_service_calls(_dev(DEV_SIREN, "siren.x"), {"tp": 5, "id": 1, "s": 1})
    assert calls == [ServiceCall("siren", "turn_on", {"entity_id": "siren.x"})]


def test_switch_empty_packet():
    assert build_service_calls(_dev(DEV_SWITCH, "switch.x"), {"tp": 5, "id": 1}) == []


# ---------- CLIMATE ----------

def test_climate_set_temperature():
    calls = build_service_calls(_dev(DEV_CLIMATE, "climate.x"), {"tp": 5, "id": 1, "th": 22.5})
    assert calls[0].service == "set_temperature"
    assert calls[0].data["temperature"] == 22.5


def test_climate_set_hvac_mode():
    calls = build_service_calls(_dev(DEV_CLIMATE, "climate.x"), {"tp": 5, "id": 1, "md": "cool"})
    assert calls[0].service == "set_hvac_mode"
    assert calls[0].data["hvac_mode"] == "cool"


def test_climate_set_fan_mode():
    calls = build_service_calls(_dev(DEV_CLIMATE, "climate.x"), {"tp": 5, "id": 1, "fn": "auto"})
    assert calls[0].service == "set_fan_mode"
    assert calls[0].data["fan_mode"] == "auto"


def test_climate_multiple_fields_produce_multiple_calls():
    """s+th+md+fn → 4 вызова в порядке s → th → md → fn."""
    calls = build_service_calls(
        _dev(DEV_CLIMATE, "climate.x"),
        {"tp": 5, "id": 1, "s": 1, "th": 22.0, "md": "heat", "fn": "low"},
    )
    services = [c.service for c in calls]
    assert services == ["turn_on", "set_temperature", "set_hvac_mode", "set_fan_mode"]


def test_climate_off():
    calls = build_service_calls(_dev(DEV_CLIMATE, "climate.x"), {"tp": 5, "id": 1, "s": 0})
    assert calls == [ServiceCall("climate", "turn_off", {"entity_id": "climate.x"})]


# ---------- WATER_HEATER ----------

def test_water_heater_on_with_temp():
    calls = build_service_calls(
        _dev(DEV_WATER_HEATER, "water_heater.x"),
        {"tp": 5, "id": 1, "s": 1, "th": 60.0},
    )
    assert len(calls) == 2
    assert calls[0].service == "turn_on"
    assert calls[1].service == "set_temperature"
    assert calls[1].data["temperature"] == 60.0


# ---------- FAN ----------

def test_fan_on_with_speed():
    calls = build_service_calls(_dev(DEV_FAN, "fan.x"), {"tp": 5, "id": 1, "s": 1, "sp": 50})
    assert len(calls) == 2
    assert calls[0].service == "turn_on"
    assert calls[1].service == "set_percentage"
    assert calls[1].data["percentage"] == 50


def test_fan_speed_only():
    calls = build_service_calls(_dev(DEV_FAN, "fan.x"), {"tp": 5, "id": 1, "sp": 75})
    assert calls == [ServiceCall("fan", "set_percentage", {"entity_id": "fan.x", "percentage": 75})]


# ---------- COVER ----------

def test_cover_open():
    calls = build_service_calls(_dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1, "cmd": "open"})
    assert calls == [ServiceCall("cover", "open_cover", {"entity_id": "cover.x"})]


def test_cover_close():
    calls = build_service_calls(_dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1, "cmd": "close"})
    assert calls == [ServiceCall("cover", "close_cover", {"entity_id": "cover.x"})]


def test_cover_stop():
    calls = build_service_calls(_dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1, "cmd": "stop"})
    assert calls == [ServiceCall("cover", "stop_cover", {"entity_id": "cover.x"})]


def test_cover_set_position():
    calls = build_service_calls(_dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1, "pos": 30})
    assert calls == [ServiceCall(
        "cover", "set_cover_position", {"entity_id": "cover.x", "position": 30}
    )]


def test_cover_cmd_has_priority_over_pos():
    calls = build_service_calls(
        _dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1, "cmd": "open", "pos": 50}
    )
    assert calls == [ServiceCall("cover", "open_cover", {"entity_id": "cover.x"})]


def test_cover_empty_packet():
    assert build_service_calls(_dev(DEV_COVER, "cover.x"), {"tp": 5, "id": 1}) == []


# ---------- LOCK ----------

def test_lock_lock():
    calls = build_service_calls(_dev(DEV_LOCK, "lock.x"), {"tp": 5, "id": 1, "cmd": "lock"})
    assert calls == [ServiceCall("lock", "lock", {"entity_id": "lock.x"})]


def test_lock_unlock():
    calls = build_service_calls(_dev(DEV_LOCK, "lock.x"), {"tp": 5, "id": 1, "cmd": "unlock"})
    assert calls == [ServiceCall("lock", "unlock", {"entity_id": "lock.x"})]


def test_lock_unknown_cmd_returns_empty():
    assert build_service_calls(_dev(DEV_LOCK, "lock.x"), {"tp": 5, "id": 1, "cmd": "wat"}) == []


# ---------- ALARM ----------

def test_alarm_arm_home_with_pin():
    calls = build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"),
        {"tp": 5, "id": 1, "cmd": "arm_home", "pin": "1234"},
    )
    assert calls == [ServiceCall(
        "alarm_control_panel", "alarm_arm_home",
        {"entity_id": "alarm_control_panel.x", "code": "1234"},
    )]


def test_alarm_arm_away():
    calls = build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"), {"tp": 5, "id": 1, "cmd": "arm_away"}
    )
    assert calls[0].service == "alarm_arm_away"


def test_alarm_arm_night():
    calls = build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"), {"tp": 5, "id": 1, "cmd": "arm_night"}
    )
    assert calls[0].service == "alarm_arm_night"


def test_alarm_disarm():
    calls = build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"), {"tp": 5, "id": 1, "cmd": "disarm"}
    )
    assert calls[0].service == "alarm_disarm"


def test_alarm_unknown_cmd_returns_empty():
    """SB-031: только 4 фиксированных значения."""
    assert build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"),
        {"tp": 5, "id": 1, "cmd": "arm_vacation"},
    ) == []


def test_alarm_no_cmd_returns_empty():
    assert build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"), {"tp": 5, "id": 1, "pin": "1234"}
    ) == []


def test_alarm_without_pin():
    calls = build_service_calls(
        _dev(DEV_ALARM, "alarm_control_panel.x"), {"tp": 5, "id": 1, "cmd": "disarm"}
    )
    assert "code" not in calls[0].data


# ---------- HUMIDIFIER ----------

def test_humidifier_on():
    calls = build_service_calls(_dev(DEV_HUMIDIFIER, "humidifier.x"), {"tp": 5, "id": 1, "s": 1})
    assert calls == [ServiceCall("humidifier", "turn_on", {"entity_id": "humidifier.x"})]


def test_humidifier_set_humidity_via_th():
    """Для humidifier th — это target HUMIDITY."""
    calls = build_service_calls(_dev(DEV_HUMIDIFIER, "humidifier.x"), {"tp": 5, "id": 1, "th": 60})
    assert calls == [ServiceCall(
        "humidifier", "set_humidity", {"entity_id": "humidifier.x", "humidity": 60}
    )]


def test_humidifier_on_with_humidity():
    calls = build_service_calls(
        _dev(DEV_HUMIDIFIER, "humidifier.x"), {"tp": 5, "id": 1, "s": 1, "th": 50}
    )
    assert len(calls) == 2
    assert calls[0].service == "turn_on"
    assert calls[1].service == "set_humidity"


# ---------- BUTTON / SCENE ----------

def test_button_press():
    calls = build_service_calls(
        _dev(DEV_BUTTON, "button.doorbell"), {"tp": 5, "id": 1, "cmd": "press"}
    )
    assert calls == [ServiceCall("button", "press", {"entity_id": "button.doorbell"})]


def test_scene_press_uses_turn_on():
    calls = build_service_calls(
        _dev(DEV_BUTTON, "scene.movie"), {"tp": 5, "id": 1, "cmd": "press"}
    )
    assert calls == [ServiceCall("scene", "turn_on", {"entity_id": "scene.movie"})]


def test_button_without_press_cmd_returns_empty():
    d = _dev(DEV_BUTTON, "button.x")
    assert build_service_calls(d, {"tp": 5, "id": 1}) == []
    assert build_service_calls(d, {"tp": 5, "id": 1, "cmd": "other"}) == []


# ---------- Неизвестный тип ----------

def test_unknown_device_type_returns_empty():
    d = Device(short_id=1, entity_id="x.y", t="UNKNOWN", n="x")
    assert build_service_calls(d, {"tp": 5, "id": 1, "s": 1}) == []


# ---------- ServiceCall ----------

def test_service_call_dataclass_equality():
    a = ServiceCall("light", "turn_on", {"entity_id": "light.x"})
    b = ServiceCall("light", "turn_on", {"entity_id": "light.x"})
    assert a == b


def test_all_calls_contain_entity_id():
    """Любой вызов всегда содержит entity_id."""
    cases = [
        ("light.x", DEV_LIGHT, {"s": 1}),
        ("switch.x", DEV_SWITCH, {"s": 1}),
        ("climate.x", DEV_CLIMATE, {"th": 22.0}),
        ("cover.x", DEV_COVER, {"cmd": "open"}),
        ("lock.x", DEV_LOCK, {"cmd": "lock"}),
        ("alarm_control_panel.x", DEV_ALARM, {"cmd": "disarm"}),
        ("fan.x", DEV_FAN, {"sp": 50}),
        ("humidifier.x", DEV_HUMIDIFIER, {"th": 60}),
        ("button.x", DEV_BUTTON, {"cmd": "press"}),
    ]
    for entity_id, t, packet in cases:
        calls = build_service_calls(_dev(t, entity_id), packet)
        assert calls, f"no calls for {t}/{packet}"
        for c in calls:
            assert c.data.get("entity_id") == entity_id
