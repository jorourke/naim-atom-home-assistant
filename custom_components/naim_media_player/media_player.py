"""Media player entity for Naim devices."""

import logging
import time
from datetime import datetime, timedelta

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .client import NaimClient
from .config_flow import get_max_volume
from .const import (
    CONF_SERIAL,
    CONF_SOURCES,
    CONF_VOLUME_STEP,
    DEFAULT_HTTP_PORT,
    DEFAULT_MAX_VOLUME,
    DEFAULT_MODEL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
    INPUT_REFRESH_INTERVAL,
)
from .state import NaimPlayerState

_LOGGER = logging.getLogger(__name__)

# power_state has no push channel — the WebSocket streams nowplaying heartbeats
# continuously even while the device is in standby, so polling /power is the only
# way to detect an externally-triggered power-on (e.g. via Spotify Connect).
SCAN_INTERVAL = timedelta(seconds=3)
# The device can report standby for ~20s after being woken (see CLAUDE.md).
WAKE_GRACE_SECONDS = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Naim Media Player from a config entry."""
    ip_address = entry.data[CONF_IP_ADDRESS]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    entity_id = entry.data.get("entity_id")
    volume_step = entry.options.get(
        CONF_VOLUME_STEP,
        entry.data.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP),
    )
    sources = entry.options.get(CONF_SOURCES) or entry.data.get(CONF_SOURCES)
    serial = entry.data.get(CONF_SERIAL)

    max_volume = get_max_volume(entry)

    player = NaimPlayer(hass, name, ip_address, entity_id, volume_step, sources, serial, entry.unique_id, max_volume)
    entry.runtime_data = player  # read by diagnostics
    async_add_entities([player], True)


class NaimPlayer(MediaPlayerEntity):
    """Thin Home Assistant entity adapter for Naim devices."""

    _BASE_FEATURES = (
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
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    # Controls a source can restrict (state.restrictions) and the feature each one removes.
    _RESTRICTION_FEATURES = {
        "pause": MediaPlayerEntityFeature.PAUSE,
        "seek": MediaPlayerEntityFeature.SEEK,
        "next": MediaPlayerEntityFeature.NEXT_TRACK,
        "previous": MediaPlayerEntityFeature.PREVIOUS_TRACK,
    }

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
        serial: str | None = None,
        unique_id: str | None = None,
        max_volume: int = DEFAULT_MAX_VOLUME,
    ) -> None:
        """Initialize the media player.

        `unique_id` should be the config entry's unique_id (computed once by
        config_flow.py from `serial or ip_address`), so the entity never
        derives a different identity than the config entry. If omitted (e.g.
        direct instantiation), it falls back to the same `serial or
        ip_address` rule to avoid a second, competing fallback string.
        """
        _LOGGER.info("Initializing Naim media player: %s at %s", name, ip_address)
        self._hass = hass
        self._attr_name = name
        self._ip_address = ip_address
        self._volume_step = volume_step / 100
        self._max_volume = max_volume

        if entity_id:
            self.entity_id = f"media_player.{entity_id}"
        # Otherwise leave entity_id unset so Home Assistant derives it from the name.

        self._attr_unique_id = unique_id or serial or ip_address
        self._attr_device_info = (
            DeviceInfo(
                identifiers={(DOMAIN, serial)},
                manufacturer="Naim",
                model=DEFAULT_MODEL,
                name=name,
            )
            if serial
            else None
        )
        self._source_map = sources if sources else self.DEFAULT_SOURCE_MAP.copy()
        self._source_list = list(self._source_map.keys())
        self._input_names = {input_id: name for name, input_id in self._source_map.items()}
        self._turned_on_at = float("-inf")
        self._state = NaimPlayerState(
            on_change=self._write_state_when_registered,
            debounce_timeout=2.0,
        )
        self._client = NaimClient(
            hass=hass,
            host=ip_address,
            http_port=DEFAULT_HTTP_PORT,
            ws_port=DEFAULT_PORT,
            state=self._state,
        )

    def _write_state_when_registered(self) -> None:
        """Write HA state, skipping updates that arrive before HA registers the entity.

        The first poll runs during update_before_add, when entity_id is not yet
        assigned; writing then raises and aborts the entity add.
        """
        if self.hass is None or self.entity_id is None:
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Start push updates and the periodic input-name refresh."""
        await self._client.start_websocket()
        # Run once now, so renames show straight after a restart instead of on the first timer tick.
        self.hass.async_create_task(self._async_refresh_input_names())
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_refresh_input_names, timedelta(seconds=INPUT_REFRESH_INTERVAL)
            )
        )

    async def _async_refresh_input_names(self, _now: datetime | None = None) -> None:
        """Apply input renames made in the Naim app, in memory only.

        The config entry is never written: its update listener reloads the entry. The user's
        selected inputs (by ID) are kept, and inputs that appeared on the device are not added.
        """
        device_inputs = await self._client.get_inputs()
        if not device_inputs:
            _LOGGER.debug("Input name refresh skipped; keeping the current names")
            return
        device_names = {input_id: name for name, input_id in device_inputs.items()}
        source_map = {device_names.get(input_id, name): input_id for name, input_id in self._source_map.items()}
        if len(source_map) != len(self._source_map):
            _LOGGER.debug("Input name refresh skipped; renamed inputs would share a name")
            return
        if source_map == self._source_map:
            return
        self._source_map = source_map
        self._source_list = list(source_map)
        self._input_names = {input_id: name for name, input_id in source_map.items()}
        self._write_state_when_registered()

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Drop the controls the current source reports as restricted (e.g. pause on radio)."""
        features = self._BASE_FEATURES
        for control in self._state.restrictions:
            features &= ~self._RESTRICTION_FEATURES[control]
        return features

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Return the now-playing audio format the device reported, leaving out missing fields."""
        if self._state.state == MediaPlayerState.OFF:
            return {}
        return {f"audio_{key}": value for key, value in self._state.audio_format.items()}

    def _require_on(self) -> None:
        """Raise a clear error for transport commands, which the device ignores in standby.

        Right after turn_on the device keeps reporting standby for up to ~20s, so "turn on, then play"
        must not be refused in that window; the command is sent as it was before this check existed.
        """
        if self._state.state == MediaPlayerState.OFF and time.monotonic() - self._turned_on_at > WAKE_GRACE_SECONDS:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_in_standby")

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Browse the saved radio favourites."""
        favourites = await self._client.get_radio_favourites()
        return BrowseMedia(
            title="Radio favourites",
            media_class=MediaClass.DIRECTORY,
            media_content_id="favourites",
            media_content_type=MediaType.CHANNEL,
            can_play=False,
            can_expand=True,
            children=[
                BrowseMedia(
                    title=favourite["name"],
                    media_class=MediaClass.CHANNEL,
                    media_content_id=favourite["id"],
                    media_content_type=MediaType.CHANNEL,
                    can_play=True,
                    can_expand=False,
                    thumbnail=favourite["image"],
                )
                for favourite in favourites
            ],
        )

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Play a radio favourite chosen from the media browser."""
        self._require_on()
        if not media_id.startswith("inputs/radio/") or ".." in media_id.split("/"):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_media_id")
        await self._client.play_radio_item(media_id)

    @property
    def available(self) -> bool:
        """Return whether the device is available.

        Either channel proves the device is alive: a healthy poll or a live
        WebSocket. A transient drop of one channel must not flap the entity.
        """
        return bool(self._state.available or self._client.connected)

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
        """Return the configured name for the device's current input.

        The device reports its input as a path ("inputs/hdmi"); Home Assistant
        expects a member of `source_list`, so an input outside the configured
        map has no name to report.
        """
        raw = self._state.source
        if not raw:
            return None
        return self._input_names.get(raw.removeprefix("inputs/"))

    @property
    def source_list(self) -> list[str]:
        """Return available sources."""
        return self._source_list

    @property
    def media_title(self) -> str | None:
        """Return media title."""
        return self._state.media_info.title

    @property
    def media_artist(self) -> str | None:
        """Return media artist."""
        return self._state.media_info.artist

    @property
    def media_album_name(self) -> str | None:
        """Return media album."""
        return self._state.media_info.album

    @property
    def media_duration(self) -> int | float | None:
        """Return media duration."""
        return self._state.media_info.duration

    @property
    def media_position(self) -> int | float | None:
        """Return media position."""
        return self._state.media_info.position

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Return when the position was last updated, so HA can interpolate the progress bar."""
        return self._state.media_info.position_updated_at

    @property
    def media_image_url(self) -> str | None:
        """Return media image URL."""
        return self._state.media_info.image_url

    async def async_update(self) -> None:
        """Poll current device state."""
        await self._client.poll_state()

    async def async_turn_on(self) -> None:
        """Turn on the device."""
        await self._client.set_power(True)
        self._turned_on_at = time.monotonic()

    async def async_turn_off(self) -> None:
        """Turn off the device."""
        await self._client.set_power(False)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        volume = max(0.0, min(1.0, volume))
        current = int(round(self._state.volume * 100))
        # Cap only raises; never push the volume below where the device already is.
        await self._client.set_volume(min(int(round(volume * 100)), max(self._max_volume, current)))

    async def _async_step_volume(self, direction: int) -> None:
        """Change volume by one configured step in the given direction (+1/-1)."""
        current_percent = int(round(self._state.volume * 100))
        if direction > 0 and current_percent > self._max_volume:
            # Set from the Naim app: never pull the volume down on the user's behalf.
            return
        step_percent = int(round(self._volume_step * 100))
        target_percent = max(0, current_percent + direction * step_percent)
        if direction > 0:
            target_percent = min(self._max_volume, target_percent)
        await self._client.set_volume(target_percent)

    async def async_volume_up(self) -> None:
        """Increase volume by one configured step."""
        await self._async_step_volume(1)

    async def async_volume_down(self) -> None:
        """Decrease volume by one configured step."""
        await self._async_step_volume(-1)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute volume."""
        await self._client.set_mute(bool(mute))

    async def async_media_play(self) -> None:
        """Play or resume media."""
        self._require_on()
        await self._client.send_playback_command("playpause")

    async def async_media_pause(self) -> None:
        """Pause media."""
        self._require_on()
        await self._client.send_playback_command("playpause")

    async def async_media_stop(self) -> None:
        """Stop media."""
        self._require_on()
        await self._client.send_playback_command("stop")

    async def async_media_next_track(self) -> None:
        """Skip to the next track."""
        self._require_on()
        await self._client.send_playback_command("next")

    async def async_media_previous_track(self) -> None:
        """Skip to the previous track."""
        self._require_on()
        await self._client.send_playback_command("prev")

    async def async_media_seek(self, position: float) -> None:
        """Seek to a position in the current track."""
        self._require_on()
        await self._client.seek(max(0, round(position * 1000)))

    async def async_select_source(self, source: str) -> None:
        """Select a source."""
        if source in self._source_map:
            await self._client.select_input(self._source_map[source])

    async def async_will_remove_from_hass(self) -> None:
        """Clean up the WebSocket connection."""
        await self._client.stop_websocket()
