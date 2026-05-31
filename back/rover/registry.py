"""Registry — единый реестр конфигурации Rover.

Хранит на бэке:
- устройства (полная запись с entity_id),
- зоны (areas),
- пользователей (users) с хешами паролей.

Отдаёт на фронт только экспортируемые виды.

Считает хеши секций (devices/users/areas) для сравнения с фронтом.
Хеш секции meta считается выше Registry — на уровне RoverRuntimeData,
потому что данные meta приходят из config_entry.

См. SPEC.md §5, §8 и DECISIONS.md SB-012, SB-035, SB-037, SB-032.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from rover.const import (
    DEV_SENSOR,
    HA_DOMAIN_TO_DEV_TYPE,
    SEC_AREAS,
    SEC_DEVICES,
    SEC_USERS,
    SECTION_HASH_LENGTH,
    SHORT_ID_MAX,
)


@dataclass
class Device:
    """Запись об одном устройстве (полная, как хранит бэк)."""
    short_id: int
    entity_id: str
    t: str
    n: str
    a: str | None = None
    u: str | None = None


@dataclass
class Area:
    """Запись о зоне."""
    id: str
    n: str


@dataclass
class User:
    """Запись о пользователе."""
    id: str
    hash: str


def _compute_short_id(entity_id: str, salt: int = 0) -> int:
    """Хеш entity_id в 16-битный Int."""
    key = entity_id if salt == 0 else f"{entity_id}#{salt}"
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return (digest[0] << 8) | digest[1]


def _hash_section(payload: list | dict) -> str:
    """Хеш одной секции конфига — MD5[:SECTION_HASH_LENGTH] от sort_keys JSON.

    Длина 4 hex знака (см. SB-035) — задача хеша только сигнализация
    изменений, не уникальность ключей.
    """
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:SECTION_HASH_LENGTH]


class Registry:
    """Единый реестр Rover: устройства + зоны + пользователи."""

    def __init__(self) -> None:
        self._by_short_id: dict[int, Device] = {}
        self._by_entity_id: dict[str, Device] = {}
        self._areas: dict[str, Area] = {}
        self._users: dict[str, User] = {}

    # ---------- Регистрация устройств ----------

    def register(
        self,
        entity_id: str,
        domain: str,
        name: str,
        area: str | None = None,
        unit: str | None = None,
    ) -> int:
        """Зарегистрировать устройство или вернуть его short_id."""
        existing = self._by_entity_id.get(entity_id)
        if existing is not None:
            existing.n = name
            existing.a = area
            existing.u = unit
            return existing.short_id

        if domain not in HA_DOMAIN_TO_DEV_TYPE:
            raise ValueError(f"Unsupported HA domain: {domain}")

        sid = self._next_short_id(entity_id)
        device = Device(
            short_id=sid,
            entity_id=entity_id,
            t=HA_DOMAIN_TO_DEV_TYPE[domain],
            n=name,
            a=area,
            u=unit,
        )
        self._by_short_id[sid] = device
        self._by_entity_id[entity_id] = device
        return sid

    def _next_short_id(self, entity_id: str) -> int:
        for salt in range(SHORT_ID_MAX + 1):
            sid = _compute_short_id(entity_id, salt=salt)
            if sid not in self._by_short_id:
                return sid
        raise RuntimeError("Registry full: no free short_id")

    # ---------- Доступ к устройствам ----------

    def get_by_short_id(self, short_id: int) -> Device | None:
        return self._by_short_id.get(short_id)

    def get_by_entity_id(self, entity_id: str) -> Device | None:
        return self._by_entity_id.get(entity_id)

    def all_devices(self) -> list[Device]:
        return sorted(self._by_short_id.values(), key=lambda d: d.short_id)

    def __len__(self) -> int:
        return len(self._by_short_id)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._by_entity_id

    # ---------- Зоны ----------

    def set_areas(self, areas: list[Area]) -> None:
        self._areas = {a.id: a for a in areas}

    def get_area(self, area_id: str) -> Area | None:
        return self._areas.get(area_id)

    def all_areas(self) -> list[Area]:
        return sorted(self._areas.values(), key=lambda a: a.id)

    # ---------- Пользователи ----------

    def set_users(self, users: list[User]) -> None:
        self._users = {u.id: u for u in users}

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def all_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.id)

    # ---------- Экспорт ----------

    def export_devices(self) -> list[dict]:
        """Устройства в виде, отправляемом на фронт. Без entity_id.

        unit включается только для DEV_SENSOR (см. SPEC §5.4).
        """
        result = []
        for d in self.all_devices():
            item: dict = {"id": d.short_id, "n": d.n, "t": d.t, "a": d.a}
            if d.t == DEV_SENSOR and d.u is not None:
                item["u"] = d.u
            result.append(item)
        return result

    def export_areas(self) -> list[dict]:
        return [{"id": a.id, "n": a.n} for a in self.all_areas()]

    def export_users(self) -> list[dict]:
        return [{"id": u.id, "hash": u.hash} for u in self.all_users()]

    # ---------- Хеши секций (SB-035) ----------

    def compute_section_hashes(self) -> dict[str, str]:
        """Хеши секций, которыми владеет Registry: u, a, d.

        Секция m (meta) считается выше — её данные приходят из config_entry,
        а не из Registry.

        Возвращает мапу {section_code: hash4hex}.
        """
        return {
            SEC_USERS: _hash_section(self.export_users()),
            SEC_AREAS: _hash_section(self.export_areas()),
            SEC_DEVICES: _hash_section(self.export_devices()),
        }

    @staticmethod
    def hash_meta(meta: dict) -> str:
        """Хеш секции meta. Принимает уже готовый dict секции.

        Вынесен в staticmethod, потому что Registry не хранит meta —
        она формируется на уровне RoverRuntimeData из config_entry.
        """
        return _hash_section(meta)

    # ---------- Удаление устройств ----------

    def remove_device(self, short_id: int) -> bool:
        """Удалить устройство по short_id.

        Возвращает True, если устройство было удалено.
        short_id после удаления может быть выдан повторно (SB-043: забываем).
        """
        device = self._by_short_id.pop(short_id, None)
        if device is None:
            return False
        self._by_entity_id.pop(device.entity_id, None)
        return True

    def remove_device_by_entity_id(self, entity_id: str) -> bool:
        """Удалить устройство по entity_id."""
        device = self._by_entity_id.get(entity_id)
        if device is None:
            return False
        return self.remove_device(device.short_id)

    # ---------- Управление пользователями ----------

    def add_user_with_password(self, user_id: str, password: str, salt: str) -> None:
        """Добавить или обновить пользователя.

        Пароль хешируется SHA-256 с общей солью (SB-042).
        """
        hashed = self._hash_password(password, salt)
        self._users[user_id] = User(id=user_id, hash=hashed)

    def remove_user(self, user_id: str) -> bool:
        """Удалить пользователя. Возвращает True, если был удалён."""
        return self._users.pop(user_id, None) is not None

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """SHA-256 от password + salt в hex."""
        return hashlib.sha256(f"{password}{salt}".encode("utf-8")).hexdigest()

    # ---------- Персистентность ----------

    def save(self, path: Path | str) -> None:
        path = Path(path)
        data = {
            "devices": [asdict(d) for d in self.all_devices()],
            "areas": [asdict(a) for a in self.all_areas()],
            "users": [asdict(u) for u in self.all_users()],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path | str) -> None:
        path = Path(path)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))

        self._by_short_id.clear()
        self._by_entity_id.clear()
        for d in data.get("devices", []):
            device = Device(
                short_id=d["short_id"],
                entity_id=d["entity_id"],
                t=d["t"],
                n=d["n"],
                a=d.get("a"),
                u=d.get("u"),
            )
            self._by_short_id[device.short_id] = device
            self._by_entity_id[device.entity_id] = device

        self._areas = {a["id"]: Area(id=a["id"], n=a["n"]) for a in data.get("areas", [])}
        self._users = {u["id"]: User(id=u["id"], hash=u["hash"]) for u in data.get("users", [])}
