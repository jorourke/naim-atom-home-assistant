"""Test the state management module."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

from homeassistant.components.media_player import MediaPlayerState

from custom_components.naim_media_player.state import (
    DEBOUNCED_FIELDS,
    MEDIA_INFO_FIELDS,
    NAIM_TRANSPORT_STATE_TO_HA_STATE,
    TRANSPORT_STATES_STRING_LOOKUP,
    MediaInfo,
    NaimPlayerState,
    NaimTransportState,
    TransportStateString,
)

# --- MediaInfo tests ---


class TestMediaInfo:
    """Tests for MediaInfo dataclass-like object."""

    def test_default_values(self):
        """All fields should be None by default."""
        info = MediaInfo()
        assert info.title is None
        assert info.artist is None
        assert info.album is None
        assert info.duration is None
        assert info.image_url is None
        assert info.position is None

    def test_set_fields(self):
        """Fields should be directly settable."""
        info = MediaInfo()
        info.title = "Test Song"
        info.artist = "Test Artist"
        info.album = "Test Album"
        info.duration = 300
        info.image_url = "http://example.com/art.jpg"
        info.position = 42

        assert info.title == "Test Song"
        assert info.artist == "Test Artist"
        assert info.album == "Test Album"
        assert info.duration == 300
        assert info.image_url == "http://example.com/art.jpg"
        assert info.position == 42

    def test_reset(self):
        """reset() should set all fields back to None."""
        info = MediaInfo()
        info.title = "Song"
        info.artist = "Artist"
        info.album = "Album"
        info.duration = 100
        info.image_url = "http://img"
        info.position = 50

        info.reset()

        assert info.title is None
        assert info.artist is None
        assert info.album is None
        assert info.duration is None
        assert info.image_url is None
        assert info.position is None


# --- Enum tests ---


class TestNaimTransportState:
    """Tests for NaimTransportState IntEnum."""

    def test_values(self):
        assert NaimTransportState.STOPPED == 1
        assert NaimTransportState.PLAYING == 2
        assert NaimTransportState.PAUSED == 3

    def test_is_int(self):
        """Should behave as an int for API compatibility."""
        assert isinstance(NaimTransportState.PLAYING, int)
        assert NaimTransportState.PLAYING + 0 == 2


class TestTransportStateString:
    """Tests for TransportStateString str enum."""

    def test_values(self):
        assert TransportStateString.PLAYING == "playing"
        assert TransportStateString.PAUSED == "paused"
        assert TransportStateString.STOPPED == "stopped"

    def test_is_str(self):
        """Should behave as a string for WebSocket message comparison."""
        assert isinstance(TransportStateString.PLAYING, str)
        assert TransportStateString.PLAYING == "playing"


# --- Lookup table tests ---


class TestLookupTables:
    """Tests for state mapping dictionaries."""

    def test_transport_states_string_lookup(self):
        assert TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.PLAYING] == MediaPlayerState.PLAYING
        assert TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.PAUSED] == MediaPlayerState.PAUSED
        assert TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.STOPPED] == MediaPlayerState.IDLE

    def test_naim_transport_state_to_ha_state(self):
        assert NAIM_TRANSPORT_STATE_TO_HA_STATE[NaimTransportState.PLAYING] == MediaPlayerState.PLAYING
        assert NAIM_TRANSPORT_STATE_TO_HA_STATE[NaimTransportState.PAUSED] == MediaPlayerState.PAUSED
        assert NAIM_TRANSPORT_STATE_TO_HA_STATE[NaimTransportState.STOPPED] == MediaPlayerState.IDLE


# --- Constants tests ---


class TestConstants:
    """Tests for module-level constants."""

    def test_media_info_fields(self):
        assert MEDIA_INFO_FIELDS == {"title", "artist", "album", "duration", "image_url", "position"}

    def test_debounced_fields(self):
        assert DEBOUNCED_FIELDS == {"volume", "muted"}


# --- NaimPlayerState basic behavior tests ---


class TestNaimPlayerStateBasic:
    """Tests for NaimPlayerState initialization and basic state."""

    async def test_initial_state(self):
        """Default state should be OFF, volume 0, not muted, available."""
        state = NaimPlayerState()
        assert state.power_state == MediaPlayerState.OFF
        assert state.playing_state == MediaPlayerState.IDLE
        assert state.volume == 0.0
        assert state.muted is False
        assert state.source is None
        assert state.available is True
        assert isinstance(state.media_info, MediaInfo)

    async def test_state_property_off(self):
        """state property returns OFF when power is off."""
        state = NaimPlayerState()
        assert state.state == MediaPlayerState.OFF

    async def test_state_property_on_idle(self):
        """state property returns ON when powered on but idle."""
        state = NaimPlayerState()
        await state.update(source="user", power_state=MediaPlayerState.ON)
        assert state.state == MediaPlayerState.ON

    async def test_state_property_playing(self):
        """state property returns PLAYING when powered on and playing."""
        state = NaimPlayerState()
        await state.update(source="user", power_state=MediaPlayerState.ON, playing_state=MediaPlayerState.PLAYING)
        assert state.state == MediaPlayerState.PLAYING

    async def test_state_property_paused(self):
        """state property returns PAUSED when powered on and paused."""
        state = NaimPlayerState()
        await state.update(source="user", power_state=MediaPlayerState.ON, playing_state=MediaPlayerState.PAUSED)
        assert state.state == MediaPlayerState.PAUSED

    async def test_state_property_off_overrides_playing(self):
        """Power OFF always takes precedence over playing_state."""
        state = NaimPlayerState()
        state.playing_state = MediaPlayerState.PLAYING
        state.power_state = MediaPlayerState.OFF
        assert state.state == MediaPlayerState.OFF

    async def test_media_info_convenience_properties(self):
        """Media info properties should delegate to media_info object."""
        state = NaimPlayerState()
        state.media_info.title = "My Song"
        state.media_info.artist = "My Artist"
        state.media_info.album = "My Album"
        state.media_info.duration = 240
        state.media_info.position = 30
        state.media_info.image_url = "http://example.com/art.jpg"

        assert state.media_title == "My Song"
        assert state.media_artist == "My Artist"
        assert state.media_album == "My Album"
        assert state.media_duration == 240
        assert state.media_position == 30
        assert state.media_image_url == "http://example.com/art.jpg"


# --- NaimPlayerState.update() tests ---


class TestNaimPlayerStateUpdate:
    """Tests for the update() method with source-aware debouncing."""

    async def test_update_direct_fields(self):
        """Direct fields (power_state, playing_state, volume, muted, available) update correctly."""
        state = NaimPlayerState()
        await state.update(
            source="user",
            power_state=MediaPlayerState.ON,
            playing_state=MediaPlayerState.PLAYING,
            volume=0.75,
            muted=True,
            available=False,
        )
        assert state.power_state == MediaPlayerState.ON
        assert state.playing_state == MediaPlayerState.PLAYING
        assert state.volume == 0.75
        assert state.muted is True
        assert state.available is False

    async def test_update_source_name(self):
        """The source_name kwarg updates the source field."""
        state = NaimPlayerState()
        await state.update(source="user", source_name="Spotify")
        assert state.source == "Spotify"

    async def test_update_media_info_fields(self):
        """Fields in MEDIA_INFO_FIELDS are forwarded to media_info."""
        state = NaimPlayerState()
        await state.update(
            source="user",
            title="Song Title",
            artist="Artist Name",
            album="Album Name",
            duration=180,
            image_url="http://example.com/img.jpg",
            position=45,
        )
        assert state.media_info.title == "Song Title"
        assert state.media_info.artist == "Artist Name"
        assert state.media_info.album == "Album Name"
        assert state.media_info.duration == 180
        assert state.media_info.image_url == "http://example.com/img.jpg"
        assert state.media_info.position == 45

    async def test_update_ignores_unknown_fields(self):
        """Unknown kwargs should be silently ignored."""
        state = NaimPlayerState()
        # Should not raise
        await state.update(source="user", nonexistent_field="value")

    async def test_update_returns_true_on_change(self):
        """update() should return True when state actually changed."""
        state = NaimPlayerState()
        changed = await state.update(source="user", volume=0.5)
        assert changed is True

    async def test_update_returns_false_on_no_change(self):
        """update() should return False when no state changed."""
        state = NaimPlayerState()
        # Set initial state
        await state.update(source="user", volume=0.5)
        # Same values again
        changed = await state.update(source="user", volume=0.5)
        assert changed is False

    async def test_update_returns_true_for_media_info_change(self):
        """update() returns True when media_info fields change."""
        state = NaimPlayerState()
        changed = await state.update(source="user", title="New Song")
        assert changed is True

        changed = await state.update(source="user", title="New Song")
        assert changed is False


# --- Source-aware debouncing tests ---


class TestSourceAwareDebouncing:
    """Tests for source-aware debouncing in update()."""

    async def test_user_source_always_updates_debounced_fields(self):
        """User source should always update volume and muted."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.5)
        assert state.volume == 0.5

        await state.update(source="user", volume=0.7)
        assert state.volume == 0.7

    async def test_user_source_sets_debounce_timestamp(self):
        """User updates to debounced fields should record a timestamp."""
        state = NaimPlayerState()
        before = time.monotonic()
        await state.update(source="user", volume=0.5)
        after = time.monotonic()

        assert state._debounce_timestamps["volume"] >= before
        assert state._debounce_timestamps["volume"] <= after

    async def test_user_source_sets_muted_debounce_timestamp(self):
        """User updates to muted should record a timestamp."""
        state = NaimPlayerState()
        before = time.monotonic()
        await state.update(source="user", muted=True)
        after = time.monotonic()

        assert state._debounce_timestamps["muted"] >= before
        assert state._debounce_timestamps["muted"] <= after

    async def test_websocket_skips_debounced_fields_within_window(self):
        """WebSocket source should skip volume/muted updates within the debounce window."""
        state = NaimPlayerState()
        # User sets volume
        await state.update(source="user", volume=0.8)
        assert state.volume == 0.8

        # WebSocket tries to update volume immediately after (within debounce window)
        await state.update(source="websocket", volume=0.3)
        # Should still be user's value
        assert state.volume == 0.8

    async def test_websocket_skips_muted_within_window(self):
        """WebSocket source should skip muted updates within the debounce window."""
        state = NaimPlayerState()
        await state.update(source="user", muted=True)
        assert state.muted is True

        await state.update(source="websocket", muted=False)
        assert state.muted is True

    async def test_poll_skips_debounced_fields_within_window(self):
        """Poll source should also skip debounced fields within the debounce window."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.6)

        await state.update(source="poll", volume=0.2)
        assert state.volume == 0.6

    async def test_websocket_updates_debounced_fields_after_window(self):
        """After the debounce window expires, WebSocket should update debounced fields."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.8)

        # Simulate the debounce window expiring by backdating the timestamp
        state._debounce_timestamps["volume"] = time.monotonic() - 3.0

        await state.update(source="websocket", volume=0.3)
        assert state.volume == 0.3

    async def test_websocket_updates_non_debounced_fields_always(self):
        """WebSocket should always be able to update non-debounced fields like playing_state."""
        state = NaimPlayerState()
        # User action sets debounce on volume
        await state.update(source="user", volume=0.5)

        # WebSocket can still update playing_state
        await state.update(source="websocket", playing_state=MediaPlayerState.PLAYING)
        assert state.playing_state == MediaPlayerState.PLAYING

    async def test_websocket_updates_source_name(self):
        """WebSocket should be able to update source_name (non-debounced)."""
        state = NaimPlayerState()
        await state.update(source="websocket", source_name="Roon")
        assert state.source == "Roon"

    async def test_websocket_updates_media_info(self):
        """WebSocket should always update media info fields (non-debounced)."""
        state = NaimPlayerState()
        await state.update(
            source="websocket",
            title="New Track",
            artist="New Artist",
        )
        assert state.media_info.title == "New Track"
        assert state.media_info.artist == "New Artist"

    async def test_mixed_update_partial_debounce(self):
        """When an update has both debounced and non-debounced fields, apply selectively."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.9)

        # WebSocket sends volume + playing_state together
        await state.update(source="websocket", volume=0.1, playing_state=MediaPlayerState.PAUSED)

        # Volume should be debounced (user value kept)
        assert state.volume == 0.9
        # Playing state should update
        assert state.playing_state == MediaPlayerState.PAUSED

    async def test_debounce_timeout_configurable(self):
        """The debounce timeout should be configurable."""
        state = NaimPlayerState(debounce_timeout=0.5)
        await state.update(source="user", volume=0.8)

        # Backdate to just before the custom timeout
        state._debounce_timestamps["volume"] = time.monotonic() - 0.4
        await state.update(source="websocket", volume=0.3)
        assert state.volume == 0.8  # Still within window

        # Now past the window
        state._debounce_timestamps["volume"] = time.monotonic() - 0.6
        await state.update(source="websocket", volume=0.3)
        assert state.volume == 0.3

    async def test_debounce_change_detection_when_skipped(self):
        """update() should return False when debounced fields are the only attempted change."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.8)

        # WebSocket tries to change volume within debounce window -- skipped, so no change
        changed = await state.update(source="websocket", volume=0.3)
        assert changed is False

    async def test_debounce_change_detection_with_mixed(self):
        """update() returns True if non-debounced fields change, even if debounced ones are skipped."""
        state = NaimPlayerState()
        await state.update(source="user", volume=0.8)

        changed = await state.update(source="websocket", volume=0.3, playing_state=MediaPlayerState.PLAYING)
        assert changed is True


# --- on_change callback tests ---


class TestOnChangeCallback:
    """Tests for the on_change callback mechanism."""

    async def test_on_change_called_when_state_changes(self):
        """on_change callback should fire when update changes state."""
        callback = AsyncMock()
        state = NaimPlayerState(on_change=callback)

        await state.update(source="user", volume=0.5)
        callback.assert_awaited_once()

    async def test_on_change_not_called_when_no_change(self):
        """on_change callback should NOT fire when nothing changes."""
        callback = AsyncMock()
        state = NaimPlayerState(on_change=callback)

        await state.update(source="user", volume=0.5)
        callback.reset_mock()

        await state.update(source="user", volume=0.5)
        callback.assert_not_awaited()

    async def test_on_change_not_called_when_debounced(self):
        """on_change should NOT fire when all changes are debounced away."""
        callback = AsyncMock()
        state = NaimPlayerState(on_change=callback)

        await state.update(source="user", volume=0.8)
        callback.reset_mock()

        await state.update(source="websocket", volume=0.3)
        callback.assert_not_awaited()

    async def test_on_change_called_for_media_info_changes(self):
        """on_change fires when media info changes."""
        callback = AsyncMock()
        state = NaimPlayerState(on_change=callback)

        await state.update(source="websocket", title="New Song")
        callback.assert_awaited_once()

    async def test_no_on_change_no_error(self):
        """If no on_change callback is set, updates should still work."""
        state = NaimPlayerState()
        # Should not raise
        await state.update(source="user", volume=0.5)


# --- Thread safety tests ---


class TestThreadSafety:
    """Tests for thread-safe concurrent access."""

    async def test_concurrent_updates(self):
        """Multiple concurrent updates should not corrupt state."""
        state = NaimPlayerState()

        async def set_volume(v):
            await state.update(source="user", volume=v)

        # Fire many updates concurrently
        tasks = [set_volume(i / 100.0) for i in range(100)]
        await asyncio.gather(*tasks)

        # Volume should be one of the values we set (not corrupted)
        assert 0.0 <= state.volume <= 0.99

    async def test_lock_prevents_interleaving(self):
        """The asyncio lock should serialize access to state."""
        state = NaimPlayerState()
        order = []

        original_update = NaimPlayerState.update

        async def tracked_update(self, **kwargs):
            order.append(f"start-{kwargs.get('volume', '?')}")
            result = await original_update(self, **kwargs)
            order.append(f"end-{kwargs.get('volume', '?')}")
            return result

        with patch.object(NaimPlayerState, "update", tracked_update):
            await asyncio.gather(
                state.update(source="user", volume=0.1),
                state.update(source="user", volume=0.2),
            )

        # Each start should be followed by its end before the next start
        # (due to lock serialization)
        assert len(order) == 4
        # Either [start-0.1, end-0.1, start-0.2, end-0.2]
        # or [start-0.2, end-0.2, start-0.1, end-0.1]
        assert order[0].startswith("start-")
        assert order[1].startswith("end-")
        assert order[0].split("-")[1] == order[1].split("-")[1]

    async def test_concurrent_read_during_update(self):
        """Reading state properties while updates are happening should not crash."""
        state = NaimPlayerState()

        async def update_loop():
            for i in range(50):
                await state.update(source="user", volume=i / 100.0)

        async def read_loop():
            for _ in range(50):
                _ = state.state
                _ = state.volume
                _ = state.media_title

        await asyncio.gather(update_loop(), read_loop())
        # If we got here without error, the test passes
