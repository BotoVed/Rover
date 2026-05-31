"""Юнит-тесты для state_extractor.py."""

from __future__ import annotations

from dataclasses import dataclass, field

from rover.const import (
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
from rover.registry import Device
from rover.state_extractor import extract_state


@dataclass
class FakeState:
    """Минимальный stub HA state-объекта."""
    state: str
    attributes: dict = field(default_factory=dict)


def _dev(t: str, entity_id: str = "x.y") -> Device:
    return Device(short_id=1, entity_id=entity_id, t=t, n="x")


# ---------- Невалидные состояния ----------

def test_none_state_returns_empty():
    assert extract_state(_dev(DEV_LIGHT), None) == {}


def test_unknown_state_returns_empty():
    assert extract_state(_dev(DEV_LIGHT), FakeState(state="unknown")) == {}


def test_unavailable_state_returns_empty():
    assert extract_state(_dev(DEV_LIGHT), FakeState(state="unavailable")) == {}


# ---------- LIGHT ----------

def test_light_off():
    assert extract_state(_dev(DEV_LIGHT), FakeState(state="off")) == {"s": 0}


def test_light_on_simple():
    assert extract_state(_dev(DEV_LIGHT), FakeState(state="on")) == {"s": 1}


def test_light_on_with_brightness_converted_0_100():
    """SB-030: HA brightness 0..255 → 0..100."""
    s = FakeState(state="on", attributes={"brightness": 128})
    result = extract_state(_dev(DEV_LIGHT), s)
    assert result["s"] == 1
    assert result["bri"] == round(128 / 2.55)


def test_light_on_bri_0_and_255_edges():
    s0 = FakeState(state="on", attributes={"brightness": 0})
    s255 = FakeState(state="on", attributes={"brightness": 255})
    assert extract_state(_dev(DEV_LIGHT), s0)["bri"] == 0
    assert extract_state(_dev(DEV_LIGHT), s255)["bri"] == 100


def test_light_on_with_color_temp():
    s = FakeState(state="on", attributes={"color_temp": 350})
    assert extract_state(_dev(DEV_LIGHT), s)["ct"] == 350


def test_light_off_no_brightness_ct():
    """При s=0 не включаем bri и ct."""
    s = FakeState(state="off", attributes={"brightness": 200, "color_temp": 300})
    assert extract_state(_dev(DEV_LIGHT), s) == {"s": 0}


# ---------- SWITCH / SIREN / BINARY_SENSOR ----------

def test_switch_on():
    assert extract_state(_dev(DEV_SWITCH), FakeState(state="on")) == {"s": 1}


def test_switch_off():
    assert extract_state(_dev(DEV_SWITCH), FakeState(state="off")) == {"s": 0}


def test_siren_on():
    assert extract_state(_dev(DEV_SIREN), FakeState(state="on")) == {"s": 1}


def test_binary_sensor_on():
    assert extract_state(_dev(DEV_BINARY_SENSOR), FakeState(state="on")) == {"s": 1}


def test_binary_sensor_off():
    assert extract_state(_dev(DEV_BINARY_SENSOR), FakeState(state="off")) == {"s": 0}


# ---------- CLIMATE ----------

def test_climate_off():
    result = extract_state(_dev(DEV_CLIMATE), FakeState(state="off"))
    assert result["s"] == 0
    assert result["md"] == "off"


def test_climate_cool_mode():
    result = extract_state(_dev(DEV_CLIMATE), FakeState(state="cool"))
    assert result["s"] == 1
    assert result["md"] == "cool"


def test_climate_with_temperatures_and_fan():
    s = FakeState(state="heat", attributes={
        "temperature": 22.5,
        "current_temperature": 21.0,
        "fan_mode": "auto",
    })
    result = extract_state(_dev(DEV_CLIMATE), s)
    assert result == {"s": 1, "md": "heat", "th": 22.5, "tc": 21.0, "fn": "auto"}


def test_climate_no_attributes():
    """Climate без attributes — только s и md."""
    result = extract_state(_dev(DEV_CLIMATE), FakeState(state="auto"))
    assert result == {"s": 1, "md": "auto"}


# ---------- WATER_HEATER ----------

def test_water_heater_with_temps():
    s = FakeState(state="electric", attributes={
        "temperature": 60.0,
        "current_temperature": 55.5,
    })
    result = extract_state(_dev(DEV_WATER_HEATER), s)
    assert result == {"s": 1, "md": "electric", "th": 60.0, "tc": 55.5}


def test_water_heater_off():
    result = extract_state(_dev(DEV_WATER_HEATER), FakeState(state="off"))
    assert result["s"] == 0
    assert result["md"] == "off"


# ---------- FAN ----------

def test_fan_off():
    assert extract_state(_dev(DEV_FAN), FakeState(state="off")) == {"s": 0}


def test_fan_on_with_percentage():
    s = FakeState(state="on", attributes={"percentage": 75})
    result = extract_state(_dev(DEV_FAN), s)
    assert result == {"s": 1, "sp": 75}


# ---------- COVER ----------

def test_cover_open_full():
    s = FakeState(state="open", attributes={"current_position": 100})
    result = extract_state(_dev(DEV_COVER), s)
    assert result == {"st": "open", "pos": 100}


def test_cover_closed():
    s = FakeState(state="closed", attributes={"current_position": 0})
    result = extract_state(_dev(DEV_COVER), s)
    assert result == {"st": "closed", "pos": 0}


def test_cover_opening_partial():
    s = FakeState(state="opening", attributes={"current_position": 45})
    result = extract_state(_dev(DEV_COVER), s)
    assert result == {"st": "opening", "pos": 45}


def test_cover_no_position():
    """Cover без current_position — только st."""
    result = extract_state(_dev(DEV_COVER), FakeState(state="open"))
    assert result == {"st": "open"}


# ---------- LOCK ----------

def test_lock_locked():
    assert extract_state(_dev(DEV_LOCK), FakeState(state="locked")) == {"st": "locked"}


def test_lock_unlocked():
    assert extract_state(_dev(DEV_LOCK), FakeState(state="unlocked")) == {"st": "unlocked"}


def test_lock_jammed():
    assert extract_state(_dev(DEV_LOCK), FakeState(state="jammed")) == {"st": "jammed"}


# ---------- ALARM ----------

def test_alarm_armed_away():
    assert extract_state(_dev(DEV_ALARM), FakeState(state="armed_away")) == {"st": "armed_away"}


def test_alarm_disarmed():
    assert extract_state(_dev(DEV_ALARM), FakeState(state="disarmed")) == {"st": "disarmed"}


def test_alarm_triggered():
    assert extract_state(_dev(DEV_ALARM), FakeState(state="triggered")) == {"st": "triggered"}


# ---------- HUMIDIFIER ----------

def test_humidifier_on_with_target():
    s = FakeState(state="on", attributes={"humidity": 50, "current_humidity": 45})
    result = extract_state(_dev(DEV_HUMIDIFIER), s)
    assert result == {"s": 1, "th": 50, "tc": 45}


def test_humidifier_off():
    assert extract_state(_dev(DEV_HUMIDIFIER), FakeState(state="off")) == {"s": 0}


# ---------- SENSOR (SB-033: всегда строка) ----------

def test_sensor_numeric_as_string():
    """Числовое значение всё равно идёт строкой."""
    s = FakeState(state="23.5", attributes={"unit_of_measurement": "°C"})
    result = extract_state(_dev(DEV_SENSOR), s)
    assert result == {"v": "23.5", "u": "°C"}


def test_sensor_enum_value():
    """Enum-сенсор: значение — нечисловая строка."""
    s = FakeState(state="running", attributes={})
    result = extract_state(_dev(DEV_SENSOR), s)
    assert result == {"v": "running"}
    assert "u" not in result


def test_sensor_timestamp_value():
    """Timestamp как строка."""
    s = FakeState(
        state="2026-05-31T14:32:00+00:00",
        attributes={"device_class": "timestamp"},
    )
    result = extract_state(_dev(DEV_SENSOR), s)
    assert result["v"] == "2026-05-31T14:32:00+00:00"


def test_sensor_integer_as_string():
    s = FakeState(state="100", attributes={"unit_of_measurement": "%"})
    result = extract_state(_dev(DEV_SENSOR), s)
    assert result == {"v": "100", "u": "%"}


# ---------- BUTTON / SCENE ----------

def test_button_no_state():
    """У button нет состояния — пустой dict."""
    assert extract_state(_dev(DEV_BUTTON), FakeState(state="2026-01-01T00:00:00")) == {}


# ---------- Неизвестный тип ----------

def test_unknown_type_returns_empty():
    d = Device(short_id=1, entity_id="x.y", t="UNKNOWN", n="x")
    assert extract_state(d, FakeState(state="on")) == {}


# ---------- attributes отсутствует ----------

def test_attributes_can_be_missing():
    """Если attributes пуст или None — не падаем."""
    s = FakeState(state="on")
    result = extract_state(_dev(DEV_LIGHT), s)
    assert result == {"s": 1}


# ---------- общее ----------

def test_all_returned_keys_are_protocol_fields():
    """Все ключи в результате — короткие имена полей протокола."""
    cases = [
        (DEV_LIGHT, FakeState(state="on", attributes={"brightness": 200, "color_temp": 300})),
        (DEV_CLIMATE, FakeState(state="heat", attributes={"temperature": 22.0})),
        (DEV_COVER, FakeState(state="open", attributes={"current_position": 50})),
        (DEV_FAN, FakeState(state="on", attributes={"percentage": 50})),
        (DEV_SENSOR, FakeState(state="23", attributes={"unit_of_measurement": "°C"})),
        (DEV_HUMIDIFIER, FakeState(state="on", attributes={"humidity": 60})),
    ]
    short_keys = {"s", "bri", "ct", "th", "tc", "md", "fn", "sp", "pos", "st", "v", "u"}
    for t, s in cases:
        result = extract_state(_dev(t), s)
        for key in result:
            assert key in short_keys, f"unexpected key '{key}' for type {t}"
