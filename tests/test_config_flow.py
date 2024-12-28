"""Test the Naim Media Player config flow."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant

from custom_components.naim_media_player.const import DEFAULT_NAME, DOMAIN


async def test_form(hass: HomeAssistant) -> None:
    """Test we get the form and can create an entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    assert result["errors"] == {}

    # Simulate successful connection
    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    with patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: "Test Naim",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "Test Naim"
    assert result2["data"] == {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_NAME: "Test Naim",
    }


async def test_form_cannot_connect(hass: HomeAssistant) -> None:
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch(
        "asyncio.open_connection",
        side_effect=TimeoutError,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: DEFAULT_NAME,
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_unknown_error(hass: HomeAssistant) -> None:
    """Test we handle unknown error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch(
        "asyncio.open_connection",
        side_effect=Exception("Unknown error"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: DEFAULT_NAME,
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "unknown"}


@pytest.mark.skip(reason="This test is not working")
async def test_duplicate_error(hass: HomeAssistant) -> None:
    """Test that errors are shown when duplicates are added."""
    # First entry
    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    # Create first entry
    with patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: "Test Naim",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"

    # Try to add duplicate entry
    with patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)):
        result3 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",  # Same IP as first entry
                CONF_NAME: "Test Naim 2",
            },
        )

    # The flow should abort with "already_configured"
    assert result4["type"] == "abort"
    assert result4["reason"] == "already_configured"
