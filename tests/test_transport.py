from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import meshtastic.serial_interface
import meshtastic.tcp_interface
import pytest

from rover.transport import Transport

pytestmark = pytest.mark.asyncio


@pytest.fixture
def transport():
    return Transport()


def _make_packet(portnum: int, data: bytes | None = None, from_id: int = 1) -> MagicMock:
    decoded = MagicMock()
    decoded.portnum = portnum
    decoded.data = data
    packet = MagicMock()
    packet.decoded = decoded
    packet.fromId = from_id
    return packet


def _make_routing_packet(request_id: int, error: bool = False) -> MagicMock:
    routing = MagicMock()
    routing.requestId = request_id
    routing.error = "some_error" if error else None
    decoded = MagicMock()
    decoded.portnum = 5  # PortNum.ROUTING_APP
    decoded.routing = routing
    packet = MagicMock()
    packet.decoded = decoded
    packet.fromId = 1
    return packet


class TestConnect:
    @patch("meshtastic.serial_interface.SerialInterface")
    @patch("meshtastic.tcp_interface.TCPInterface")
    async def test_connect_serial(
        self, mock_tcp_iface, mock_serial_iface, transport
    ):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface

        await transport.connect("serial", "/dev/ttyACM0")

        mock_serial_iface.assert_called_once_with("/dev/ttyACM0")
        assert transport._interface is mock_iface
        assert transport._connected is True
        assert transport._connection_type == "serial"
        assert transport._port == "/dev/ttyACM0"

    @patch("meshtastic.serial_interface.SerialInterface")
    @patch("meshtastic.tcp_interface.TCPInterface")
    async def test_connect_tcp(self, mock_tcp_iface, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_tcp_iface.return_value = mock_iface

        await transport.connect("tcp", "192.168.1.1:9500")

        mock_tcp_iface.assert_called_once_with(
            hostname="192.168.1.1:9500"
        )
        assert transport._interface is mock_iface
        assert transport._connected is True

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_connect_failure_starts_reconnect(
        self, mock_serial_iface, transport
    ):
        mock_serial_iface.side_effect = Exception("No device")

        result = await transport._do_connect()

        assert result is False
        assert transport._connected is False
        assert transport._interface is None
        assert transport._reconnect_task is not None
        assert not transport._reconnect_task.done()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_connect_calls_on_reconnect(self, mock_serial_iface, transport):
        on_reconnect = MagicMock()
        transport.set_callbacks(on_reconnect=on_reconnect)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        transport._connection_type = "serial"
        transport._port = "/dev/ttyACM0"

        await transport._do_connect()

        on_reconnect.assert_called_once()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_successful_connect_stops_reconnect(
        self, mock_serial_iface, transport
    ):
        transport._reconnect_task = asyncio.create_task(asyncio.sleep(999))
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        transport._connection_type = "serial"
        transport._port = "/dev/ttyACM0"

        await transport._do_connect()

        assert transport._reconnect_task is None or transport._reconnect_task.done()


class TestSend:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_send_calls_sendData(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        result = await transport.send(b"hello", want_ack=True)

        mock_iface.sendData.assert_called_once_with(
            b"hello",
            destinationId=0xFFFFFFFF,
            portNum=256,
            wantAck=True,
        )
        assert result == 0

    async def test_send_returns_none_when_disconnected(self, transport):
        result = await transport.send(b"hello")
        assert result is None

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_send_want_ack_false(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        await transport.send(b"data", want_ack=False)

        mock_iface.sendData.assert_called_once_with(
            b"data",
            destinationId=0xFFFFFFFF,
            portNum=256,
            wantAck=False,
        )


class TestHandleReceive:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_on_packet_called_for_private_app(
        self, mock_serial_iface, transport
    ):
        on_packet = MagicMock()
        transport.set_callbacks(on_packet=on_packet)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        packet = _make_packet(256, b"test_payload", from_id=42)
        transport._handle_receive(packet)
        await asyncio.sleep(0)

        on_packet.assert_called_once_with(b"test_payload", 42)

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_on_packet_not_called_wrong_port(
        self, mock_serial_iface, transport
    ):
        on_packet = MagicMock()
        transport.set_callbacks(on_packet=on_packet)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        packet = _make_packet(999, b"test", from_id=1)
        transport._handle_receive(packet)

        on_packet.assert_not_called()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_on_ack_called_for_routing_app(
        self, mock_serial_iface, transport
    ):
        on_ack = MagicMock()
        transport.set_callbacks(on_ack=on_ack)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        packet = _make_routing_packet(request_id=123, error=False)
        transport._handle_receive(packet)
        await asyncio.sleep(0)

        on_ack.assert_called_once_with(123, True)

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_on_ack_called_with_error(
        self, mock_serial_iface, transport
    ):
        on_ack = MagicMock()
        transport.set_callbacks(on_ack=on_ack)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        packet = _make_routing_packet(request_id=456, error=True)
        transport._handle_receive(packet)
        await asyncio.sleep(0)

        on_ack.assert_called_once_with(456, False)

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_handle_receive_ignored_when_disconnected(
        self, mock_serial_iface, transport
    ):
        on_packet = MagicMock()
        transport.set_callbacks(on_packet=on_packet)
        transport._connected = False

        packet = _make_packet(256, b"test", from_id=1)
        transport._handle_receive(packet)

        on_packet.assert_not_called()


class TestMarkDisconnected:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_calls_on_disconnect(self, mock_serial_iface, transport):
        on_disconnect = MagicMock()
        transport.set_callbacks(on_disconnect=on_disconnect)
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        transport._mark_disconnected()

        on_disconnect.assert_called_once()
        assert transport._connected is False

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_starts_reconnect_loop(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        transport._mark_disconnected()

        assert transport._reconnect_task is not None
        assert not transport._reconnect_task.done()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_closes_interface(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        transport._mark_disconnected()

        mock_iface.close.assert_called_once()
        assert transport._interface is None


class TestReconnectLoop:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_reconnect_stops_on_success(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        transport._port = "/dev/ttyACM0"
        transport._connection_type = "serial"
        transport._reconnect_interval = 0.01

        transport._start_reconnect_loop()
        await asyncio.sleep(0.05)

        assert transport._connected is True
        assert transport._reconnect_task is None or transport._reconnect_task.done()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_reconnect_retries_on_failure(self, mock_serial_iface, transport):
        mock_serial_iface.side_effect = Exception("Fail")
        transport._port = "/dev/ttyACM0"
        transport._connection_type = "serial"
        transport._reconnect_interval = 0.01

        transport._start_reconnect_loop()
        await asyncio.sleep(0.07)

        assert mock_serial_iface.call_count >= 2
        assert transport._connected is False


class TestDisconnect:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_disconnect_stops_reconnect(self, mock_serial_iface, transport):
        transport._reconnect_task = asyncio.create_task(asyncio.sleep(999))
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        await transport.disconnect()

        assert transport._connected is False
        assert transport._interface is None
        assert transport._reconnect_task is None or transport._reconnect_task.done()

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_disconnect_closes_interface(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        await transport.disconnect()

        mock_iface.close.assert_called_once()


class TestCheckAlive:
    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_mark_disconnected_if_not_connected(
        self, mock_serial_iface, transport
    ):
        on_disconnect = MagicMock()
        transport.set_callbacks(on_disconnect=on_disconnect)
        mock_iface = MagicMock()
        mock_iface.isConnected = False
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        transport.check_alive()

        on_disconnect.assert_called_once()
        assert transport._connected is False

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_noop_when_connected(self, mock_serial_iface, transport):
        on_disconnect = MagicMock()
        transport.set_callbacks(on_disconnect=on_disconnect)
        mock_iface = MagicMock()
        mock_iface.isConnected = True
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")

        transport.check_alive()

        on_disconnect.assert_not_called()
        assert transport._connected is True


class TestIsConnected:
    def test_false_by_default(self, transport):
        assert transport.is_connected is False

    @patch("meshtastic.serial_interface.SerialInterface")
    async def test_true_after_connect(self, mock_serial_iface, transport):
        mock_iface = MagicMock()
        mock_serial_iface.return_value = mock_iface
        await transport.connect("serial", "/dev/ttyACM0")
        assert transport.is_connected is True
