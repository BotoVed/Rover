"""Registry — единый реестр конфигурации Rover.

Хранит на бэке:
- устройства (полная запись с entity_id),
- зоны (areas),
- пользователей (users) с хешами паролей.

Отдаёт на фронт только экспортируемые виды (без entity_id, без unit для не-sensor).
Считает cfgh — хеш экспортируемого конфига для сравнения с фронтом.

Поддерживает сохранение и загрузку из JSON-файла для персистентности
между перезапусками HA.

См. SPEC.md §5, §8.3 и DECISIONS.md SB-012, SB-029, SB-032.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rover.const import DEV_SENSOR, HA_DOMAIN_TO_DEV_TYPE, SHORT_ID_MAX


@dataclass
class Device:
    """Запись об одном устройстве (полная, как хранит бэк)."""
    short_id: int          # 0..65535
    entity_id: str         # HA entity_id, локально на бэке
    t: str                 # код типа Rover (L, SW, C, ...)
    n: str                 # friendly name
    a: str | None = None   # area ID (или None)
    u: str | None = None   # unit_of_measurement для сенсоров (или None)


@dataclass
class Area:
    """Запись о зоне."""
    id: str                # area ID из HA
    n: str                 # отображаемое имя


@dataclass
class User:
    """Запись о пользователе."""
    id: str                # идентификатор пользователя
    hash: str              # SHA-256 пароля с солью (hex)


def _compute_short_id(entity_id: str, salt: int = 0) -> int:
    """Хеш entity_id в 16-битный Int.

    salt позволяет получить другое значение при коллизии.
    """
    key = entity_id if salt == 0 else f"{entity_id}#{salt}"
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return (digest[0] << 8) | digest[1]


class Registry:
    """Единый реестр Rover: устройства + зоны + пользователи.

    Все мутации — через публичные методы. Прямой доступ к внутренним dict'ам
    не предусмотрен (используем геттеры).
    """

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
        """Зарегистрировать устройство или вернуть его short_id, если уже есть.

        При повторной регистрации обновляются name/area/unit, но не short_id
        и не тип.
        """
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
        """Найти свободный short_id для нового entity_id."""
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
        """Все устройства, отсортированные по short_id (детерминированный порядок)."""
        return sorted(self._by_short_id.values(), key=lambda d: d.short_id)

    def __len__(self) -> int:
        return len(self._by_short_id)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._by_entity_id

    # ---------- Зоны ----------

    def set_areas(self, areas: list[Area]) -> None:
        """Полностью переписать список зон."""
        self._areas = {a.id: a for a in areas}

    def get_area(self, area_id: str) -> Area | None:
        return self._areas.get(area_id)

    def all_areas(self) -> list[Area]:
        return sorted(self._areas.values(), key=lambda a: a.id)

    # ---------- Пользователи ----------

    def set_users(self, users: list[User]) -> None:
        """Полностью переписать список пользователей."""
        self._users = {u.id: u for u in users}

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def all_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.id)

    # ---------- Экспортируемые виды (для CONFIG-пакетов и cfgh) ----------

    def export_devices(self) -> list[dict]:
        """Устройства в виде, отправляемом на фронт.

        Без entity_id. unit включается только для сенсоров (DEV_SENSOR).
        """
        result = []
        for d in self.all_devices():
            item: dict = {"id": d.short_id, "n": d.n, "t": d.t, "a": d.a}
            if d.t == DEV_SENSOR and d.u is not None:
                item["u"] = d.u
            result.append(item)
        return result

    def export_areas(self) -> list[dict]:
        """Зоны в виде, отправляемом на фронт."""
        return [{"id": a.id, "n": a.n} for a in self.all_areas()]

    def export_users(self) -> list[dict]:
        """Пользователи в виде, отправляемом на фронт.

        Только id и hash пароля. Открытых паролей нет — их вообще нет на бэке.
        """
        return [{"id": u.id, "hash": u.hash} for u in self.all_users()]

    # ---------- cfgh ----------

    def compute_cfgh(self) -> str:
        """Хеш экспортируемого конфига.

        Считается только по тому, что реально уходит на фронт (см. SB-029).
        Изменения внутреннего entity_id не влияют на cfgh — фронту это знать
        не нужно.
        """
        payload = {
            "devices": self.export_devices(),
            "areas": self.export_areas(),
            "users": self.export_users(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.md5(raw).hexdigest()[:8]

    # ---------- Персистентность ----------

    def save(self, path: Path | str) -> None:
        """Сохранить весь реестр (устройства + зоны + пользователи) в JSON."""
        path = Path(path)
        data = {
            "devices": [asdict(d) for d in self.all_devices()],
            "areas": [asdict(a) for a in self.all_areas()],
            "users": [asdict(u) for u in self.all_users()],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path | str) -> None:
        """Загрузить реестр из JSON. Текущее состояние очищается перед загрузкой."""
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
