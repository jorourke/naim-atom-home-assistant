"""Media player entity for Naim devices."""

import logging
import random
import string

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .client import NaimClient
from .const import (
    CONF_SOURCES,
    CONF_VOLUME_STEP,
    DEFAULT_HTTP_PORT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_VOLUME_STEP,
)
from .state import NaimPlayerState

PLATFORMS = [Platform.MEDIA_PLAYER]

_LOGGER = logging.getLogger(__name__)


def round_to_nearest(val: float, step: float = 0.01) -> float:
    """Round a value to the nearest step."""
    return round(val / step) * step


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Naim Media Player from a config entry."""
    ip_address = entry.data[CONF_IP_ADDRESS]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    entity_id = entry.data.get("entity_id")
    volume_step = entry.data.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
    sources = entry.options.get(CONF_SOURCES) or entry.data.get(CONF_SOURCES)

    async_add_entities(
        [NaimPlayer(hass, name, ip_address, entity_id, volume_step, sources)],
        True,
    )


class NaimPlayer(MediaPlayerEntity):
    """Thin Home Assistant entity adapter for Naim devices."""

    DEFAULT_SOURCE_MAP = {
        "Analog 1": "ana1",
        "Digital 1": "dig1",
        "Digital 2": "dig2",
        "Digital 3": "dig3",
        "Bluetooth": "bluetooth",
        "Web Radio": "radio",
        "Spotify": "spotify",
        "Roon": "roon",
        "HDMI": "hdmi",
    }

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        ip_address: str,
        entity_id: str | None = None,
        volume_step: float = DEFAULT_VOLUME_STEP,
        sources: dict[str, str] | None = None,
    ) -> None:
        """Initialize the media player."""
        _LOGGER.info("Initializing Naim media player: %s at %s", name, ip_address)
        self._hass = hass
        self._name = name
        self._ip_address = ip_address
        self._volume_step = volume_step / 100

        if entity_id:
            self.entity_id = f"media_player.{entity_id}"
        else:
            suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
            self.entity_id = f"media_player.{name.lower().replace(' ', '_')}_{suffix}"

        self._attr_unique_id = f"naim_{ip_address}"
        self._source_map = sources if sources else self.DEFAULT_SOURCE_MAP.copy()
        self._source_list = list(self._source_map.keys())
        self._state = NaimPlayerState(
            on_change=self.async_write_ha_state,
            debounce_timeout=2.0,
        )
        self._client = NaimClient(
            hass=hass,
            host=ip_address,
            http_port=DEFAULT_HTTP_PORT,
            ws_port=DEFAULT_PORT,
            state=self._state,
        )

    async def async_added_to_hass(self) -> None:
        """Start push updates when Home Assistant adds the entity."""
        await self._client.start_websocket()

    @property
    def available(self) -> bool:
        """Return whether the device is available."""
        return self._state.available

    @property
    def supported_features(self) -> int:
        """Flag media player features that are supported."""
        return (
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

    @property
    def name(self) -> str:
        """Return the player name."""
        return self._name

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the current state."""
        return self._state.state

    @property
    def volume_level(self) -> float:
        """Return the volume level."""
        return self._state.volume

    @property
    def is_volume_muted(self) -> bool:
        """Return whether volume is muted."""
        return self._state.muted

    @property
    def source(self) -> str | None:
        """Return the current source."""
        return self._state.source

    @property
    def source_list(self) -> list[str]:
        """Return available sources."""
        return self._source_list

    @property
    def media_title(self) -> str | None:
        """Return media title."""
        return self._state.media_title

    @property
    def media_artist(self) -> str | None:
        """Return media artist."""
        return self._state.media_artist

    @property
    def media_album_name(self) -> str | None:
        """Return media album."""
        return self._state.media_album

    @property
    def media_duration(self) -> int | float | None:
        """Return media duration."""
        return self._state.media_duration

    @property
    def media_position(self) -> int | float | None:
        """Return media position."""
        return self._state.media_position

    @property
    def media_image_url(self) -> str | None:
        """Return media image URL."""
        return self._state.media_image_url

    async def async_update(self) -> None:
        """Poll current device state."""
        await self._client.poll_state()

    async def async_turn_on(self) -> None:
        """Turn on the device."""
        await self._client.set_power(True)

    async def async_turn_off(self) -> None:
        """Turn off the device."""
        await self._client.set_power(False)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        volume = max(0.0, min(1.0, volume))
        await self._client.set_volume(int(round_to_nearest(volume) * 100))

    async def async_volume_up(self) -> None:
        """Increase volume by one configured step."""
        new_volume = min(1.0, self._state.volume + self._volume_step)
        new_volume = round_to_nearest(new_volume, step=self._volume_step)
        await self._client.set_volume(int(new_volume * 100))

    async def async_volume_down(self) -> None:
        """Decrease volume by one configured step."""
        new_volume = max(0.0, self._state.volume - self._volume_step)
        new_volume = round_to_nearest(new_volume, step=self._volume_step)
        await self._client.set_volume(int(new_volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute volume."""
        await self._client.set_mute(bool(mute))

    async def async_media_play(self) -> None:
        """Play or resume media."""
        await self._client.send_playback_command("playpause")

    async def async_media_pause(self) -> None:
        """Pause media."""
        await self._client.send_playback_command("playpause")

    async def async_media_stop(self) -> None:
        """Stop media."""
        await self._client.send_playback_command("stop")

    async def async_media_next_track(self) -> None:
        """Skip to the next track."""
        await self._client.send_playback_command("next")

    async def async_media_previous_track(self) -> None:
        """Skip to the previous track."""
        await self._client.send_playback_command("prev")

    async def async_select_source(self, source: str) -> None:
        """Select a source."""
        if source in self._source_map:
            await self._client.select_input(self._source_map[source])

    async def async_will_remove_from_hass(self) -> None:
        """Clean up the WebSocket connection."""
        await self._client.stop_websocket()
