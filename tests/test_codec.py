"""Tests for codec.py."""
import pytest
from custom_components.rover.codec import encode, decode


def test_roundtrip():
    """Test encode/decode roundtrip."""
    original = {"tp": 5, "id": 1, "s": True, "b": 75}
    assert decode(encode(original)) == original


def test_various_types():
    """Test codec with various types."""
    data = {
        "int": 42,
        "str": "hello",
        "bool": True,
        "none": None,
        "list": [1, 2, 3],
        "dict": {"nested": "value"},
    }
    assert decode(encode(data)) == data
