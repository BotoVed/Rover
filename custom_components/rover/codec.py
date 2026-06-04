"""Codec for Rover protocol — msgpack encode/decode."""
from __future__ import annotations

import msgpack


def encode(fields: dict) -> bytes:
    return msgpack.packb(fields, use_bin_type=True)


def decode(data: bytes) -> dict:
    return msgpack.unpackb(data, raw=False)
