import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional, Union

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .exceptions import NaimConnectionError

_LOGGER = logging.getLogger(__name__)


class NaimWebSocketClient:
    """Handle WebSocket connection to Naim device."""

    def __init__(self, ip_address: str, port: int, message_handler: Callable, reconnect_interval: int = 5):
        """Initialize the WebSocket connection."""
        self.ip_address = ip_address
        self.port = port
        self.message_handler = message_handler
        self.reconnect_interval = reconnect_interval
        self._task = None
        self._connected = False
        self._buffer = ""
        self._decoder = json.JSONDecoder()

    async def start(self):
        """Start the WebSocket connection."""
        self._task = asyncio.create_task(self._socket_listener())

    async def stop(self):
        """Stop the WebSocket connection."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                done, pending = await asyncio.wait([self._task], timeout=1.0)
                if pending:
                    _LOGGER.warning("Timeout waiting for websocket to close")
            except Exception as err:
                _LOGGER.error("Error stopping websocket: %s", err)

    async def _socket_listener(self):
        """Listen to TCP socket updates from the device."""
        _LOGGER.info("Starting WebSocket listener at %s:%d", self.ip_address, self.port)

        while True:
            writer = None
            # Clear buffer at the start of each connection attempt to prevent
            # stale partial JSON data from previous connections
            self._buffer = ""
            try:
                reader, writer = await asyncio.open_connection(self.ip_address, self.port)
                self._connected = True
                _LOGGER.info("WebSocket connected successfully to %s:%d", self.ip_address, self.port)

                while True:
                    try:
                        data = await reader.read(4096)
                        if not data:
                            _LOGGER.warning("Connection closed by server")
                            break

                        self._buffer += data.decode("utf-8")
                        while self._buffer:
                            try:
                                # Attempt to decode a JSON object from the buffer
                                obj, idx = self._decoder.raw_decode(self._buffer)
                                message = self._buffer[:idx]
                                self._buffer = self._buffer[idx:]
                                await self.message_handler(message)
                            except json.JSONDecodeError:
                                # Not enough data to decode a full JSON object
                                break
                    except Exception as error:
                        _LOGGER.error("Error receiving data: %s", error)
                        break

            except Exception as error:
                self._connected = False
                # Log as debug since device being offline is expected during normal operation
                _LOGGER.debug(
                    "WebSocket connection failed (%s:%d): %s. Retrying in %s seconds",
                    self.ip_address,
                    self.port,
                    str(error),
                    self.reconnect_interval,
                )

            finally:
                self._connected = False
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception as error:
                        _LOGGER.warning("Error closing WebSocket connection: %s", error)

            # Always delay before reconnecting to avoid hammering the device
            # This handles both initial connection failures and connection drops
            await asyncio.sleep(self.reconnect_interval)


class NaimApiClient:
    """Client to handle Naim HTTP API and WebSocket requests."""

    def __init__(
        self,
        hass: HomeAssistant,
        ip_address: str,
        http_port: int = 15081,
        ws_port: int = 4545,
        websocket_message_handler: Optional[Callable] = None,
        websocket_reconnect_interval: int = 5,
        request_timeout: float = 10.0,
        max_retries: int = 3,
    ):
        """Initialize the API client."""
        self._hass = hass
        self._ip_address = ip_address
        self._http_port = http_port
        self._ws_port = ws_port
        self._session = async_get_clientsession(hass)
        self._request_timeout = request_timeout
        self._max_retries = max_retries

        # Initialize WebSocket client if a message handler is provided
        self._websocket = None
        if websocket_message_handler:
            self._websocket = NaimWebSocketClient(
                ip_address=ip_address,
                port=ws_port,
                message_handler=websocket_message_handler,
                reconnect_interval=websocket_reconnect_interval,
            )

    async def start_websocket(self):
        """Start the WebSocket connection if available."""
        if self._websocket:
            await self._websocket.start()

    async def stop_websocket(self):
        """Stop the WebSocket connection if running."""
        if self._websocket:
            await self._websocket.stop()

    async def get_value(self, endpoint: str, variable: str) -> Any:
        """Get value from API endpoint with retries."""
        for retry in range(self._max_retries):
            try:
                url = f"http://{self._ip_address}:{self._http_port}/{endpoint}"
                async with self._session.get(url, timeout=self._request_timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get(variable)
                    else:
                        _LOGGER.error("Error response %s from GET %s", response.status, url)

                # If we got here, it means we didn't get a 200 response
                # Wait before retrying (exponential backoff)
                if retry < self._max_retries - 1:  # Don't sleep after the last attempt
                    await asyncio.sleep(2**retry)

            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout getting %s from %s (attempt %d/%d)", variable, endpoint, retry + 1, self._max_retries
                )
                # Wait before retrying
                if retry < self._max_retries - 1:
                    await asyncio.sleep(2**retry)
            except aiohttp.ClientError as error:
                raise NaimConnectionError(f"Failed to get {variable} from {endpoint}: {error}") from error

        # If we got here, we've exhausted all retries
        raise NaimConnectionError(f"Failed to get {variable} from {endpoint} after {self._max_retries} attempts")

    async def set_value(self, endpoint: str, params: Dict[str, Union[str, int, bool]]) -> bool:
        """Set value through API endpoint with retries."""
        for retry in range(self._max_retries):
            try:
                url = f"http://{self._ip_address}:{self._http_port}/{endpoint}"
                async with self._session.put(url, params=params, timeout=self._request_timeout) as response:
                    if response.status == 200:
                        return True
                    else:
                        _LOGGER.error("Error response %s from PUT %s with params %s", response.status, url, params)

                # If we got here, it means we didn't get a 200 response
                # Wait before retrying (exponential backoff)
                if retry < self._max_retries - 1:  # Don't sleep after the last attempt
                    await asyncio.sleep(2**retry)

            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout setting values to %s (attempt %d/%d)", endpoint, retry + 1, self._max_retries)
                # Wait before retrying
                if retry < self._max_retries - 1:
                    await asyncio.sleep(2**retry)
            except aiohttp.ClientError as error:
                raise NaimConnectionError(f"Failed to set values to {endpoint}: {error}") from error

        # If we got here, we've exhausted all retries
        raise NaimConnectionError(f"Failed to set values to {endpoint} after {self._max_retries} attempts")

    async def send_command(self, endpoint: str, cmd: str, **params) -> bool:
        """Send command to device."""
        command_params = {"cmd": cmd}
        command_params.update(params)

        for retry in range(self._max_retries):
            try:
                url = f"http://{self._ip_address}:{self._http_port}/{endpoint}"
                async with self._session.get(url, params=command_params, timeout=self._request_timeout) as response:
                    if response.status == 200:
                        return True
                    else:
                        _LOGGER.error(
                            "Error response %s from command %s to %s with params %s", response.status, cmd, url, params
                        )

                # If we got here, it means we didn't get a 200 response
                # Wait before retrying (exponential backoff)
                if retry < self._max_retries - 1:  # Don't sleep after the last attempt
                    await asyncio.sleep(2**retry)

            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout sending command %s to %s (attempt %d/%d)", cmd, endpoint, retry + 1, self._max_retries
                )
                # Wait before retrying
                if retry < self._max_retries - 1:
                    await asyncio.sleep(2**retry)
            except aiohttp.ClientError as error:
                raise NaimConnectionError(f"Failed to send command {cmd} to {endpoint}: {error}") from error

        # If we got here, we've exhausted all retries
        raise NaimConnectionError(f"Failed to send command {cmd} to {endpoint} after {self._max_retries} attempts")

    async def select_input(self, input_id: str) -> bool:
        """Select input source."""
        return await self.send_command(f"inputs/{input_id}", "select")
