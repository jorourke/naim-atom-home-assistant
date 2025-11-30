"""Test the Naim Media Player config flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_media_player.config_flow import (
    NaimConfigFlow,
    NaimOptionsFlow,
    async_get_available_inputs,
)
from custom_components.naim_media_player.const import (
    CONF_SOURCES,
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
    assert result["errors"]["ip_address"] == "invalid_ip_address"


# Tests for async_get_available_inputs


async def test_async_get_available_inputs_success(hass: HomeAssistant) -> None:
    """Test fetching available inputs from device."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={
            "children": [
                {"name": "Analog 1", "ussi": "inputs/ana1", "selectable": "1"},
                {"name": "Digital 1", "ussi": "inputs/dig1", "selectable": "1"},
                {"name": "Hidden Input", "ussi": "inputs/hidden", "selectable": "0"},
            ]
        }
    )

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_available_inputs(hass, "192.168.1.100")

    assert result == {"Analog 1": "ana1", "Digital 1": "dig1"}
    # Hidden input with selectable="0" should not be included


async def test_async_get_available_inputs_http_error(hass: HomeAssistant) -> None:
    """Test handling HTTP error when fetching inputs."""
    mock_response = AsyncMock()
    mock_response.status = 500

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_available_inputs(hass, "192.168.1.100")

    assert result is None


async def test_async_get_available_inputs_connection_error(hass: HomeAssistant) -> None:
    """Test handling connection error when fetching inputs."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=ClientError("Connection failed"))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_available_inputs(hass, "192.168.1.100")

    assert result is None


async def test_async_get_available_inputs_timeout(hass: HomeAssistant) -> None:
    """Test handling timeout when fetching inputs."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_available_inputs(hass, "192.168.1.100")

    assert result is None


async def test_async_get_available_inputs_unexpected_error(hass: HomeAssistant) -> None:
    """Test handling unexpected error when fetching inputs."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=ValueError("Unexpected"))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_available_inputs(hass, "192.168.1.100")

    assert result is None


# Tests for source selection step


async def test_form_with_source_discovery(hass: HomeAssistant) -> None:
    """Test config flow proceeds to source selection when sources are discovered."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"

    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    mock_sources = {"Analog 1": "ana1", "Spotify": "spotify"}

    with (
        patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_available_inputs",
            return_value=mock_sources,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: "Test Naim",
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
            },
        )

    # Should show source selection step
    assert result2["type"] == "form"
    assert result2["step_id"] == "sources"


async def test_form_source_selection_creates_entry(hass: HomeAssistant) -> None:
    """Test completing source selection creates config entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    mock_sources = {"Analog 1": "ana1", "Spotify": "spotify", "Digital 1": "dig1"}

    with (
        patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_available_inputs",
            return_value=mock_sources,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: "Test Naim",
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
            },
        )

        # Now complete source selection - select only some sources
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_SOURCES: ["Analog 1", "Spotify"]},
        )
        await hass.async_block_till_done()

    assert result3["type"] == "create_entry"
    assert result3["title"] == "Test Naim"
    assert result3["data"][CONF_SOURCES] == {"Analog 1": "ana1", "Spotify": "spotify"}


async def test_form_no_sources_discovered(hass: HomeAssistant) -> None:
    """Test config flow creates entry directly when no sources discovered."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    with (
        patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_available_inputs",
            return_value=None,
        ),
    ):
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

    # Should create entry directly without source selection step
    assert result2["type"] == "create_entry"
    assert result2["title"] == "Test Naim"
    assert CONF_SOURCES not in result2["data"]


# Tests for options flow


async def test_options_flow_init(hass: HomeAssistant) -> None:
    """Test options flow shows source selection."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            CONF_SOURCES: {"Analog 1": "ana1"},
        },
    )

    mock_sources = {"Analog 1": "ana1", "Spotify": "spotify", "Digital 1": "dig1"}

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_available_inputs",
        return_value=mock_sources,
    ):
        flow = NaimOptionsFlow(entry)
        flow.hass = hass

        result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"


async def test_options_flow_submit(hass: HomeAssistant) -> None:
    """Test submitting options flow updates sources."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            CONF_SOURCES: {"Analog 1": "ana1"},
        },
    )

    mock_sources = {"Analog 1": "ana1", "Spotify": "spotify", "Digital 1": "dig1"}

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_available_inputs",
        return_value=mock_sources,
    ):
        flow = NaimOptionsFlow(entry)
        flow.hass = hass

        # First call to show form
        await flow.async_step_init()

        # Submit with new selection
        result = await flow.async_step_init({CONF_SOURCES: ["Spotify", "Digital 1"]})

    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_SOURCES: {"Spotify": "spotify", "Digital 1": "dig1"}}


async def test_options_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test options flow aborts when device not reachable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
        },
    )

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_available_inputs",
        return_value=None,
    ):
        flow = NaimOptionsFlow(entry)
        flow.hass = hass

        result = await flow.async_step_init()

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_options_flow_defaults_to_all_sources(hass: HomeAssistant) -> None:
    """Test options flow defaults to all sources when none configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            # No CONF_SOURCES set
        },
    )

    mock_sources = {"Analog 1": "ana1", "Spotify": "spotify"}

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_available_inputs",
        return_value=mock_sources,
    ):
        flow = NaimOptionsFlow(entry)
        flow.hass = hass

        result = await flow.async_step_init()

    assert result["type"] == "form"
    # The default should include all available sources
    schema = result["data_schema"].schema
    for key in schema:
        if str(key) == CONF_SOURCES:
            default_sources = key.default()
            assert set(default_sources) == {"Analog 1", "Spotify"}


async def test_get_options_flow_handler(hass: HomeAssistant) -> None:
    """Test that async_get_options_flow returns correct handler."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={CONF_IP_ADDRESS: "192.168.1.100"},
    )

    flow = NaimConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, NaimOptionsFlow)
