"""Юнит-тесты для codec.py."""

from __future__ import annotations

import time

import msgpack
import pytest

from rover.codec import (
    FRAGMENT_TIMEOUT_SEC,
    MAX_PACKET_SIZE,
    TP_FRAGMENT,
    FragmentBuffer,
    decode,
    encode,
    fragment,
)


# ---------- Round-trip для разных типов пакетов ----------

def test_roundtrip_cmd():
    msg = {"tp": 5, "id": 12345, "cmid": 1, "s": 1, "ts": 1700000000}
    assert decode(encode(msg)) == msg


def test_roundtrip_status():
    msg = {"tp": 2, "id": 12345, "s": 1, "bri": 200, "ct": 350}
    assert decode(encode(msg)) == msg


def test_roundtrip_push():
    msg = {"tp": 3, "id": 999, "s": 0}
    assert decode(encode(msg)) == msg


def test_roundtrip_ping():
    msg = {"tp": 6, "ts": 1700000000}
    assert decode(encode(msg)) == msg


def test_roundtrip_config_meta():
    msg = {
        "tp": 4, "s": "meta", "n": "Мой дом", "gw": "!077ccb09",
        "ch": "LongFast", "key": "AQ==", "upd": 15, "rty": 5,
        "psh": 1, "hop": 0, "cfgh": "3d9f21ac",
    }
    assert decode(encode(msg)) == msg


def test_roundtrip_double_field():
    """Поле th — Double (целевая температура)."""
    msg = {"tp": 5, "id": 12345, "th": 22.5}
    assert decode(encode(msg)) == msg


# ---------- Числовые типы Int / Long ----------

def test_decode_accepts_small_int():
    """Маленькое число — Int в MessagePack."""
    raw = msgpack.packb({"tp": 5, "id": 100}, use_bin_type=True)
    result = decode(raw)
    assert result["id"] == 100


def test_decode_accepts_large_long():
    """Большое число (Unix timestamp) — Long в MessagePack."""
    raw = msgpack.packb({"tp": 6, "ts": 4_000_000_000}, use_bin_type=True)
    result = decode(raw)
    assert result["ts"] == 4_000_000_000


def test_decode_accepts_short_id_max():
    """short_id может быть до 65535 — на границе uint16."""
    raw = msgpack.packb({"tp": 3, "id": 65535}, use_bin_type=True)
    assert decode(raw)["id"] == 65535


# ---------- Фрагментация ----------

def test_small_message_not_fragmented():
    """Маленькое сообщение возвращается одним пакетом без конверта."""
    msg = {"tp": 5, "id": 12345, "s": 1}
    packets = fragment(msg)
    assert len(packets) == 1
    decoded = decode(packets[0])
    assert decoded == msg
    assert decoded.get("tp") == 5  # не обёрнуто в tp=7


def test_large_message_fragmented():
    """Большое сообщение режется на несколько tp=7 пакетов."""
    big_msg = {
        "tp": 4, "s": "dev", "pg": 1, "pgt": 1,
        "d": [
            {"id": i, "n": f"Устройство номер {i} с длинным именем", "t": "L", "a": "zone1"}
            for i in range(50)
        ],
    }
    packets = fragment(big_msg)
    assert len(packets) > 1
    for pkt in packets:
        assert len(pkt) <= MAX_PACKET_SIZE
        decoded = decode(pkt)
        assert decoded["tp"] == TP_FRAGMENT
        assert "fid" in decoded
        assert "fi" in decoded
        assert "fn" in decoded
        assert "d" in decoded


def test_fragment_assembly():
    """Большое сообщение, разрезанное на фрагменты, собирается обратно идентично."""
    original = {
        "tp": 4, "s": "dev", "pg": 1, "pgt": 1,
        "d": [
            {"id": i, "n": f"Device {i}", "t": "SW", "a": "kitchen"}
            for i in range(30)
        ],
    }
    packets = fragment(original)
    assert len(packets) > 1

    buf = FragmentBuffer()
    result = None
    for raw in packets:
        decoded = decode(raw)
        result = buf.feed(decoded)
    assert result == original
    assert buf.pending_count() == 0


def test_fragment_assembly_out_of_order():
    """Фрагменты пришли в обратном порядке — должны собраться корректно."""
    original = {
        "tp": 4, "s": "ar", "pg": 1, "pgt": 1,
        "d": [{"id": i, "n": f"Zone {i}"} for i in range(20)],
    }
    packets = fragment(original)
    assert len(packets) > 1

    buf = FragmentBuffer()
    result = None
    for raw in reversed(packets):
        decoded = decode(raw)
        result = buf.feed(decoded)
    assert result == original


def test_fragment_buffer_ignores_non_fragment():
    """feed() с не-фрагментом возвращает None и ничего не ломает."""
    buf = FragmentBuffer()
    assert buf.feed({"tp": 5, "id": 1}) is None
    assert buf.pending_count() == 0


def test_fragment_buffer_partial_not_assembled():
    """Если пришла только часть фрагментов — результата нет, буфер хранит."""
    original = {"tp": 4, "s": "dev", "d": [{"id": i, "n": "x" * 100} for i in range(10)]}
    packets = fragment(original)
    assert len(packets) >= 2

    buf = FragmentBuffer()
    first = decode(packets[0])
    assert buf.feed(first) is None
    assert buf.pending_count() == 1


def test_fragment_buffer_cleanup_by_timeout():
    """Старые буферы удаляются по таймауту."""
    original = {"tp": 4, "d": [{"id": i, "n": "x" * 100} for i in range(10)]}
    packets = fragment(original)
    buf = FragmentBuffer(timeout=10.0)
    buf.feed(decode(packets[0]))
    assert buf.pending_count() == 1

    future = time.monotonic() + 20.0
    removed = buf.cleanup(now=future)
    assert removed == 1
    assert buf.pending_count() == 0


def test_fragment_buffer_cleanup_keeps_fresh():
    """Свежие буферы не удаляются."""
    original = {"tp": 4, "d": [{"id": i, "n": "x" * 100} for i in range(10)]}
    packets = fragment(original)
    buf = FragmentBuffer(timeout=60.0)
    buf.feed(decode(packets[0]))
    removed = buf.cleanup()
    assert removed == 0
    assert buf.pending_count() == 1


# ---------- Совместимость с MessagePack-вариантами ----------

def test_decode_str_field():
    """Строковые поля декодируются как str, не bytes."""
    msg = {"tp": 5, "md": "cool", "fn": "auto"}
    decoded = decode(encode(msg))
    assert isinstance(decoded["md"], str)
    assert decoded["md"] == "cool"


def test_fragment_d_is_bytes():
    """Поле d в фрагменте — bytes."""
    original = {"tp": 4, "d": [{"id": i, "n": "x" * 100} for i in range(10)]}
    packets = fragment(original)
    decoded = decode(packets[0])
    assert decoded["tp"] == TP_FRAGMENT
    assert isinstance(decoded["d"], bytes)
