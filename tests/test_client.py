import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.naim_media_player.client import NaimApiClient, NaimWebSocketClient
from custom_components.naim_media_player.exceptions import NaimConnectionError

# ============================================================================
# NaimApiClient Tests
# ============================================================================


async def test_naim_api_client_init(hass):
    """Test NaimApiClient initialization."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)
    assert client._ip_address == "192.168.1.100"
    assert client._http_port == 15081
    assert client._ws_port == 4545
    assert client._max_retries == 3
    assert client._request_timeout == 10.0
    assert client._websocket is None


async def test_naim_api_client_init_with_websocket(hass):
    """Test NaimApiClient initialization with websocket handler."""
    handler = AsyncMock()
    client = NaimApiClient(
        hass,
        "192.168.1.100",
        websocket_message_handler=handler,
        websocket_reconnect_interval=10,
    )
    assert client._websocket is not None
    assert client._websocket.message_handler == handler
    assert client._websocket.reconnect_interval == 10


async def test_get_value_success(hass):
    """Test successful get_value call."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "test_value"})
        result = await client.get_value("test", "test_var")
        assert result == "test_value"


async def test_get_value_client_error(hass):
    """Test get_value with client error."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=aiohttp.ClientError())
        with pytest.raises(NaimConnectionError, match="Failed to get test_var from test"):
            await client.get_value("test", "test_var")


async def test_get_value_timeout_with_retries(hass):
    """Test get_value timeout with retries."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2, request_timeout=0.1)

    with aioresponses() as mock:
        # Both attempts timeout
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())

        with pytest.raises(NaimConnectionError, match="Failed to get test_var from test after 2 attempts"):
            await client.get_value("test", "test_var")


async def test_get_value_non_200_response_with_retries(hass):
    """Test get_value with non-200 response and retries."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2)

    with aioresponses() as mock:
        # First attempt fails with 500
        mock.get("http://192.168.1.100:15081/test", status=500)
        # Second attempt fails with 404
        mock.get("http://192.168.1.100:15081/test", status=404)

        with pytest.raises(NaimConnectionError, match="Failed to get test_var from test after 2 attempts"):
            await client.get_value("test", "test_var")


async def test_get_value_retry_then_success(hass):
    """Test get_value that fails then succeeds on retry."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=3)

    with aioresponses() as mock:
        # First attempt times out
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        # Second attempt succeeds
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "success"})

        result = await client.get_value("test", "test_var")
        assert result == "success"


async def test_set_value_success(hass):
    """Test successful set_value call."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        # params get added to URL as query parameters
        mock.put("http://192.168.1.100:15081/settings?volume=50", status=200)
        result = await client.set_value("settings", {"volume": 50})
        assert result is True


async def test_set_value_client_error(hass):
    """Test set_value with client error."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/settings?volume=50", exception=aiohttp.ClientError("Connection failed"))
        with pytest.raises(NaimConnectionError, match="Failed to set values to settings"):
            await client.set_value("settings", {"volume": 50})


async def test_set_value_timeout_with_retries(hass):
    """Test set_value timeout with retries."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2)

    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/settings?volume=50", exception=asyncio.TimeoutError())
        mock.put("http://192.168.1.100:15081/settings?volume=50", exception=asyncio.TimeoutError())

        with pytest.raises(NaimConnectionError, match="Failed to set values to settings after 2 attempts"):
            await client.set_value("settings", {"volume": 50})


async def test_set_value_non_200_response(hass):
    """Test set_value with non-200 response."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2)

    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/settings?volume=50", status=500)
        mock.put("http://192.168.1.100:15081/settings?volume=50", status=500)

        with pytest.raises(NaimConnectionError, match="Failed to set values to settings after 2 attempts"):
            await client.set_value("settings", {"volume": 50})


async def test_send_command_success(hass):
    """Test successful send_command call."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", status=200)
        result = await client.send_command("controls/play", "play")
        assert result is True


async def test_send_command_with_params(hass):
    """Test send_command with additional parameters."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/volume?cmd=set&level=50", status=200)
        result = await client.send_command("volume", "set", level=50)
        assert result is True


async def test_send_command_client_error(hass):
    """Test send_command with client error."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", exception=aiohttp.ClientError())
        with pytest.raises(NaimConnectionError, match="Failed to send command play to controls/play"):
            await client.send_command("controls/play", "play")


async def test_send_command_timeout_with_retries(hass):
    """Test send_command timeout with retries."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", exception=asyncio.TimeoutError())
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", exception=asyncio.TimeoutError())

        with pytest.raises(NaimConnectionError, match="Failed to send command play to controls/play after 2 attempts"):
            await client.send_command("controls/play", "play")


async def test_send_command_non_200_response(hass):
    """Test send_command with non-200 response."""
    client = NaimApiClient(hass, "192.168.1.100", 15081, max_retries=2)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", status=404)
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", status=404)

        with pytest.raises(NaimConnectionError, match="Failed to send command play to controls/play after 2 attempts"):
            await client.send_command("controls/play", "play")


async def test_select_input(hass):
    """Test select_input method."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/inputs/analog1?cmd=select", status=200)
        result = await client.select_input("analog1")
        assert result is True


async def test_start_websocket_no_websocket(hass):
    """Test start_websocket when no websocket is configured."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)
    # Should not raise error
    await client.start_websocket()


async def test_stop_websocket_no_websocket(hass):
    """Test stop_websocket when no websocket is configured."""
    client = NaimApiClient(hass, "192.168.1.100", 15081)
    # Should not raise error
    await client.stop_websocket()


async def test_start_websocket_with_websocket(hass):
    """Test start_websocket with websocket configured."""
    handler = AsyncMock()
    client = NaimApiClient(hass, "192.168.1.100", websocket_message_handler=handler)

    with patch.object(client._websocket, "start", new_callable=AsyncMock) as mock_start:
        await client.start_websocket()
        mock_start.assert_called_once()


async def test_stop_websocket_with_websocket(hass):
    """Test stop_websocket with websocket configured."""
    handler = AsyncMock()
    client = NaimApiClient(hass, "192.168.1.100", websocket_message_handler=handler)

    with patch.object(client._websocket, "stop", new_callable=AsyncMock) as mock_stop:
        await client.stop_websocket()
        mock_stop.assert_called_once()


# ============================================================================
# NaimWebSocketClient Tests
# ============================================================================


async def test_websocket_client_init():
    """Test NaimWebSocketClient initialization."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=10)

    assert client.ip_address == "192.168.1.100"
    assert client.port == 4545
    assert client.message_handler == handler
    assert client.reconnect_interval == 10
    assert client._task is None
    assert client._connected is False
    assert client._buffer == ""
    assert client._decoder is not None


async def test_websocket_start():
    """Test WebSocket start method."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)

    with patch("asyncio.create_task") as mock_create_task:
        await client.start()
        mock_create_task.assert_called_once()


async def test_websocket_stop_no_task():
    """Test WebSocket stop when no task exists."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)
    # Should not raise error
    await client.stop()


async def test_websocket_stop_with_completed_task():
    """Test WebSocket stop with completed task."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)

    mock_task = MagicMock()
    mock_task.done.return_value = True
    client._task = mock_task

    await client.stop()
    # Task is already done, should not cancel
    mock_task.cancel.assert_not_called()


async def test_websocket_stop_with_running_task():
    """Test WebSocket stop with running task."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)

    mock_task = MagicMock()
    mock_task.done.return_value = False
    client._task = mock_task

    with patch("asyncio.wait", new_callable=AsyncMock) as mock_wait:
        mock_wait.return_value = (set(), set())  # done, pending
        await client.stop()
        mock_task.cancel.assert_called_once()


async def test_websocket_stop_with_timeout():
    """Test WebSocket stop with timeout waiting for task."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)

    mock_task = MagicMock()
    mock_task.done.return_value = False
    client._task = mock_task

    with patch("asyncio.wait", new_callable=AsyncMock) as mock_wait:
        # Simulate pending tasks (timeout)
        mock_wait.return_value = (set(), {mock_task})
        await client.stop()
        mock_task.cancel.assert_called_once()


async def test_websocket_stop_with_error():
    """Test WebSocket stop with exception."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler)

    mock_task = MagicMock()
    mock_task.done.return_value = False
    client._task = mock_task

    with patch("asyncio.wait", new_callable=AsyncMock) as mock_wait:
        mock_wait.side_effect = Exception("Test error")
        await client.stop()  # Should not raise


async def test_websocket_listener_connection_success():
    """Test WebSocket listener successful connection and message handling."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    # Create mock reader and writer
    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    # Simulate receiving JSON messages
    message1 = '{"type": "status", "state": "playing"}'
    message2 = '{"type": "volume", "level": 50}'

    # First read returns message1, second returns message2, third returns empty (connection closed)
    mock_reader.read.side_effect = [
        message1.encode("utf-8"),
        message2.encode("utf-8"),
        b"",  # Empty data signals connection closed
    ]

    call_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_reader, mock_writer
        # On second connection attempt, sleep forever to prevent reconnection
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        # Start the listener
        task = asyncio.create_task(client._socket_listener())

        # Wait for messages to be processed
        await asyncio.sleep(0.1)

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify handler was called with messages
        assert handler.call_count == 2
        handler.assert_any_call(message1)
        handler.assert_any_call(message2)


async def test_websocket_listener_partial_json():
    """Test WebSocket listener with partial JSON messages."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    # Simulate partial JSON that arrives in chunks
    chunk1 = '{"type": "sta'
    chunk2 = 'tus", "state": "playing"}'

    mock_reader.read.side_effect = [
        chunk1.encode("utf-8"),
        chunk2.encode("utf-8"),
        b"",  # Connection closed
    ]

    call_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_reader, mock_writer
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have assembled and processed the complete message
        assert handler.call_count == 1
        handler.assert_called_with(chunk1 + chunk2)


async def test_websocket_listener_connection_error():
    """Test WebSocket listener handles connection errors."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    attempt_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionRefusedError("Connection refused")
        # After 3 attempts, sleep forever
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())

        # Wait for multiple connection attempts
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have attempted to connect multiple times
        assert attempt_count >= 2


async def test_websocket_listener_read_error():
    """Test WebSocket listener handles read errors."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    # First read succeeds, second raises error
    mock_reader.read.side_effect = [
        b'{"type": "status"}',
        Exception("Read error"),
    ]

    call_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_reader, mock_writer
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have processed first message before error
        assert handler.call_count == 1


async def test_websocket_listener_writer_close_error():
    """Test WebSocket listener handles writer close errors."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.close.side_effect = Exception("Close error")
    mock_writer.wait_closed = AsyncMock(side_effect=Exception("Wait closed error"))

    mock_reader.read.return_value = b""  # Connection closed

    call_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_reader, mock_writer
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should handle close error gracefully
        assert client._connected is False


async def test_websocket_listener_multiple_json_objects_in_buffer():
    """Test WebSocket listener with multiple JSON objects in one read."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    # Multiple complete JSON objects in one chunk
    messages = '{"type": "status"}{"type": "volume"}'

    mock_reader.read.side_effect = [
        messages.encode("utf-8"),
        b"",  # Connection closed
    ]

    call_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_reader, mock_writer
        await asyncio.sleep(100)

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have processed both messages
        assert handler.call_count == 2


async def test_websocket_listener_buffer_cleared_on_reconnect():
    """Test that buffer is cleared between connection attempts."""
    handler = AsyncMock()
    client = NaimWebSocketClient("192.168.1.100", 4545, handler, reconnect_interval=0.01)

    # Set initial buffer with partial data
    client._buffer = '{"incomplete'

    mock_reader = AsyncMock()
    mock_writer = MagicMock()

    mock_reader.read.side_effect = [
        b'{"type": "status"}',
        b"",  # Connection closed
    ]

    buffer_was_cleared = False

    async def mock_open_connection(*args, **kwargs):
        nonlocal buffer_was_cleared
        # Check if buffer was cleared
        if client._buffer == "":
            buffer_was_cleared = True
        return mock_reader, mock_writer

    with patch("asyncio.open_connection", side_effect=mock_open_connection):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify buffer was cleared before connection
        assert buffer_was_cleared
