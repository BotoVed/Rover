"""Codec — слой между байтами Meshtastic и dict-сообщениями Rover.

Знает только про сериализацию (MessagePack) и фрагментацию (tp=7).
НЕ знает про очередь, транспорт, Home Assistant.

См. SPEC.md §3, §4, §7.4 и DECISIONS.md SB-004, SB-010, SB-011.
"""

from __future__ import annotations

import time
import random
from dataclasses import dataclass, field

import msgpack

# Константы протокола
TP_FRAGMENT = 7
MAX_PACKET_SIZE = 200          # лимит пакета LoRa, байт
FRAGMENT_OVERHEAD = 28         # запас на конверт {tp, fid, fi, fn, d, ...}
FRAGMENT_CHUNK_SIZE = MAX_PACKET_SIZE - FRAGMENT_OVERHEAD  # размер куска данных
FRAGMENT_TIMEOUT_SEC = 60      # таймаут сборки фрагментов


def encode(msg: dict) -> bytes:
    """Сериализовать dict в MessagePack-байты.

    use_bin_type=True — строки идут как str, bytes как bin.
    """
    return msgpack.packb(msg, use_bin_type=True)


def decode(data: bytes) -> dict:
    """Десериализовать MessagePack-байты в dict.

    raw=False — строки декодируются в str (не bytes).
    strict_map_key=False — позволяет числовые ключи в map (на всякий случай).
    Числа возвращаются как int (Python int безразмерный, покрывает и Int, и Long).
    """
    return msgpack.unpackb(data, raw=False, strict_map_key=False)


def fragment(msg: dict, max_size: int = MAX_PACKET_SIZE) -> list[bytes]:
    """Разрезать сообщение на серию пакетов.

    Если сообщение влезает в один пакет — возвращает [encode(msg)].
    Иначе сериализует, режет на куски и заворачивает каждый в конверт tp=7.

    Конверт: {tp:7, fid:int, fi:int, fn:int, d:bytes}
    """
    raw = encode(msg)
    if len(raw) <= max_size:
        return [raw]

    # Уникальный 16-битный fid
    fid = random.randint(1, 0xFFFF)
    chunk_size = max_size - FRAGMENT_OVERHEAD
    chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    fn = len(chunks)

    return [
        encode({"tp": TP_FRAGMENT, "fid": fid, "fi": i, "fn": fn, "d": chunk})
        for i, chunk in enumerate(chunks)
    ]


@dataclass
class _Pending:
    """Частично собранное фрагментированное сообщение."""
    fn: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.monotonic)


class FragmentBuffer:
    """Буфер сборки фрагментов tp=7 на стороне приёмника.

    feed() кладёт фрагмент. Если этим фрагментом сообщение собрано полностью —
    возвращает распарсенный исходный dict. Иначе None.

    cleanup() удаляет буферы старше FRAGMENT_TIMEOUT_SEC.
    """

    def __init__(self, timeout: float = FRAGMENT_TIMEOUT_SEC) -> None:
        self._timeout = timeout
        self._pending: dict[int, _Pending] = {}

    def feed(self, fragment_packet: dict) -> dict | None:
        """Принять один распарсенный пакет tp=7.

        Возвращает собранный dict, если сообщение готово, иначе None.
        Пакеты, не являющиеся фрагментами, игнорируются (возврат None).
        """
        if fragment_packet.get("tp") != TP_FRAGMENT:
            return None

        fid = fragment_packet["fid"]
        fi = fragment_packet["fi"]
        fn = fragment_packet["fn"]
        chunk = fragment_packet["d"]

        pending = self._pending.get(fid)
        if pending is None:
            pending = _Pending(fn=fn)
            self._pending[fid] = pending

        pending.chunks[fi] = chunk

        if len(pending.chunks) < pending.fn:
            return None

        # Все фрагменты пришли — склеить по индексу
        raw = b"".join(pending.chunks[i] for i in range(pending.fn))
        del self._pending[fid]
        return decode(raw)

    def cleanup(self, now: float | None = None) -> int:
        """Удалить буферы старше timeout. Возвращает число удалённых."""
        if now is None:
            now = time.monotonic()
        expired = [
            fid for fid, p in self._pending.items()
            if now - p.first_seen > self._timeout
        ]
        for fid in expired:
            del self._pending[fid]
        return len(expired)

    def pending_count(self) -> int:
        """Сколько частично собранных сообщений сейчас в буфере."""
        return len(self._pending)
