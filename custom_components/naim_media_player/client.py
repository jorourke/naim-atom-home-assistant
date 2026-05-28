"""Device communication client for Naim Media Player."""

import asyncio
import contextlib
import json
import logging
import random
from typing import Any

import aiohttp
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .exceptions import NaimConnectionError
from .state import (
    NAIM_TRANSPORT_STATE_TO_HA_STATE,
    TRANSPORT_STATES_STRING_LOOKUP,
    NaimPlayerState,
    NaimTransportState,
    TransportStateString,
)

_LOGGER = logging.getLogger(__name__)

MAX_BUFFER_SIZE = 65536


class NaimClient:
    """Consolidated HTTP API and WebSocket client for Naim devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        http_port: int,
        ws_port: int,
        state: NaimPlayerState,
        request_timeout: float = 10.0,
        max_retries: int = 3,
        ws_reconnect_interval: float = 5,
    ) -> None:
        """Initialize the client."""
        self._hass = hass
        self._host = host
        self._http_port = http_port
        self._ws_port = ws_port
        self._state = state
        self._session = async_get_clientsession(hass)
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._ws_reconnect_interval = ws_reconnect_interval
        self._ws_task: asyncio.Task | None = None
        self._connected = False
        self._buffer = ""
        self._decoder = json.JSONDecoder()

    async def get_value(self, endpoint: str, variable: str) -> Any:
        """Get a value from an API endpoint with retries."""
        data = await self._get_json(endpoint)
        return data.get(variable)

    async def set_value(self, endpoint: str, params: dict[str, str | int | bool]) -> bool:
        """Set values through an API endpoint with retries."""
        await self._request("put", endpoint, params=params)
        return True

    async def send_command(self, endpoint: str, cmd: str, **params) -> bool:
        """Send a command to the device with retries."""
        await self._request("get", endpoint, params={"cmd": cmd, **params})
        return True

    async def select_input(self, input_id: str) -> bool:
        """Select an input source."""
        return await self.send_command(f"inputs/{input_id}", "select")

    async def set_volume(self, volume: int) -> None:
        """Set device volume as an integer percentage."""
        volume = max(0, min(100, volume))
        await self._state.update(source="user", volume=volume / 100)
        await self.set_value("levels/room", {"volume": volume})

    async def set_mute(self, mute: bool) -> None:
        """Set device mute state."""
        await self._state.update(source="user", muted=mute)
        await self.set_value("levels/room", {"mute": int(mute)})

    async def set_power(self, on: bool) -> None:
        """Set device power state."""
        await self.set_value("power", {"system": "on" if on else "lona"})
        await self._state.update(
            source="user",
            power_state=MediaPlayerState.ON if on else MediaPlayerState.OFF,
        )

    async def send_playback_command(self, cmd: str) -> None:
        """Send a playback command."""
        await self.send_command("nowplaying", cmd)

    async def poll_state(self) -> None:
        """Fetch full device state via HTTP and write it to state."""
        power = await self._get_json_safe("power")
        if power is None:
            await self._state.update(source="poll", available=False)
            return

        await self._state.update(source="poll", available=True)

        if power.get("system") == "lona":
            await self._state.update(source="poll", power_state=MediaPlayerState.OFF)
            return

        nowplaying = await self._get_json_safe("nowplaying") or {}
        levels = await self._get_json_safe("levels/room") or {}

        transport = nowplaying.get("transportState")
        playing_state = self._transport_state_to_ha(transport)
        updates: dict[str, Any] = {
            "power_state": MediaPlayerState.ON,
            "playing_state": playing_state,
            "title": nowplaying.get("title"),
            "artist": nowplaying.get("artistName"),
            "album": nowplaying.get("albumName"),
            "duration": nowplaying.get("duration"),
            "position": nowplaying.get("transportPosition"),
            "image_url": nowplaying.get("artwork"),
        }

        if "volume" in levels:
            with contextlib.suppress(TypeError, ValueError):
                updates["volume"] = int(levels["volume"]) / 100
        if "mute" in levels:
            with contextlib.suppress(TypeError, ValueError):
                updates["muted"] = bool(int(levels["mute"]))
        if nowplaying.get("source"):
            updates["source_name"] = nowplaying["source"]

        await self._state.update(source="poll", **updates)

    async def start_websocket(self) -> None:
        """Start the WebSocket listener task."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._socket_listener())

    async def stop_websocket(self) -> None:
        """Stop the WebSocket listener task."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._ws_task, timeout=1.0)

    async def _socket_listener(self) -> None:
        """Listen to socket updates from the device."""
        _LOGGER.info("Starting WebSocket listener at %s:%d", self._host, self._ws_port)

        while True:
            writer = None
            self._buffer = ""
            try:
                reader, writer = await asyncio.open_connection(self._host, self._ws_port)
                self._connected = True
                _LOGGER.info("WebSocket connected to %s:%d", self._host, self._ws_port)

                await self.poll_state()

                while True:
                    data = await reader.read(4096)
                    if not data:
                        _LOGGER.warning("WebSocket connection closed by server")
                        break

                    self._buffer += data.decode("utf-8")
                    if len(self._buffer) > MAX_BUFFER_SIZE:
                        _LOGGER.warning("WebSocket buffer exceeded %d bytes; clearing", MAX_BUFFER_SIZE)
                        self._buffer = ""
                        continue

                    await self._drain_buffer()

            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.debug(
                    "WebSocket connection failed (%s:%d): %s",
                    self._host,
                    self._ws_port,
                    error,
                )
            finally:
                self._connected = False
                if writer is not None:
                    with contextlib.suppress(Exception):
                        writer.close()
                        await writer.wait_closed()

            jitter = random.uniform(0, self._ws_reconnect_interval * 0.3)
            await asyncio.sleep(self._ws_reconnect_interval + jitter)

    async def _handle_message(self, raw_message: str) -> None:
        """Parse a WebSocket JSON message and update state."""
        try:
            all_state = json.loads(raw_message)
        except json.JSONDecodeError as error:
            _LOGGER.error("Error parsing WebSocket message: %s", error)
            return

        state_data = all_state.get("data", {})
        updates: dict[str, Any] = {}

        track_roles = state_data.get("trackRoles", {})
        media_data = track_roles.get("mediaData", {}).get("metaData", {})
        if "title" in track_roles:
            updates["title"] = track_roles.get("title")
        if "artist" in media_data:
            updates["artist"] = media_data.get("artist")
        if "album" in media_data:
            updates["album"] = media_data.get("album")
        if "icon" in track_roles:
            updates["image_url"] = track_roles.get("icon")

        playing_state = state_data.get("state")
        if playing_state:
            updates["playing_state"] = self._transport_string_to_ha(playing_state)

        duration_ms = state_data.get("status", {}).get("duration")
        if duration_ms is not None:
            with contextlib.suppress(TypeError, ValueError):
                updates["duration"] = float(duration_ms) / 1000

        position_ms = all_state.get("playTime", {}).get("i64_")
        if position_ms is not None:
            with contextlib.suppress(TypeError, ValueError):
                updates["position"] = float(position_ms) / 1000

        source = self._extract_source(state_data)
        if source:
            updates["source_name"] = source

        await self._state.update(source="websocket", **updates)

    async def _get_json(self, endpoint: str) -> dict[str, Any]:
        """Get JSON from an endpoint with retries."""
        return await self._request("get", endpoint)

    async def _get_json_safe(self, endpoint: str) -> dict[str, Any] | None:
        """Get JSON from an endpoint, returning None on failure."""
        try:
            return await self._get_json(endpoint)
        except NaimConnectionError as error:
            _LOGGER.debug("Cannot reach device at %s for %s: %s", self._host, endpoint, error)
            return None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, str | int | bool] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request with retries."""
        url = f"http://{self._host}:{self._http_port}/{endpoint}"
        request = self._session.get if method == "get" else self._session.put

        for retry in range(self._max_retries):
            try:
                async with request(url, params=params, timeout=self._request_timeout) as response:
                    if response.status == 200:
                        if method == "get":
                            return await response.json()
                        return {}
                    _LOGGER.error("Error response %s from %s %s", response.status, method.upper(), url)
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout on %s %s (attempt %d/%d)",
                    method.upper(),
                    endpoint,
                    retry + 1,
                    self._max_retries,
                )
            except aiohttp.ClientError as error:
                raise NaimConnectionError(f"Failed to request {endpoint}: {error}") from error

            if retry < self._max_retries - 1:
                await asyncio.sleep(2**retry)

        raise NaimConnectionError(f"Failed to request {endpoint} after {self._max_retries} attempts")

    async def _drain_buffer(self) -> None:
        """Decode and handle complete JSON objects from the socket buffer."""
        while self._buffer:
            self._buffer = self._buffer.lstrip()
            if not self._buffer:
                return
            try:
                _obj, idx = self._decoder.raw_decode(self._buffer)
            except json.JSONDecodeError:
                return

            message = self._buffer[:idx]
            self._buffer = self._buffer[idx:]
            await self._handle_message(message)

    def _extract_source(self, live_status: dict[str, Any]) -> str | None:
        """Extract source name from WebSocket status data."""
        media_roles = live_status.get("mediaRoles", {})
        if media_roles:
            meta = media_roles.get("mediaData", {}).get("metaData", {})
            if meta.get("serviceID") == "roon":
                return "Roon"
            if media_roles.get("title"):
                return media_roles["title"]

        context = live_status.get("contextPath")
        if isinstance(context, str) and context.startswith("spotify"):
            return "Spotify"
        return None

    def _transport_state_to_ha(self, transport: Any) -> MediaPlayerState:
        """Map a Naim transport integer to Home Assistant state."""
        try:
            return NAIM_TRANSPORT_STATE_TO_HA_STATE[NaimTransportState(int(transport))]
        except (TypeError, ValueError, KeyError):
            return MediaPlayerState.ON

    def _transport_string_to_ha(self, transport: str) -> MediaPlayerState:
        """Map a Naim transport string to Home Assistant state."""
        try:
            return TRANSPORT_STATES_STRING_LOOKUP[TransportStateString(transport)]
        except ValueError:
            return MediaPlayerState.IDLE
