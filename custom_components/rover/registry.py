"""Registry for Rover integration."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_TCP_PORT,
    LOGGER_REG,
    MAX_PENDING_REMOTES,
    ROLE_OWNER,
    ROLE_REGULAR,
    SHORT_ID_MAX,
    SHORT_ID_MIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    TYPE_DEFS,
)


class RoverRegistry:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}
        self._on_changed_cb: Callable[[str], None] | None = None
        self._logger = logging.getLogger(LOGGER_REG)

    @staticmethod
    def _compute_hash(data: Any) -> str:
        canonical = json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.md5(canonical.encode("utf-8")).hexdigest()[:4]

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if loaded is None:
            self._data = {
                "meta": {
                    "server_name": "Rover Hub",
                    "version": "0.3.0",
                    "tcp_port": DEFAULT_TCP_PORT,
                    "local_ip": "",
                    "ssid": "",
                },
                "users": [],
                "areas": [],
                "devices": [],
                "pending": [],
                "_next_short_id": 1,
                "_next_area_id": 1,
                "_hash_m": "0000",
                "_hash_u": "0000",
                "_hash_a": "0000",
                "_hash_d": "0000",
            }
        else:
            self._data = loaded
        self._recalc_hashes()
        self._logger.info(
            "Registry loaded: %d devices, %d users, %d areas",
            len(self._data["devices"]),
            len(self._data["users"]),
            len(self._data["areas"]),
        )

    async def async_save(self) -> None:
        await self._store.async_save(self._data)
        self._logger.debug("Registry saved")

    def _recalc_hashes(self) -> None:
        self._data["_hash_m"] = self._compute_hash(self._data["meta"])
        self._data["_hash_u"] = self._compute_hash(
            {"users": self._data["users"], "pending": self._data["pending"]}
        )
        self._data["_hash_a"] = self._compute_hash(self._data["areas"])
        self._data["_hash_d"] = self._compute_hash(self._data["devices"])

    def _on_changed(self, section: str) -> None:
        if self._on_changed_cb:
            self._on_changed_cb(section)

    def set_on_changed(self, callback: Callable[[str], None] | None) -> None:
        self._on_changed_cb = callback

    async def add_device(
        self,
        entity_id: str,
        name: str,
        type_code: str,
        area_id: int | None = None,
    ) -> int:
        if type_code not in TYPE_DEFS:
            raise ValueError(f"Invalid type code: {type_code}")
        for d in self._data["devices"]:
            if d["entity_id"] == entity_id:
                raise ValueError(f"Device {entity_id} already exists")
        if self._data["_next_short_id"] <= SHORT_ID_MAX:
            short_id = self._data["_next_short_id"]
            self._data["_next_short_id"] += 1
        else:
            used = {d["short_id"] for d in self._data["devices"]}
            for sid in range(SHORT_ID_MIN, SHORT_ID_MAX + 1):
                if sid not in used:
                    short_id = sid
                    break
            else:
                raise ValueError("short_id overflow")
        old_hash = self._data["_hash_d"]
        self._data["devices"].append(
            {
                "entity_id": entity_id,
                "short_id": short_id,
                "name": name,
                "type": type_code,
                "area_id": area_id,
                "enabled": True,
            }
        )
        self._recalc_hashes()
        new_hash = self._data["_hash_d"]
        self._logger.info(
            "MUTATION add_device id=%s type=%s: d %s->%s",
            short_id,
            type_code,
            old_hash,
            new_hash,
        )
        self._on_changed("d")
        await self.async_save()
        return short_id

    async def remove_device(self, short_id: int) -> bool:
        for i, d in enumerate(self._data["devices"]):
            if d["short_id"] == short_id:
                old_hash = self._data["_hash_d"]
                self._data["devices"].pop(i)
                self._recalc_hashes()
                new_hash = self._data["_hash_d"]
                self._logger.info(
                    "MUTATION remove_device id=%s: d %s->%s",
                    short_id,
                    old_hash,
                    new_hash,
                )
                self._on_changed("d")
                await self.async_save()
                return True
        return False

    async def update_device(self, short_id: int, **kwargs) -> bool:
        for d in self._data["devices"]:
            if d["short_id"] == short_id:
                old_hash = self._data["_hash_d"]
                for key in ("name", "area_id", "enabled"):
                    if key in kwargs:
                        d[key] = kwargs[key]
                self._recalc_hashes()
                new_hash = self._data["_hash_d"]
                self._logger.info(
                    "MUTATION update_device id=%s: d %s->%s",
                    short_id,
                    old_hash,
                    new_hash,
                )
                self._on_changed("d")
                await self.async_save()
                return True
        return False

    def get_device(self, short_id: int) -> dict | None:
        for d in self._data["devices"]:
            if d["short_id"] == short_id:
                return dict(d)
        return None

    def get_device_by_entity_id(self, entity_id: str) -> dict | None:
        for d in self._data["devices"]:
            if d["entity_id"] == entity_id:
                return dict(d)
        return None

    def all_devices(self) -> list[dict]:
        return list(self._data["devices"])

    async def add_area(self, name: str) -> int:
        area_id = self._data["_next_area_id"]
        self._data["_next_area_id"] += 1
        old_hash = self._data["_hash_a"]
        self._data["areas"].append({"id": area_id, "name": name})
        self._recalc_hashes()
        new_hash = self._data["_hash_a"]
        self._logger.info(
            "MUTATION add_area id=%s: a %s->%s", area_id, old_hash, new_hash
        )
        self._on_changed("a")
        await self.async_save()
        return area_id

    def get_area(self, area_id: int) -> dict | None:
        for a in self._data["areas"]:
            if a["id"] == area_id:
                return dict(a)
        return None

    def all_areas(self) -> list[dict]:
        return list(self._data["areas"])

    async def add_pending(
        self,
        identity_hash: str,
        name: str,
        requested_at: float | None = None,
    ) -> bool:
        if requested_at is None:
            requested_at = time.time()
        if len(self._data["pending"]) >= MAX_PENDING_REMOTES:
            self._logger.warning("pending queue full")
            return False
        for u in self._data["users"]:
            if u["hash"] == identity_hash:
                return False
        for p in self._data["pending"]:
            if p["hash"] == identity_hash:
                return False
        old_hash = self._data["_hash_u"]
        self._data["pending"].append(
            {
                "hash": identity_hash,
                "name": name,
                "requested_at": requested_at,
            }
        )
        self._recalc_hashes()
        new_hash = self._data["_hash_u"]
        self._logger.info(
            "MUTATION add_pending hash=%s: u %s->%s",
            identity_hash[:8],
            old_hash,
            new_hash,
        )
        self._on_changed("u")
        await self.async_save()
        return True

    async def approve_pending(
        self, identity_hash: str, role: str = ROLE_REGULAR
    ) -> bool:
        pending_item = None
        for p in self._data["pending"]:
            if p["hash"] == identity_hash:
                pending_item = p
                break
        if pending_item is None:
            return False
        old_hash = self._data["_hash_u"]
        self._data["pending"].remove(pending_item)
        if len(self._data["users"]) == 0:
            role = ROLE_OWNER
        self._data["users"].append(
            {
                "hash": identity_hash,
                "name": pending_item["name"],
                "role": role,
            }
        )
        self._recalc_hashes()
        new_hash = self._data["_hash_u"]
        self._logger.info(
            "MUTATION approve hash=%s role=%s: u %s->%s",
            identity_hash[:8],
            role,
            old_hash,
            new_hash,
        )
        self._on_changed("u")
        await self.async_save()
        return True

    async def revoke_user(self, identity_hash: str) -> bool:
        for i, u in enumerate(self._data["users"]):
            if u["hash"] == identity_hash:
                old_hash = self._data["_hash_u"]
                self._data["users"].pop(i)
                self._recalc_hashes()
                new_hash = self._data["_hash_u"]
                self._logger.info(
                    "MUTATION revoke hash=%s: u %s->%s",
                    identity_hash[:8],
                    old_hash,
                    new_hash,
                )
                self._on_changed("u")
                await self.async_save()
                return True
        return False

    def get_user(self, identity_hash: str) -> dict | None:
        for u in self._data["users"]:
            if u["hash"] == identity_hash:
                return dict(u)
        return None

    def is_approved(self, identity_hash: str) -> bool:
        return any(u["hash"] == identity_hash for u in self._data["users"])

    def all_users(self) -> list[dict]:
        return list(self._data["users"])

    def all_pending(self) -> list[dict]:
        return list(self._data["pending"])

    async def set_server_name(self, name: str) -> None:
        old_hash = self._data["_hash_m"]
        self._data["meta"]["server_name"] = name
        self._recalc_hashes()
        new_hash = self._data["_hash_m"]
        self._logger.info(
            "MUTATION set_server_name: m %s->%s", old_hash, new_hash
        )
        self._on_changed("m")
        await self.async_save()

    async def set_tcp_port(self, port: int) -> None:
        old_hash = self._data["_hash_m"]
        self._data["meta"]["tcp_port"] = port
        self._recalc_hashes()
        new_hash = self._data["_hash_m"]
        self._logger.info(
            "MUTATION set_tcp_port %s: m %s->%s", port, old_hash, new_hash
        )
        self._on_changed("m")
        await self.async_save()

    async def set_local_ip(self, ip: str) -> None:
        old_hash = self._data["_hash_m"]
        self._data["meta"]["local_ip"] = ip
        self._recalc_hashes()
        new_hash = self._data["_hash_m"]
        self._logger.info(
            "MUTATION set_local_ip %s: m %s->%s", ip, old_hash, new_hash
        )
        self._on_changed("m")
        await self.async_save()

    async def set_ssid(self, ssid: str) -> None:
        old_hash = self._data["_hash_m"]
        self._data["meta"]["ssid"] = ssid
        self._recalc_hashes()
        new_hash = self._data["_hash_m"]
        self._logger.info(
            "MUTATION set_ssid: m %s->%s", old_hash, new_hash
        )
        self._on_changed("m")
        await self.async_save()

    def get_meta(self) -> dict:
        return dict(self._data["meta"])

    def get_hashes(self) -> dict[str, str]:
        return {
            "m": self._data["_hash_m"],
            "u": self._data["_hash_u"],
            "a": self._data["_hash_a"],
            "d": self._data["_hash_d"],
        }
