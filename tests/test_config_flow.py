"""Tests for the config and options flow."""
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.luxor.const import (
    CONF_COALESCE_EXTINGUISH,
    CONF_GROUP_INTERVAL,
    CONF_HOST,
    CONF_REQUEST_TIMEOUT,
    CONF_SEND_INTERVAL,
    CONF_THEME_INTERVAL,
    DOMAIN,
)

USER_INPUT = {CONF_HOST: " 192.0.2.1 ", CONF_GROUP_INTERVAL: 60, CONF_THEME_INTERVAL: 600}


async def test_user_flow_creates_entry(hass, controller):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.luxor.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "lxtwo-275610"
    assert result["data"][CONF_HOST] == "192.0.2.1"
    assert result["result"].unique_id == "lxtwo-275610"


async def test_user_flow_cannot_connect(hass, controller):
    controller.disconnect["ControllerName"] = 100
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(hass, controller, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass, setup_integration):
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_GROUP_INTERVAL: 30,
            CONF_THEME_INTERVAL: 300,
            CONF_SEND_INTERVAL: 1.5,
            CONF_REQUEST_TIMEOUT: 5.0,
            CONF_COALESCE_EXTINGUISH: False,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SEND_INTERVAL] == 1.5
    assert entry.options[CONF_COALESCE_EXTINGUISH] is False
    assert entry.state is config_entries.ConfigEntryState.LOADED
