"""Юнит-тесты для queue.py."""

from __future__ import annotations

import pytest

from rover.codec import MAX_PACKET_SIZE, decode
from rover.queue import Batcher, InDedup, OutQueue


# ---------- OutQueue: базовое поведение ----------

def test_put_and_get():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1}, retries=5, period=15.0, now=100.0)
    item = q.get(1)
    assert item is not None
    assert item.msg == {"tp": 5, "id": 1}
    assert item.retries_left == 5
    assert item.next_send_time == 100.0  # первая отправка немедленно


def test_put_overwrites_same_key():
    """Новая запись с тем же key полностью затирает старую, счётчик сбрасывается."""
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1, "s": 0}, retries=5, period=15.0, now=100.0)
    q.mark_sent(1, period=15.0, now=100.0)
    assert q.get(1).retries_left == 4

    q.put(key=1, msg={"tp": 5, "id": 1, "s": 1}, retries=5, period=15.0, now=200.0)
    item = q.get(1)
    assert item.msg["s"] == 1
    assert item.retries_left == 5
    assert item.next_send_time == 200.0


def test_remove():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5}, retries=5, period=15.0, now=0.0)
    assert q.remove(1) is True
    assert 1 not in q
    assert q.remove(1) is False


def test_len_and_contains():
    q = OutQueue()
    assert len(q) == 0
    q.put(key=1, msg={"tp": 5}, retries=5, period=15.0, now=0.0)
    q.put(key=2, msg={"tp": 5}, retries=5, period=15.0, now=0.0)
    assert len(q) == 2
    assert 1 in q
    assert 3 not in q


# ---------- OutQueue: сортировка и mark_sent ----------

def test_sorted_by_next_send_time():
    q = OutQueue()
    q.put(key="a", msg={"tp": 5}, retries=5, period=15.0, now=100.0)
    q.put(key="b", msg={"tp": 5}, retries=5, period=15.0, now=50.0)
    q.put(key="c", msg={"tp": 5}, retries=5, period=15.0, now=200.0)

    sorted_keys = [i.key for i in q.sorted_items()]
    assert sorted_keys == ["b", "a", "c"]


def test_ready_items_filters_by_time():
    q = OutQueue()
    q.put(key="a", msg={"tp": 5}, retries=5, period=15.0, now=100.0)
    q.mark_sent("a", period=15.0, now=100.0)

    assert q.ready_items(now=110.0) == []
    ready = q.ready_items(now=120.0)
    assert len(ready) == 1
    assert ready[0].key == "a"


def test_mark_sent_updates_time_and_retries():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5}, retries=3, period=15.0, now=100.0)
    q.mark_sent(1, period=15.0, now=100.0)

    item = q.get(1)
    assert item.retries_left == 2
    assert item.next_send_time == 115.0


def test_mark_sent_removes_when_retries_exhausted():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5}, retries=2, period=15.0, now=100.0)
    q.mark_sent(1, period=15.0, now=100.0)
    assert q.get(1).retries_left == 1

    q.mark_sent(1, period=15.0, now=115.0)
    assert q.get(1) is None


def test_mark_sent_after_remove_is_noop():
    q = OutQueue()
    q.mark_sent("nope", period=15.0, now=0.0)


# ---------- InDedup ----------

def test_dedup_first_seen_is_false():
    d = InDedup()
    assert d.seen("msg-1", now=100.0) is False


def test_dedup_second_seen_is_true():
    d = InDedup()
    d.seen("msg-1", now=100.0)
    assert d.seen("msg-1", now=200.0) is True


def test_dedup_expires_after_window():
    d = InDedup(window=600.0)
    d.seen("msg-1", now=100.0)
    assert d.seen("msg-1", now=800.0) is False


def test_dedup_cleanup():
    d = InDedup(window=600.0)
    d.seen("a", now=100.0)
    d.seen("b", now=100.0)
    d.seen("c", now=500.0)
    removed = d.cleanup(now=800.0)
    assert removed == 2
    assert len(d) == 1
    assert d.seen("c", now=800.0) is True


def test_dedup_repeat_refreshes_timestamp():
    """Повторное обращение к тому же ID освежает его окно."""
    d = InDedup(window=600.0)
    d.seen("a", now=100.0)
    assert d.seen("a", now=500.0) is True
    assert d.seen("a", now=900.0) is True
    assert d.seen("a", now=1600.0) is False  # 900+600=1500 < 1600


# ---------- Batcher ----------

def test_batcher_empty_queue():
    q = OutQueue()
    batch = Batcher().build_batch(q, now=100.0)
    assert batch.packets == []
    assert batch.sent_keys == []


def test_batcher_single_small_message():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1, "s": 1}, retries=5, period=15.0, now=100.0)
    batch = Batcher().build_batch(q, now=100.0)
    assert len(batch.packets) == 1
    assert batch.sent_keys == [1]


def test_batcher_combines_small_messages():
    """Несколько мелких сообщений склеиваются в один пакет."""
    q = OutQueue()
    for i in range(5):
        q.put(key=i, msg={"tp": 5, "id": i, "s": i % 2}, retries=5, period=15.0, now=100.0)
    batch = Batcher().build_batch(q, now=100.0)
    assert len(batch.packets) == 1
    assert len(batch.sent_keys) == 5
    assert len(batch.packets[0]) <= MAX_PACKET_SIZE


def test_batcher_skips_oversized_when_batch_not_empty():
    """SB-027: большое сообщение пропускается, если пачка уже не пуста."""
    q = OutQueue()
    q.put(key="small", msg={"tp": 5, "id": 1}, retries=5, period=15.0, now=50.0)
    big = {"tp": 4, "s": "dev", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, retries=5, period=15.0, now=100.0)

    batch = Batcher().build_batch(q, now=200.0)
    assert "small" in batch.sent_keys
    assert "big" not in batch.sent_keys


def test_batcher_fragments_oversized_when_batch_empty():
    """SB-027: большое сообщение в пустой пачке — фрагментируется, пачка закрывается."""
    q = OutQueue()
    big = {"tp": 4, "s": "dev", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, retries=5, period=15.0, now=100.0)

    batch = Batcher().build_batch(q, now=200.0)
    assert batch.sent_keys == ["big"]
    assert len(batch.packets) > 1

    for pkt in batch.packets:
        assert len(pkt) <= MAX_PACKET_SIZE
        decoded = decode(pkt)
        assert decoded["tp"] == 7


def test_batcher_does_not_take_after_fragmentation():
    """После фрагментации больше ничего в пачку не добавляется."""
    q = OutQueue()
    big = {"tp": 4, "s": "dev", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, retries=5, period=15.0, now=100.0)
    q.put(key="small", msg={"tp": 5, "id": 1}, retries=5, period=15.0, now=150.0)

    batch = Batcher().build_batch(q, now=200.0)
    assert batch.sent_keys == ["big"]


def test_batcher_takes_next_small_after_skipping_oversized():
    """Если после первого мелкого встретилось большое — пропустим, возьмём следующее мелкое."""
    q = OutQueue()
    q.put(key="a", msg={"tp": 5, "id": 1}, retries=5, period=15.0, now=50.0)
    big = {"tp": 4, "s": "dev", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, retries=5, period=15.0, now=100.0)
    q.put(key="b", msg={"tp": 5, "id": 2}, retries=5, period=15.0, now=150.0)

    batch = Batcher().build_batch(q, now=200.0)
    assert "a" in batch.sent_keys
    assert "b" in batch.sent_keys
    assert "big" not in batch.sent_keys
    assert len(batch.packets) == 1


def test_batcher_ignores_not_ready_items():
    """Элементы с next_send_time > now не попадают в пачку."""
    q = OutQueue()
    q.put(key="ready", msg={"tp": 5, "id": 1}, retries=5, period=15.0, now=50.0)
    q.put(key="future", msg={"tp": 5, "id": 2}, retries=5, period=15.0, now=500.0)

    batch = Batcher().build_batch(q, now=100.0)
    assert batch.sent_keys == ["ready"]
