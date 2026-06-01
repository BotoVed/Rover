from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .codec import encode, fragment
from .commands import build_service_calls
from .const import (
    CONF_ACK_TIMEOUT,
    CONF_MAX_RETRIES,
    CONF_QUEUE_PERIOD,
    DEFAULT_ACK_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_PERIOD,
    DEVICES_PER_PAGE,
    HA_SETTLE_DELAY_SEC,
    OFFLINE_THRESHOLD_SEC,
    PONG_QUEUE_KEY,
    SEC_AREAS,
    SEC_DEVICES,
    SEC_META,
    SEC_USERS,
    TP_CONFIG,
    TP_PING,
    TP_PUSH,
    TP_STATUS,
)
from .registry import Registry
from .state_extractor import extract_state

_LOGGER = logging.getLogger(__name__)


class Handlers:
    def __init__(self, registry: Registry, ha_bridge, outbox, config: dict) -> None:
        self._registry = registry
        self._ha = ha_bridge
        self._outbox = outbox
        self._config = config
        self._online_nodes: dict[int, float] = {}
        self._meta_dict: dict = {}
        self._meta_hash: str = ""
        self._last_hashes: dict[str, str] = {}
        self._ha_settle_delay = config.get("ha_settle_delay", HA_SETTLE_DELAY_SEC)
        self._max_retries = config.get(CONF_MAX_RETRIES, DEFAULT_MAX_RETRIES)
        self._queue_period = config.get(CONF_QUEUE_PERIOD, DEFAULT_QUEUE_PERIOD)
        self._ack_timeout = config.get(CONF_ACK_TIMEOUT, DEFAULT_ACK_TIMEOUT)

    def set_meta_dict(self, meta: dict) -> None:
        self._meta_dict = meta
        self._meta_hash = Registry.hash_meta(meta)

    def get_section_hashes(self) -> dict[str, str]:
        hashes = self._registry.compute_section_hashes()
        hashes[SEC_META] = self._meta_hash
        return hashes

    async def on_ping(self, packet: dict, from_node: int) -> None:
        self._online_nodes[from_node] = time.time()
        ts = packet.get("ts", 0)
        hashes = self.get_section_hashes()
        pong = {"tp": TP_PING, "ts": ts, "h": hashes}
        self._outbox.enqueue(PONG_QUEUE_KEY, pong, self._max_retries, self._queue_period)
        self._outbox.wake_suspended(self._max_retries)

    async def on_command(self, packet: dict, from_node: int) -> None:
        short_id = packet.get("id")
        device = self._registry.get_by_short_id(short_id)
        if not device:
            _LOGGER.warning("Unknown device id=%s", short_id)
            return

        service_calls = build_service_calls(device, packet)
        if not service_calls:
            return

        for call in service_calls:
            await self._ha.call_service(call.domain, call.service, call.data)

        await asyncio.sleep(self._ha_settle_delay)

        ha_state = await self._ha.get_state(device.entity_id)
        if ha_state:
            state_dict = extract_state(device, ha_state)
            push = {"tp": TP_PUSH, "id": short_id}
            push.update(state_dict)
            self._outbox.enqueue(short_id, push, self._max_retries, self._queue_period)

    async def on_req_one(self, packet: dict, from_node: int) -> None:
        req_ids = packet.get("req")
        if isinstance(req_ids, (list, tuple)):
            short_ids = req_ids
        else:
            short_ids = [req_ids]
        for sid in short_ids:
            device = self._registry.get_by_short_id(sid)
            if not device:
                continue
            ha_state = await self._ha.get_state(device.entity_id)
            if ha_state:
                state_dict = extract_state(device, ha_state)
                status = {"tp": TP_STATUS, "id": sid}
                status.update(state_dict)
                self._outbox.enqueue(sid, status, self._max_retries, self._queue_period)

    async def on_req_all(self, from_node: int) -> None:
        for device in self._registry.all_devices():
            ha_state = await self._ha.get_state(device.entity_id)
            if ha_state:
                state_dict = extract_state(device, ha_state)
                status = {"tp": TP_STATUS, "id": device.short_id}
                status.update(state_dict)
                self._outbox.enqueue(device.short_id, status, self._max_retries, self._queue_period)

    async def on_req_config(self, packet: dict, from_node: int) -> None:
        section = packet.get("s")
        page = packet.get("pg")

        if section == SEC_META:
            await self._send_meta_section()
        elif section == SEC_USERS:
            users = self._registry.export_users()
            pages = self._paginate(users, 999)
            await self._send_config_pages(section, pages, page)
        elif section == SEC_AREAS:
            areas = self._registry.export_areas()
            pages = self._paginate(areas, 999)
            await self._send_config_pages(section, pages, page)
        elif section == SEC_DEVICES:
            devices = self._registry.export_devices()
            pages = self._paginate(devices, DEVICES_PER_PAGE)
            await self._send_config_pages(section, pages, page)

    async def _send_meta_section(self) -> None:
        meta = self._meta_dict
        config = {"tp": TP_CONFIG, "s": SEC_META, "pg": 1, "pgt": 1, "d": meta}
        self._outbox.enqueue(("config", SEC_META, 1), config, self._max_retries, self._queue_period)

    async def _send_config_pages(self, section: str, pages: list, requested_page: int | None = None) -> None:
        for i, page_data in enumerate(pages):
            pg_num = i + 1
            if requested_page and pg_num != requested_page:
                continue
            config = {"tp": TP_CONFIG, "s": section, "pg": pg_num, "pgt": len(pages), "d": page_data}
            self._outbox.enqueue(("config", section, pg_num), config, self._max_retries, self._queue_period)

    @staticmethod
    def _paginate(items: list, per_page: int) -> list[list]:
        pages = []
        for i in range(0, len(items), per_page):
            pages.append(items[i:i + per_page])
        return pages if pages else [[]]

    async def on_ha_state_changed(self, entity_id: str, ha_state: Any) -> None:
        device = self._registry.get_by_entity_id(entity_id)
        if not device:
            return
        state_dict = extract_state(device, ha_state)
        push = {"tp": TP_PUSH, "id": device.short_id}
        push.update(state_dict)
        self._outbox.enqueue(device.short_id, push, self._max_retries, self._queue_period)

    def on_ha_registry_changed(self) -> None:
        new_hashes = self.get_section_hashes()
        old_hashes = self._last_hashes
        if new_hashes != old_hashes:
            self._last_hashes = new_hashes
            pong = {"tp": TP_PING, "ts": int(time.time()), "h": new_hashes}
            self._outbox.enqueue(PONG_QUEUE_KEY, pong, self._max_retries, self._queue_period)

    def is_anyone_online(self) -> bool:
        threshold = time.time() - OFFLINE_THRESHOLD_SEC
        return any(t > threshold for t in self._online_nodes.values())

    def mark_node_online(self, node_id: int) -> None:
        self._online_nodes[node_id] = time.time()
        self._outbox.wake_suspended(self._max_retries)
