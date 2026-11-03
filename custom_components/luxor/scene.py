"""Luxor themes as Home Assistant scenes."""
from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HassJob, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LuxorError, LuxorTheme
from .const import DOMAIN, SCENE_SETTLE_DELAY
from .coordinator import LuxorConfigEntry, LuxorRuntimeData, LuxorThemeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a scene for every theme, including themes added later."""
    data = entry.runtime_data
    known: set[int] = set()

    @callback
    def _add_new_themes() -> None:
        new = [
            LuxorScene(data, theme)
            for index, theme in data.themes.data.themes.items()
            if index not in known
        ]
        if new:
            known.update(scene.theme_index for scene in new)
            async_add_entities(new)

    _add_new_themes()
    entry.async_on_unload(data.themes.async_add_listener(_add_new_themes))


class LuxorScene(CoordinatorEntity[LuxorThemeCoordinator], Scene):
    """One Luxor theme."""

    def __init__(self, data: LuxorRuntimeData, theme: LuxorTheme) -> None:
        super().__init__(data.themes)
        self._data = data
        self.theme_index = theme.index
        self._initial_name = theme.name
        # Same unique ID scheme as the original integration (name + index), so
        # existing scene entities survive the switch to this fork.
        self._attr_unique_id = f"{theme.name}{theme.index}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, data.info.name)})
        self._cancel_settle_refresh = None

    @property
    def _theme(self) -> LuxorTheme | None:
        return self.coordinator.data.themes.get(self.theme_index)

    @property
    def available(self) -> bool:
        return super().available and self._theme is not None

    @property
    def name(self) -> str:
        theme = self._theme
        return theme.name if theme else self._initial_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        theme = self._theme
        return {
            "luxor_theme": self.theme_index,
            "theme_on": bool(theme and theme.on),
        }

    async def async_activate(self, **kwargs: Any) -> None:
        try:
            await self._data.client.async_illuminate_theme(self.theme_index, True)
        except LuxorError as err:
            raise HomeAssistantError(str(err)) from err

        # The controller never reports changes by itself (protocol 1.1): read
        # back the group intensities now, and once more after the fixtures
        # have settled.
        await self._data.groups.async_request_refresh()
        await self.coordinator.async_request_refresh()

        if self._cancel_settle_refresh is not None:
            self._cancel_settle_refresh()

        @callback
        def _refresh_later(_now) -> None:
            self._cancel_settle_refresh = None
            self.hass.async_create_task(self._data.groups.async_request_refresh())

        self._cancel_settle_refresh = async_call_later(
            self.hass,
            SCENE_SETTLE_DELAY,
            HassJob(_refresh_later, cancel_on_shutdown=True),
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_settle_refresh is not None:
            self._cancel_settle_refresh()
            self._cancel_settle_refresh = None
        await super().async_will_remove_from_hass()
