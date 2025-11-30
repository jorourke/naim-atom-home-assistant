"""Config flow for Naim Media Player integration."""

from __future__ import annotations

import asyncio
import logging
from ipaddress import ip_address
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import (
    CONF_SOURCES,
    CONF_VOLUME_STEP,
    DEFAULT_ENTITY_ID,
    DEFAULT_HTTP_PORT,
    DEFAULT_IP,
    DEFAULT_NAME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_get_available_inputs(hass, ip_address: str, port: int = DEFAULT_HTTP_PORT) -> dict[str, str] | None:
    """Fetch available inputs from the Naim device.

    Returns a dict mapping display name to input ID, or None on failure.
    Only returns inputs with selectable="1".
    """
    try:
        session = async_get_clientsession(hass)
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"http://{ip_address}:{port}/inputs"

        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                _LOGGER.warning("Failed to fetch inputs: HTTP %s", response.status)
                return None

            data = await response.json()
            children = data.get("children", [])

            # Filter to selectable inputs and build the map
            sources = {}
            for child in children:
                if child.get("selectable") == "1":
                    name = child.get("name")
                    ussi = child.get("ussi", "")
                    # Extract input ID from ussi (e.g., "inputs/ana1" -> "ana1")
                    input_id = ussi.split("/")[-1] if "/" in ussi else ussi
                    if name and input_id:
                        sources[name] = input_id

            _LOGGER.debug("Discovered %d selectable inputs: %s", len(sources), list(sources.keys()))
            return sources

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        _LOGGER.debug("Failed to fetch inputs from %s: %s", ip_address, error)
        return None
    except Exception as error:
        _LOGGER.warning("Unexpected error fetching inputs: %s", error)
        return None


def valid_ip_address(value: str) -> bool:
    try:
        ip_address(value)
        return True
    except ValueError:
        return False


class NaimConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Naim Media Player."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}
        self._available_sources: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "NaimOptionsFlow":
        """Get the options flow for this handler."""
        return NaimOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> "FlowResult":
        """Handle the initial step with voluptuous validation."""
        errors: dict[str, str] = {}
        # Set up default/suggested values
        suggested_values = {
            CONF_IP_ADDRESS: DEFAULT_IP,
            CONF_NAME: DEFAULT_NAME,
            "entity_id": DEFAULT_ENTITY_ID,
            CONF_VOLUME_STEP: DEFAULT_VOLUME_STEP,
        }

        # Create the voluptuous schema.
        # Note: IP validation is done manually after form submission because
        # custom validator functions cannot be serialized for the frontend.
        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS, default=suggested_values[CONF_IP_ADDRESS]): str,
                vol.Optional(CONF_NAME, default=suggested_values[CONF_NAME]): str,
                vol.Optional("entity_id", default=suggested_values["entity_id"]): str,
                vol.Optional(CONF_VOLUME_STEP, default=DEFAULT_VOLUME_STEP): vol.All(
                    vol.Coerce(float), vol.In([1, 5, 10])
                ),
            }
        )

        # If no input is provided, show the form.
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "default_ip": suggested_values[CONF_IP_ADDRESS],
                    "default_name": suggested_values[CONF_NAME],
                },
            )

        # Validate the input using the schema.
        try:
            validated_input = schema(user_input)
        except vol.Invalid as exc:
            errors["base"] = str(exc)
            # Merge current inputs into suggested values so the form is prefilled.
            suggested_values.update(user_input)
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "default_ip": suggested_values[CONF_IP_ADDRESS],
                    "default_name": suggested_values[CONF_NAME],
                },
            )

        # Validate IP address manually (can't use custom validator in schema for UI serialization)
        if not valid_ip_address(validated_input[CONF_IP_ADDRESS]):
            errors[CONF_IP_ADDRESS] = "invalid_ip_address"
            suggested_values.update(user_input)
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "default_ip": suggested_values[CONF_IP_ADDRESS],
                    "default_name": suggested_values[CONF_NAME],
                },
            )

        # Test connection to the device.
        try:
            await self._test_connection(validated_input[CONF_IP_ADDRESS])
        except ConfigEntryNotReady as err:
            _LOGGER.error("Error connecting to device: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "default_ip": suggested_values[CONF_IP_ADDRESS],
                    "default_name": suggested_values[CONF_NAME],
                },
            )
        except Exception as err:
            _LOGGER.exception("Unexpected exception: %s", err)
            errors["base"] = "unknown"
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "default_ip": suggested_values[CONF_IP_ADDRESS],
                    "default_name": suggested_values[CONF_NAME],
                },
            )

        # At this point, the IP is valid and the device is reachable.
        # Create a unique ID based on the IP address.
        await self.async_set_unique_id(validated_input[CONF_IP_ADDRESS])
        self._abort_if_unique_id_configured()

        # Store the user input and try to discover sources
        self._user_input = validated_input
        self._available_sources = await async_get_available_inputs(self.hass, validated_input[CONF_IP_ADDRESS]) or {}

        # If we discovered sources, show the selection step
        if self._available_sources:
            return await self.async_step_sources()

        # Otherwise, create the entry without source selection (fallback to hardcoded)
        return self.async_create_entry(title=validated_input[CONF_NAME], data=validated_input)

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the source selection step."""
        if user_input is not None:
            # Build the selected sources dict
            selected_names = user_input.get(CONF_SOURCES, [])
            selected_sources = {name: self._available_sources[name] for name in selected_names}

            # Merge with the original user input
            data = {**self._user_input, CONF_SOURCES: selected_sources}
            return self.async_create_entry(title=self._user_input[CONF_NAME], data=data)

        # Build a multi-select schema with all sources pre-selected
        source_names = list(self._available_sources.keys())
        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCES, default=source_names): SelectSelector(
                    SelectSelectorConfig(
                        options=source_names,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="sources",
            data_schema=schema,
            description_placeholders={"device_name": self._user_input.get(CONF_NAME, "Naim Device")},
        )

    async def _test_connection(self, ip: str) -> None:
        """Test connection to the device asynchronously."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 4545),
                timeout=10,  # 10 second timeout
            )
            writer.close()
            await writer.wait_closed()
        except asyncio.TimeoutError as err:
            raise ConfigEntryNotReady("Device not responding") from err
        except OSError as err:
            raise ConfigEntryNotReady(f"Connection failed: {err}") from err


class NaimOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Naim Media Player."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._available_sources: dict[str, str] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial options step."""
        ip_address = self._config_entry.data.get(CONF_IP_ADDRESS)

        # Fetch available sources from the device
        self._available_sources = await async_get_available_inputs(self.hass, ip_address) or {}

        if not self._available_sources:
            # Can't reach device, show error
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            # Build the selected sources dict
            selected_names = user_input.get(CONF_SOURCES, [])
            selected_sources = {name: self._available_sources[name] for name in selected_names}

            return self.async_create_entry(title="", data={CONF_SOURCES: selected_sources})

        # Get currently configured sources (from options first, then data, then empty)
        current_sources = self._config_entry.options.get(CONF_SOURCES, self._config_entry.data.get(CONF_SOURCES, {}))
        current_source_names = list(current_sources.keys()) if current_sources else []

        # If no current sources, default to all available
        if not current_source_names:
            current_source_names = list(self._available_sources.keys())

        # Build the schema
        source_names = list(self._available_sources.keys())
        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCES, default=current_source_names): SelectSelector(
                    SelectSelectorConfig(
                        options=source_names,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"device_name": self._config_entry.data.get(CONF_NAME, "Naim Device")},
        )
