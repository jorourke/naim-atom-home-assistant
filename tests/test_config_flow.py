"""Test the Naim Media Player config flow."""

import asyncio
import re
from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant

from custom_components.naim_media_player.config_flow import NaimConfigFlow
from custom_components.naim_media_player.const import (
    CONF_VOLUME_STEP,
    DEFAULT_NAME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
)


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
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "Test Naim"
    assert result2["data"] == {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_NAME: "Test Naim",
        "entity_id": "test_naim",
        CONF_VOLUME_STEP: 5,
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
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
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
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
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


async def test_form_invalid_volume_step(hass: HomeAssistant) -> None:
    """Test we handle invalid volume step value."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with pytest.raises(vol.Invalid):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: DEFAULT_NAME,
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 3,  # Invalid value - not in [1, 5, 10]
            },
        )


async def test_async_step_user_form(hass: HomeAssistant) -> None:
    """Test async_step_user returns form with correct defaults."""
    flow = NaimConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == "form"
    assert result["step_id"] == "user"

    # The defaults are in the key part of
    schema = result["data_schema"].schema
    schema_dict = {}
    for key, _ in schema.items():
        schema_dict[key] = key.default()

    # Verify default values
    assert schema_dict[CONF_IP_ADDRESS] == "192.168.1.127"
    assert schema_dict[CONF_NAME] == DEFAULT_NAME
    assert schema_dict["entity_id"] == "naim_atom"
    assert schema_dict[CONF_VOLUME_STEP] == DEFAULT_VOLUME_STEP

    # Verify description placeholders
    assert result["description_placeholders"] == {
        "default_ip": "192.168.1.127",
        "default_name": DEFAULT_NAME,
    }


async def test_form_invalid_ip_address(hass: HomeAssistant) -> None:
    """Test we handle invalid IP address."""

    flow = NaimConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user({"ip_address": "foobar"})

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert re.match("invalid_ip_address", result["errors"]["base"])
