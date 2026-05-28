"""Tests for the Naim Media Player entity."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)

from custom_components.naim_media_player.media_player import NaimPlayer


@pytest.fixture
def mock_player(hass):
    """Create a mock NaimPlayer with patched client."""
    with patch("custom_components.naim_media_player.media_player.NaimClient") as mock_client:
        client = mock_client.return_value
        client.start_websocket = AsyncMock()
        client.stop_websocket = AsyncMock()
        client.poll_state = AsyncMock()
        client.set_volume = AsyncMock()
        client.set_mute = AsyncMock()
        client.set_power = AsyncMock()
        client.send_playback_command = AsyncMock()
        client.select_input = AsyncMock()

        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
        player._client = client
        yield player


async def test_player_initialization(mock_player):
    """Test player initialization."""
    assert mock_player.name == "Test Naim"
    assert mock_player.state == MediaPlayerState.OFF
    assert mock_player.volume_level == 0.0
    assert mock_player.is_volume_muted is False
    assert mock_player.available is True


async def test_supported_features(mock_player):
    """Test supported features flags."""
    features = mock_player.supported_features
    assert features & MediaPlayerEntityFeature.PAUSE
    assert features & MediaPlayerEntityFeature.VOLUME_SET
    assert features & MediaPlayerEntityFeature.VOLUME_MUTE
    assert features & MediaPlayerEntityFeature.TURN_ON
    assert features & MediaPlayerEntityFeature.TURN_OFF
    assert features & MediaPlayerEntityFeature.PLAY
    assert features & MediaPlayerEntityFeature.STOP
    assert features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert features & MediaPlayerEntityFeature.NEXT_TRACK
    assert features & MediaPlayerEntityFeature.PREVIOUS_TRACK


async def test_source_list_default(mock_player):
    """Test default source list."""
    assert "Spotify" in mock_player.source_list
    assert "Bluetooth" in mock_player.source_list


async def test_source_list_configured(hass):
    """Test configured source list."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(
            hass,
            "Test",
            "192.168.1.100",
            sources={"Radio": "radio", "Spotify": "spotify"},
        )
    assert player.source_list == ["Radio", "Spotify"]


async def test_properties_delegate_to_state(mock_player):
    """Test that properties delegate to state."""
    mock_player._state.volume = 0.75
    mock_player._state.muted = True
    mock_player._state.source = "Spotify"
    mock_player._state.media_info.title = "Test Song"
    mock_player._state.media_info.artist = "Test Artist"
    mock_player._state.media_info.album = "Test Album"
    mock_player._state.media_info.duration = 300
    mock_player._state.media_info.position = 60
    mock_player._state.media_info.image_url = "http://example.com/art.jpg"

    assert mock_player.volume_level == 0.75
    assert mock_player.is_volume_muted is True
    assert mock_player.source == "Spotify"
    assert mock_player.media_title == "Test Song"
    assert mock_player.media_artist == "Test Artist"
    assert mock_player.media_album_name == "Test Album"
    assert mock_player.media_duration == 300
    assert mock_player.media_position == 60
    assert mock_player.media_image_url == "http://example.com/art.jpg"


async def test_async_update_delegates_to_client(mock_player):
    """Test async_update calls client.poll_state."""
    await mock_player.async_update()
    mock_player._client.poll_state.assert_called_once()


async def test_turn_on(mock_player):
    """Test turn on delegates to client."""
    await mock_player.async_turn_on()
    mock_player._client.set_power.assert_called_once_with(True)


async def test_turn_off(mock_player):
    """Test turn off delegates to client."""
    await mock_player.async_turn_off()
    mock_player._client.set_power.assert_called_once_with(False)


async def test_set_volume(mock_player):
    """Test volume set delegates to client."""
    await mock_player.async_set_volume_level(0.75)
    mock_player._client.set_volume.assert_called_once_with(75)


async def test_volume_up(mock_player):
    """Test volume up increments and delegates."""
    mock_player._state.volume = 0.50
    await mock_player.async_volume_up()
    mock_player._client.set_volume.assert_called_once_with(55)


async def test_volume_down(mock_player):
    """Test volume down decrements and delegates."""
    mock_player._state.volume = 0.50
    await mock_player.async_volume_down()
    mock_player._client.set_volume.assert_called_once_with(45)


async def test_volume_boundaries(mock_player):
    """Test volume clamping at boundaries."""
    mock_player._state.volume = 0.98
    await mock_player.async_volume_up()
    mock_player._client.set_volume.assert_called_once_with(100)

    mock_player._client.set_volume.reset_mock()
    mock_player._state.volume = 0.02
    await mock_player.async_volume_down()
    mock_player._client.set_volume.assert_called_once_with(0)


async def test_mute(mock_player):
    """Test mute delegates to client."""
    await mock_player.async_mute_volume(True)
    mock_player._client.set_mute.assert_called_once_with(True)


async def test_media_play(mock_player):
    """Test play delegates to client."""
    await mock_player.async_media_play()
    mock_player._client.send_playback_command.assert_called_once_with("playpause")


async def test_media_pause(mock_player):
    """Test pause delegates to client."""
    await mock_player.async_media_pause()
    mock_player._client.send_playback_command.assert_called_once_with("playpause")


async def test_media_stop(mock_player):
    """Test stop delegates to client."""
    await mock_player.async_media_stop()
    mock_player._client.send_playback_command.assert_called_once_with("stop")


async def test_media_next_track(mock_player):
    """Test next track delegates to client."""
    await mock_player.async_media_next_track()
    mock_player._client.send_playback_command.assert_called_once_with("next")


async def test_media_previous_track(mock_player):
    """Test previous track delegates to client."""
    await mock_player.async_media_previous_track()
    mock_player._client.send_playback_command.assert_called_once_with("prev")


async def test_select_source(mock_player):
    """Test source selection delegates to client."""
    await mock_player.async_select_source("Spotify")
    mock_player._client.select_input.assert_called_once_with("spotify")


async def test_select_invalid_source(mock_player):
    """Test selecting invalid source does nothing."""
    await mock_player.async_select_source("Invalid Source")
    mock_player._client.select_input.assert_not_called()


async def test_cleanup(mock_player):
    """Test cleanup stops websocket."""
    await mock_player.async_will_remove_from_hass()
    mock_player._client.stop_websocket.assert_called_once()
