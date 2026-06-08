"""Tests for rns_transport.py — wire format normalization."""
from custom_components.rover.rns_transport import _to_wire


def test_to_wire_pong():
    result = _to_wire({"tp": 2, "h": {"m": "ab12"}})
    assert result == {0: 2, 2: {"m": "ab12"}}


def test_to_wire_config():
    result = _to_wire({"tp": 4, "section": "m", "h": "abcd", "data": {"k": "v"}})
    assert result == {0: 4, 1: "m", 2: "abcd", 3: {"k": "v"}}


def test_to_wire_status():
    result = _to_wire({"tp": 2, "s": [{"id": 1, "v": "on"}]})
    assert result == {0: 2, 2: [{0: 1, 1: "on"}]}


def test_to_wire_unknown_key_passthrough():
    result = _to_wire({"tp": 3, "id": 1, "v": "on"})
    assert result == {0: 3, "id": 1, "v": "on"}


def test_to_wire_nested_config_devices():
    result = _to_wire({"tp": 4, "section": "d", "h": "abcd", "data": [{"id": 1, "n": "Lamp", "dt": "SW", "a": 1}]})
    assert result == {0: 4, 1: "d", 2: "abcd", 3: [{0: 1, 1: "Lamp", 2: "SW", 3: 1}]}


def test_to_wire_nested_meta():
    result = _to_wire({"tp": 4, "section": "m", "h": "abcd", "data": {"server_name": "Hub", "version": "0.5"}})
    assert result == {0: 4, 1: "m", 2: "abcd", 3: {2: "Hub", 1: "0.5"}}


def test_to_wire_empty():
    assert _to_wire({}) == {}
