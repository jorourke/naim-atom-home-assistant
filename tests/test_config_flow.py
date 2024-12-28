"""Test the Naim Control config flow."""

from unittest.mock import patch

import pytest
import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from custom_components.naim_media_player.const import DOMAIN, DEFAULT_NAME

# The bypass_get_data fixture will be used automatically
async def test_form(hass, bypass_get_data):
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: "1.1.1.1",
            CONF_NAME: "Naim Test",
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "Naim Test"


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "aiohttp.ClientSession.get",
        side_effect=aiohttp.ClientError,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "1.1.1.1",
                CONF_NAME: DEFAULT_NAME,
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_invalid_response(hass: HomeAssistant) -> None:
    """Test we handle invalid response error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "aiohttp.ClientSession.get",
        return_value=aiohttp.web.Response(
            status=200,
            body=b'{"invalid": "response"}',
            content_type="application/json",
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "1.1.1.1",
                CONF_NAME: DEFAULT_NAME,
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "invalid_response"}
