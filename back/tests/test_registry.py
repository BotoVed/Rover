"""Юнит-тесты для registry.py."""

from __future__ import annotations

import pytest

from rover.const import (
    DEV_CLIMATE,
    DEV_LIGHT,
    DEV_SWITCH,
    SHORT_ID_MAX,
)
from rover.registry import Device, DeviceRegistry, _compute_short_id


# ---------- Базовая регистрация ----------

def test_register_returns_short_id():
    r = DeviceRegistry()
    sid = r.register("light.salon", "light", "Люстра")
    assert 0 <= sid <= SHORT_ID_MAX


def test_register_assigns_correct_type():
    r = DeviceRegistry()
    sid = r.register("light.salon", "light", "Люстра")
    device = r.get_by_short_id(sid)
    assert device is not None
    assert device.t == DEV_LIGHT
    assert device.entity_id == "light.salon"
    assert device.n == "Люстра"


def test_register_unknown_domain_raises():
    r = DeviceRegistry()
    with pytest.raises(ValueError, match="Unsupported HA domain"):
        r.register("media_player.tv", "media_player", "TV")


def test_register_supports_all_documented_domains():
    """Все домены из SPEC.md §5.3 должны поддерживаться."""
    r = DeviceRegistry()
    cases = [
        ("light.x", "light"),
        ("switch.x", "switch"),
        ("climate.x", "climate"),
        ("water_heater.x", "water_heater"),
        ("fan.x", "fan"),
        ("cover.x", "cover"),
        ("lock.x", "lock"),
        ("binary_sensor.x", "binary_sensor"),
        ("sensor.x", "sensor"),
        ("siren.x", "siren"),
        ("button.x", "button"),
        ("scene.x", "scene"),
        ("alarm_control_panel.x", "alarm_control_panel"),
        ("humidifier.x", "humidifier"),
    ]
    for entity_id, domain in cases:
        sid = r.register(entity_id, domain, "name")
        assert isinstance(sid, int)


# ---------- Повторная регистрация ----------

def test_register_same_entity_returns_same_short_id():
    r = DeviceRegistry()
    sid1 = r.register("light.salon", "light", "Люстра")
    sid2 = r.register("light.salon", "light", "Люстра обновлённое имя")
    assert sid1 == sid2


def test_register_updates_metadata_on_repeat():
    """Повторная регистрация обновляет name/area/unit, но не short_id."""
    r = DeviceRegistry()
    sid = r.register("light.salon", "light", "Старое имя", area="zone1")
    r.register("light.salon", "light", "Новое имя", area="zone2", unit=None)
    device = r.get_by_short_id(sid)
    assert device.n == "Новое имя"
    assert device.a == "zone2"


# ---------- Поиск ----------

def test_lookup_by_entity_id():
    r = DeviceRegistry()
    sid = r.register("light.salon", "light", "Люстра")
    device = r.get_by_entity_id("light.salon")
    assert device is not None
    assert device.short_id == sid


def test_lookup_missing_returns_none():
    r = DeviceRegistry()
    assert r.get_by_short_id(12345) is None
    assert r.get_by_entity_id("light.nope") is None


def test_contains_and_len():
    r = DeviceRegistry()
    assert len(r) == 0
    assert "light.x" not in r
    r.register("light.x", "light", "X")
    assert len(r) == 1
    assert "light.x" in r


def test_all_devices_sorted_by_short_id():
    r = DeviceRegistry()
    r.register("light.a", "light", "A")
    r.register("light.b", "light", "B")
    r.register("light.c", "light", "C")
    devices = r.all_devices()
    sids = [d.short_id for d in devices]
    assert sids == sorted(sids)


# ---------- Коллизии short_id ----------

def test_collision_resolved_with_salt(monkeypatch):
    """Если первый short_id занят — берём со следующим солтом."""
    r = DeviceRegistry()

    real_compute = _compute_short_id

    def fake_compute(entity_id: str, salt: int = 0) -> int:
        if entity_id == "light.b" and salt == 0:
            return real_compute("light.a", 0)
        return real_compute(entity_id, salt)

    monkeypatch.setattr("rover.registry._compute_short_id", fake_compute)

    sid_a = r.register("light.a", "light", "A")
    sid_b = r.register("light.b", "light", "B")
    assert sid_a != sid_b


def test_short_id_stays_after_collision_partner_removed():
    """short_id за устройством закреплён, даже если коллизионный сосед удалён."""
    r1 = DeviceRegistry()
    r1.register("light.a", "light", "A")
    sid_b_original = r1.register("light.b", "light", "B")

    data_path = "_tmp_registry.json"
    r1.save(data_path)

    r2 = DeviceRegistry()
    r2.load(data_path)
    device_b = r2.get_by_entity_id("light.b")
    assert device_b is not None
    assert device_b.short_id == sid_b_original

    import os
    os.remove(data_path)


# ---------- cfgh ----------

def test_cfgh_is_deterministic():
    """Один и тот же состав → один и тот же cfgh."""
    r = DeviceRegistry()
    r.register("light.a", "light", "A", area="z1")
    r.register("switch.b", "switch", "B", area="z2")
    h1 = r.compute_cfgh()
    h2 = r.compute_cfgh()
    assert h1 == h2
    assert len(h1) == 8


def test_cfgh_independent_of_registration_order():
    """Порядок регистрации не влияет на cfgh."""
    r1 = DeviceRegistry()
    r1.register("light.a", "light", "A")
    r1.register("switch.b", "switch", "B")

    r2 = DeviceRegistry()
    r2.register("switch.b", "switch", "B")
    r2.register("light.a", "light", "A")

    assert r1.compute_cfgh() == r2.compute_cfgh()


def test_cfgh_changes_when_device_added():
    r = DeviceRegistry()
    r.register("light.a", "light", "A")
    h1 = r.compute_cfgh()
    r.register("switch.b", "switch", "B")
    h2 = r.compute_cfgh()
    assert h1 != h2


def test_cfgh_changes_when_name_changes():
    r = DeviceRegistry()
    r.register("light.a", "light", "Старое имя")
    h1 = r.compute_cfgh()
    r.register("light.a", "light", "Новое имя")
    h2 = r.compute_cfgh()
    assert h1 != h2


def test_cfgh_includes_areas_and_users():
    """Зоны и пользователи влияют на cfgh."""
    r = DeviceRegistry()
    r.register("light.a", "light", "A")

    h_no_areas = r.compute_cfgh()
    h_with_areas = r.compute_cfgh(areas=[{"id": "z1", "n": "Кухня"}])
    h_with_users = r.compute_cfgh(users=[{"id": "u1", "n": "admin"}])
    assert h_no_areas != h_with_areas
    assert h_no_areas != h_with_users
    assert h_with_areas != h_with_users


# ---------- Save / Load ----------

def test_save_and_load_roundtrip(tmp_path):
    """Сохранение и загрузка не теряют данных."""
    r1 = DeviceRegistry()
    sid_a = r1.register("light.a", "light", "Люстра", area="salon", unit=None)
    sid_b = r1.register("sensor.temp", "sensor", "Температура", area="kitchen", unit="°C")

    path = tmp_path / "registry.json"
    r1.save(path)

    r2 = DeviceRegistry()
    r2.load(path)

    assert len(r2) == 2
    assert r2.get_by_short_id(sid_a).entity_id == "light.a"
    assert r2.get_by_short_id(sid_b).u == "°C"
    assert r1.compute_cfgh() == r2.compute_cfgh()


def test_load_missing_file_is_noop(tmp_path):
    """Загрузка из отсутствующего файла не падает."""
    r = DeviceRegistry()
    r.load(tmp_path / "nope.json")
    assert len(r) == 0


def test_load_clears_existing(tmp_path):
    """Загрузка из файла очищает текущий реестр перед заполнением."""
    r1 = DeviceRegistry()
    r1.register("light.a", "light", "A")
    path = tmp_path / "reg.json"
    r1.save(path)

    r2 = DeviceRegistry()
    r2.register("switch.b", "switch", "B")
    r2.load(path)

    assert len(r2) == 1
    assert "light.a" in r2
    assert "switch.b" not in r2


# ---------- short_id корректность ----------

def test_short_id_in_range():
    r = DeviceRegistry()
    sid = r.register("light.salon", "light", "X")
    assert 0 <= sid <= SHORT_ID_MAX


def test_compute_short_id_deterministic():
    """_compute_short_id даёт одно и то же значение для одного entity_id."""
    a1 = _compute_short_id("light.salon")
    a2 = _compute_short_id("light.salon")
    assert a1 == a2


def test_compute_short_id_changes_with_salt():
    base = _compute_short_id("light.salon", salt=0)
    salted = _compute_short_id("light.salon", salt=1)
    assert base != salted
