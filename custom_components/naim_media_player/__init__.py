"""The Naim Media Player integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["media_player"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema("naim_media_player")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Naim Media Player component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Naim Media Player from a config entry."""
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Reload integration when options are changed (e.g. volume step, sources)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        return True
    except Exception as err:
        _LOGGER.error("Error setting up Naim Media Player: %s", err)
        raise ConfigEntryNotReady from err


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
