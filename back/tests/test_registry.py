"""Юнит-тесты для registry.py."""

from __future__ import annotations

import pytest

from rover.const import (
    DEV_LIGHT,
    DEV_SENSOR,
    SEC_AREAS,
    SEC_DEVICES,
    SEC_USERS,
    SECTION_HASH_LENGTH,
    SHORT_ID_MAX,
)
from rover.registry import Area, Device, Registry, User, _compute_short_id


# ---------- Базовая регистрация устройств ----------

def test_register_returns_short_id():
    r = Registry()
    sid = r.register("light.salon", "light", "Люстра")
    assert 0 <= sid <= SHORT_ID_MAX


def test_register_assigns_correct_type():
    r = Registry()
    sid = r.register("light.salon", "light", "Люстра")
    d = r.get_by_short_id(sid)
    assert d is not None
    assert d.t == DEV_LIGHT
    assert d.entity_id == "light.salon"
    assert d.n == "Люстра"


def test_register_unknown_domain_raises():
    r = Registry()
    with pytest.raises(ValueError, match="Unsupported HA domain"):
        r.register("media_player.tv", "media_player", "TV")


def test_register_supports_all_documented_domains():
    r = Registry()
    cases = [
        ("light.x", "light"), ("switch.x", "switch"), ("climate.x", "climate"),
        ("water_heater.x", "water_heater"), ("fan.x", "fan"), ("cover.x", "cover"),
        ("lock.x", "lock"), ("binary_sensor.x", "binary_sensor"), ("sensor.x", "sensor"),
        ("siren.x", "siren"), ("button.x", "button"), ("scene.x", "scene"),
        ("alarm_control_panel.x", "alarm_control_panel"), ("humidifier.x", "humidifier"),
    ]
    for entity_id, domain in cases:
        sid = r.register(entity_id, domain, "name")
        assert isinstance(sid, int)


def test_register_same_entity_returns_same_short_id():
    r = Registry()
    sid1 = r.register("light.salon", "light", "X")
    sid2 = r.register("light.salon", "light", "Y")
    assert sid1 == sid2


def test_register_updates_metadata_on_repeat():
    r = Registry()
    sid = r.register("light.salon", "light", "Старое", area="z1")
    r.register("light.salon", "light", "Новое", area="z2", unit=None)
    d = r.get_by_short_id(sid)
    assert d.n == "Новое"
    assert d.a == "z2"


# ---------- Поиск ----------

def test_lookup_by_entity_id():
    r = Registry()
    sid = r.register("light.salon", "light", "X")
    assert r.get_by_entity_id("light.salon").short_id == sid


def test_lookup_missing_returns_none():
    r = Registry()
    assert r.get_by_short_id(12345) is None
    assert r.get_by_entity_id("light.nope") is None


def test_contains_and_len():
    r = Registry()
    assert len(r) == 0
    r.register("light.x", "light", "X")
    assert len(r) == 1
    assert "light.x" in r


def test_all_devices_sorted_by_short_id():
    r = Registry()
    r.register("light.a", "light", "A")
    r.register("light.b", "light", "B")
    r.register("light.c", "light", "C")
    sids = [d.short_id for d in r.all_devices()]
    assert sids == sorted(sids)


# ---------- Коллизии ----------

def test_collision_resolved_with_salt(monkeypatch):
    r = Registry()
    real = _compute_short_id

    def fake(entity_id: str, salt: int = 0) -> int:
        if entity_id == "light.b" and salt == 0:
            return real("light.a", 0)
        return real(entity_id, salt)

    monkeypatch.setattr("rover.registry._compute_short_id", fake)
    sid_a = r.register("light.a", "light", "A")
    sid_b = r.register("light.b", "light", "B")
    assert sid_a != sid_b


# ---------- Зоны ----------

def test_set_and_get_areas():
    r = Registry()
    r.set_areas([Area(id="salon", n="Гостиная"), Area(id="kitchen", n="Кухня")])
    assert r.get_area("salon").n == "Гостиная"
    assert r.get_area("nope") is None


def test_set_areas_replaces_previous():
    r = Registry()
    r.set_areas([Area(id="a", n="A")])
    r.set_areas([Area(id="b", n="B")])
    assert r.get_area("a") is None
    assert r.get_area("b") is not None


def test_all_areas_sorted():
    r = Registry()
    r.set_areas([Area(id="c", n="C"), Area(id="a", n="A"), Area(id="b", n="B")])
    assert [a.id for a in r.all_areas()] == ["a", "b", "c"]


# ---------- Пользователи ----------

def test_set_and_get_users():
    r = Registry()
    r.set_users([User(id="admin", hash="abc123")])
    assert r.get_user("admin").hash == "abc123"
    assert r.get_user("nope") is None


def test_set_users_replaces_previous():
    r = Registry()
    r.set_users([User(id="a", hash="h1")])
    r.set_users([User(id="b", hash="h2")])
    assert r.get_user("a") is None
    assert r.get_user("b") is not None


def test_all_users_sorted():
    r = Registry()
    r.set_users([User(id="zoe", hash="h"), User(id="alex", hash="h")])
    assert [u.id for u in r.all_users()] == ["alex", "zoe"]


# ---------- Экспорт ----------

def test_export_devices_omits_entity_id():
    r = Registry()
    r.register("light.salon", "light", "Люстра", area="salon")
    exported = r.export_devices()
    assert len(exported) == 1
    assert "entity_id" not in exported[0]
    assert exported[0]["id"] >= 0
    assert exported[0]["n"] == "Люстра"
    assert exported[0]["t"] == DEV_LIGHT
    assert exported[0]["a"] == "salon"


def test_export_devices_includes_unit_only_for_sensor():
    r = Registry()
    r.register("light.x", "light", "Light", unit=None)
    r.register("sensor.temp", "sensor", "Temp", unit="°C")
    exported = {item["t"]: item for item in r.export_devices()}
    assert "u" not in exported[DEV_LIGHT]
    assert exported[DEV_SENSOR]["u"] == "°C"


def test_export_areas_format():
    r = Registry()
    r.set_areas([Area(id="salon", n="Гостиная")])
    assert r.export_areas() == [{"id": "salon", "n": "Гостиная"}]


def test_export_users_format():
    r = Registry()
    r.set_users([User(id="admin", hash="sha256hex")])
    assert r.export_users() == [{"id": "admin", "hash": "sha256hex"}]


# ---------- Хеши секций (SB-035) ----------

def test_section_hashes_keys():
    """compute_section_hashes возвращает ровно 3 секции: u, a, d (без m)."""
    r = Registry()
    hashes = r.compute_section_hashes()
    assert set(hashes.keys()) == {SEC_USERS, SEC_AREAS, SEC_DEVICES}


def test_section_hashes_length():
    """Каждый хеш — 4 hex знака."""
    r = Registry()
    r.register("light.x", "light", "X")
    hashes = r.compute_section_hashes()
    for code, h in hashes.items():
        assert len(h) == SECTION_HASH_LENGTH, f"{code}: {h}"
        assert all(c in "0123456789abcdef" for c in h), f"{code}: {h}"


def test_section_hashes_deterministic():
    r = Registry()
    r.register("light.a", "light", "A")
    r.set_areas([Area(id="z", n="Z")])
    r.set_users([User(id="u", hash="h")])
    h1 = r.compute_section_hashes()
    h2 = r.compute_section_hashes()
    assert h1 == h2


def test_section_hashes_independent_of_order():
    r1 = Registry()
    r1.register("light.a", "light", "A")
    r1.register("switch.b", "switch", "B")

    r2 = Registry()
    r2.register("switch.b", "switch", "B")
    r2.register("light.a", "light", "A")

    assert r1.compute_section_hashes() == r2.compute_section_hashes()


def test_section_hashes_devices_changes_when_device_added():
    r = Registry()
    r.register("light.a", "light", "A")
    h_d_before = r.compute_section_hashes()[SEC_DEVICES]
    r.register("switch.b", "switch", "B")
    h_d_after = r.compute_section_hashes()[SEC_DEVICES]
    assert h_d_before != h_d_after


def test_section_hashes_devices_changes_when_name_changes():
    r = Registry()
    r.register("light.a", "light", "Старое")
    h1 = r.compute_section_hashes()[SEC_DEVICES]
    r.register("light.a", "light", "Новое")
    h2 = r.compute_section_hashes()[SEC_DEVICES]
    assert h1 != h2


def test_section_hashes_users_changes_when_user_added():
    r = Registry()
    r.register("light.x", "light", "X")
    h_before = r.compute_section_hashes()
    r.set_users([User(id="u", hash="h")])
    h_after = r.compute_section_hashes()
    assert h_before[SEC_DEVICES] == h_after[SEC_DEVICES]
    assert h_before[SEC_USERS] != h_after[SEC_USERS]
    assert h_before[SEC_AREAS] == h_after[SEC_AREAS]


def test_section_hashes_users_changes_when_hash_changes():
    r = Registry()
    r.set_users([User(id="admin", hash="old")])
    h1 = r.compute_section_hashes()[SEC_USERS]
    r.set_users([User(id="admin", hash="new")])
    h2 = r.compute_section_hashes()[SEC_USERS]
    assert h1 != h2


def test_section_hashes_areas_isolated_from_others():
    """Изменение areas меняет только areas-хеш, не трогает d и u."""
    r = Registry()
    r.register("light.x", "light", "X")
    r.set_users([User(id="u", hash="h")])
    h_before = r.compute_section_hashes()
    r.set_areas([Area(id="z", n="Z")])
    h_after = r.compute_section_hashes()
    assert h_before[SEC_AREAS] != h_after[SEC_AREAS]
    assert h_before[SEC_DEVICES] == h_after[SEC_DEVICES]
    assert h_before[SEC_USERS] == h_after[SEC_USERS]


def test_section_hashes_unaffected_by_entity_id():
    """Изменения entity_id не должны просачиваться в хеши, т.к. в экспорте entity_id нет."""
    r = Registry()
    r.register("light.a", "light", "A")
    exported = r.export_devices()
    for item in exported:
        assert "entity_id" not in item


def test_hash_meta_staticmethod():
    """Registry.hash_meta — staticmethod, считает хеш переданного dict."""
    meta1 = {"n": "Дом", "gw": "!abc", "upd": 15}
    meta2 = {"upd": 15, "n": "Дом", "gw": "!abc"}
    h1 = Registry.hash_meta(meta1)
    h2 = Registry.hash_meta(meta2)
    assert h1 == h2
    assert len(h1) == SECTION_HASH_LENGTH


def test_hash_meta_changes_with_content():
    meta1 = {"n": "Дом", "upd": 15}
    meta2 = {"n": "Дом", "upd": 30}
    assert Registry.hash_meta(meta1) != Registry.hash_meta(meta2)


# ---------- Save / Load ----------

def test_save_and_load_roundtrip(tmp_path):
    r1 = Registry()
    sid = r1.register("light.salon", "light", "Люстра", area="salon")
    r1.set_areas([Area(id="salon", n="Гостиная")])
    r1.set_users([User(id="admin", hash="abc")])

    path = tmp_path / "registry.json"
    r1.save(path)

    r2 = Registry()
    r2.load(path)

    assert len(r2) == 1
    assert r2.get_by_short_id(sid).entity_id == "light.salon"
    assert r2.get_area("salon").n == "Гостиная"
    assert r2.get_user("admin").hash == "abc"
    assert r1.compute_section_hashes() == r2.compute_section_hashes()


def test_load_missing_file_is_noop(tmp_path):
    r = Registry()
    r.load(tmp_path / "nope.json")
    assert len(r) == 0


def test_load_clears_existing(tmp_path):
    r1 = Registry()
    r1.register("light.a", "light", "A")
    r1.set_areas([Area(id="z1", n="Z1")])
    r1.set_users([User(id="u1", hash="h1")])
    path = tmp_path / "reg.json"
    r1.save(path)

    r2 = Registry()
    r2.register("switch.b", "switch", "B")
    r2.set_areas([Area(id="z2", n="Z2")])
    r2.set_users([User(id="u2", hash="h2")])
    r2.load(path)

    assert "light.a" in r2
    assert "switch.b" not in r2
    assert r2.get_area("z1") is not None
    assert r2.get_area("z2") is None
    assert r2.get_user("u1") is not None
    assert r2.get_user("u2") is None


def test_short_id_stays_after_persistence(tmp_path):
    r1 = Registry()
    sid = r1.register("light.special", "light", "X")
    path = tmp_path / "reg.json"
    r1.save(path)

    r2 = Registry()
    r2.load(path)
    assert r2.get_by_entity_id("light.special").short_id == sid


# ---------- short_id корректность ----------

def test_short_id_in_range():
    r = Registry()
    sid = r.register("light.salon", "light", "X")
    assert 0 <= sid <= SHORT_ID_MAX


def test_compute_short_id_deterministic():
    assert _compute_short_id("light.salon") == _compute_short_id("light.salon")


def test_compute_short_id_changes_with_salt():
    assert _compute_short_id("light.salon", salt=0) != _compute_short_id("light.salon", salt=1)
