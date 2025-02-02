"""Config flow for Naim Media Player integration."""

from __future__ import annotations

import asyncio
import logging
from ipaddress import ip_address
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_VOLUME_STEP, DEFAULT_ENTITY_ID, DEFAULT_IP, DEFAULT_NAME, DEFAULT_VOLUME_STEP, DOMAIN

_LOGGER = logging.getLogger(__name__)


def valid_ip_address(value: str) -> bool:
    try:
        ip_address(value)
        return True
    except ValueError:
        return False


class NaimConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Naim Media Player."""

    VERSION = 1

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

        # Define a custom validator for IP addresses.
        def ip_validator(value: str) -> str:
            if not valid_ip_address(value):
                raise vol.Invalid("invalid_ip_address")
            return value

        # Create the voluptuous schema.
        schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS, default=suggested_values[CONF_IP_ADDRESS]): vol.All(str, ip_validator),
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

        return self.async_create_entry(title=validated_input[CONF_NAME], data=validated_input)

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
