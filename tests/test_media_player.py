"""Tests for the Naim Media Player entity."""

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.util import dt as dt_util

from custom_components.naim_media_player.const import DOMAIN
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


async def test_available_when_socket_down_but_polling_healthy(mock_player):
    """A WebSocket drop must not mark the device unavailable while HTTP polling succeeds."""
    mock_player._state.available = True
    mock_player._client.connected = False
    assert mock_player.available is True


async def test_available_via_socket_when_poll_blips(mock_player):
    """A single failed poll must not mark the device unavailable while the socket is live."""
    mock_player._state.available = False
    mock_player._client.connected = True
    assert mock_player.available is True


async def test_unavailable_when_both_channels_down(mock_player):
    """Device loss (poll failing and socket down) must mark the entity unavailable."""
    mock_player._state.available = False
    mock_player._client.connected = False
    assert mock_player.available is False


async def test_source_list_default(mock_player):
    """Test default source list."""
    assert "Spotify" in mock_player.source_list
    assert "Bluetooth" in mock_player.source_list


def test_no_random_entity_id_suffix_generation():
    """A grep for random.choices in media_player.py should find nothing."""
    from custom_components.naim_media_player import media_player

    source = inspect.getsource(media_player)
    assert "random.choices" not in source
    assert "import random" not in source


async def test_entity_id_not_set_when_not_configured(hass):
    """Without an explicit entity_id, HA should derive it from the name (not a random suffix)."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
    assert player.entity_id is None


async def test_state_change_before_registration_does_not_raise(hass):
    """A state change during update_before_add (entity_id not yet assigned) must not raise.

    HA runs the first poll before generating an entity_id; a raising write callback
    aborts the entity add entirely.
    """
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
    player.hass = hass
    assert player.entity_id is None
    await player._state.update(source="poll", power_state=MediaPlayerState.ON)


async def test_state_change_after_registration_writes_state(hass):
    """Once the entity is registered, state changes must write HA state."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
    player.hass = hass
    player.entity_id = "media_player.test_naim"
    with patch.object(player, "async_write_ha_state") as write_state:
        await player._state.update(source="poll", power_state=MediaPlayerState.ON)
    write_state.assert_called_once()


async def test_entity_id_explicit_still_honored(hass):
    """An explicitly configured entity_id must still be used, for backward compatibility."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100", entity_id="test_naim")
    assert player.entity_id == "media_player.test_naim"


async def test_unique_id_falls_back_to_ip_without_serial(hass):
    """Without a serial, unique_id falls back to the IP-derived value for backward compat."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
    assert player.unique_id == "naim_192.168.1.100"
    assert player.device_info is None


async def test_unique_id_uses_serial_when_available(hass):
    """The entity unique_id should be the device serial, not the IP, when known."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100", serial="SERIAL123")
    assert player.unique_id == "SERIAL123"


async def test_device_info_registers_device_with_serial(hass):
    """The entity should expose DeviceInfo keyed by the serial for device registry entries."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100", serial="SERIAL123")
    device_info = player.device_info
    assert device_info is not None
    assert device_info["manufacturer"] == "Naim"
    assert device_info["model"]
    assert device_info["identifiers"] == {(DOMAIN, "SERIAL123")}


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


async def test_media_position_updated_at_delegates_to_state(mock_player):
    """The entity should expose the state's position timestamp for progress bar interpolation."""
    assert mock_player.media_position_updated_at is None

    timestamp = dt_util.utcnow()
    mock_player._state.media_info.position = 60
    mock_player._state.media_info.position_updated_at = timestamp

    assert mock_player.media_position_updated_at == timestamp


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


async def test_volume_up_even_steps_step_3(mock_player):
    """Step 3% from 30% produces even jumps: 33, 36, 39."""
    mock_player._volume_step = 0.03
    mock_player._state.volume = 0.30
    for expected in (33, 36, 39):
        await mock_player.async_volume_up()
        mock_player._client.set_volume.assert_called_once_with(expected)
        mock_player._client.set_volume.reset_mock()
        mock_player._state.volume = expected / 100


async def test_volume_up_even_steps_step_7(mock_player):
    """Step 7% from 56% produces even jumps: 63, 70, 77."""
    mock_player._volume_step = 0.07
    mock_player._state.volume = 0.56
    for expected in (63, 70, 77):
        await mock_player.async_volume_up()
        mock_player._client.set_volume.assert_called_once_with(expected)
        mock_player._client.set_volume.reset_mock()
        mock_player._state.volume = expected / 100


async def test_volume_down_even_steps_step_3(mock_player):
    """Step 3% down from 48% produces even jumps: 45, 42, 39."""
    mock_player._volume_step = 0.03
    mock_player._state.volume = 0.48
    for expected in (45, 42, 39):
        await mock_player.async_volume_down()
        mock_player._client.set_volume.assert_called_once_with(expected)
        mock_player._client.set_volume.reset_mock()
        mock_player._state.volume = expected / 100


async def test_volume_up_clamps_to_100(mock_player):
    """Volume up near the top clamps to 100."""
    mock_player._volume_step = 0.07
    mock_player._state.volume = 0.96
    await mock_player.async_volume_up()
    mock_player._client.set_volume.assert_called_once_with(100)


async def test_volume_down_clamps_to_0(mock_player):
    """Volume down near the bottom clamps to 0."""
    mock_player._volume_step = 0.07
    mock_player._state.volume = 0.04
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
