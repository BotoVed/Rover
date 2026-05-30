"""DeviceRegistry — реестр устройств с короткими 2-байтовыми ID.

Хранит маппинг short_id ↔ entity_id, типы устройств, имена и зоны.
Назначенный short_id за устройством закреплён навсегда.

Расчёт cfgh — детерминированный MD5[:8] от JSON-сериализации текущего состава.

Поддерживает сохранение и загрузку из JSON-файла для персистентности
между перезапусками HA.

См. SPEC.md §5, §8.3 и DECISIONS.md SB-012.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rover.const import HA_DOMAIN_TO_DEV_TYPE, SHORT_ID_MAX


@dataclass
class Device:
    """Запись об одном устройстве в реестре."""
    short_id: int          # 0..65535
    entity_id: str         # HA entity_id, например "light.salon_main"
    t: str                 # код типа Rover (L, SW, C, ...)
    n: str                 # friendly name
    a: str | None = None   # area ID (или None)
    u: str | None = None   # unit_of_measurement для сенсоров (или None)


def _compute_short_id(entity_id: str, salt: int = 0) -> int:
    """Хеш entity_id в 16-битный Int.

    salt позволяет получить другое значение при коллизии (см. _next_short_id).
    """
    key = entity_id if salt == 0 else f"{entity_id}#{salt}"
    digest = hashlib.md5(key.encode("utf-8")).digest()
    # Первые 2 байта в big-endian
    return (digest[0] << 8) | digest[1]


class DeviceRegistry:
    """Реестр устройств Rover.

    register() возвращает short_id (новый или уже существующий, если устройство
    зарегистрировано ранее).

    compute_cfgh() — детерминированный хеш состава для сравнения с фронтом.
    """

    def __init__(self) -> None:
        self._by_short_id: dict[int, Device] = {}
        self._by_entity_id: dict[str, Device] = {}

    # ---------- регистрация ----------

    def register(
        self,
        entity_id: str,
        domain: str,
        name: str,
        area: str | None = None,
        unit: str | None = None,
    ) -> int:
        """Зарегистрировать устройство или вернуть его short_id, если уже есть.

        Если entity_id уже зарегистрирован — обновляем поля name/area/unit
        (могли измениться), но short_id и тип не трогаем.
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
        """Найти свободный short_id для нового entity_id.

        При коллизии — инкрементировать соль до уникальности. После SHORT_ID_MAX
        итераций — бросить (реестр переполнен, что нереально на практике).
        """
        for salt in range(SHORT_ID_MAX + 1):
            sid = _compute_short_id(entity_id, salt=salt)
            if sid not in self._by_short_id:
                return sid
        raise RuntimeError("DeviceRegistry full: no free short_id")

    # ---------- доступ ----------

    def get_by_short_id(self, short_id: int) -> Device | None:
        return self._by_short_id.get(short_id)

    def get_by_entity_id(self, entity_id: str) -> Device | None:
        return self._by_entity_id.get(entity_id)

    def all_devices(self) -> list[Device]:
        """Все устройства, отсортированные по short_id для детерминизма."""
        return sorted(self._by_short_id.values(), key=lambda d: d.short_id)

    def __len__(self) -> int:
        return len(self._by_short_id)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._by_entity_id

    # ---------- cfgh ----------

    def compute_cfgh(
        self,
        areas: list[dict] | None = None,
        users: list[dict] | None = None,
    ) -> str:
        """Хеш текущего состава конфига.

        cfgh = MD5(json.dumps(payload, sort_keys=True))[:8]
        payload — устройства + зоны + пользователи.

        Зоны и пользователи прокидываются извне (DeviceRegistry их не хранит).
        """
        payload = {
            "devices": [asdict(d) for d in self.all_devices()],
            "areas": areas or [],
            "users": users or [],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.md5(raw).hexdigest()[:8]

    # ---------- персистентность ----------

    def save(self, path: Path | str) -> None:
        """Сохранить реестр в JSON-файл."""
        path = Path(path)
        data = {"devices": [asdict(d) for d in self.all_devices()]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path | str) -> None:
        """Загрузить реестр из JSON-файла. Текущее состояние реестра очищается."""
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
