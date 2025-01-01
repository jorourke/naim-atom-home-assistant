import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.naim_media_player.websocket import NaimWebSocket


@pytest.fixture
async def websocket(mock_message_handler):
    """Create a websocket instance with mocked message handler."""
    ws = NaimWebSocket(
        ip_address="192.168.1.100", port=4545, message_handler=mock_message_handler, reconnect_interval=0.1
    )
    yield ws
    await ws.stop()


@pytest.fixture
def mock_message_handler():
    """Create a mock message handler."""
    return AsyncMock()


async def test_websocket_lifecycle(websocket, mock_message_handler):
    """Test WebSocket connection lifecycle."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    # Setup mock reader to return one message then raise CancelledError
    mock_reader.read.side_effect = [
        b'{"test": "message"}',
        asyncio.CancelledError(),
    ]

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await websocket.start()
        # Allow time for message processing
        await asyncio.sleep(0.1)

    # Verify message was handled
    mock_message_handler.assert_called_once_with('{"test": "message"}')


async def test_websocket_reconnection(websocket, mock_message_handler):
    """Test WebSocket reconnection on failure."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    connection_attempts = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            raise ConnectionError("First connection attempt fails")
        raise asyncio.CancelledError()

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        await websocket.start()
        await asyncio.sleep(0.2)

    # Verify reconnection was attempted
    assert connection_attempts == 2


async def test_websocket_message_buffering(websocket, mock_message_handler):
    """Test handling of partial and complete JSON messages."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    # Split a JSON message into two parts
    message = '{"test": "message"}'
    part1 = message[:10]
    part2 = message[10:]

    mock_reader.read.side_effect = [
        part1.encode(),
        part2.encode(),
        asyncio.CancelledError(),
    ]

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await websocket.start()
        await asyncio.sleep(0.1)

    # Verify the complete message was handled
    mock_message_handler.assert_called_once_with(message)


async def test_websocket_invalid_json(websocket, mock_message_handler):
    """Test handling of invalid JSON data."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    mock_reader.read.side_effect = [
        b'{"invalid": json',
        asyncio.CancelledError(),
    ]

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await websocket.start()
        await asyncio.sleep(0.1)

    # Verify no messages were handled
    mock_message_handler.assert_not_called()


async def test_websocket_multiple_messages(websocket, mock_message_handler):
    """Test handling of multiple messages in one data chunk."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    messages = ['{"message": "1"}', '{"message": "2"}', '{"message": "3"}']

    # Combine messages into one chunk
    data = "".join(messages).encode()
    mock_reader.read.side_effect = [
        data,
        asyncio.CancelledError(),
    ]

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await websocket.start()
        await asyncio.sleep(0.1)

    # Verify all messages were handled
    assert mock_message_handler.call_count == 3
    for message in messages:
        mock_message_handler.assert_any_call(message)
