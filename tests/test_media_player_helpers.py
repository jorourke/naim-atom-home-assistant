from unittest import TestCase

from homeassistant.components.media_player import MediaPlayerState

from custom_components.naim_media_player.media_player import (
    TRANSPORT_STATES_STRING_LOOKUP,
    MediaInfo,
    NaimPlayerState,
    TransportStateString,
)


class TestMediaInfo(TestCase):
    def test_init(self):
        """Test MediaInfo initialization."""
        info = MediaInfo()
        self.assertIsNone(info.title)
        self.assertIsNone(info.artist)
        self.assertIsNone(info.album)
        self.assertIsNone(info.duration)
        self.assertIsNone(info.image_url)
        self.assertIsNone(info.position)


class TestNaimPlayerState(TestCase):
    def setUp(self):
        """Set up test cases."""
        self.state = NaimPlayerState()

    def test_init(self):
        """Test NaimPlayerState initialization."""
        self.assertEqual(self.state.power_state, MediaPlayerState.OFF)
        self.assertEqual(self.state.playing_state, MediaPlayerState.IDLE)
        self.assertEqual(self.state.volume, 0.0)
        self.assertFalse(self.state.muted)
        self.assertIsNone(self.state.source)
        self.assertIsInstance(self.state.media_info, MediaInfo)

    def test_update(self):
        """Test state updates."""
        self.state.update(
            power_state=MediaPlayerState.ON,
            volume=0.5,
            muted=True,
            source="Spotify",
            title="Test Song",
            artist="Test Artist",
        )

        self.assertEqual(self.state.power_state, MediaPlayerState.ON)
        self.assertEqual(self.state.volume, 0.5)
        self.assertTrue(self.state.muted)
        self.assertEqual(self.state.source, "Spotify")
        self.assertEqual(self.state.media_info.title, "Test Song")
        self.assertEqual(self.state.media_info.artist, "Test Artist")

    def test_state_property(self):
        """Test state property returns correct states."""
        # When playing_state is IDLE, should return power_state
        self.state.power_state = MediaPlayerState.OFF
        self.state.playing_state = MediaPlayerState.IDLE
        self.assertEqual(self.state.state, MediaPlayerState.OFF)

        # When playing_state is not IDLE, should return playing_state
        self.state.power_state = MediaPlayerState.ON
        self.state.playing_state = MediaPlayerState.PLAYING
        self.assertEqual(self.state.state, MediaPlayerState.PLAYING)

    def test_media_properties(self):
        """Test media-related properties."""
        test_data = {
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "duration": 300,
            "position": 120,
            "image_url": "http://example.com/image.jpg",
        }
        self.state.update(**test_data)

        self.assertEqual(self.state.media_title, "Test Song")
        self.assertEqual(self.state.media_artist, "Test Artist")
        self.assertEqual(self.state.media_album, "Test Album")
        self.assertEqual(self.state.media_duration, 300)
        self.assertEqual(self.state.media_position, 120)
        self.assertEqual(self.state.media_image_url, "http://example.com/image.jpg")


class TestTransportStates(TestCase):
    def test_transport_states_mapping(self):
        """Test transport states string mapping."""
        self.assertEqual(TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.PLAYING], MediaPlayerState.PLAYING)
        self.assertEqual(TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.PAUSED], MediaPlayerState.PAUSED)
        self.assertEqual(TRANSPORT_STATES_STRING_LOOKUP[TransportStateString.STOPPED], MediaPlayerState.IDLE)
