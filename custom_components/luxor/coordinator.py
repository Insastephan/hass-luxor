"""Data update coordinators for the Luxor integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ControllerInfo, LuxorClient, LuxorError, LuxorGroup, ThemeList
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

REFRESH_COOLDOWN = 0.5


@dataclass
class LuxorRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: LuxorClient
    info: ControllerInfo
    groups: "LuxorGroupCoordinator"
    themes: "LuxorThemeCoordinator"
    controller_device_id: str | None = None


type LuxorConfigEntry = ConfigEntry[LuxorRuntimeData]


class LuxorGroupCoordinator(DataUpdateCoordinator[dict[int, LuxorGroup]]):
    """Polls the group list (and the color list on color controllers)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LuxorClient,
        info: ControllerInfo,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_groups",
            update_interval=timedelta(seconds=interval),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=True
            ),
        )
        self.client = client
        self.info = info
        self.colors: dict[int, tuple[int, int]] = {}

    async def _async_update_data(self) -> dict[int, LuxorGroup]:
        try:
            groups = await self.client.async_get_groups()
        except LuxorError as err:
            raise UpdateFailed(str(err)) from err
        if self.info.has_color and any(g.is_color for g in groups.values()):
            try:
                self.colors = await self.client.async_get_colors()
            except LuxorError as err:
                # Colors are secondary; keep the last known list.
                _LOGGER.debug("Could not read Luxor color list: %s", err)
        return groups


class LuxorThemeCoordinator(DataUpdateCoordinator[ThemeList]):
    """Polls the theme list."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LuxorClient,
        interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_themes",
            update_interval=timedelta(seconds=interval),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN, immediate=True
            ),
        )
        self.client = client

    async def _async_update_data(self) -> ThemeList:
        try:
            return await self.client.async_get_themes()
        except LuxorError as err:
            raise UpdateFailed(str(err)) from err
