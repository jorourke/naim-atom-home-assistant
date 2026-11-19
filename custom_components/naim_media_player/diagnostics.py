"""Diagnostics for Naim Media Player."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL

TO_REDACT = {CONF_IP_ADDRESS, CONF_HOST, CONF_SERIAL}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return entry data, options and a snapshot of the player state, with identifiers redacted."""
    player = getattr(entry, "runtime_data", None)
    snapshot = None
    if player is not None:
        state = player._state
        info = state.media_info
        snapshot = {
            "state": str(state.state),
            "available": state.available,
            "source": state.source,
            "volume": state.volume,
            "muted": state.muted,
            "restrictions": sorted(state.restrictions),
            "audio_format": state.audio_format,
            "title": info.title,
            "artist": info.artist,
            "album": info.album,
            "duration": info.duration,
            "position": info.position,
        }

    return {
        "entry": async_redact_data(
            {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "state": snapshot,
    }
