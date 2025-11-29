import asyncio
import json
import logging

_LOGGER = logging.getLogger(__name__)


class NaimWebSocket:
    """Handle WebSocket connection to Naim device."""

    def __init__(self, ip_address: str, port: int, message_handler, reconnect_interval: int = 5):
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
                await asyncio.wait([self._task], timeout=1.0)
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout waiting for websocket to close")
            except Exception as err:
                _LOGGER.error("Error stopping websocket: %s", err)

    async def _socket_listener(self):
        """Listen to TCP socket updates from the device."""
        _LOGGER.info("Starting WebSocket listener at %s:%d", self.ip_address, self.port)

        while True:
            writer = None
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
                await asyncio.sleep(self.reconnect_interval)

            finally:
                self._connected = False
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception as error:
                        _LOGGER.warning("Error closing WebSocket connection: %s", error)
