"""Tests for the Naim Media Player client module."""

import asyncio
import time
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


async def test_get_json_success(hass, state):
    """Test a successful JSON GET."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "test_value"})
        result = await client._get_json("test")
    assert result == {"test_var": "test_value"}


async def test_get_json_client_error(hass, state):
    """Test _get_json with client error eventually raises after retries are exhausted."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=aiohttp.ClientError())
        with pytest.raises(NaimConnectionError):
            await client._get_json("test")


async def test_get_json_timeout_with_retries(hass, state):
    """Test _get_json timeout with retries."""
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
            await client._get_json("test")


async def test_get_json_retry_then_success(hass, state):
    """Test _get_json that fails then succeeds on retry."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=3)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=asyncio.TimeoutError())
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "success"})
        result = await client._get_json("test")
    assert result == {"test_var": "success"}


async def test_get_json_client_error_retries_then_succeeds(hass, state):
    """aiohttp.ClientError must be retried with backoff, not raised immediately."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=2)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/test", exception=aiohttp.ClientError())
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "success"})
        result = await client._get_json("test")
    assert result == {"test_var": "success"}


async def test_get_json_malformed_body_eventually_raises(hass, state):
    """A malformed 200 JSON body must degrade like any other failed request, not raise ValueError."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
    with aioresponses() as mock:
        mock.get(
            "http://192.168.1.100:15081/test",
            body="not json",
            content_type="application/json",
        )
        with pytest.raises(NaimConnectionError):
            await client._get_json("test")


async def test_get_json_malformed_body_retries_then_succeeds(hass, state):
    """A single malformed body must be retried like a transient failure, not fatal immediately."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=2)
    with aioresponses() as mock:
        mock.get(
            "http://192.168.1.100:15081/test",
            body="not json",
            content_type="application/json",
        )
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "success"})
        result = await client._get_json("test")
    assert result == {"test_var": "success"}


async def test_set_value_success(hass, state):
    """Test successful set_value call."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.put("http://192.168.1.100:15081/settings?volume=50", status=200)
        await client.set_value("settings", {"volume": 50})


async def test_set_value_client_error(hass, state):
    """Test set_value with client error eventually raises after retries are exhausted."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
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
        await client.send_command("controls/play", "play")


async def test_send_command_client_error(hass, state):
    """Test send_command with client error eventually raises after retries are exhausted."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
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
        await client.select_input("analog1")


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


async def test_set_volume_failed_command_leaves_state_and_debounce_unarmed(hass, state):
    """A failed set_volume command must not show a stale user value or arm the debounce."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
    await state.update(source="poll", volume=0.5)
    with aioresponses() as mock:
        mock.put(
            "http://192.168.1.100:15081/levels/room?volume=75",
            exception=aiohttp.ClientError(),
        )
        with pytest.raises(NaimConnectionError):
            await client.set_volume(75)

    assert state.volume == 0.5
    assert "volume" not in state._debounce_timestamps

    # A subsequent poll/websocket update must be free to correct the value.
    await state.update(source="poll", volume=0.3)
    assert state.volume == 0.3


async def test_set_mute_failed_command_leaves_state_and_debounce_unarmed(hass, state):
    """A failed set_mute command must not show a stale user value or arm the debounce."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=1)
    await state.update(source="poll", muted=False)
    with aioresponses() as mock:
        mock.put(
            "http://192.168.1.100:15081/levels/room?mute=1",
            exception=aiohttp.ClientError(),
        )
        with pytest.raises(NaimConnectionError):
            await client.set_mute(True)

    assert state.muted is False
    assert "muted" not in state._debounce_timestamps

    # A subsequent poll/websocket update must be free to correct the value.
    await state.update(source="poll", muted=True)
    assert state.muted is True


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
    assert state.media_info.title == "Test Song"
    assert state.media_info.artist == "Test Artist"
    assert state.media_info.album == "Test Album"
    assert state.media_info.duration == 300
    assert state.media_info.position == 120
    assert state.media_info.image_url == "http://example.com/art.jpg"


async def test_poll_state_device_off(hass, state):
    """Test poll_state when device is in standby."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", payload={"system": "lona"})
        await client.poll_state()
    assert state.power_state == MediaPlayerState.OFF


async def test_poll_state_tolerates_malformed_json_without_orphaning_sibling(hass, state):
    """A malformed nowplaying body must not crash poll_state or drop the levels/room fetch."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=3)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", payload={"system": "on"})
        mock.get(
            "http://192.168.1.100:15081/nowplaying",
            body="not json",
            content_type="application/json",
        )
        mock.get(
            "http://192.168.1.100:15081/levels/room",
            payload={"volume": "50", "mute": "0"},
        )
        # poll_state must complete without raising, and the sibling fetch's
        # result must still be consumed.
        await client.poll_state()

    assert state.available is True
    assert state.volume == 0.5
    assert state.muted is False


async def test_poll_state_device_unreachable(hass, state):
    """Test poll_state when device is unreachable."""
    state.available = True
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/power", exception=aiohttp.ClientError())
        await client.poll_state()
    assert state.available is False


async def test_poll_state_uses_single_attempt_request_path(hass, state):
    """Polling must use a single-attempt request path, not the client's default retries."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state, max_retries=5)
    responses = {
        "power": {"system": "on"},
        "nowplaying": {"transportState": 2},
        "levels/room": {"volume": "50", "mute": "0"},
    }

    async def fake_request(method, endpoint, params=None, single_attempt=False):
        return responses[endpoint]

    with patch.object(client, "_request", new=AsyncMock(side_effect=fake_request)) as mock_request:
        await client.poll_state()

    assert mock_request.call_args_list
    for call in mock_request.call_args_list:
        assert call.kwargs.get("single_attempt") is True


async def test_poll_state_fetches_nowplaying_and_levels_concurrently(hass, state):
    """nowplaying and levels/room must be fetched concurrently, not sequentially."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)

    async def fake_request(method, endpoint, params=None, single_attempt=False):
        if endpoint == "power":
            return {"system": "on"}
        await asyncio.sleep(0.2)
        if endpoint == "nowplaying":
            return {"transportState": 2}
        return {"volume": "50", "mute": "0"}

    with patch.object(client, "_request", new=AsyncMock(side_effect=fake_request)):
        start = time.monotonic()
        await client.poll_state()
        elapsed = time.monotonic() - start

    assert elapsed < 0.35


async def test_client_connected_property(hass, state):
    """The public connected property should mirror the internal WebSocket flag."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    assert client.connected is False
    client._connected = True
    assert client.connected is True


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


async def test_drain_buffer_resyncs_after_garbage_before_newline(hass, state):
    """Garbage at the buffer head followed by a newline must be dropped so parsing resumes."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    client._buffer = 'garbage-not-json\n{"data": {"state": "playing"}}'

    await client._drain_buffer()

    assert state.playing_state == MediaPlayerState.PLAYING
    assert client._buffer == ""


async def test_drain_buffer_waits_for_more_data_without_newline(hass, state):
    """A decode failure with no newline yet is treated as an incomplete message."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    client._buffer = "not json and no newline"

    await client._drain_buffer()

    # Buffer is preserved untouched, waiting for more data.
    assert client._buffer == "not json and no newline"


async def test_websocket_resyncs_after_overflow_leaves_garbage(hass, state):
    """Garbage left at the buffer head after an overflow clear must not stall parsing forever."""
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)

    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    valid_message = b'{"data": {"state": "playing"}}'
    mock_reader.read.side_effect = [
        b"x" * (MAX_BUFFER_SIZE + 1),
        b"tail-of-cut-message\n" + valid_message,
        asyncio.CancelledError(),
    ]

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        patch.object(client, "poll_state", new_callable=AsyncMock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await client._socket_listener()

    assert state.playing_state == MediaPlayerState.PLAYING


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
    assert state.media_info.title == "Live Track"
    assert state.media_info.artist == "Live Artist"
    assert state.media_info.album == "Live Album"
    assert state.media_info.duration == 120
    assert state.media_info.position == 45
    assert state.media_info.image_url == "http://example.com/icon.jpg"
    assert state.source == "Spotify"


async def test_websocket_source_prefers_spotify_context_over_playlist_title(hass, state):
    """A Spotify Connect playlist/queue name (mediaRoles.title) must not shadow the actual source.

    Naim's status payload includes mediaRoles.title for the currently-loaded playlist/queue
    (e.g. "Liked Songs"), separate from contextPath, which identifies the streaming service.
    Source detection must resolve to "Spotify" here, not the playlist name, otherwise the
    Home Assistant source dropdown reports a value absent from source_list.
    """
    client = NaimClient(hass, "192.168.1.100", 15081, 4545, state)
    await client._handle_message(
        """
        {
            "data": {
                "state": "playing",
                "trackRoles": {
                    "title": "I'll Fly Away"
                },
                "mediaRoles": {
                    "title": "Liked Songs",
                    "mediaData": {
                        "metaData": {}
                    }
                },
                "contextPath": "spotify:user:liked_songs"
            }
        }
        """
    )

    assert state.source == "Spotify"
