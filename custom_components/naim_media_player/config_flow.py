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
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .client import parse_inputs
from .const import (
    CONF_MAX_VOLUME,
    CONF_SERIAL,
    CONF_SOURCES,
    CONF_VOLUME_STEP,
    DEFAULT_ENTITY_ID,
    DEFAULT_HTTP_PORT,
    DEFAULT_IP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_NAME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Shared selector for the volume step field, used by both the setup and options
# flows. Wrap it in vol.All(..., vol.Coerce(int)) in a schema to reject/coerce
# fractional input server-side.
VOLUME_STEP_SELECTOR = NumberSelector(NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX))

MAX_VOLUME_SELECTOR = NumberSelector(NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX))

# Note: IP validation is done manually after form submission because custom
# validator functions cannot be serialized for the frontend.
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS, default=DEFAULT_IP): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional("entity_id", default=DEFAULT_ENTITY_ID): str,
        vol.Required(CONF_VOLUME_STEP, default=DEFAULT_VOLUME_STEP): vol.All(VOLUME_STEP_SELECTOR, vol.Coerce(int)),
    }
)


def _get_max_volume(config_entry: config_entries.ConfigEntry) -> int:
    """Return the configured maximum volume (defaults to 100, which changes nothing)."""
    return config_entry.options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)


def _get_volume_step(config_entry: config_entries.ConfigEntry) -> int:
    """Return the configured volume step, preferring options over data."""
    return config_entry.options.get(
        CONF_VOLUME_STEP,
        config_entry.data.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP),
    )


async def _async_fetch_device_json(
    hass, ip_address: str, path: str, port: int = DEFAULT_HTTP_PORT
) -> dict[str, Any] | None:
    """Fetch and parse JSON from a Naim device HTTP endpoint.

    Shared by `async_get_available_inputs` and `async_get_device_serial`.
    Returns the parsed JSON body, or None on any failure (non-200 status,
    timeout, client error, or unexpected error).
    """
    try:
        session = async_get_clientsession(hass)
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"http://{ip_address}:{port}/{path}"

        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                _LOGGER.warning("Failed to fetch %s: HTTP %s", path, response.status)
                return None

            return await response.json()

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        _LOGGER.debug("Failed to fetch %s from %s: %s", path, ip_address, error)
        return None
    except Exception as error:
        _LOGGER.warning("Unexpected error fetching %s: %s", path, error)
        return None


async def async_get_available_inputs(hass, ip_address: str, port: int = DEFAULT_HTTP_PORT) -> dict[str, str] | None:
    """Fetch available inputs from the Naim device.

    Returns a dict mapping display name to input ID, or None on failure.
    Only returns inputs with selectable="1".
    """
    data = await _async_fetch_device_json(hass, ip_address, "inputs", port)
    if data is None:
        return None

    sources = parse_inputs(data)

    _LOGGER.debug("Discovered %d selectable inputs: %s", len(sources), list(sources.keys()))
    return sources


async def async_get_device_serial(hass, ip_address: str, port: int = DEFAULT_HTTP_PORT) -> str | None:
    """Fetch the device serial number from the Naim device's /system endpoint.

    Returns the serial as a string, or None if it could not be determined.
    """
    data = await _async_fetch_device_json(hass, ip_address, "system", port)
    if data is None:
        return None

    # Naim firmware exposes the device serial as "hardwareSerial"; older
    # assumptions used a bare "serial" key, kept as a fallback.
    serial = data.get("hardwareSerial") or data.get("serial")
    return str(serial) if serial else None


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

    def _show_user_form(self, errors: dict[str, str]) -> "FlowResult":
        """Render the user step form."""
        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
            description_placeholders={"default_ip": DEFAULT_IP, "default_name": DEFAULT_NAME},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> "FlowResult":
        """Handle the initial step with voluptuous validation."""
        if user_input is None:
            return self._show_user_form({})

        try:
            validated_input = USER_SCHEMA(user_input)
        except vol.Invalid as exc:
            return self._show_user_form({"base": str(exc)})

        ip = validated_input[CONF_IP_ADDRESS]
        if not valid_ip_address(ip):
            return self._show_user_form({CONF_IP_ADDRESS: "invalid_ip_address"})

        try:
            await self._test_connection(ip)
        except ConfigEntryNotReady as err:
            _LOGGER.error("Error connecting to device: %s", err)
            return self._show_user_form({"base": "cannot_connect"})
        except Exception as err:
            _LOGGER.exception("Unexpected exception: %s", err)
            return self._show_user_form({"base": "unknown"})

        # A device re-added after the serial-based unique_id migration must
        # still be recognized as already configured: an existing entry keyed
        # by the legacy bare-IP unique_id (or any entry stored against this
        # IP) is the same device even if this run's /system fetch resolves
        # differently. Checking the stored IP first keeps identity
        # deterministic and prevents a duplicate entry regardless of whether
        # the existing entry was keyed by serial or by IP.
        for entry in self._async_current_entries():
            if entry.data.get(CONF_IP_ADDRESS) == ip:
                return self.async_abort(reason="already_configured")

        # Prefer a stable unique ID based on the device serial (survives DHCP
        # address changes); fall back to the IP address if it can't be
        # fetched. Fetch the serial and the available inputs concurrently to
        # avoid two sequential 10s-timeout round-trips during setup.
        serial, self._available_sources = await asyncio.gather(
            async_get_device_serial(self.hass, ip),
            async_get_available_inputs(self.hass, ip),
        )
        self._available_sources = self._available_sources or {}
        await self.async_set_unique_id(serial or ip)
        self._abort_if_unique_id_configured()

        # Store the user input
        self._user_input = validated_input
        if serial:
            self._user_input[CONF_SERIAL] = serial

        return await self._async_select_sources_or_create()

    async def _async_select_sources_or_create(self) -> "FlowResult":
        """Show source selection if inputs were discovered; otherwise create the entry (hardcoded fallback)."""
        if self._available_sources:
            return await self.async_step_sources()
        return self.async_create_entry(title=self._user_input[CONF_NAME], data=self._user_input)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> "FlowResult":
        """Handle a `_sues800device._tcp` service announced by a Naim device."""
        if not str(discovery_info.properties.get("manufacturer", "")).lower().startswith("naim"):
            return self.async_abort(reason="not_naim_device")

        host = discovery_info.host
        # Same legacy check as the user flow: an entry stored against this IP is this device.
        if any(entry.data.get(CONF_IP_ADDRESS) == host for entry in self._async_current_entries()):
            return self.async_abort(reason="already_configured")

        serial = await async_get_device_serial(self.hass, host)
        if not serial:
            return self.async_abort(reason="no_serial")

        await self.async_set_unique_id(serial)
        # If the device is known but moved to a new IP, follow it (this also reloads the entry).
        self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: host})

        name = discovery_info.properties.get("name") or DEFAULT_NAME
        self._user_input = {
            CONF_IP_ADDRESS: host,
            CONF_NAME: name,
            "entity_id": DEFAULT_ENTITY_ID,
            CONF_VOLUME_STEP: DEFAULT_VOLUME_STEP,
            CONF_SERIAL: serial,
        }
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> "FlowResult":
        """Confirm the discovered device, then run the same source selection as manual setup."""
        if user_input is None:
            return self.async_show_form(
                step_id="discovery_confirm",
                description_placeholders={
                    "name": self._user_input[CONF_NAME],
                    "host": self._user_input[CONF_IP_ADDRESS],
                },
            )
        self._available_sources = await async_get_available_inputs(self.hass, self._user_input[CONF_IP_ADDRESS]) or {}
        return await self._async_select_sources_or_create()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> "FlowResult":
        """Change the device host, after checking the new host is the same device."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_IP_ADDRESS]
            if not valid_ip_address(host):
                errors[CONF_IP_ADDRESS] = "invalid_ip_address"
            elif not (serial := await async_get_device_serial(self.hass, host)):
                errors["base"] = "cannot_connect"
            elif not entry.data.get(CONF_SERIAL):
                return self.async_abort(reason="no_serial")
            elif serial != entry.data[CONF_SERIAL]:
                return self.async_abort(reason="wrong_device")
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_IP_ADDRESS: host})

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_IP_ADDRESS, default=entry.data[CONF_IP_ADDRESS]): str}),
            errors=errors,
        )

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

        # Try to fetch available sources from the device. The device may be
        # unreachable; volume step can still be configured in that case, so we
        # don't abort here — we just skip the source selection field.
        self._available_sources = await async_get_available_inputs(self.hass, ip_address) or {}
        device_reachable = bool(self._available_sources)

        # Currently configured sources (from options first, then data, then empty)
        current_sources = self._config_entry.options.get(CONF_SOURCES, self._config_entry.data.get(CONF_SOURCES, {}))

        if user_input is not None:
            data = {
                CONF_VOLUME_STEP: int(user_input.get(CONF_VOLUME_STEP, _get_volume_step(self._config_entry))),
                CONF_MAX_VOLUME: int(user_input.get(CONF_MAX_VOLUME, _get_max_volume(self._config_entry))),
            }

            if device_reachable:
                # Build the selected sources dict from the refreshed device list.
                selected_names = user_input.get(CONF_SOURCES, [])
                data[CONF_SOURCES] = {name: self._available_sources[name] for name in selected_names}
            else:
                # Couldn't refresh sources from the device; keep the existing ones.
                data[CONF_SOURCES] = current_sources

            return self.async_create_entry(title="", data=data)

        current_volume_step = _get_volume_step(self._config_entry)

        schema_dict: dict[Any, Any] = {}
        if device_reachable:
            # Match by input ID, not name: a name changes when the input is renamed in the Naim app.
            current_ids = set(current_sources.values())
            current_source_names = [
                name for name, input_id in self._available_sources.items() if input_id in current_ids
            ]
            # If no current sources, default to all available
            if not current_source_names:
                current_source_names = list(self._available_sources.keys())

            source_names = list(self._available_sources.keys())
            schema_dict[vol.Required(CONF_SOURCES, default=current_source_names)] = SelectSelector(
                SelectSelectorConfig(
                    options=source_names,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )

        schema_dict[vol.Required(CONF_VOLUME_STEP, default=current_volume_step)] = vol.All(
            VOLUME_STEP_SELECTOR, vol.Coerce(int)
        )
        schema_dict[vol.Required(CONF_MAX_VOLUME, default=_get_max_volume(self._config_entry))] = vol.All(
            MAX_VOLUME_SELECTOR, vol.Coerce(int)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"device_name": self._config_entry.data.get(CONF_NAME, "Naim Device")},
        )
