"""Tests for the Naim Media Player integration setup."""

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.naim_media_player import async_setup_entry
from custom_components.naim_media_player.const import DOMAIN


async def test_async_setup_entry_registers_update_listener(hass):
    """Setup should register an update listener that reloads the entry on options changes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim"},
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock(return_value=True)):
        assert await async_setup_entry(hass, entry)

    assert entry.update_listeners


async def test_update_listener_triggers_reload(hass):
    """Options-flow saves must reload the entry so the entity picks up new sources."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim"},
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock(return_value=True)):
        assert await async_setup_entry(hass, entry)

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
        for listener in entry.update_listeners:
            await listener(hass, entry)

    mock_reload.assert_called_once_with(entry.entry_id)


async def test_options_update_fires_update_listener(hass):
    """Updating entry options via config_entries must invoke the registered reload listener."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_NAME: "Test Naim"},
        options={},
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock(return_value=True)):
        assert await async_setup_entry(hass, entry)

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as mock_reload:
        hass.config_entries.async_update_entry(entry, options={"sources": {"Spotify": "spotify"}})
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(entry.entry_id)
