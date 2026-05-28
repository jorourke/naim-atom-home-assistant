"""State management for Naim Media Player."""

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from enum import Enum, IntEnum

from homeassistant.components.media_player import MediaPlayerState

_LOGGER = logging.getLogger(__name__)

DEBOUNCED_FIELDS = {"volume", "muted"}
MEDIA_INFO_FIELDS = {"title", "artist", "album", "duration", "image_url", "position"}


class MediaInfo:
    """Handle media information."""

    def __init__(self) -> None:
        """Initialize media information."""
        self.title = None
        self.artist = None
        self.album = None
        self.duration = None
        self.image_url = None
        self.position = None

    def reset(self) -> None:
        """Reset all media fields."""
        self.title = None
        self.artist = None
        self.album = None
        self.duration = None
        self.image_url = None
        self.position = None


class NaimTransportState(IntEnum):
    """Enum for transport states from the HTTP API."""

    STOPPED = 1
    PLAYING = 2
    PAUSED = 3


class TransportStateString(str, Enum):
    """Enum for transport states from WebSocket messages."""

    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


TRANSPORT_STATES_STRING_LOOKUP = {
    TransportStateString.PLAYING: MediaPlayerState.PLAYING,
    TransportStateString.PAUSED: MediaPlayerState.PAUSED,
    TransportStateString.STOPPED: MediaPlayerState.IDLE,
}

NAIM_TRANSPORT_STATE_TO_HA_STATE = {
    NaimTransportState.PLAYING: MediaPlayerState.PLAYING,
    NaimTransportState.PAUSED: MediaPlayerState.PAUSED,
    NaimTransportState.STOPPED: MediaPlayerState.IDLE,
}


class NaimPlayerState:
    """Single source of truth for Naim device state."""

    def __init__(
        self,
        on_change: Callable[[], object] | None = None,
        debounce_timeout: float = 2.0,
    ) -> None:
        """Initialize state."""
        self._lock = asyncio.Lock()
        self._on_change = on_change
        self._debounce_timeout = debounce_timeout
        self._debounce_timestamps: dict[str, float] = {}

        self.power_state = MediaPlayerState.OFF
        self.playing_state = MediaPlayerState.IDLE
        self.volume = 0.0
        self.muted = False
        self.source = None
        self.available = True
        self.media_info = MediaInfo()

    async def update(self, source: str = "poll", **kwargs) -> bool:
        """Update state fields and return whether anything changed."""
        current_time = time.monotonic()
        changed = False

        async with self._lock:
            for key, value in kwargs.items():
                attr_name = "source" if key == "source_name" else key

                if attr_name in MEDIA_INFO_FIELDS:
                    target = self.media_info
                    target_attr = attr_name
                elif hasattr(self, attr_name) and attr_name != "media_info":
                    target = self
                    target_attr = attr_name
                else:
                    continue

                if source != "user" and attr_name in DEBOUNCED_FIELDS:
                    last_user_action = self._debounce_timestamps.get(attr_name, 0)
                    if current_time - last_user_action < self._debounce_timeout:
                        _LOGGER.debug(
                            "Skipping %s update for %s because debounce is active",
                            source,
                            attr_name,
                        )
                        continue

                if source == "user" and attr_name in DEBOUNCED_FIELDS:
                    self._debounce_timestamps[attr_name] = current_time

                if getattr(target, target_attr) != value:
                    setattr(target, target_attr, value)
                    changed = True

        if changed and self._on_change:
            result = self._on_change()
            if inspect.isawaitable(result):
                await result

        return changed

    @property
    def state(self) -> MediaPlayerState:
        """Get the Home Assistant player state."""
        if self.power_state == MediaPlayerState.OFF:
            return MediaPlayerState.OFF
        if self.playing_state == MediaPlayerState.IDLE:
            return self.power_state
        return self.playing_state

    @property
    def media_title(self) -> str | None:
        """Get media title."""
        return self.media_info.title

    @property
    def media_artist(self) -> str | None:
        """Get media artist."""
        return self.media_info.artist

    @property
    def media_album(self) -> str | None:
        """Get media album."""
        return self.media_info.album

    @property
    def media_duration(self) -> int | float | None:
        """Get media duration."""
        return self.media_info.duration

    @property
    def media_position(self) -> int | float | None:
        """Get media position."""
        return self.media_info.position

    @property
    def media_image_url(self) -> str | None:
        """Get media image URL."""
        return self.media_info.image_url
