"""Media player platform for controlling a device via local HTTP endpoint."""

import asyncio
import json
import logging
import random
import string
from enum import Enum, IntEnum

import aiohttp
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_VOLUME_STEP,
    DEFAULT_NAME,
    DEFAULT_VOLUME_STEP,
)
from .websocket import NaimWebSocket

PLATFORMS = [Platform.MEDIA_PLAYER]

_LOGGER = logging.getLogger(__name__)


class MediaInfo:
    """Handle media information."""

    def __init__(self):
        """Initialize media information."""
        self.title = None
        self.artist = None
        self.album = None
        self.duration = None
        self.image_url = None
        self.position = None


class NaimPlayerState:
    """Handle Naim player state."""

    def __init__(self):
        """Initialize state."""
        self._lock = asyncio.Lock()
        self.power_state = MediaPlayerState.OFF
        self.playing_state = MediaPlayerState.IDLE
        self.volume = 0.0
        self.muted = False
        self.source = None
        self.media_info = MediaInfo()

    async def update(self, **kwargs):
        """Update state attributes."""
        async with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
                # Handle nested media_info updates
                elif hasattr(self.media_info, key):
                    setattr(self.media_info, key, value)

    @property
    def state(self) -> MediaPlayerState:
        """Get player state."""
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
    def media_duration(self) -> int | None:
        """Get media duration."""
        return self.media_info.duration

    @property
    def media_position(self) -> int | None:
        """Get media position."""
        return self.media_info.position

    @property
    def media_image_url(self) -> str | None:
        """Get media image URL."""
        return self.media_info.image_url


class NaimTransportState(IntEnum):
    """Enum for transport states."""

    STOPPED = 1
    PLAYING = 2
    PAUSED = 3


class TransportStateString(str, Enum):
    """Enum for transport states."""

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

CONST_VOLUME_STEP = 0.05


def round_to_nearest(val: float, step: float = 0.01) -> float:
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

    async_add_entities([NaimPlayer(hass, name, ip_address, entity_id, volume_step)], True)


class NaimPlayer(MediaPlayerEntity):
    """Representation of a Naim Player."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        ip_address: str,
        entity_id: str | None = None,
        volume_step: float = DEFAULT_VOLUME_STEP,
    ):
        """Initialize the media player."""
        _LOGGER.info("Initializing Naim Control media player: %s at %s", name, ip_address)
        self._hass = hass
        self._name = name
        self._ip_address = ip_address
        # It's a percentage, so we need to divide by 100, whereas for the user, it's easier
        # to work in 1-100
        self._volume_step = volume_step / 100

        # Use provided entity_id or generate one from the name
        if entity_id:
            self.entity_id = f"media_player.{entity_id}"
        else:
            suggested_id = (
                name.lower().replace(" ", "_")
                + "_"
                + "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
            )
            self.entity_id = f"media_player.{suggested_id}"

        self._attr_unique_id = f"naim_{ip_address}"
        self._state = NaimPlayerState()
        self._source_map = {
            "Analog 1": "ana1",
            "Digital 1": "dig1",
            "Digital 2": "dig2",
            "Digital 3": "dig3",
            "Bluetooth": "bluetooth",
            "Web Radio": "radio",
            "Spotify": "spotify",
        }
        self._source_list = list(self._source_map.keys())
        self._media_title = None
        self._media_artist = None
        self._media_album_name = None
        self._media_duration = None
        self._media_position = None
        self._media_image_url = None
        self._socket_reconnect_interval = 5

        # Replace the direct socket handling with NaimWebSocket
        self._websocket = NaimWebSocket(
            ip_address=self._ip_address,
            port=4545,
            message_handler=self._handle_socket_message,
            reconnect_interval=self._socket_reconnect_interval,
        )
        # Start WebSocket connection
        asyncio.create_task(self._websocket.start())

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

    async def _handle_socket_message(self, message):
        """Handle socket message."""
        try:
            all_state = json.loads(message)
            state_data = all_state.get("data", {})
            _LOGGER.info(
                "Socket message: title='%s', state=%s, audio=%sx%sHz",
                state_data.get("trackRoles", {}).get("title"),
                state_data.get("state"),
                state_data.get("trackRoles", {}).get("mediaData", {}).get("activeResource", {}).get("bitsPerSample"),
                state_data.get("trackRoles", {}).get("mediaData", {}).get("activeResource", {}).get("sampleFrequency"),
            )

            # Extract the 'data' dictionary
            _LOGGER.debug("Processing live status data: %s", state_data)

            # Create update dictionary
            updates = {}

            # Update media info
            track_roles = state_data.get("trackRoles", {})
            media_data = track_roles.get("mediaData", {}).get("metaData", {})

            updates.update(
                {
                    "title": track_roles.get("title"),
                    "artist": media_data.get("artist"),
                    "album": media_data.get("album"),
                    "image_url": track_roles.get("icon"),
                }
            )

            # Update playback state
            playing_state_str = state_data.get("state")
            updates["playing_state"] = TRANSPORT_STATES_STRING_LOOKUP.get(playing_state_str, MediaPlayerState.IDLE)

            # Update media duration and position
            duration_ms = state_data.get("status", {}).get("duration")
            if duration_ms is not None:
                try:
                    _LOGGER.debug(f"Setting duration to: {duration_ms}")
                    updates["duration"] = float(duration_ms) / 1000  # Convert to seconds
                except (ValueError, TypeError):
                    _LOGGER.warning("Invalid media duration value received: %s", duration_ms)

            position_ms = all_state.get("playTime", {}).get("i64_")
            if position_ms is not None:
                _LOGGER.debug(f"Setting position to: {position_ms}")
                updates["position"] = position_ms / 1000  # Convert to seconds

            # TODO: Sender volume is not updating when, say, I change the volume
            # on the spotify app. For example the value that is coming back can remain stuck
            # for the payload here in the websocket payload.
            # volume = all_state.get("senderVolume", {}).get("i32_")
            # if volume is not None:
            #     _LOGGER.debug(f"Updating state of volume to: {volume}")
            #     updates["volume"] = int(volume) / 100

            # Update mute state
            muted = all_state.get("senderMute", {}).get("i32_")
            if muted is not None:
                _LOGGER.debug(f"Setting mute to: {muted}")
                updates["muted"] = bool(int(muted))

            # Update source
            source = self.get_source(state_data)
            if source:
                _LOGGER.debug(f"Setting source to: {source}")
                updates["source"] = source

            # Update state object with all changes
            await self._state.update(**updates)
            self.async_write_ha_state()

        except json.JSONDecodeError as error:
            _LOGGER.error("Error parsing socket message for %s: %s", self._name, error)
        except Exception as error:
            _LOGGER.error("Error handling socket message for %s: %s", self._name, error)

    def get_source(self, live_status):
        """Get source from live status."""
        source = live_status.get("mediaRoles", {}).get("title", None)
        if not source:
            source = live_status.get("contextPath")
            if source is not None:
                if source.startswith("spotify"):
                    source = "Spotify"
        return source

    async def async_get_current_value(self, url_pattern, variable):
        """Get current value from device API."""
        try:
            _LOGGER.debug("Getting current value from %s for variable %s", url_pattern, variable)
            r = await async_get_clientsession(self._hass).get(url_pattern.format(ip=self._ip_address))
            if r.status == 200:
                content = await r.text()
                j = json.loads(content)
                if variable in j:
                    _LOGGER.debug("Got value %s for variable %s", j[variable], variable)
                    return j[variable]
        except aiohttp.ClientError as error:
            _LOGGER.error("Error getting current value: %s", error)
        return None

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        return self._state.media_image_url

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        return self._state.media_duration

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        return self._state.media_position

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media, music track only."""
        return self._state.media_album

    @property
    def media_artist(self) -> str | None:
        """Album artist of current playing media, music track only."""
        return self._state.media_artist

    @property
    def is_playing(self):
        """Return true if the device is playing."""
        return self._state.state == MediaPlayerState.PLAYING

    @property
    def is_paused(self):
        """Return true if the device is paused."""
        return self._state.state == MediaPlayerState.PAUSED

    @property
    def is_idle(self):
        """Return true if the device is idle."""
        return self._state.state == MediaPlayerState.IDLE

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        return self._state.state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._state.volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._state.muted

    @property
    def source(self):
        """Return the current input source."""
        return self._state.source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_list

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self._state.media_title

    async def async_update(self):
        """Fetch state from the device."""
        _LOGGER.debug("Updating state for %s", self._name)
        try:
            # Get power state
            power = await self.async_get_current_value("http://{ip}:15081/power", "system")
            if power == "lona":
                await self._state.update(power_state=MediaPlayerState.OFF)
            elif power == "on":
                transport_state = await self.async_get_current_value("http://{ip}:15081/nowplaying", "transportState")
                await self._state.update(
                    power_state=MediaPlayerState.ON,
                    playing_state=NAIM_TRANSPORT_STATE_TO_HA_STATE.get(transport_state, MediaPlayerState.ON),
                )

            # Get volume
            volume = await self.async_get_current_value("http://{ip}:15081/levels/room", "volume")
            if volume is not None:
                await self._state.update(volume=int(volume) / 100)

            # Get mute state
            mute = await self.async_get_current_value("http://{ip}:15081/levels/room", "mute")
            if mute is not None:
                await self._state.update(muted=bool(int(mute)))

            # Update media info
            await self.update_media_info()

        except aiohttp.ClientError as error:
            _LOGGER.error("Error fetching state for %s: %s", self._name, error)

    async def update_media_info(self):
        """Update media info from nowplaying endpoint."""
        updates = {
            "title": await self.async_get_current_value("http://{ip}:15081/nowplaying", "title"),
            "artist": await self.async_get_current_value("http://{ip}:15081/nowplaying", "artistName"),
            "album": await self.async_get_current_value("http://{ip}:15081/nowplaying", "albumName"),
            "duration": await self.async_get_current_value("http://{ip}:15081/nowplaying", "duration"),
            "position": await self.async_get_current_value("http://{ip}:15081/nowplaying", "transportPosition"),
            "image_url": await self.async_get_current_value("http://{ip}:15081/nowplaying", "artwork"),
        }

        device_source = await self.async_get_current_value("http://{ip}:15081/nowplaying", "source")
        if device_source:
            updates["source"] = next((k for k, v in self._source_map.items() if v == device_source), self._state.source)

        await self._state.update(**updates)

    async def async_turn_on(self):
        """Turn the media player on."""
        _LOGGER.info("Turning on %s", self._name)
        try:
            await async_get_clientsession(self._hass).put(f"http://{self._ip_address}:15081/power?system=on")
            await self.update_state()
            _LOGGER.debug("Successfully turned on %s", self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error turning on %s: %s", self._name, error)

    async def async_turn_off(self):
        """Turn the media player off."""
        _LOGGER.info("Turning off %s", self._name)
        try:
            await async_get_clientsession(self._hass).put(f"http://{self._ip_address}:15081/power?system=lona")
            await self.update_state()
            _LOGGER.debug("Successfully turned off %s", self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error turning off %s: %s", self._name, error)

    async def update_state(self) -> None:
        """Update the state of the media player."""
        _LOGGER.info("Updating state for %s", self._name)
        state = await self.async_get_current_value("http://{ip}:15081/power", "system")
        if state == "lona":
            await self._state.update(power_state=MediaPlayerState.OFF)
        elif state == "on":
            transport_state = await self.async_get_current_value("http://{ip}:15081/nowplaying", "transportState")
            await self._state.update(
                power_state=MediaPlayerState.ON,
                playing_state=NAIM_TRANSPORT_STATE_TO_HA_STATE.get(transport_state, MediaPlayerState.ON),
            )
        _LOGGER.debug(
            f"Power state updated to {self._state.power_state}, "
            f"playing state to {self._state.playing_state} for {self._name}"
        )

    async def async_mute_volume(self, mute):
        """Mute the volume."""
        _LOGGER.info("Setting mute to %s for %s", mute, self._name)
        try:
            current_mute = await self.async_get_current_value("http://{ip}:15081/levels/room", "mute")
            if current_mute is not None:
                # Use the mute parameter directly instead of toggling
                mute_value = int(bool(mute))
                await async_get_clientsession(self._hass).put(
                    f"http://{self._ip_address}:15081/levels/room?mute={mute_value}"
                )
                await self._state.update(muted=bool(mute_value))
                _LOGGER.debug("Successfully set mute to %s for %s", self._state.muted, self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error setting mute for %s: %s", self._name, error)

    async def _set_volume(self, volume: float) -> None:
        try:
            # Round to nearest 0.05 and ensure between 0-1
            volume = max(0.0, min(1.0, volume))
            volume = round_to_nearest(volume)
            device_volume = int(volume * 100)

            await async_get_clientsession(self._hass).put(
                f"http://{self._ip_address}:15081/levels/room?volume={device_volume}"
            )
            await self._state.update(volume=volume)
            _LOGGER.debug(
                "Successfully set volume to %s (%d%%) for %s",
                volume,
                device_volume,
                self._name,
            )
        except aiohttp.ClientError as error:
            _LOGGER.error("Error setting volume for %s: %s", self._name, error)

    async def async_set_volume_level(self, volume: float):
        """Set volume level, range 0..1."""
        _LOGGER.info("Setting volume to %s for %s", volume, self._name)
        await self._set_volume(volume)

    async def async_volume_up(self):
        """Increment volume by a fixed amount."""
        _LOGGER.info("Incrementing volume for %s, current volume is %s", self._name, self._state.volume)
        try:
            new_volume = min(1.0, self._state.volume + self._volume_step)
            new_volume = round_to_nearest(new_volume, step=self._volume_step)
            await self.async_set_volume_level(new_volume)
            _LOGGER.debug("Successfully incremented volume to %s for %s", new_volume, self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error incrementing volume for %s: %s", self._name, error)

    async def async_volume_down(self):
        """Decrement volume by a fixed amount."""
        _LOGGER.info("Decrementing volume for %s, current volume is %s", self._name, self._state.volume)
        try:
            new_volume = max(0.0, self._state.volume - self._volume_step)  # Decrement by 10%, min at 0%
            new_volume = round_to_nearest(new_volume, step=self._volume_step)
            await self.async_set_volume_level(new_volume)
            _LOGGER.debug("Successfully decremented volume to %s for %s", new_volume, self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error decrementing volume for %s: %s", self._name, error)

    async def async_select_source(self, source):
        """Select input source."""
        _LOGGER.info("Selecting source %s for %s", source, self._name)
        if source in self._source_list:
            try:
                input_id = self._source_map[source]
                await async_get_clientsession(self._hass).get(
                    f"http://{self._ip_address}:15081/inputs/{input_id}?cmd=select"
                )
                await self._state.update(source=source)
                _LOGGER.debug("Successfully selected source %s for %s", source, self._name)
            except aiohttp.ClientError as error:
                _LOGGER.error("Error selecting source for %s: %s", self._name, error)

    async def async_media_play(self):
        """Send play command."""
        await self.async_media_play_pause()

    async def async_media_pause(self):
        """Send pause command."""
        await self.async_media_play_pause()

    async def async_media_play_pause(self):
        """Send play/pause command."""
        _LOGGER.info("Toggling play/pause for %s", self._name)
        try:
            await async_get_clientsession(self._hass).get(f"http://{self._ip_address}:15081/nowplaying?cmd=playpause")
            await self.update_state()
            _LOGGER.debug("Successfully toggled play/pause for %s", self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error sending play/pause command: %s", error)

    async def async_media_next_track(self):
        """Send next track command."""
        _LOGGER.info("Sending next track command for %s", self._name)
        try:
            await async_get_clientsession(self._hass).get(f"http://{self._ip_address}:15081/nowplaying?cmd=next")
            _LOGGER.debug("Successfully sent next track command for %s", self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error sending next track command: %s", error)

    async def async_media_previous_track(self):
        """Send previous track command."""
        _LOGGER.info("Sending previous track command for %s", self._name)
        try:
            await async_get_clientsession(self._hass).get(f"http://{self._ip_address}:15081/nowplaying?cmd=prev")
            _LOGGER.debug("Successfully sent previous track command for %s", self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error sending previous track command: %s", error)

    async def async_media_seek(self, position):
        """Seek the media to a specific position."""
        _LOGGER.info("Seeking to position %s for %s", position, self._name)
        try:
            # Convert position to milliseconds for the API
            position_ms = int(position * 1000)
            await async_get_clientsession(self._hass).get(
                f"http://{self._ip_address}:15081/nowplaying?cmd=seek&position={position_ms}"
            )
            await self._state.update(position=position)
            _LOGGER.debug("Successfully seeked to position %s for %s", position, self._name)

        except aiohttp.ClientError as error:
            _LOGGER.error("Error seeking position for %s: %s", self._name, error)

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        await self._websocket.stop()
