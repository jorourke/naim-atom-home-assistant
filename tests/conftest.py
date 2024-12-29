"""Global fixtures for naim_media_player integration."""

from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


# This fixture is used to prevent HomeAssistant from attempting to load our custom integration
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant."""
    yield


# This fixture, when used, will result in calls to async_get_data to return None. To have the call
# return a value, we would add that value in the mock.
@pytest.fixture(name="bypass_get_data")
def bypass_get_data_fixture():
    """Skip calls to get data from API."""
    with patch("custom_components.naim_media_player.config_flow.validate_input", return_value={"title": "Naim Test"}):
        yield
