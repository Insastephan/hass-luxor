"""Shared fixtures."""
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luxor.const import (
    CONF_HOST,
    CONF_SEND_INTERVAL,
    DOMAIN,
)

from .fake_controller import FakeController

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/luxor."""
    yield


@pytest.fixture
def controller_kind() -> str:
    return "luxor2"


@pytest.fixture
def controller(controller_kind) -> FakeController:
    """Simulated controller used as the aiohttp session of the integration."""
    fake = FakeController(controller_kind)
    with patch(
        "custom_components.luxor.async_get_clientsession", return_value=fake
    ), patch(
        "custom_components.luxor.config_flow.async_get_clientsession",
        return_value=fake,
    ):
        yield fake


@pytest.fixture
def config_entry(controller) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=controller.name,
        unique_id=controller.name,
        data={CONF_HOST: "192.0.2.1"},
        # Keep the tests fast; the default is the protocol's one second.
        options={CONF_SEND_INTERVAL: 0.05},
    )


@pytest.fixture
async def setup_integration(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
