"""Test the Naim Media Player config flow."""

import asyncio
import time
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
    _async_fetch_device_json,
    async_get_available_inputs,
    async_get_device_serial,
)
from custom_components.naim_media_player.const import (
    CONF_SERIAL,
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

    with (
        patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_available_inputs",
            return_value=None,
        ),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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
                CONF_VOLUME_STEP: 25,  # Invalid value - outside NumberSelector range 1-20
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


# Tests for the shared HTTP-fetch helper used by both discovery functions


async def test_available_inputs_and_serial_share_fetch_helper(hass: HomeAssistant) -> None:
    """Both discovery functions must delegate to the same fetch helper, not duplicate the scaffolding."""
    with patch(
        "custom_components.naim_media_player.config_flow._async_fetch_device_json",
        new=AsyncMock(return_value=None),
    ) as mock_fetch:
        await async_get_available_inputs(hass, "192.168.1.100")
        await async_get_device_serial(hass, "192.168.1.100")

    assert mock_fetch.await_count == 2
    fetched_paths = {call.args[2] for call in mock_fetch.await_args_list}
    assert fetched_paths == {"inputs", "system"}


async def test_fetch_device_json_returns_none_on_http_error(hass: HomeAssistant) -> None:
    """The shared helper returns None on a non-200 response."""
    mock_response = AsyncMock()
    mock_response.status = 500

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await _async_fetch_device_json(hass, "192.168.1.100", "system")

    assert result is None


# Tests for async_get_device_serial


async def test_async_get_device_serial_success(hass: HomeAssistant) -> None:
    """Test fetching the device serial from the /system endpoint.

    Real Naim firmware (Atom, fw 3.12) exposes the serial as "hardwareSerial";
    there is no bare "serial" key. Payload mirrors an actual device response.
    """
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={
            "name": "system",
            "chromecastSerial": "386EAFB080E8E8B7",
            "hardwareSerial": "521103",
            "hardwareType": "stream800",
        }
    )

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_device_serial(hass, "192.168.1.100")

    assert result == "521103"


async def test_async_get_device_serial_legacy_serial_key(hass: HomeAssistant) -> None:
    """Test falling back to a bare "serial" key if hardwareSerial is absent."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"serial": "ABC123"})

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_device_serial(hass, "192.168.1.100")

    assert result == "ABC123"


async def test_async_get_device_serial_http_error(hass: HomeAssistant) -> None:
    """Test handling an HTTP error while fetching the serial."""
    mock_response = AsyncMock()
    mock_response.status = 500

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_device_serial(hass, "192.168.1.100")

    assert result is None


async def test_async_get_device_serial_connection_error(hass: HomeAssistant) -> None:
    """Test handling a connection error while fetching the serial."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=ClientError("Connection failed"))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_device_serial(hass, "192.168.1.100")

    assert result is None


async def test_async_get_device_serial_missing_field(hass: HomeAssistant) -> None:
    """Test handling a response with no serial field."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={})

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await async_get_device_serial(hass, "192.168.1.100")

    assert result is None


# Tests for serial-based unique_id / identity


async def test_form_uses_serial_as_unique_id(hass: HomeAssistant) -> None:
    """Test the config entry unique_id and data use the fetched serial, not the IP."""
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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
            return_value="SERIAL123",
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

    assert result2["type"] == "create_entry"
    assert result2["data"][CONF_SERIAL] == "SERIAL123"

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "SERIAL123"


async def test_form_falls_back_to_ip_when_serial_unavailable(hass: HomeAssistant) -> None:
    """Test the flow keeps working and falls back to the IP-based identity if serial fetch fails."""
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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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

    assert result2["type"] == "create_entry"
    assert CONF_SERIAL not in result2["data"]

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "192.168.1.100"


async def test_form_fetches_serial_and_inputs_concurrently(hass: HomeAssistant) -> None:
    """Serial and inputs discovery must run concurrently, not as two sequential round-trips."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    mock_writer = MagicMock()
    mock_writer.close.return_value = None
    mock_writer.wait_closed = MagicMock(return_value=asyncio.Future())
    mock_writer.wait_closed.return_value.set_result(None)

    async def slow_serial(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        return "SERIAL123"

    async def slow_inputs(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        return None

    with (
        patch("asyncio.open_connection", return_value=(MagicMock(), mock_writer)),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_available_inputs",
            side_effect=slow_inputs,
        ),
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
            side_effect=slow_serial,
        ),
    ):
        start = time.monotonic()
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_IP_ADDRESS: "192.168.1.100",
                CONF_NAME: "Test Naim",
                "entity_id": "test_naim",
                CONF_VOLUME_STEP: 5,
            },
        )
        elapsed = time.monotonic() - start
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert elapsed < 0.35


# Tests for duplicate-entry detection across the serial/IP identity migration


async def test_reconfigure_ip_keyed_entry_aborts_even_when_serial_now_available(
    hass: HomeAssistant,
) -> None:
    """A pre-migration entry keyed by bare IP must be recognized even if this run fetches a serial.

    Without a same-IP check, `async_set_unique_id(serial or ip)` would compute a
    different unique_id than the existing IP-keyed entry and create a duplicate.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.100",
        title="Test Naim",
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim"},
    )
    existing.add_to_hass(hass)

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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
            return_value="SERIAL123",
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

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_serial_keyed_entry_aborts_even_when_serial_fetch_is_flaky(
    hass: HomeAssistant,
) -> None:
    """A serial-keyed entry must still be recognized when a later /system fetch flakily fails.

    The IP match must catch this case so identity never silently flips from
    serial back to a bare-IP duplicate.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="SERIAL123",
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            CONF_SERIAL: "SERIAL123",
        },
    )
    existing.add_to_hass(hass)

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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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
        patch(
            "custom_components.naim_media_player.config_flow.async_get_device_serial",
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
        result = await flow.async_step_init({CONF_SOURCES: ["Spotify", "Digital 1"], CONF_VOLUME_STEP: 5})

    assert result["type"] == "create_entry"
    assert result["data"] == {
        CONF_SOURCES: {"Spotify": "spotify", "Digital 1": "dig1"},
        CONF_VOLUME_STEP: 5,
    }


async def test_options_flow_volume_step_when_unreachable(hass: HomeAssistant) -> None:
    """Test volume step can still be changed when the device is unreachable."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Naim",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_NAME: "Test Naim",
            CONF_SOURCES: {"Analog 1": "ana1"},
            CONF_VOLUME_STEP: 3,
        },
    )

    with patch(
        "custom_components.naim_media_player.config_flow.async_get_available_inputs",
        return_value=None,
    ):
        flow = NaimOptionsFlow(entry)
        flow.hass = hass

        # Form is still shown, with the volume step field but no sources field.
        result = await flow.async_step_init()
        assert result["type"] == "form"
        assert result["step_id"] == "init"
        schema_keys = {str(key) for key in result["data_schema"].schema}
        assert CONF_VOLUME_STEP in schema_keys
        assert CONF_SOURCES not in schema_keys

        # Submitting a new volume step preserves the existing sources.
        result = await flow.async_step_init({CONF_VOLUME_STEP: 7})

    assert result["type"] == "create_entry"
    assert result["data"] == {
        CONF_SOURCES: {"Analog 1": "ana1"},
        CONF_VOLUME_STEP: 7,
    }


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
