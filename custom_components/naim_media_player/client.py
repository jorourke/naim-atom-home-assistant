from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .exceptions import NaimConnectionError


class NaimApiClient:
    """Client to handle Naim HTTP API requests."""

    def __init__(self, hass: HomeAssistant, ip_address: str, port: int):
        """Initialize the API client."""
        self._hass = hass
        self._ip_address = ip_address
        self._port = port
        self._session = async_get_clientsession(hass)

    async def get_value(self, endpoint: str, variable: str) -> Any:
        """Get value from API endpoint."""
        try:
            url = f"http://{self._ip_address}:{self._port}/{endpoint}"
            async with self._session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get(variable)
        except aiohttp.ClientError as error:
            raise NaimConnectionError(f"Failed to get {variable} from {endpoint}: {error}") from error
