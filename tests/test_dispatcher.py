"""Tests for dispatcher.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.rover.dispatcher import RoverDispatcher
from custom_components.rover.const import TP_CMD, TP_PING_PONG, TP_REQ, TP_REGISTER


@pytest.fixture
def handlers():
    h = MagicMock()
    h.handle_cmd = AsyncMock()
    h.handle_ping = AsyncMock()
    h.handle_req = AsyncMock()
    h.handle_register = AsyncMock()
    return h


@pytest.fixture
def dispatcher(handlers):
    return RoverDispatcher(handlers)


@pytest.mark.asyncio
async def test_dispatch_cmd(dispatcher, handlers):
    src = b"\xaa" * 16
    fields = {"tp": TP_CMD, "id": 1, "s": True}
    await dispatcher.dispatch(src, fields)
    handlers.handle_cmd.assert_awaited_once_with(src, fields)


@pytest.mark.asyncio
async def test_dispatch_ping(dispatcher, handlers):
    await dispatcher.dispatch(b"\xbb" * 16, {"tp": TP_PING_PONG, "h": {}})
    handlers.handle_ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_req(dispatcher, handlers):
    await dispatcher.dispatch(b"\xcc" * 16, {"tp": TP_REQ, "section": "d"})
    handlers.handle_req.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_register(dispatcher, handlers):
    await dispatcher.dispatch(b"\xdd" * 16, {"tp": TP_REGISTER, "name": "X"})
    handlers.handle_register.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_unsupported_tp(dispatcher, handlers):
    await dispatcher.dispatch(b"\xee" * 16, {"tp": 3, "id": 1, "v": "on"})
    handlers.handle_cmd.assert_not_awaited()
    handlers.handle_ping.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_missing_tp(dispatcher, handlers):
    await dispatcher.dispatch(b"\xff" * 16, {"id": 1})
    handlers.handle_cmd.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_not_dict(dispatcher, handlers):
    await dispatcher.dispatch(b"\x00" * 16, "not a dict")
    handlers.handle_cmd.assert_not_awaited()
