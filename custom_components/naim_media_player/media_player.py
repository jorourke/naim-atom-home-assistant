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

from .const import DEFAULT_NAME

PLATFORMS = [Platform.MEDIA_PLAYER]

_LOGGER = logging.getLogger(__name__)


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Naim Media Player from a config entry."""
    ip_address = entry.data[CONF_IP_ADDRESS]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    entity_id = entry.data.get("entity_id")

    async_add_entities([NaimPlayer(hass, name, ip_address, entity_id)], True)


class NaimPlayer(MediaPlayerEntity):
    """Representation of a Naim Player."""

    def __init__(self, hass, name, ip_address, entity_id=None):
        """Initialize the media player."""
        _LOGGER.info("Initializing Naim Control media player: %s at %s", name, ip_address)
        self._hass = hass
        self._name = name
        self._ip_address = ip_address

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
        self._state = MediaPlayerState.OFF
        self._playing_state = MediaPlayerState.IDLE
        self._volume = 0.0
        self._muted = False
        self._source = None
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

        # WebSocket connection
        self._socket_task = None
        self._socket_reconnect_interval = 5  # seconds
        self._socket_connected = False

        # Start WebSocket connection
        self._socket_task = asyncio.create_task(self._socket_listener())

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

    async def _socket_listener(self):
        """Listen to TCP socket updates from the device."""
        _LOGGER.info("Starting WebSocket listener for %s at %s:4545", self._name, self._ip_address)
        buffer = ""
        decoder = json.JSONDecoder()
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self._ip_address, 4545)
                self._socket_connected = True
                _LOGGER.info("WebSocket connected successfully to %s:4545", self._ip_address)

                while True:
                    try:
                        data = await reader.read(4096)
                        if not data:
                            _LOGGER.warning("Connection closed by server")
                            break

                        buffer += data.decode("utf-8")
                        while buffer:
                            try:
                                # Attempt to decode a JSON object from the buffer
                                obj, idx = decoder.raw_decode(buffer)
                                message = buffer[:idx]
                                buffer = buffer[idx:]
                                _LOGGER.debug("Parsed JSON object: %s", message)
                                await self._handle_socket_message(message)
                            except json.JSONDecodeError:
                                # Not enough data to decode a full JSON object
                                break
                    except Exception as error:
                        _LOGGER.error("Error receiving data: %s", error)
                        break

            except Exception as error:
                self._socket_connected = False
                _LOGGER.error(
                    "WebSocket connection failed for %s (%s:4545): %s. Retrying in %s seconds",
                    self._name,
                    self._ip_address,
                    str(error),
                    self._socket_reconnect_interval,
                )
                await asyncio.sleep(self._socket_reconnect_interval)

            finally:
                self._socket_connected = False
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception as error:
                        _LOGGER.warning("Error closing WebSocket connection: %s", error)

    async def _handle_socket_message(self, message):
        """Handle socket message."""
        try:
            data = json.loads(message)
            _LOGGER.debug("Parsed socket message data: %s", data)

            # Flag to track if any state has changed
            state_changed = False

            # Extract the 'data' dictionary
            live_status = data.get("data", {})
            _LOGGER.debug("Processing live status data: %s", live_status)

            # Update media title
            new_media_title = live_status.get("trackRoles", {}).get("title")
            if new_media_title != self._media_title:
                self._media_title = new_media_title
                _LOGGER.debug("Updated media title to: %s", self._media_title)
                state_changed = True

            # Update media artist
            new_media_artist = live_status.get("trackRoles", {}).get("mediaData", {}).get("metaData", {}).get("artist")
            if new_media_artist != self._media_artist:
                self._media_artist = new_media_artist
                _LOGGER.debug("Updated media artist to: %s", self._media_artist)
                state_changed = True

            # Update media album name
            new_media_album_name = (
                live_status.get("trackRoles", {}).get("mediaData", {}).get("metaData", {}).get("album")
            )
            if new_media_album_name != self._media_album_name:
                self._media_album_name = new_media_album_name
                _LOGGER.debug("Updated media album name to: %s", self._media_album_name)
                state_changed = True

            # Update playback state
            playing_state_str = live_status.get("state")
            new_playing_state = TRANSPORT_STATES_STRING_LOOKUP.get(playing_state_str, self._playing_state)
            if new_playing_state != self._playing_state:
                self._playing_state = new_playing_state
                _LOGGER.debug("Updated playing state to: %s", self._playing_state)
                state_changed = True

            # Update media image URL
            new_media_image_url = live_status.get("trackRoles", {}).get("icon")
            if new_media_image_url != self._media_image_url:
                self._media_image_url = new_media_image_url
                _LOGGER.debug("Updated media image URL to: %s", self._media_image_url)
                state_changed = True

            # Update media duration
            new_media_duration_ms = live_status.get("status", {}).get("duration")
            if new_media_duration_ms is not None:
                try:
                    new_media_duration = float(new_media_duration_ms) / 1000  # Convert to seconds
                    if new_media_duration != self._media_duration:
                        self._media_duration = new_media_duration
                        _LOGGER.debug("Updated media duration to: %s seconds", self._media_duration)
                        state_changed = True
                except (ValueError, TypeError):
                    _LOGGER.warning("Invalid media duration value received: %s", new_media_duration_ms)

            # Update media position
            new_media_position_ms = data.get("playTime", {}).get("i64_")
            if new_media_position_ms is not None:
                new_media_position = new_media_position_ms / 1000  # Convert to seconds
                if new_media_position != self._media_position:
                    self._media_position = new_media_position
                    _LOGGER.debug("Updated media position to: %s seconds", self._media_position)
                    state_changed = True

            # Update volume
            new_volume = data.get("senderVolume", {}).get("i32_")
            if new_volume is not None:
                new_volume_level = int(new_volume) / 100
                if new_volume_level != self._volume:
                    self._volume = new_volume_level
                    _LOGGER.debug("Updated volume level to: %s", self._volume)
                    state_changed = True

            # Update mute state if provided
            new_muted = data.get("senderMute", {}).get("i32_")
            if new_muted is not None:
                new_muted_bool = bool(int(new_muted))
                if new_muted_bool != self._muted:
                    self._muted = new_muted_bool
                    _LOGGER.debug("Updated mute state to: %s", self._muted)
                    state_changed = True

            # Update source
            new_source = live_status.get("contextPath")
            if new_source is not None and new_source != self._source:
                if new_source.startswith("spotify"):
                    new_source = "Spotify"
                self._source = new_source
                _LOGGER.debug("Updated source to: %s", self._source)
                state_changed = True

            if state_changed:
                _LOGGER.debug("State changed, updating Home Assistant")
                self.async_write_ha_state()
            else:
                _LOGGER.debug("State unchanged, no update required")

        except json.JSONDecodeError as error:
            _LOGGER.error("Error parsing socket message for %s: %s", self._name, error)
        except Exception as error:
            _LOGGER.error("Error handling socket message for %s: %s", self._name, error)

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
        return self._media_image_url

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        return self._media_duration

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        return self._media_position

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media, music track only."""
        return self._media_album_name

    @property
    def media_artist(self) -> str | None:
        """Album artist of current playing media, music track only."""
        return self._media_artist

    @property
    def is_playing(self):
        """Return true if the device is playing."""
        return self.state == MediaPlayerState.PLAYING

    @property
    def is_paused(self):
        """Return true if the device is paused."""
        return self.state == MediaPlayerState.PAUSED

    @property
    def is_idle(self):
        """Return true if the device is idle."""
        return self.state == MediaPlayerState.IDLE

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if self._playing_state == MediaPlayerState.IDLE:
            return self._state
        return self._playing_state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def source(self):
        """Return the current input source."""
        return self._source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_list

    @property
    def media_title(self):
        """Title of current playing media."""
        return self._media_title

    async def async_update(self):
        """Fetch state from the device."""
        _LOGGER.debug("Updating state for %s", self._name)
        try:
            await self.update_state()
            # Get volume
            volume = await self.async_get_current_value("http://{ip}:15081/levels/room", "volume")
            if volume is not None:
                _LOGGER.debug("Volume retrieved: %s", volume)
                self._volume = int(volume) / 100

            # Get mute state
            mute = await self.async_get_current_value("http://{ip}:15081/levels/room", "mute")
            if mute is not None:
                self._muted = bool(int(mute))
                _LOGGER.debug("Mute state: %s", self._muted)

            await self.update_media_info()

        except aiohttp.ClientError as error:
            _LOGGER.error("Error fetching state for %s: %s", self._name, error)

    async def update_media_info(self):
        """Update media info from nowplaying endpoint."""
        self._media_title = await self.async_get_current_value("http://{ip}:15081/nowplaying", "title")
        self._media_artist = await self.async_get_current_value("http://{ip}:15081/nowplaying", "artistName")
        self._media_album_name = await self.async_get_current_value("http://{ip}:15081/nowplaying", "albumName")
        self._media_duration = await self.async_get_current_value("http://{ip}:15081/nowplaying", "duration")
        self._media_position = await self.async_get_current_value("http://{ip}:15081/nowplaying", "transportPosition")
        self._media_image_url = await self.async_get_current_value("http://{ip}:15081/nowplaying", "artwork")
        device_source = await self.async_get_current_value("http://{ip}:15081/nowplaying", "source")
        self._source = next((k for k, v in self._source_map.items() if v == device_source), self._source)
        _LOGGER.debug("Media title: %s", self._media_title)
        _LOGGER.debug("Media artist: %s", self._media_artist)
        _LOGGER.debug("Media album: %s", self._media_album_name)
        _LOGGER.debug("Media duration: %s", self._media_duration)
        _LOGGER.debug("Media position: %s", self._media_position)
        _LOGGER.debug("Media image URL: %s", self._media_image_url)
        _LOGGER.debug("Source: %s", self._source)

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

    async def update_state(self):
        """Update the state of the media player."""
        _LOGGER.info("Updating state for %s", self._name)
        state = await self.async_get_current_value("http://{ip}:15081/power", "system")
        if state == "lona":
            self._state = MediaPlayerState.OFF
        elif state == "on":
            transport_state = await self.async_get_current_value("http://{ip}:15081/nowplaying", "transportState")
            self._state = NAIM_TRANSPORT_STATE_TO_HA_STATE.get(transport_state, MediaPlayerState.ON)
            _LOGGER.debug("State updated to %s for %s", self._state, self._name)

    async def async_mute_volume(self, mute):
        """Mute the volume."""
        _LOGGER.info("Setting mute to %s for %s", mute, self._name)
        try:
            current_mute = await self.async_get_current_value("http://{ip}:15081/levels/room", "mute")
            if current_mute is not None:
                value = int(not (int(current_mute) > 0))
                await async_get_clientsession(self._hass).put(
                    f"http://{self._ip_address}:15081/levels/room?mute={value}"
                )
                self._muted = bool(value)
                _LOGGER.debug("Successfully set mute to %s for %s", self._muted, self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error setting mute for %s: %s", self._name, error)

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        _LOGGER.info("Setting volume to %s for %s", volume, self._name)
        try:
            device_volume = int(volume * 100)
            self._volume = volume
            await async_get_clientsession(self._hass).put(
                f"http://{self._ip_address}:15081/levels/room?volume={device_volume}"
            )
            _LOGGER.info(
                "Successfully set volume to %s for %s, current volume is now %s",
                volume,
                self._name,
                self._volume,
            )
        except aiohttp.ClientError as error:
            _LOGGER.error("Error setting volume for %s: %s", self._name, error)

    async def async_volume_up(self):
        """Increment volume by a fixed amount."""
        _LOGGER.info("Incrementing volume for %s, current volume is %s", self._name, self._volume)
        try:
            new_volume = min(1.0, self._volume + CONST_VOLUME_STEP)  # Increment by 10%, max at 100%
            await self.async_set_volume_level(new_volume)
            _LOGGER.debug("Successfully incremented volume to %s for %s", new_volume, self._name)
        except aiohttp.ClientError as error:
            _LOGGER.error("Error incrementing volume for %s: %s", self._name, error)

    async def async_volume_down(self):
        """Decrement volume by a fixed amount."""
        _LOGGER.info("Decrementing volume for %s, current volume is %s", self._name, self._volume)
        try:
            new_volume = max(0.0, self._volume - CONST_VOLUME_STEP)  # Decrement by 10%, min at 0%
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
                self._source = source
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
            self._media_position = position
            _LOGGER.debug("Successfully seeked to position %s for %s", position, self._name)

        except aiohttp.ClientError as error:
            _LOGGER.error("Error seeking position for %s: %s", self._name, error)

    async def async_will_remove_from_hass(self):
        """Clean up when entity is removed."""
        if self._socket_task:
            self._socket_task.cancel()
            try:
                await self._socket_task
            except asyncio.CancelledError:
                pass
