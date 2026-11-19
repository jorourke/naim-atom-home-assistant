"""Tests for the Naim Media Player entity."""

import inspect
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_media_player import media_player
from custom_components.naim_media_player.const import CONF_SERIAL, DOMAIN
from custom_components.naim_media_player.media_player import NaimPlayer, async_setup_entry


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
        client.seek = AsyncMock()

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
    """Without a serial or an explicit unique_id, unique_id falls back to the bare IP.

    This is the same bare-IP fallback config_flow.py uses, so entity and
    config-entry identity never drift.
    """
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100")
    assert player.unique_id == "192.168.1.100"
    assert player.device_info is None


async def test_unique_id_prefers_explicit_value_over_serial_and_ip(hass):
    """An explicitly passed unique_id (from the config entry) takes priority."""
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Test Naim", "192.168.1.100", serial="SERIAL123", unique_id="ENTRY_UNIQUE_ID")
    assert player.unique_id == "ENTRY_UNIQUE_ID"


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


async def test_source_maps_device_input_id_to_configured_name(hass):
    """The device reports `inputs/<id>`; the entity presents the configured name.

    `source` must be a member of `source_list`, otherwise the frontend dropdown
    shows a value it cannot select.
    """
    player = NaimPlayer(hass, "Test", "192.168.1.100", sources={"HDMI": "hdmi", "Spotify": "spotify"})

    player._state.source = "inputs/hdmi"
    assert player.source == "HDMI"

    player._state.source = "inputs/spotify"
    assert player.source == "Spotify"


async def test_source_is_none_when_input_unknown_or_unset(hass):
    """An input outside the configured map has no name to present."""
    player = NaimPlayer(hass, "Test", "192.168.1.100", sources={"HDMI": "hdmi"})

    assert player.source is None

    player._state.source = "inputs/airplay"
    assert player.source is None


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
    mock_player._state.source = "inputs/spotify"
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


def test_scan_interval_is_fast_enough_to_catch_externally_triggered_power_on():
    """power_state is only ever refreshed by polling /power (WebSocket carries no power signal
    — confirmed by capturing live device traffic, which streams nowplaying heartbeats
    continuously even while the device reports standby over HTTP). A slow scan interval means
    a device woken by Spotify Connect (outside HA) can sit at `off` in HA for up to a full
    interval after it actually started playing.
    """
    assert media_player.SCAN_INTERVAL <= timedelta(seconds=5)


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
    await _on(mock_player)
    await mock_player.async_media_play()
    mock_player._client.send_playback_command.assert_called_once_with("playpause")


async def test_media_pause(mock_player):
    """Test pause delegates to client."""
    await _on(mock_player)
    await mock_player.async_media_pause()
    mock_player._client.send_playback_command.assert_called_once_with("playpause")


async def test_media_stop(mock_player):
    """Test stop delegates to client."""
    await _on(mock_player)
    await mock_player.async_media_stop()
    mock_player._client.send_playback_command.assert_called_once_with("stop")


async def test_media_next_track(mock_player):
    """Test next track delegates to client."""
    await _on(mock_player)
    await mock_player.async_media_next_track()
    mock_player._client.send_playback_command.assert_called_once_with("next")


async def test_media_previous_track(mock_player):
    """Test previous track delegates to client."""
    await _on(mock_player)
    await mock_player.async_media_previous_track()
    mock_player._client.send_playback_command.assert_called_once_with("prev")


async def test_media_seek(mock_player):
    """The device takes a position in milliseconds; Home Assistant gives seconds."""
    await _on(mock_player)
    await mock_player.async_media_seek(109.568)
    mock_player._client.seek.assert_called_once_with(109568)


async def test_media_seek_clamps_negative(mock_player):
    """A drag to the very start of the bar can arrive as a small negative."""
    await _on(mock_player)
    await mock_player.async_media_seek(-0.4)
    mock_player._client.seek.assert_called_once_with(0)


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


# --- Config-entry / entity unique_id identity tests ---


async def test_async_setup_entry_unique_id_matches_entry_for_serial(hass):
    """The entity's unique_id must equal the config entry's unique_id in the serial case."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="SERIAL123",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            CONF_SERIAL: "SERIAL123",
        },
    )
    entry.add_to_hass(hass)

    added_entities: list[NaimPlayer] = []

    def fake_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        await async_setup_entry(hass, entry, fake_add_entities)

    assert added_entities[0].unique_id == entry.unique_id == "SERIAL123"


async def test_async_setup_entry_unique_id_matches_entry_for_ip_fallback(hass):
    """The entity's unique_id must equal the config entry's unique_id in the IP-fallback case."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.100",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
        },
    )
    entry.add_to_hass(hass)

    added_entities: list[NaimPlayer] = []

    def fake_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        await async_setup_entry(hass, entry, fake_add_entities)

    assert added_entities[0].unique_id == entry.unique_id == "192.168.1.100"


# --- Competitor-parity features: capability flags, format, cap, standby, refresh, favourites ---

from aioresponses import aioresponses  # noqa: E402
from homeassistant.components.media_player import MediaPlayerEntityFeature as F  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from custom_components.naim_media_player.const import CONF_MAX_VOLUME, CONF_SOURCES  # noqa: E402


async def _on(player, **kwargs):
    await player._state.update(source="poll", power_state=MediaPlayerState.ON, **kwargs)


async def test_features_unchanged_when_flags_absent(mock_player):
    assert mock_player.supported_features == (
        F.PAUSE
        | F.VOLUME_SET
        | F.VOLUME_MUTE
        | F.TURN_ON
        | F.TURN_OFF
        | F.PLAY
        | F.STOP
        | F.SELECT_SOURCE
        | F.NEXT_TRACK
        | F.PREVIOUS_TRACK
        | F.SEEK
        | F.BROWSE_MEDIA
        | F.PLAY_MEDIA
    )


@pytest.mark.parametrize(
    ("control", "feature"),
    [("pause", F.PAUSE), ("seek", F.SEEK), ("next", F.NEXT_TRACK), ("previous", F.PREVIOUS_TRACK)],
)
async def test_restriction_removes_feature_and_clearing_restores_it(mock_player, control, feature):
    await mock_player._state.update(source="poll", restrictions=frozenset({control}))
    assert not mock_player.supported_features & feature
    assert mock_player.supported_features & F.PLAY
    await mock_player._state.update(source="poll", restrictions=frozenset())
    assert mock_player.supported_features & feature


async def test_audio_format_attributes(mock_player):
    await _on(mock_player, audio_format={"codec": "AAC", "sample_rate": 44100, "bit_rate": 126431})
    assert mock_player.extra_state_attributes == {
        "audio_codec": "AAC",
        "audio_sample_rate": 44100,
        "audio_bit_rate": 126431,
    }


async def test_audio_format_attributes_empty_when_missing_or_off(mock_player):
    await _on(mock_player)
    assert not mock_player.extra_state_attributes
    await _on(mock_player, audio_format={"codec": "AAC"})
    await mock_player._state.update(source="poll", power_state=MediaPlayerState.OFF)
    assert not mock_player.extra_state_attributes


async def test_buffering_state_shown(mock_player):
    await _on(mock_player, playing_state=MediaPlayerState.BUFFERING)
    assert mock_player.state == MediaPlayerState.BUFFERING


# -- standby


@pytest.mark.parametrize(
    "method",
    [
        ("async_media_play", ()),
        ("async_media_pause", ()),
        ("async_media_stop", ()),
        ("async_media_next_track", ()),
        ("async_media_previous_track", ()),
        ("async_media_seek", (10,)),
        ("async_play_media", ("channel", "inputs/radio/favourites/1")),
    ],
)
async def test_transport_commands_in_standby_raise_and_send_nothing(hass, method):
    player = NaimPlayer(hass, "Test", "192.168.1.100")
    name, args = method
    with aioresponses() as mock:
        with pytest.raises(ServiceValidationError) as err:
            await getattr(player, name)(*args)
        assert not mock.requests
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "device_in_standby"


async def test_select_source_in_standby_still_sends_select(hass):
    player = NaimPlayer(hass, "Test", "192.168.1.100", sources={"Analog 1": "ana1"})
    with aioresponses() as mock:
        mock.get("http://192.168.1.100:15081/inputs/ana1?cmd=select", status=200, payload={})
        await player.async_select_source("Analog 1")
        mock.assert_called_once()
    assert player._state.power_state == MediaPlayerState.OFF  # never claims power-on


async def test_transport_commands_work_when_on(mock_player):
    await _on(mock_player)
    await mock_player.async_media_pause()
    mock_player._client.send_playback_command.assert_awaited_once_with("playpause")


# -- volume cap


def _capped(mock_player, cap, volume_percent):
    mock_player._max_volume = cap
    mock_player._state.volume = volume_percent / 100
    return mock_player


async def test_volume_set_stops_at_cap(mock_player):
    await _capped(mock_player, 50, 10).async_set_volume_level(0.9)
    mock_player._client.set_volume.assert_awaited_once_with(50)


async def test_volume_set_above_cap_never_lowers_volume(mock_player):
    await _capped(mock_player, 50, 70).async_set_volume_level(0.8)
    mock_player._client.set_volume.assert_awaited_once_with(70)


async def test_volume_up_stops_at_cap(mock_player):
    await _capped(mock_player, 40, 38).async_volume_up()
    mock_player._client.set_volume.assert_awaited_once_with(40)


async def test_volume_up_above_cap_does_nothing_and_down_still_works(mock_player):
    _capped(mock_player, 50, 70)
    await mock_player.async_volume_up()
    mock_player._client.set_volume.assert_not_awaited()
    await mock_player.async_volume_down()
    mock_player._client.set_volume.assert_awaited_once_with(65)


async def test_default_cap_leaves_volume_calls_unchanged(mock_player):
    assert mock_player._max_volume == 100
    mock_player._state.volume = 0.98
    await mock_player.async_volume_up()
    mock_player._client.set_volume.assert_awaited_once_with(100)
    await mock_player.async_set_volume_level(1.0)
    mock_player._client.set_volume.assert_awaited_with(100)


async def test_setup_entry_passes_max_volume_option(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim"},
        options={CONF_MAX_VOLUME: 40},
    )
    entry.add_to_hass(hass)
    added = []
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        await async_setup_entry(hass, entry, lambda entities, update_before_add=False: added.extend(entities))
    assert added[0]._max_volume == 40
    assert entry.runtime_data is added[0]


# -- input name refresh


async def test_refresh_renames_sources_in_memory_only(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_SOURCES: {"Analog 1": "ana1", "HDMI": "hdmi"}},
    )
    entry.add_to_hass(hass)
    added = []
    with patch("custom_components.naim_media_player.media_player.NaimClient") as client_cls:
        await async_setup_entry(hass, entry, lambda entities, update_before_add=False: added.extend(entities))
        player = added[0]
        client_cls.return_value.get_inputs = AsyncMock(
            return_value={"Turntable": "ana1", "HDMI": "hdmi", "Digital 1": "dig1"}
        )
        client_cls.return_value.select_input = AsyncMock()
        player._state.source = "inputs/ana1"
        with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload:
            await player._async_refresh_input_names()
            await hass.async_block_till_done()

    assert player.source == "Turntable"
    assert player.source_list == ["Turntable", "HDMI"]  # selection kept; dig1 not added
    reload.assert_not_called()
    assert entry.data == {CONF_IP_ADDRESS: "192.168.1.100", CONF_SOURCES: {"Analog 1": "ana1", "HDMI": "hdmi"}}
    assert entry.options == {}
    await player.async_select_source("Turntable")
    player._client.select_input.assert_awaited_once_with("ana1")


@pytest.mark.parametrize("result", [None, {}])
async def test_refresh_failure_keeps_old_names(mock_player, result):
    mock_player._client.get_inputs = AsyncMock(return_value=result)
    before = list(mock_player.source_list)
    await mock_player._async_refresh_input_names()
    assert mock_player.source_list == before


# -- favourites


async def test_browse_media_lists_favourites(mock_player):
    mock_player._client.get_radio_favourites = AsyncMock(
        return_value=[{"name": "Jazz", "id": "inputs/radio/favourites/1", "image": None}]
    )
    root = await mock_player.async_browse_media()
    assert [(c.title, c.media_content_id, c.can_play) for c in root.children] == [
        ("Jazz", "inputs/radio/favourites/1", True)
    ]


async def test_browse_media_without_favourites_is_empty_not_error(mock_player):
    mock_player._client.get_radio_favourites = AsyncMock(return_value=[])
    root = await mock_player.async_browse_media()
    assert root.children == []


async def test_play_media_plays_favourite(mock_player):
    await _on(mock_player)
    mock_player._client.play_radio_item = AsyncMock()
    await mock_player.async_play_media("channel", "inputs/radio/favourites/1")
    mock_player._client.play_radio_item.assert_awaited_once_with("inputs/radio/favourites/1")


async def test_play_media_rejects_non_radio_path(mock_player):
    await _on(mock_player)
    mock_player._client.play_radio_item = AsyncMock()
    with pytest.raises(ServiceValidationError) as err:
        await mock_player.async_play_media("channel", "system")
    assert err.value.translation_key == "invalid_media_id"
    mock_player._client.play_radio_item.assert_not_awaited()
