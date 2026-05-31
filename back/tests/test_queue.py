"""Юнит-тесты для queue.py с ACK-механизмом."""

from __future__ import annotations

from rover.codec import MAX_PACKET_SIZE, decode
from rover.queue import Batcher, InDedup, OutQueue


# =====================================================================
# OutQueue — базовое поведение
# =====================================================================

def test_put_creates_active_item():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1}, max_retries=5, now=100.0)
    item = q.get(1)
    assert item is not None
    assert item.phase == "active"
    assert item.retries_left == 5
    assert item.max_retries == 5
    assert item.next_send_time == 100.0
    assert item.packet_id is None
    assert item.sent_at is None


def test_put_overwrites_in_any_phase():
    """Новый put затирает элемент независимо от его фазы."""
    q = OutQueue()
    # active
    q.put(key=1, msg={"a": 1}, max_retries=5, now=100.0)
    q.put(key=1, msg={"a": 2}, max_retries=5, now=200.0)
    assert q.get(1).msg == {"a": 2}
    assert q.get(1).next_send_time == 200.0

    # awaiting_ack
    q.mark_sent(1, packet_id=999, now=200.0)
    assert q.get(1).phase == "awaiting_ack"
    q.put(key=1, msg={"a": 3}, max_retries=5, now=300.0)
    assert q.get(1).phase == "active"
    assert q.get(1).msg == {"a": 3}
    assert q.get(1).retries_left == 5

    # suspended
    q2 = OutQueue()
    q2.put(key="k", msg={"x": 1}, max_retries=1, now=0.0)
    q2.mark_sent("k", packet_id=1, now=0.0)
    q2.on_nak(1, period=15.0, now=1.0)
    assert q2.get("k").phase == "suspended"
    q2.put(key="k", msg={"x": 2}, max_retries=3, now=100.0)
    assert q2.get("k").phase == "active"
    assert q2.get("k").retries_left == 3


def test_remove_and_contains():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5}, max_retries=5, now=0.0)
    assert 1 in q
    assert q.remove(1) is True
    assert 1 not in q
    assert q.remove(1) is False


def test_len():
    q = OutQueue()
    assert len(q) == 0
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.put(key=2, msg={}, max_retries=5, now=0.0)
    assert len(q) == 2


# =====================================================================
# Фазы и переходы
# =====================================================================

def test_active_items_filter():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.put(key=2, msg={}, max_retries=5, now=0.0)
    q.mark_sent(2, packet_id=10, now=0.0)
    assert {i.key for i in q.active_items()} == {1}
    assert {i.key for i in q.awaiting_ack_items()} == {2}


def test_ready_items_filter():
    q = OutQueue()
    q.put(key="a", msg={}, max_retries=5, now=50.0)
    q.put(key="b", msg={}, max_retries=5, now=200.0)
    keys = [i.key for i in q.ready_items(now=100.0)]
    assert keys == ["a"]


def test_ready_items_excludes_awaiting_ack():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.mark_sent(1, packet_id=10, now=0.0)
    assert q.ready_items(now=100.0) == []


def test_ready_items_excludes_suspended():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=1, now=0.0)
    q.mark_sent(1, packet_id=10, now=0.0)
    q.on_nak(10, period=15.0, now=1.0)
    assert q.ready_items(now=1000.0) == []


# =====================================================================
# mark_sent
# =====================================================================

def test_mark_sent_transitions_to_awaiting_ack():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=100.0)
    q.mark_sent(1, packet_id=42, now=100.0)
    item = q.get(1)
    assert item.phase == "awaiting_ack"
    assert item.packet_id == 42
    assert item.sent_at == 100.0
    assert item.retries_left == 4


def test_mark_sent_ignores_non_active():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.mark_sent(1, packet_id=10, now=0.0)
    q.mark_sent(1, packet_id=20, now=1.0)
    assert q.get(1).packet_id == 10


def test_mark_sent_unknown_key_is_noop():
    q = OutQueue()
    q.mark_sent("unknown", packet_id=1, now=0.0)


# =====================================================================
# on_ack
# =====================================================================

def test_on_ack_removes_item():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.mark_sent(1, packet_id=42, now=0.0)
    removed_key = q.on_ack(42)
    assert removed_key == 1
    assert 1 not in q


def test_on_ack_unknown_packet_id_returns_none():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=5, now=0.0)
    q.mark_sent(1, packet_id=42, now=0.0)
    assert q.on_ack(999) is None
    assert q.get(1) is not None


def test_on_ack_for_overwritten_item_is_noop():
    q = OutQueue()
    q.put(key=1, msg={"v": 1}, max_retries=5, now=0.0)
    q.mark_sent(1, packet_id=42, now=0.0)
    q.put(key=1, msg={"v": 2}, max_retries=5, now=100.0)
    result = q.on_ack(42)
    assert result is None
    assert q.get(1).msg == {"v": 2}
    assert q.get(1).phase == "active"


# =====================================================================
# on_nak
# =====================================================================

def test_on_nak_retries_when_retries_left():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=3, now=100.0)
    q.mark_sent(1, packet_id=42, now=100.0)
    q.on_nak(42, period=15.0, now=105.0)
    item = q.get(1)
    assert item.phase == "active"
    assert item.next_send_time == 105.0 + 15.0
    assert item.packet_id is None
    assert item.sent_at is None
    assert item.retries_left == 2


def test_on_nak_suspends_when_retries_exhausted():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=1, now=100.0)
    q.mark_sent(1, packet_id=42, now=100.0)
    q.on_nak(42, period=15.0, now=105.0)
    item = q.get(1)
    assert item.phase == "suspended"


def test_on_nak_unknown_packet_id_returns_none():
    q = OutQueue()
    assert q.on_nak(999, period=15.0, now=0.0) is None


# =====================================================================
# check_ack_timeouts
# =====================================================================

def test_ack_timeout_triggers_retry():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=3, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    assert q.check_ack_timeouts(ack_timeout=10.0, period=15.0, now=105.0) == []
    processed = q.check_ack_timeouts(ack_timeout=10.0, period=15.0, now=115.0)
    assert processed == [1]
    assert q.get(1).phase == "active"
    assert q.get(1).next_send_time == 115.0 + 15.0


def test_ack_timeout_suspends_when_retries_exhausted():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=1, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    q.check_ack_timeouts(ack_timeout=10.0, period=15.0, now=115.0)
    assert q.get(1).phase == "suspended"


def test_ack_timeout_processes_multiple_items():
    q = OutQueue()
    q.put(key="a", msg={}, max_retries=3, now=100.0)
    q.put(key="b", msg={}, max_retries=3, now=100.0)
    q.mark_sent("a", packet_id=1, now=100.0)
    q.mark_sent("b", packet_id=2, now=100.0)
    processed = q.check_ack_timeouts(ack_timeout=10.0, period=15.0, now=115.0)
    assert set(processed) == {"a", "b"}


def test_ack_timeout_ignores_active_and_suspended():
    q = OutQueue()
    q.put(key="a", msg={}, max_retries=5, now=0.0)
    q.put(key="b", msg={}, max_retries=1, now=0.0)
    q.mark_sent("b", packet_id=10, now=0.0)
    q.on_nak(10, period=15.0, now=1.0)
    processed = q.check_ack_timeouts(ack_timeout=10.0, period=15.0, now=1000.0)
    assert processed == []


# =====================================================================
# wake_suspended
# =====================================================================

def test_wake_suspended_transitions_to_active():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=1, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    q.on_nak(10, period=15.0, now=105.0)
    assert q.get(1).phase == "suspended"
    woken = q.wake_suspended(now=500.0)
    assert woken == [1]
    item = q.get(1)
    assert item.phase == "active"
    assert item.next_send_time == 500.0
    assert item.retries_left == 1
    assert item.packet_id is None
    assert item.sent_at is None


def test_wake_suspended_ignores_active_and_awaiting():
    q = OutQueue()
    q.put(key="a", msg={}, max_retries=5, now=0.0)
    q.put(key="b", msg={}, max_retries=5, now=0.0)
    q.mark_sent("b", packet_id=10, now=0.0)
    woken = q.wake_suspended(now=100.0)
    assert woken == []
    assert q.get("a").phase == "active"
    assert q.get("b").phase == "awaiting_ack"


def test_wake_suspended_wakes_multiple():
    q = OutQueue()
    for k in ["a", "b", "c"]:
        q.put(key=k, msg={}, max_retries=1, now=0.0)
        q.mark_sent(k, packet_id=hash(k), now=0.0)
        q.on_nak(hash(k), period=15.0, now=1.0)
    assert all(q.get(k).phase == "suspended" for k in ["a", "b", "c"])
    woken = q.wake_suspended(now=100.0)
    assert set(woken) == {"a", "b", "c"}
    assert all(q.get(k).phase == "active" for k in ["a", "b", "c"])
    assert all(q.get(k).retries_left == 1 for k in ["a", "b", "c"])


def test_wake_suspended_uses_remembered_max_retries():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=7, now=0.0)
    q.mark_sent(1, packet_id=10, now=0.0)
    for i in range(7):
        q.check_ack_timeouts(ack_timeout=1.0, period=2.0, now=2.0 + i * 4.0)
        item = q.get(1)
        if item.phase != "suspended":
            q.mark_sent(1, packet_id=10 + i + 1, now=item.next_send_time)
    assert q.get(1).phase == "suspended"
    q.wake_suspended(now=1000.0)
    assert q.get(1).retries_left == 7


# =====================================================================
# Полный сценарий
# =====================================================================

def test_full_lifecycle_ack():
    q = OutQueue()
    q.put(key=1, msg={"v": 1}, max_retries=5, now=100.0)
    q.mark_sent(1, packet_id=42, now=101.0)
    assert q.on_ack(42) == 1
    assert 1 not in q


def test_full_lifecycle_nak_retry_ack():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=3, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    q.on_nak(10, period=15.0, now=105.0)
    assert q.get(1).phase == "active"
    q.mark_sent(1, packet_id=20, now=115.0)
    assert q.get(1).retries_left == 1
    q.on_ack(20)
    assert 1 not in q


def test_full_lifecycle_exhaust_to_suspended_then_wake():
    q = OutQueue()
    q.put(key=1, msg={}, max_retries=2, now=0.0)
    q.mark_sent(1, packet_id=1, now=0.0)
    q.on_nak(1, period=15.0, now=1.0)
    q.mark_sent(1, packet_id=2, now=15.0)
    q.on_nak(2, period=15.0, now=16.0)
    assert q.get(1).phase == "suspended"
    q.wake_suspended(now=100.0)
    assert q.get(1).phase == "active"
    assert q.get(1).retries_left == 2
    q.mark_sent(1, packet_id=99, now=101.0)
    q.on_ack(99)
    assert 1 not in q


# =====================================================================
# InDedup
# =====================================================================

def test_dedup_first_seen_false():
    d = InDedup()
    assert d.seen("msg-1", now=100.0) is False


def test_dedup_second_seen_true():
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
    assert d.cleanup(now=800.0) == 2
    assert len(d) == 1
    assert d.seen("c", now=800.0) is True


def test_dedup_repeat_refreshes_timestamp():
    d = InDedup(window=600.0)
    d.seen("a", now=100.0)
    assert d.seen("a", now=500.0) is True
    assert d.seen("a", now=900.0) is True
    assert d.seen("a", now=1600.0) is False


# =====================================================================
# Batcher
# =====================================================================

def test_batcher_empty_queue():
    assert Batcher().build_batch(OutQueue(), now=100.0).packets == []


def test_batcher_single_small():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1}, max_retries=5, now=100.0)
    batch = Batcher().build_batch(q, now=100.0)
    assert len(batch.packets) == 1
    assert batch.sent_keys == [1]


def test_batcher_combines_small():
    q = OutQueue()
    for i in range(5):
        q.put(key=i, msg={"tp": 5, "id": i}, max_retries=5, now=100.0)
    batch = Batcher().build_batch(q, now=100.0)
    assert len(batch.packets) == 1
    assert len(batch.sent_keys) == 5
    assert len(batch.packets[0]) <= MAX_PACKET_SIZE


def test_batcher_skips_oversized_when_batch_not_empty():
    q = OutQueue()
    q.put(key="small", msg={"tp": 5, "id": 1}, max_retries=5, now=50.0)
    big = {"tp": 4, "s": "d", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, max_retries=5, now=100.0)
    batch = Batcher().build_batch(q, now=200.0)
    assert "small" in batch.sent_keys
    assert "big" not in batch.sent_keys


def test_batcher_fragments_oversized_when_batch_empty():
    q = OutQueue()
    big = {"tp": 4, "s": "d", "d": [{"id": i, "n": "x" * 50} for i in range(20)]}
    q.put(key="big", msg=big, max_retries=5, now=100.0)
    batch = Batcher().build_batch(q, now=200.0)
    assert batch.sent_keys == ["big"]
    assert len(batch.packets) > 1
    for pkt in batch.packets:
        assert len(pkt) <= MAX_PACKET_SIZE
        assert decode(pkt)["tp"] == 7


def test_batcher_excludes_awaiting_ack():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1}, max_retries=5, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    batch = Batcher().build_batch(q, now=200.0)
    assert batch.packets == []
    assert batch.sent_keys == []


def test_batcher_excludes_suspended():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5, "id": 1}, max_retries=1, now=100.0)
    q.mark_sent(1, packet_id=10, now=100.0)
    q.on_nak(10, period=15.0, now=101.0)
    batch = Batcher().build_batch(q, now=1000.0)
    assert batch.packets == []


def test_batcher_ignores_future_active():
    q = OutQueue()
    q.put(key=1, msg={"tp": 5}, max_retries=5, now=500.0)
    batch = Batcher().build_batch(q, now=100.0)
    assert batch.packets == []
