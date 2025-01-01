import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.naim_media_player.client import NaimApiClient
from custom_components.naim_media_player.exceptions import NaimConnectionError


async def test_naim_api_client(hass):
    """Test NaimApiClient functionality."""
    # Create the client
    client = NaimApiClient(hass, "192.168.1.100", 15081)

    with aioresponses() as mock:
        # Test successful API call
        mock.get("http://192.168.1.100:15081/test", payload={"test_var": "test_value"})
        result = await client.get_value("test", "test_var")
        assert result == "test_value"

        # Test failed API call
        mock.get("http://192.168.1.100:15081/test", exception=aiohttp.ClientError())
        with pytest.raises(NaimConnectionError):
            await client.get_value("test", "test_var")
