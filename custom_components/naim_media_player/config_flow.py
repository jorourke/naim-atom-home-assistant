"""Config flow for Naim Media Player integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class NaimConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Naim Media Player."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Set up default/suggested values
        suggested_values = {
            CONF_IP_ADDRESS: "192.168.1.127",  # Example default IP
            CONF_NAME: DEFAULT_NAME,
            "entity_id": "naim_atom",  # Example default entity_id
        }

        if user_input is not None:
            try:
                # Test connection to the device
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(user_input[CONF_IP_ADDRESS], 4545),
                        timeout=10,  # 10 second timeout
                    )
                    writer.close()
                    await writer.wait_closed()
                except asyncio.TimeoutError as err:
                    raise ConfigEntryNotReady("Device not responding") from err
                except OSError as err:
                    raise ConfigEntryNotReady(f"Connection failed: {err}") from err

                # Create unique ID based on IP
                await self.async_set_unique_id(user_input[CONF_IP_ADDRESS])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

            except ConfigEntryNotReady as err:
                _LOGGER.error("Error connecting to device: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as error:
                _LOGGER.exception("Unexpected exception: %s", error)
                errors["base"] = "unknown"

            # If there were errors, keep the user's input as the suggested values
            suggested_values.update(user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=suggested_values[CONF_IP_ADDRESS]): str,
                    vol.Optional(CONF_NAME, default=suggested_values[CONF_NAME]): str,
                    vol.Optional("entity_id", default=suggested_values["entity_id"]): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "default_ip": suggested_values[CONF_IP_ADDRESS],
                "default_name": suggested_values[CONF_NAME],
            },
        )
