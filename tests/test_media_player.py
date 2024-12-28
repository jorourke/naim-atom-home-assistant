"""Test the Naim Media Player."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME

from custom_components.naim_media_player.media_player import NaimPlayer


@pytest.fixture
def mock_player(hass):
    """Create a mock naim player."""
    mock_task = MagicMock()
    mock_task.done.return_value = True
    mock_task.cancel = MagicMock()

    # Create a mock coroutine that accepts self
    async def mock_socket_listener(self):
        return None

    with (
        patch("asyncio.create_task", return_value=mock_task),
        patch.object(NaimPlayer, "_socket_listener", mock_socket_listener),
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
