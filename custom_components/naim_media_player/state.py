"""State management for Naim Media Player."""

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.media_player import MediaPlayerState
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DEBOUNCED_FIELDS = {"volume", "muted"}
MEDIA_INFO_FIELDS = {"title", "artist", "album", "duration", "image_url", "position"}

# Transport-state mappings. The HTTP API reports integers (1=stopped,
# 2=playing, 3=paused); WebSocket messages report strings.
TRANSPORT_INT_TO_HA_STATE = {
    1: MediaPlayerState.IDLE,
    2: MediaPlayerState.PLAYING,
    3: MediaPlayerState.PAUSED,
}

TRANSPORT_STRING_TO_HA_STATE = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": MediaPlayerState.IDLE,
}


def transport_int_to_ha_state(transport) -> MediaPlayerState:
    """Map a Naim transport integer to a Home Assistant state (ON if unknown)."""
    try:
        return TRANSPORT_INT_TO_HA_STATE.get(int(transport), MediaPlayerState.ON)
    except (TypeError, ValueError):
        return MediaPlayerState.ON


def transport_string_to_ha_state(transport) -> MediaPlayerState:
    """Map a Naim transport string to a Home Assistant state (IDLE if unknown)."""
    try:
        return TRANSPORT_STRING_TO_HA_STATE.get(transport, MediaPlayerState.IDLE)
    except TypeError:
        return MediaPlayerState.IDLE


@dataclass
class MediaInfo:
    """Currently playing media metadata."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: int | float | None = None
    image_url: str | None = None
    position: int | float | None = None
    position_updated_at: datetime | None = None


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

                if attr_name == "duration" and isinstance(value, (int, float)) and value < 0:
                    # Naim devices report a negative duration (e.g. -0.001) for
                    # endless streams such as web radio; treat as "no duration".
                    value = None

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

                    if attr_name == "position" and value is not None:
                        self.media_info.position_updated_at = dt_util.utcnow()

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
