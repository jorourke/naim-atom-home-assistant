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


# --- Diagnostics ---


async def test_diagnostics_redacts_ip_host_and_serial(hass):
    import json

    from homeassistant.components.media_player import MediaPlayerState

    from custom_components.naim_media_player.diagnostics import async_get_config_entry_diagnostics
    from custom_components.naim_media_player.media_player import NaimPlayer

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Atom",
        unique_id="521103",
        data={CONF_IP_ADDRESS: "192.168.1.127", CONF_NAME: "Atom", "host": "192.168.1.127", "serial": "521103"},
        options={"volume_step": 5, "max_volume": 40},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.naim_media_player.media_player.NaimClient"):
        player = NaimPlayer(hass, "Atom", "192.168.1.127", serial="521103", unique_id="521103")
    await player._state.update(
        source="poll",
        power_state=MediaPlayerState.ON,
        playing_state=MediaPlayerState.PLAYING,
        title="Fallen Light",
        audio_format={"codec": "AAC"},
        restrictions=frozenset({"seek"}),
    )
    entry.runtime_data = player

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diagnostics)

    assert "192.168.1.127" not in text
    assert "521103" not in text
    assert diagnostics["entry"]["options"] == {"volume_step": 5, "max_volume": 40}
    assert diagnostics["state"]["title"] == "Fallen Light"
    assert diagnostics["state"]["state"] == "playing"
    assert diagnostics["state"]["restrictions"] == ["seek"]
    assert diagnostics["state"]["audio_format"] == {"codec": "AAC"}


async def test_diagnostics_without_loaded_player(hass):
    from custom_components.naim_media_player.diagnostics import async_get_config_entry_diagnostics

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_IP_ADDRESS: "192.168.1.127"})
    entry.add_to_hass(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["state"] is None
    assert diagnostics["entry"]["data"][CONF_IP_ADDRESS] == "**REDACTED**"
