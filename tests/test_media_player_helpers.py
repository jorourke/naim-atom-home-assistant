from unittest import IsolatedAsyncioTestCase, TestCase

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

    async def test_update(self):
        """Test state updates."""
        await self.state.update(
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

    async def test_media_properties(self):
        """Test media-related properties."""
        test_data = {
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "duration": 300,
            "position": 120,
            "image_url": "http://example.com/image.jpg",
        }
        await self.state.update(**test_data)

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


class TestNaimPlayerStateThreadSafety(IsolatedAsyncioTestCase):
    # Skip this class
    pass

    # async def asyncSetUp(self):
    #     """Set up test cases."""
    #     self.state = NaimPlayerState()

    # async def test_concurrent_updates(self):
    #     """Test that concurrent state updates are handled safely."""
    #     # Number of concurrent updates to perform
    #     num_updates = 100

    #     # Create a list to track successful updates
    #     results = []

    #     async def update_volume(index):
    #         """Update volume and track the update."""
    #         volume = index / num_updates
    #         await self.state.update(volume=volume)
    #         results.append(volume)

    #     # Create and gather multiple concurrent update tasks
    #     tasks = [update_volume(i) for i in range(num_updates)]
    #     await asyncio.gather(*tasks)

    #     # Verify that we processed all updates
    #     self.assertEqual(len(results), num_updates)
    #     # Verify that the final state matches the last update
    #     self.assertEqual(self.state.volume, (num_updates - 1) / num_updates)

    # async def test_mixed_concurrent_updates(self):
    #     """Test concurrent updates of different attributes."""
    #     test_values = {
    #         "volume": 0.5,
    #         "muted": True,
    #         "source": "Test Source",
    #         "title": "Test Title",
    #         "artist": "Test Artist",
    #     }

    #     results = []

    #     async def update_attribute(attr, value):
    #         """Update a single attribute and track the update."""
    #         await self.state.update(**{attr: value})
    #         results.append((attr, value))

    #     # Create concurrent updates for different attributes
    #     tasks = [update_attribute(attr, value) for attr, value in test_values.items()]

    #     await asyncio.gather(*tasks)

    #     # Verify all updates were processed
    #     self.assertEqual(len(results), len(test_values))

    #     # Verify final state
    #     self.assertEqual(self.state.volume, test_values["volume"])
    #     self.assertEqual(self.state.muted, test_values["muted"])
    #     self.assertEqual(self.state.source, test_values["source"])
    #     self.assertEqual(self.state.media_info.title, test_values["title"])
    #     self.assertEqual(self.state.media_info.artist, test_values["artist"])

    # async def test_rapid_updates(self):
    #     """Test rapid sequential updates to the same attribute."""
    #     update_count = 1000

    #     async def rapid_updates():
    #         """Perform rapid updates to volume."""
    #         for i in range(update_count):
    #             await self.state.update(volume=i / update_count)
    #             # Add a small delay to simulate real-world conditions
    #             await asyncio.sleep(0.001)

    #     # Run multiple rapid update sequences concurrently
    #     tasks = [rapid_updates() for _ in range(3)]
    #     await asyncio.gather(*tasks)

    #     # Final value should be from the last update
    #     expected_final_volume = (update_count - 1) / update_count
    #     self.assertEqual(self.state.volume, expected_final_volume)

    # async def test_atomic_updates(self):
    #     """Test that updates are atomic and can't be interrupted mid-operation."""

    #     # Track the intermediate states we observe
    #     observed_states = []
    #     update_completed = asyncio.Event()

    #     async def slow_update():
    #         """Perform a slow update that could be interrupted."""
    #         updates = {"volume": 0.5, "muted": True, "source": "Test Source"}
    #         # Simulate a slow update by adding delays between each attribute
    #         for attr, value in updates.items():
    #             await self.state.update(**{attr: value})
    #             await asyncio.sleep(0.1)  # Give plenty of time for race conditions
    #         update_completed.set()

    #     async def state_observer():
    #         """Try to catch the state in an inconsistent state."""
    #         while not update_completed.is_set():
    #             # Capture the current state
    #             state_snapshot = {"volume": self.state.volume, "muted": self.state.muted, "source": self.state.source}
    #             observed_states.append(state_snapshot)
    #             await asyncio.sleep(0.01)  # Check state frequently

    #     # Run the slow update and observer concurrently
    #     await asyncio.gather(slow_update(), state_observer())

    #     # Verify no inconsistent states were observed
    #     for state in observed_states:
    #         # Either we should see the initial state or the final state
    #         # but never a mix of old and new values
    #         initial_state = {"volume": 0.0, "muted": False, "source": None}
    #         final_state = {"volume": 0.5, "muted": True, "source": "Test Source"}

    #         self.assertTrue(state == initial_state or state == final_state, f"Found inconsistent state: {state}")
