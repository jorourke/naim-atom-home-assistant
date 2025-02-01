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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Set up default/suggested values
        suggested_values = {
            CONF_IP_ADDRESS: DEFAULT_IP,
            CONF_NAME: DEFAULT_NAME,
            "entity_id": DEFAULT_ENTITY_ID,
            CONF_VOLUME_STEP: DEFAULT_VOLUME_STEP,
        }

        if user_input is not None:
            # First validate IP format
            if not valid_ip_address(user_input[CONF_IP_ADDRESS]):
                errors["base"] = "invalid_ip"
            else:
                try:
                    # Test connection to the device
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(user_input[CONF_IP_ADDRESS], 4545),
                            timeout=10,  # 10 second timeout
                        )
                        writer.close()
                        await writer.wait_closed()

                        # Create unique ID based on IP
                        await self.async_set_unique_id(user_input[CONF_IP_ADDRESS])
                        self._abort_if_unique_id_configured()

                        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

                    except asyncio.TimeoutError as err:
                        raise ConfigEntryNotReady("Device not responding") from err
                    except OSError as err:
                        raise ConfigEntryNotReady(f"Connection failed: {err}") from err

                except ConfigEntryNotReady as err:
                    _LOGGER.error("Error connecting to device: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception as error:
                    _LOGGER.exception("Unexpected exception: %s", error)
                    errors["base"] = "unknown"

            suggested_values.update(user_input)

        # Always return a form (either initial or with errors)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=suggested_values[CONF_IP_ADDRESS]): str,
                    vol.Optional(CONF_NAME, default=suggested_values[CONF_NAME]): str,
                    vol.Optional("entity_id", default=suggested_values["entity_id"]): str,
                    vol.Optional(CONF_VOLUME_STEP, default=DEFAULT_VOLUME_STEP): vol.All(
                        vol.Coerce(float), vol.In([1, 5, 10])
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "default_ip": suggested_values[CONF_IP_ADDRESS],
                "default_name": suggested_values[CONF_NAME],
            },
        )
