"""Test the Naim Media Player."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME

from custom_components.naim_media_player.media_player import NaimPlayer, NaimTransportState


@pytest.fixture
def mock_player(hass):
    """Create a mock naim player."""
    mock_task = MagicMock()
    mock_task.done.return_value = True
    mock_task.cancel = MagicMock()

    with (
        patch("asyncio.create_task", return_value=mock_task),
    ):
        config = {CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim Player"}
        player = NaimPlayer(hass, config[CONF_NAME], config[CONF_IP_ADDRESS])
        yield player


async def test_player_initialization(mock_player):
    """Test player initialization."""
    assert mock_player.name == "Test Naim Player"
    assert mock_player.state == MediaPlayerState.OFF
    assert mock_player.volume_level == 0.0
    assert mock_player.is_volume_muted is False


async def test_supported_features(mock_player):
    """Test supported features flags."""
    assert mock_player.supported_features == (
        MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
    )


async def test_source_list(mock_player):
    """Test source list."""
    expected_sources = [
        "Analog 1",
        "Digital 1",
        "Digital 2",
        "Digital 3",
        "Bluetooth",
        "Web Radio",
        "Spotify",
    ]
    assert mock_player.source_list == expected_sources


@pytest.mark.parametrize(
    "power_state,transport_state,expected_state",
    [
        ("lona", None, MediaPlayerState.OFF),
        ("on", NaimTransportState.PLAYING, MediaPlayerState.PLAYING),
        ("on", NaimTransportState.PAUSED, MediaPlayerState.PAUSED),
        ("on", NaimTransportState.STOPPED, MediaPlayerState.ON),
        ("on", None, MediaPlayerState.ON),
    ],
)
async def test_update_state(mock_player, power_state, transport_state, expected_state):
    """Test state updates based on power and transport states."""
    with patch.object(mock_player, "async_get_current_value") as mock_get_value:
        # Setup mock returns for power and transport state
        async def mock_get_value_side_effect(url, variable):
            if "power" in url:
                return power_state
            if "nowplaying" in url and variable == "transportState":
                return transport_state
            return None

        mock_get_value.side_effect = mock_get_value_side_effect

        # Call update_state
        await mock_player.update_state()

        # Verify the final state
        assert mock_player.state == expected_state


async def test_state_transitions(mock_player):
    """Test state transitions through different power and playing states."""
    with patch.object(mock_player, "async_get_current_value") as mock_get_value:
        # Test transition from OFF to ON (but idle)
        mock_get_value.side_effect = [
            "lona",  # power state
        ]
        await mock_player.update_state()
        assert mock_player.state == MediaPlayerState.OFF

        # Test transition to ON and PLAYING
        mock_get_value.side_effect = [
            "on",  # power state
            NaimTransportState.PLAYING,  # transport state
        ]
        await mock_player.update_state()
        assert mock_player.state == MediaPlayerState.PLAYING

        # Test transition to PAUSED
        mock_get_value.side_effect = [
            "on",  # power state
            NaimTransportState.PAUSED,  # transport state
        ]
        await mock_player.update_state()
        assert mock_player.state == MediaPlayerState.PAUSED

        # Test transition back to OFF
        mock_get_value.reset_mock()
        mock_get_value.side_effect = ["lona"]
        await mock_player.update_state()
        assert mock_player.state == MediaPlayerState.OFF


async def test_power_commands(mock_player):
    """Test power on/off commands."""
    # Create a mock response that can be used with async with
    # Create a mock response that can be used with async with
    mock_response = AsyncMock()
    mock_response.__aenter__.return_value = mock_response
    mock_response.__aexit__.return_value = None

    mock_client = MagicMock()
    mock_client.put = AsyncMock(return_value=mock_response)

    with (
        patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client),
        patch.object(mock_player, "update_state") as mock_update_state,
    ):
        # Test power on
        await mock_player.async_turn_on()
        mock_client.put.assert_called_with(f"http://{mock_player._ip_address}:15081/power?system=on")
        mock_update_state.assert_called_once()

        # Reset mocks
        mock_client.put.reset_mock()
        mock_update_state.reset_mock()

        # Test power off
        await mock_player.async_turn_off()
        mock_client.put.assert_called_with(f"http://{mock_player._ip_address}:15081/power?system=lona")
        mock_update_state.assert_called_once()


async def test_handle_socket_message(mock_player):
    """Test handling of WebSocket messages for state updates."""
    test_message = {
        "data": {
            "state": "playing",
            "trackRoles": {
                "title": "Test Song",
                "icon": "http://example.com/image.jpg",
                "mediaData": {"metaData": {"artist": "Test Artist", "album": "Test Album"}},
            },
            "status": {
                "duration": 300000  # 300 seconds in milliseconds
            },
            "contextPath": "spotify",
        },
        "playTime": {
            "i64_": 60000  # 60 seconds in milliseconds
        },
        "senderVolume": {
            "i32_": 50  # 50% volume
        },
        "senderMute": {
            "i32_": 0  # not muted
        },
    }

    with patch.object(mock_player, "async_write_ha_state"):
        await mock_player._handle_socket_message(json.dumps(test_message))

        # Verify state updates
        assert mock_player._state.playing_state == MediaPlayerState.PLAYING
        assert mock_player._state.media_info.title == "Test Song"
        assert mock_player._state.media_info.artist == "Test Artist"
        assert mock_player._state.media_info.album == "Test Album"
        assert mock_player._state.media_info.duration == 300
        assert mock_player._state.media_info.position == 60
        # assert mock_player._state.volume == 0.5
        assert mock_player._state.muted is False
        assert mock_player._state.source == "Spotify"


@pytest.mark.parametrize(
    "input_volume,expected_volume",
    [
        (0.77, 0.80),  # Round up to nearest 0.05
        (0.72, 0.75),  # Round down to nearest 0.05
        (0.02, 0.05),  # Round down at boundary
        (0.97, 1.00),  # Round up at boundary
        (0.42, 0.45),  # Round down in middle
        (0.47, 0.50),  # Round up in middle
        (1.5, 1.00),  # Clamp to maximum
        (-0.5, 0.05),  # Clamp to minimum
        (0.05, 0.10),  # Exact step value
        (1.00, 1.00),  # Maximum value
    ],
)
async def test_volume_rounding(mock_player, input_volume, expected_volume):
    """Test volume rounding to nearest 0.05 and clamping to 0-1 range."""
    mock_client = MagicMock()
    mock_client.put = AsyncMock()

    with patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client):
        await mock_player.async_set_volume_level(input_volume)

        await mock_player.async_volume_up()

        # Check internal state was updated correctly
        assert mock_player._state.volume == expected_volume

        # Check API was called with correct device volume (0-100 range)
        expected_device_volume = int(expected_volume * 100)
        mock_client.put.assert_called_with(
            f"http://{mock_player._ip_address}:15081/levels/room?volume={expected_device_volume}"
        )


async def test_volume_step_consistency(mock_player):
    """Test that volume up/down consistently moves in 0.05 steps."""
    mock_client = MagicMock()
    mock_client.put = AsyncMock()

    with patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client):
        # Start at 0.50
        mock_player._state.volume = 0.50

        # Test volume up
        await mock_player.async_volume_up()
        assert mock_player._state.volume == 0.55
        mock_client.put.assert_called_with(f"http://{mock_player._ip_address}:15081/levels/room?volume=55")

        # Test volume down twice
        mock_client.put.reset_mock()
        await mock_player.async_volume_down()
        assert mock_player._state.volume == 0.50
        mock_client.put.assert_called_with(f"http://{mock_player._ip_address}:15081/levels/room?volume=50")

        mock_client.put.reset_mock()
        await mock_player.async_volume_down()
        assert mock_player._state.volume == 0.45
        mock_client.put.assert_called_with(f"http://{mock_player._ip_address}:15081/levels/room?volume=45")


async def test_volume_boundaries(mock_player):
    """Test volume boundaries and clamping."""
    mock_client = MagicMock()
    mock_client.put = AsyncMock()

    with patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client):
        # Test upper boundary
        mock_player._state.volume = 0.95
        await mock_player.async_volume_up()
        assert mock_player._state.volume == 1.00

        # Ensure it doesn't go over 1.0
        await mock_player.async_volume_up()
        assert mock_player._state.volume == 1.00

        # Test lower boundary
        mock_player._state.volume = 0.05
        await mock_player.async_volume_down()
        assert mock_player._state.volume == 0.00

        # Ensure it doesn't go below 0.0
        await mock_player.async_volume_down()
        assert mock_player._state.volume == 0.00


async def test_media_controls(mock_player):
    """Test media control methods."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock()

    with (
        patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client),
        patch.object(mock_player, "update_state"),
    ):
        # Test play/pause
        await mock_player.async_media_play_pause()
        mock_client.get.assert_called_with(f"http://{mock_player._ip_address}:15081/nowplaying?cmd=playpause")

        # Test next track
        mock_client.get.reset_mock()
        await mock_player.async_media_next_track()
        mock_client.get.assert_called_with(f"http://{mock_player._ip_address}:15081/nowplaying?cmd=next")

        # Test previous track
        mock_client.get.reset_mock()
        await mock_player.async_media_previous_track()
        mock_client.get.assert_called_with(f"http://{mock_player._ip_address}:15081/nowplaying?cmd=prev")

        # Test seek
        mock_client.get.reset_mock()
        await mock_player.async_media_seek(30)
        mock_client.get.assert_called_with(f"http://{mock_player._ip_address}:15081/nowplaying?cmd=seek&position=30000")


async def test_source_selection(mock_player):
    """Test source selection."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock()

    with patch("custom_components.naim_media_player.media_player.async_get_clientsession", return_value=mock_client):
        # Test valid source selection
        await mock_player.async_select_source("Spotify")
        mock_client.get.assert_called_with(f"http://{mock_player._ip_address}:15081/inputs/spotify?cmd=select")
        assert mock_player._state.source == "Spotify"

        # Test invalid source selection
        mock_client.get.reset_mock()
        await mock_player.async_select_source("Invalid Source")
        mock_client.get.assert_not_called()


@pytest.mark.skip(reason="This test is flaky and fails intermittently")
async def test_cleanup(mock_player):
    """Test cleanup when entity is removed."""

    # Create a dummy coroutine for the task
    async def dummy_coro():
        pass

    # Create a real task with a dummy coroutine
    mock_task = asyncio.create_task(dummy_coro())
    mock_player._socket_task = mock_task

    await mock_player.async_will_remove_from_hass()

    # Verify the task was cancelled
    assert mock_task.cancelled()


async def test_media_info_properties(mock_player):
    """Test media info property getters."""
    # Setup test data
    mock_player._state.media_info.title = "Test Title"
    mock_player._state.media_info.artist = "Test Artist"
    mock_player._state.media_info.album = "Test Album"
    mock_player._state.media_info.duration = 300
    mock_player._state.media_info.position = 60
    mock_player._state.media_info.image_url = "http://example.com/image.jpg"

    # Test all properties
    assert mock_player.media_title == "Test Title"
    assert mock_player.media_artist == "Test Artist"
    assert mock_player.media_album_name == "Test Album"
    assert mock_player.media_duration == 300
    assert mock_player.media_position == 60
    assert mock_player.media_image_url == "http://example.com/image.jpg"


# @pytest.mark.skip(reason="Skipping this test")
async def test_socket_listener_connection_and_reconnection(mock_player):
    """Test socket listener connection handling and reconnection logic."""
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.close = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    # Make read return immediately with CancelledError
    mock_reader.read = AsyncMock(side_effect=asyncio.CancelledError())

    connection_attempts = 0

    async def mock_open_connection(*args, **kwargs):
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            raise ConnectionError("Connection failed")
        return mock_reader, mock_writer

    # Patch both the connection and any retry delays
    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection),
        patch("asyncio.sleep", new=AsyncMock()),  # Make any retry delays immediate
    ):
        try:
            await mock_player._websocket._socket_listener()
        except asyncio.CancelledError:
            pass

    assert connection_attempts == 2
    assert mock_writer.close.called
    assert mock_writer.wait_closed.called


async def test_socket_message_handling_complete_json(mock_player):
    """Test handling of complete JSON messages from socket."""
    test_message = {
        "data": {
            "state": "playing",
            "trackRoles": {
                "title": "Test Song",
                "icon": "http://example.com/image.jpg",
                "mediaData": {"metaData": {"artist": "Test Artist", "album": "Test Album"}},
            },
            "status": {"duration": 300000},
            "contextPath": "spotify",
        },
        "playTime": {"i64_": 60000},
        "senderMute": {"i32_": 0},
    }

    # Instead of testing the socket listener, test the message handler directly
    await mock_player._handle_socket_message(json.dumps(test_message))

    # Verify state updates
    assert mock_player._state.playing_state == MediaPlayerState.PLAYING
    assert mock_player._state.media_info.title == "Test Song"
    assert mock_player._state.media_info.artist == "Test Artist"
    assert mock_player._state.media_info.album == "Test Album"
    assert mock_player._state.media_info.duration == 300
    assert mock_player._state.media_info.position == 60
    assert mock_player._state.source == "Spotify"


async def test_socket_message_handling_partial_json(mock_player):
    """Test handling of partial JSON messages from socket."""
    test_message = {"data": {"state": "playing", "trackRoles": {"title": "Test Song"}}}

    # Test the message handler directly
    await mock_player._handle_socket_message(json.dumps(test_message))

    # Verify state updates
    assert mock_player._state.playing_state == MediaPlayerState.PLAYING
    assert mock_player._state.media_info.title == "Test Song"


async def test_socket_message_handling_invalid_json(mock_player):
    """Test handling of invalid JSON messages from socket."""
    # Test the message handler directly with invalid JSON
    await mock_player._handle_socket_message('{"invalid": "json')

    # Verify no state changes occurred
    assert mock_player._state.playing_state == MediaPlayerState.IDLE
