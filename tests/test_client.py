"""Tests for the Naim Media Player client module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.components.media_player import MediaPlayerState

from custom_components.naim_media_player.client import MAX_BUFFER_SIZE, NaimClient
from custom_components.naim_media_player.exceptions import NaimConnectionError
from custom_components.naim_media_player.state import NaimPlayerState


@pytest.fixture
def state():
    """Create a NaimPlayerState instance."""
    return NaimPlayerState()


async def test_client_init(hass, state):
    """Test NaimClient initialization."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    assert client._host == "192.168.1.100"
    assert client._http_port == 15081
    assert client._ws_port == 4545


async def test_get_value_success(hass, state):
    """Test successful get_value call."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "test_value"})
        result = await client.get_value("test", "test_var")
    assert result == "test_value"


async def test_get_value_client_error(hass, state):
    """Test get_value with client error."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=aiohttp.ClientError())
        with pytest.raises(NaimConnectionError):
            await client.get_value("test", "test_var")


async def test_get_value_timeout_with_retries(hass, state):
    """Test get_value timeout with retries."""
    client = NaimClient(
        hass,
        "192.168.1.100",
        15081,
        4545,
        state,
        max_retries=2,
        request_timeout=0.1,
    )
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        with pytest.raises(NaimConnectionError):
            await client.get_value("test", "test_var")


async def test_get_value_retry_then_success(hass, state):
    """Test get_value that fails then succeeds on retry."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=3)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "success"})
        result = await client.get_value("test", "test_var")
    assert result == "success"


async def test_set_value_success(hass, state):
    """Test successful set_value call."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/settings?volume=50", status=200)
        result = await client.set_value("settings", {"volume": 50})
    assert result is True


async def test_set_value_client_error(hass, state):
    """Test set_value with client error."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put(
            "http://192.168.1.100:15081/settings?volume=50",
            exception=aiohttp.ClientError(),
        )
        with pytest.raises(NaimConnectionError):
            await client.set_value("settings", {"volume": 50})


async def test_send_command_success(hass, state):
    """Test successful send_command call."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/controls/play?cmd=play", status=200)
        result = await client.send_command("controls/play", "play")
    assert result is True


async def test_send_command_client_error(hass, state):
    """Test send_command with client error."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get(
            "http://192.168.1.100:15081/controls/play?cmd=play",
            exception=aiohttp.ClientError(),
        )
        with pytest.raises(NaimConnectionError):
            await client.send_command("controls/play", "play")


async def test_select_input(hass, state):
    """Test select_input method."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/inputs/analog1?cmd=select", status=200)
        result = await client.select_input("analog1")
    assert result is True


async def test_set_volume_updates_state_and_device(hass, state):
    """Test set_volume optimistically writes state and sends HTTP command."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/levels/room?volume=75", status=200)
        await client.set_volume(75)
    assert state.volume == 0.75
    assert "volume" in state._debounce_timestamps


async def test_set_mute_updates_state_and_device(hass, state):
    """Test set_mute optimistically writes state and sends HTTP command."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/levels/room?mute=1", status=200)
        await client.set_mute(True)
    assert state.muted is True
    assert "muted" in state._debounce_timestamps


async def test_set_power_updates_state_and_device(hass, state):
    """Test set_power sends command and updates power state."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/power?system=on", status=200)
        await client.set_power(True)
    assert state.power_state == MediaPlayerState.ON


async def test_poll_state_device_on(hass, state):
    """Test poll_state when device is on and playing."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", payload={"system": "on"})
        mock.get(
            "http://192.168.1.100:15081/nowplaying",
            payload={
                "transportState": 2,
                "title": "Test Song",
                "artistName": "Test Artist",
                "albumName": "Test Album",
                "duration": 300,
                "transportPosition": 120,
                "artwork": "http://example.com/art.jpg",
                "source": "spotify",
            },
        )
        mock.get(
            "http://192.168.1.100:15081/levels/room",
            payload={"volume": "75", "mute": "0"},
        )
        await client.poll_state()

    assert state.available is True
    assert state.power_state == MediaPlayerState.ON
    assert state.playing_state == MediaPlayerState.PLAYING
    assert state.volume == 0.75
    assert state.muted is False
    assert state.source == "spotify"
    assert state.media_title == "Test Song"
    assert state.media_artist == "Test Artist"
    assert state.media_album == "Test Album"
    assert state.media_duration == 300
    assert state.media_position == 120
    assert state.media_image_url == "http://example.com/art.jpg"


async def test_poll_state_device_off(hass, state):
    """Test poll_state when device is in standby."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", payload={"system": "lona"})
        await client.poll_state()
    assert state.power_state == MediaPlayerState.OFF


async def test_poll_state_device_unreachable(hass, state):
    """Test poll_state when device is unreachable."""
    state.available = True
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", exception=aiohttp.ClientError())
        await client.poll_state()
    assert state.available is False


async def test_websocket_start_stop(hass, state):
    """Test WebSocket lifecycle."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_reader.read.side_effect = [
        b'{"data": {"state": "playing"}}',
        asyncio.CancelledError(),
    ]

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch.object(client, "poll_state", new_callable=AsyncMock),
    ):
        await client.start_websocket()
        await asyncio.sleep(0.05)
        await client.stop_websocket()

    assert state.playing_state == MediaPlayerState.PLAYING


async def test_websocket_buffer_cleared_on_reconnect(hass, state):
    """Test that buffer is cleared between connection attempts."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    client._buffer = '{"incomplete'

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_reader.read.side_effect = [b'{"data": {"state": "playing"}}', b""]
    buffer_was_cleared = False

    async def mock_open_connection(*args, **kwargs):
        nonlocal buffer_was_cleared
        if client._buffer == "":
            buffer_was_cleared = True
        return mock_reader, mock_writer

    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection),
        patch.object(client, "poll_state", new_callable=AsyncMock),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_sleep.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await client._socket_listener()

    assert buffer_was_cleared


async def test_websocket_connection_restored_triggers_poll(hass, state):
    """Test that reconnection triggers a full state poll."""
    client = NaimClient(
        hass,
        "192.168.1.100",
        15081,
        4545,
        state,
        ws_reconnect_interval=0.01,
    )
    connection_count = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        if connection_count == 1:
            raise ConnectionError("First attempt fails")
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_reader.read.side_effect = [asyncio.CancelledError()]
        return mock_reader, mock_writer

    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection),
        patch.object(client, "poll_state", new_callable=AsyncMock) as mock_poll,
    ):
        task = asyncio.create_task(client._socket_listener())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_poll.assert_called_once()


async def test_websocket_buffer_overflow(hass, state):
    """Test that buffer is cleared when exceeding max size."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_reader.read.side_effect = [b"x" * (MAX_BUFFER_SIZE + 1), asyncio.CancelledError()]

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch.object(client, "poll_state", new_callable=AsyncMock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await client._socket_listener()

    assert client._buffer == ""


async def test_websocket_partial_json(hass, state):
    """Test WebSocket handles partial JSON correctly."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_reader.read.side_effect = [
        b'{"data": {"sta',
        b'te": "playing"}}',
        asyncio.CancelledError(),
    ]

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch.object(client, "poll_state", new_callable=AsyncMock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await client._socket_listener()

    assert state.playing_state == MediaPlayerState.PLAYING


async def test_websocket_multiple_json_objects(hass):
    """Test WebSocket handles multiple JSON objects in one read."""
    callback = AsyncMock()
    state = NaimPlayerState(on_change=callback)
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    messages = '{"data": {"state": "playing"}}{"data": {"state": "paused"}}'
    mock_reader.read.side_effect = [messages.encode(), asyncio.CancelledError()]

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch.object(client, "poll_state", new_callable=AsyncMock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await client._socket_listener()

    assert state.playing_state == MediaPlayerState.PAUSED
    assert callback.await_count == 2


async def test_websocket_updates_metadata(hass, state):
    """Test WebSocket metadata parsing."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    await client._handle_message(
        """
        {
            "data": {
                "state": "playing",
                "trackRoles": {
                    "title": "Live Track",
                    "icon": "http://example.com/icon.jpg",
                    "mediaData": {
                        "metaData": {
                            "artist": "Live Artist",
                            "album": "Live Album"
                        }
                    }
                },
                "status": {
                    "duration": 120000
                },
                "contextPath": "spotify:album"
            },
            "playTime": {
                "i64_": 45000
            }
        }
        """
    )

    assert state.playing_state == MediaPlayerState.PLAYING
    assert state.media_title == "Live Track"
    assert state.media_artist == "Live Artist"
    assert state.media_album == "Live Album"
    assert state.media_duration == 120
    assert state.media_position == 45
    assert state.media_image_url == "http://example.com/icon.jpg"
    assert state.source == "Spotify"
