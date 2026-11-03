"""Tests for setup, lights and scenes running inside Home Assistant."""
import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_HS_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ColorMode,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from custom_components.luxor.const import DOMAIN


async def test_setup_creates_entities(hass, controller, setup_integration):
    assert setup_integration.state is ConfigEntryState.LOADED

    hedge = hass.states.get("light.hedge")
    assert hedge.state == STATE_ON
    assert hedge.attributes[ATTR_BRIGHTNESS] == 102  # 40 %
    assert hass.states.get("light.wall").state == STATE_OFF
    assert hass.states.get("scene.lxtwo_275610_all_on") is not None

    device = dr.async_get(hass).async_get_device({(DOMAIN, "lxtwo-275610")})
    assert device.model == "Luxor 2"


async def test_setup_retries_when_controller_is_offline(hass, controller, config_entry):
    controller.disconnect["ControllerName"] = 100
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("controller_kind", ["zd"])
async def test_monochrome_controller(hass, controller, setup_integration):
    tree = hass.states.get("light.tree")
    assert tree.attributes[ATTR_SUPPORTED_COLOR_MODES] == [ColorMode.BRIGHTNESS]
    assert not controller.commands("ColorListGet")


async def test_color_group(hass, controller, setup_integration):
    tree = hass.states.get("light.tree")
    assert tree.attributes[ATTR_SUPPORTED_COLOR_MODES] == [ColorMode.HS]

    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: "light.tree", ATTR_HS_COLOR: (120, 50)},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert ("ColorListSet", {"C": 1, "Hue": 120, "Sat": 50}) in controller.commands()
    assert controller.groups[2]["color"] == 1
    assert controller.groups[2]["intensity"] == 100
    state = hass.states.get("light.tree")
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.HS
    assert state.attributes[ATTR_HS_COLOR] == (120.0, 50.0)


async def test_turn_on_and_off(hass, controller, setup_integration):
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: "light.wall", ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert controller.groups[1]["intensity"] == 50
    assert hass.states.get("light.wall").state == STATE_ON

    await hass.services.async_call(
        "light", "turn_off", {ATTR_ENTITY_ID: "light.wall"}, blocking=True
    )
    await hass.async_block_till_done()
    assert controller.groups[1]["intensity"] == 0
    assert hass.states.get("light.wall").state == STATE_OFF


async def test_switching_everything_off_sends_one_command(
    hass, controller, setup_integration
):
    controller.calls.clear()
    await hass.services.async_call(
        "light",
        "turn_off",
        {ATTR_ENTITY_ID: ["light.wall", "light.tree", "light.hedge"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    sent = [c for c, _ in controller.commands("IlluminateGroup", "ExtinguishAll")]
    assert sent == ["ExtinguishAll"]
    assert all(g["intensity"] == 0 for g in controller.groups.values())


async def test_dmx_group_cannot_be_switched(hass, controller, setup_integration):
    controller.groups[3]["color"] = 65535
    await setup_integration.runtime_data.groups.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("light.hedge").attributes["dmx_control"] is True

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "light", "turn_off", {ATTR_ENTITY_ID: "light.hedge"}, blocking=True
        )
    assert not controller.commands("IlluminateGroup")


async def test_scene_updates_lights_immediately(hass, controller, setup_integration):
    await hass.services.async_call(
        "scene", "turn_on", {ATTR_ENTITY_ID: "scene.lxtwo_275610_all_on"}, blocking=True
    )
    await hass.async_block_till_done()
    assert ("IlluminateTheme", {"ThemeIndex": 0, "OnOff": 1}) in controller.commands()
    # No waiting for the next poll: the lights already show the new state.
    assert hass.states.get("light.wall").state == STATE_ON
    assert hass.states.get("light.wall").attributes[ATTR_BRIGHTNESS] == 255
    assert await hass.config_entries.async_unload(setup_integration.entry_id)


async def test_scene_error_is_reported(hass, controller, setup_integration):
    controller.status["IlluminateTheme"] = 251
    with pytest.raises(HomeAssistantError, match="Bad theme Index"):
        await hass.services.async_call(
            "scene", "turn_on", {ATTR_ENTITY_ID: "scene.lxtwo_275610_all_on"}, blocking=True
        )


async def test_unload(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
