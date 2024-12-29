import asyncio


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

    async def start(self):
        """Start the WebSocket connection."""
        self._task = asyncio.create_task(self._listener())

    async def stop(self):
        """Stop the WebSocket connection."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
