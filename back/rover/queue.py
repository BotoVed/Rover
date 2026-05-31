"""Queue — очередь исходящих с ACK-механизмом и дедуп входящих.

OutQueue хранит элементы в трёх фазах:
- active        — готов к отправке (next_send_time определяет момент)
- awaiting_ack  — отправлен, ждёт ACK от Meshtastic
- suspended     — все retries исчерпаны, ждёт пробуждения

ACK с известным packet_id → удаление элемента.
NAK или истечение ack_timeout → retry или suspended.
Пробуждение всех suspended → при PING от фронта или ACK на любой пакет.

InDedup — окно дедупликации входящих по уникальному ID (15 минут).

Batcher — собирает пачку до MAX_PACKET_SIZE из active-элементов.
Фрагментирует крупные сообщения через codec.fragment().

См. SPEC.md §7 и DECISIONS.md SB-008, SB-009, SB-010, SB-013, SB-027, SB-040.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Hashable, Literal

from rover.codec import MAX_PACKET_SIZE, encode, fragment
from rover.const import (
    DEFAULT_ACK_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_PERIOD,
)

DEDUP_WINDOW_SEC = 15 * 60   # 15 минут

Phase = Literal["active", "awaiting_ack", "suspended"]


@dataclass
class QueueItem:
    """Элемент исходящей очереди."""
    key: Hashable
    msg: dict
    phase: Phase
    next_send_time: float
    retries_left: int
    max_retries: int            # запоминаем для пробуждения из suspended
    packet_id: int | None = None
    sent_at: float | None = None


class OutQueue:
    """Исходящая очередь с тремя фазами элементов.

    Все методы — синхронные и принимают `now` явно (для тестов).
    Внешний код вызывает методы по таймерам и колбекам транспорта.
    """

    def __init__(self) -> None:
        self._items: dict[Hashable, QueueItem] = {}

    # ---------- Базовые операции ----------

    def put(
        self,
        key: Hashable,
        msg: dict,
        max_retries: int = DEFAULT_MAX_RETRIES,
        now: float | None = None,
    ) -> None:
        """Положить сообщение в очередь.

        Если запись с таким key уже есть (в любой фазе) — затирается.
        Новый элемент стартует в фазе active с next_send_time = now.
        """
        if now is None:
            now = time.monotonic()
        self._items[key] = QueueItem(
            key=key,
            msg=msg,
            phase="active",
            next_send_time=now,
            retries_left=max_retries,
            max_retries=max_retries,
        )

    def get(self, key: Hashable) -> QueueItem | None:
        return self._items.get(key)

    def remove(self, key: Hashable) -> bool:
        return self._items.pop(key, None) is not None

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._items

    def all_items(self) -> list[QueueItem]:
        """Все элементы во всех фазах, отсортированные по next_send_time."""
        return sorted(self._items.values(), key=lambda i: i.next_send_time)

    # ---------- Доступ по фазам ----------

    def active_items(self) -> list[QueueItem]:
        return [i for i in self._items.values() if i.phase == "active"]

    def awaiting_ack_items(self) -> list[QueueItem]:
        return [i for i in self._items.values() if i.phase == "awaiting_ack"]

    def suspended_items(self) -> list[QueueItem]:
        return [i for i in self._items.values() if i.phase == "suspended"]

    def ready_items(self, now: float | None = None) -> list[QueueItem]:
        """Active-элементы, готовые к отправке (next_send_time <= now)."""
        if now is None:
            now = time.monotonic()
        return sorted(
            (i for i in self._items.values()
             if i.phase == "active" and i.next_send_time <= now),
            key=lambda i: i.next_send_time,
        )

    # ---------- Переходы между фазами ----------

    def mark_sent(self, key: Hashable, packet_id: int, now: float | None = None) -> None:
        """Перевести элемент в awaiting_ack после отправки в радио.

        retries_left уменьшается на 1.
        """
        if now is None:
            now = time.monotonic()
        item = self._items.get(key)
        if item is None or item.phase != "active":
            return
        item.phase = "awaiting_ack"
        item.packet_id = packet_id
        item.sent_at = now
        item.retries_left -= 1

    def on_ack(self, packet_id: int) -> Hashable | None:
        """ACK по packet_id → удалить элемент.

        Возвращает key удалённого элемента (или None, если не найден —
        например, ACK на затёртый элемент: молчаливо игнорируется).
        """
        for key, item in list(self._items.items()):
            if item.phase == "awaiting_ack" and item.packet_id == packet_id:
                del self._items[key]
                return key
        return None

    def on_nak(
        self,
        packet_id: int,
        period: float = DEFAULT_QUEUE_PERIOD,
        now: float | None = None,
    ) -> Hashable | None:
        """NAK по packet_id → retry или suspended.

        Возвращает key обработанного элемента (или None, если не найден).
        """
        if now is None:
            now = time.monotonic()
        for key, item in self._items.items():
            if item.phase == "awaiting_ack" and item.packet_id == packet_id:
                self._retry_or_suspend(item, period, now)
                return key
        return None

    def check_ack_timeouts(
        self,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
        period: float = DEFAULT_QUEUE_PERIOD,
        now: float | None = None,
    ) -> list[Hashable]:
        """Найти awaiting_ack элементы с истёкшим таймаутом → retry или suspended.

        Возвращает список keys обработанных элементов.
        """
        if now is None:
            now = time.monotonic()
        processed: list[Hashable] = []
        for item in list(self._items.values()):
            if (
                item.phase == "awaiting_ack"
                and item.sent_at is not None
                and (now - item.sent_at) > ack_timeout
            ):
                self._retry_or_suspend(item, period, now)
                processed.append(item.key)
        return processed

    def _retry_or_suspend(self, item: QueueItem, period: float, now: float) -> None:
        """Внутреннее: NAK/timeout → active с увеличенным временем или suspended."""
        item.packet_id = None
        item.sent_at = None
        if item.retries_left > 0:
            item.phase = "active"
            item.next_send_time = now + period
        else:
            item.phase = "suspended"
            item.next_send_time = float("inf")  # никогда не попадёт в ready_items

    def wake_suspended(self, now: float | None = None) -> list[Hashable]:
        """Перевести все suspended в active с полным запасом retries.

        Вызывается при признаке онлайна фронта: PING или ACK на любой пакет.
        Возвращает список keys пробуждённых элементов.
        """
        if now is None:
            now = time.monotonic()
        woken: list[Hashable] = []
        for item in self._items.values():
            if item.phase == "suspended":
                item.phase = "active"
                item.next_send_time = now
                item.retries_left = item.max_retries
                item.packet_id = None
                item.sent_at = None
                woken.append(item.key)
        return woken


class InDedup:
    """Дедуп входящих сообщений по уникальному ID.

    seen(id) возвращает True, если ID уже видели в окне DEDUP_WINDOW_SEC.
    Повторное обращение освежает timestamp.
    """

    def __init__(self, window: float = DEDUP_WINDOW_SEC) -> None:
        self._window = window
        self._seen: dict[Hashable, float] = {}

    def seen(self, msg_id: Hashable, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        last_seen = self._seen.get(msg_id)
        if last_seen is not None and (now - last_seen) <= self._window:
            self._seen[msg_id] = now
            return True
        self._seen[msg_id] = now
        return False

    def cleanup(self, now: float | None = None) -> int:
        if now is None:
            now = time.monotonic()
        expired = [k for k, ts in self._seen.items() if (now - ts) > self._window]
        for k in expired:
            del self._seen[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._seen)


@dataclass
class Batch:
    """Результат формирования пачки.

    packets — список байтовых пакетов, готовых к отправке.
    sent_keys — ключи элементов, которые были упакованы.
                Внешний код после реальной отправки должен вызвать
                queue.mark_sent(key, packet_id, now) для каждого.
    """
    packets: list[bytes] = field(default_factory=list)
    sent_keys: list[Hashable] = field(default_factory=list)


class Batcher:
    """Формирователь пачки из active-элементов очереди.

    Использует SB-027: фрагментация только в пустой пачке.
    """

    def __init__(self, max_size: int = MAX_PACKET_SIZE) -> None:
        self._max_size = max_size

    def build_batch(self, queue: OutQueue, now: float | None = None) -> Batch:
        ready = queue.ready_items(now=now)
        batch = Batch()
        current_packet = b""

        for item in ready:
            raw = encode(item.msg)
            size = len(raw)

            if not batch.packets and not current_packet and size > self._max_size:
                fragments = fragment(item.msg, max_size=self._max_size)
                batch.packets.extend(fragments)
                batch.sent_keys.append(item.key)
                return batch

            if len(current_packet) + size <= self._max_size:
                current_packet += raw
                batch.sent_keys.append(item.key)
            # не влезает — пропускаем, элемент остаётся в очереди

        if current_packet:
            batch.packets.append(current_packet)

        return batch
