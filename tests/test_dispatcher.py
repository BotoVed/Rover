from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rover.dispatcher import Dispatcher

pytestmark = pytest.mark.asyncio


@pytest.fixture
def handlers():
    h = MagicMock()
    h.on_command = AsyncMock()
    h.on_req_all = AsyncMock()
    h.on_req_one = AsyncMock()
    h.on_ping = AsyncMock()
    h.on_req_config = AsyncMock()
    return h


@pytest.fixture
def dispatcher(handlers):
    return Dispatcher(handlers)


@pytest.fixture
def mock_decode():
    with patch("rover.dispatcher.decode") as m:
        yield m


class TestDispatch:
    async def test_tp_cmd_with_id_calls_on_command(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 5, "id": 1, "s": 1}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_command.assert_awaited_once_with({"tp": 5, "id": 1, "s": 1}, 42)
        handlers.on_ping.assert_not_called()
        handlers.on_req_config.assert_not_called()

    async def test_tp_cmd_with_req_all_calls_on_req_all(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 5, "req": "all"}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_req_all.assert_awaited_once_with(42)

    async def test_tp_cmd_with_req_list_calls_on_req_one(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 5, "req": [1, 2]}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_req_one.assert_awaited_once_with(
            {"tp": 5, "req": [1, 2]}, 42
        )

    async def test_tp_ping_calls_on_ping(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 6, "ts": 1000}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_ping.assert_awaited_once_with({"tp": 6, "ts": 1000}, 42)

    async def test_tp_req_calls_on_req_config(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 8, "s": "d"}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_req_config.assert_awaited_once_with({"tp": 8, "s": "d"}, 42)

    async def test_duplicate_cmid_is_ignored(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 5, "id": 1, "cmid": "abc"}

        await dispatcher.dispatch(b"payload", 42)
        await dispatcher.dispatch(b"payload", 42)

        handlers.on_command.assert_awaited_once()

    async def test_tp_2_does_not_call_handlers(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 2}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_command.assert_not_called()
        handlers.on_ping.assert_not_called()
        handlers.on_req_config.assert_not_called()
        handlers.on_req_all.assert_not_called()
        handlers.on_req_one.assert_not_called()

    async def test_tp_3_does_not_call_handlers(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 3}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_command.assert_not_called()
        handlers.on_ping.assert_not_called()
        handlers.on_req_config.assert_not_called()

    async def test_tp_4_does_not_call_handlers(
        self, dispatcher, handlers, mock_decode
    ):
        mock_decode.return_value = {"tp": 4}

        await dispatcher.dispatch(b"payload", 42)

        handlers.on_command.assert_not_called()
        handlers.on_ping.assert_not_called()
        handlers.on_req_config.assert_not_called()
