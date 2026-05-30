"""Queue — очередь исходящих сообщений и дедуп входящих.

OutQueue: сортированная по next_send_time очередь, ключ — произвольный hashable
(обычно short_id устройства). Новая запись по тому же ключу затирает старую.

InDedup: окно дедупликации входящих сообщений по их уникальному ID (cmid/fid/...).
Хранит ID 15 минут с момента последней активности.

Batcher: формирует пачку до MAX_PACKET_SIZE байт из верха OutQueue.
Если первое готовое сообщение не помещается — фрагментирует через codec.fragment().

См. SPEC.md §7 и DECISIONS.md SB-008, SB-009, SB-010, SB-013, SB-027.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Hashable

from rover.codec import MAX_PACKET_SIZE, encode, fragment

DEDUP_WINDOW_SEC = 15 * 60   # 15 минут


@dataclass
class QueueItem:
    """Элемент исходящей очереди."""
    key: Hashable
    msg: dict
    next_send_time: float
    retries_left: int


class OutQueue:
    """Исходящая очередь с перезаписью по ключу и сортировкой по времени.

    Никакого встроенного цикла — внешний код вызывает pop_ready() в нужный момент.
    """

    def __init__(self) -> None:
        self._items: dict[Hashable, QueueItem] = {}

    def put(
        self,
        key: Hashable,
        msg: dict,
        retries: int,
        period: float,
        now: float | None = None,
    ) -> None:
        """Положить сообщение в очередь.

        Если запись с таким key уже есть — затирается полностью, счётчик
        повторов и next_send_time сбрасываются. Первая отправка — немедленно
        (next_send_time = now).
        """
        if now is None:
            now = time.monotonic()
        self._items[key] = QueueItem(
            key=key,
            msg=msg,
            next_send_time=now,
            retries_left=retries,
        )

    def get(self, key: Hashable) -> QueueItem | None:
        """Вернуть элемент по ключу, или None."""
        return self._items.get(key)

    def remove(self, key: Hashable) -> bool:
        """Удалить элемент. Возвращает True, если был удалён."""
        return self._items.pop(key, None) is not None

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._items

    def sorted_items(self) -> list[QueueItem]:
        """Все элементы, отсортированные по next_send_time возрастанию."""
        return sorted(self._items.values(), key=lambda i: i.next_send_time)

    def ready_items(self, now: float | None = None) -> list[QueueItem]:
        """Элементы, готовые к отправке (next_send_time <= now)."""
        if now is None:
            now = time.monotonic()
        return [i for i in self.sorted_items() if i.next_send_time <= now]

    def mark_sent(self, key: Hashable, period: float, now: float | None = None) -> None:
        """Отметить, что элемент отправлен.

        next_send_time = now + period, retries_left уменьшается на 1.
        Если retries_left достиг 0 — элемент удаляется.
        """
        if now is None:
            now = time.monotonic()
        item = self._items.get(key)
        if item is None:
            return
        item.retries_left -= 1
        if item.retries_left <= 0:
            del self._items[key]
        else:
            item.next_send_time = now + period


class InDedup:
    """Дедуп входящих сообщений по их уникальному ID.

    seen(id) возвращает True, если ID уже видели в окне DEDUP_WINDOW_SEC.
    Иначе запоминает ID и возвращает False.

    cleanup() удаляет ID старше окна.
    """

    def __init__(self, window: float = DEDUP_WINDOW_SEC) -> None:
        self._window = window
        self._seen: dict[Hashable, float] = {}

    def seen(self, msg_id: Hashable, now: float | None = None) -> bool:
        """Проверить и одновременно отметить ID.

        Если ID уже зарегистрирован и его запись свежая — True (дубль).
        Иначе — False, ID запоминается с текущим временем.
        """
        if now is None:
            now = time.monotonic()
        last_seen = self._seen.get(msg_id)
        if last_seen is not None and (now - last_seen) <= self._window:
            # Освежим timestamp, чтобы дубли продлевали окно
            self._seen[msg_id] = now
            return True
        self._seen[msg_id] = now
        return False

    def cleanup(self, now: float | None = None) -> int:
        """Удалить ID старше окна. Возвращает число удалённых."""
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
    sent_keys — ключи элементов очереди, которые были упакованы (нужно отметить
                mark_sent после реальной отправки).
    """
    packets: list[bytes] = field(default_factory=list)
    sent_keys: list[Hashable] = field(default_factory=list)


class Batcher:
    """Формирователь пачки из верха OutQueue.

    build_batch() возвращает Batch с готовыми к отправке байтами.
    Не вызывает mark_sent сам — это задача внешнего кода после реальной отправки.
    """

    def __init__(self, max_size: int = MAX_PACKET_SIZE) -> None:
        self._max_size = max_size

    def build_batch(self, queue: OutQueue, now: float | None = None) -> Batch:
        """Сформировать пачку из готовых к отправке элементов очереди.

        Алгоритм (SB-027):
        1. Идём по готовым элементам в порядке next_send_time.
        2. Для каждого считаем размер encode(msg).
        3. Если пачка пуста и сообщение > max_size → fragment() → закрыть пачку.
        4. Если влезает в остаток → добавить.
        5. Не влезает → пропустить, идти дальше.
        """
        ready = queue.ready_items(now=now)
        batch = Batch()
        current_packet = b""

        for item in ready:
            raw = encode(item.msg)
            size = len(raw)

            # Пустая пачка + большое сообщение → фрагментация
            if not batch.packets and not current_packet and size > self._max_size:
                fragments = fragment(item.msg, max_size=self._max_size)
                batch.packets.extend(fragments)
                batch.sent_keys.append(item.key)
                return batch  # пачка закрыта на фрагменте

            # Сообщение влезает в остаток текущего пакета
            if len(current_packet) + size <= self._max_size:
                current_packet += raw
                batch.sent_keys.append(item.key)
            # Не влезает — пропускаем (item остаётся в очереди со своим временем)

        # Зафиксировать текущий пакет, если он не пуст
        if current_packet:
            batch.packets.append(current_packet)

        return batch
