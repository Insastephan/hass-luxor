"""The FXLuminaire Luxor integration."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LuxorClient, LuxorError
from .const import (
    CONF_COALESCE_EXTINGUISH,
    CONF_GROUP_INTERVAL,
    CONF_HOST,
    CONF_REQUEST_TIMEOUT,
    CONF_SEND_INTERVAL,
    CONF_THEME_INTERVAL,
    DEFAULT_COALESCE_EXTINGUISH,
    DEFAULT_GROUP_INTERVAL,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SEND_INTERVAL,
    DEFAULT_THEME_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
)
from .coordinator import (
    LuxorConfigEntry,
    LuxorGroupCoordinator,
    LuxorRuntimeData,
    LuxorThemeCoordinator,
)

_LOGGER = logging.getLogger(__name__)


def get_setting(entry: LuxorConfigEntry, key: str, default):
    """Options override the values entered when the entry was created."""
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup_entry(hass: HomeAssistant, entry: LuxorConfigEntry) -> bool:
    """Set up a Luxor controller from a config entry."""
    client = LuxorClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        send_interval=float(
            get_setting(entry, CONF_SEND_INTERVAL, DEFAULT_SEND_INTERVAL)
        ),
        timeout=float(get_setting(entry, CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT)),
        coalesce_extinguish=bool(
            get_setting(entry, CONF_COALESCE_EXTINGUISH, DEFAULT_COALESCE_EXTINGUISH)
        ),
    )

    try:
        info = await client.async_get_info()
    except LuxorError as err:
        await client.async_close()
        raise ConfigEntryNotReady(str(err)) from err

    groups = LuxorGroupCoordinator(
        hass,
        entry,
        client,
        info,
        int(get_setting(entry, CONF_GROUP_INTERVAL, DEFAULT_GROUP_INTERVAL)),
    )
    themes = LuxorThemeCoordinator(
        hass,
        entry,
        client,
        int(get_setting(entry, CONF_THEME_INTERVAL, DEFAULT_THEME_INTERVAL)),
    )
    try:
        await groups.async_config_entry_first_refresh()
        await themes.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.async_close()
        raise

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, info.name)},
        manufacturer=MANUFACTURER,
        model=info.model,
        name=info.name,
    )

    entry.runtime_data = LuxorRuntimeData(
        client=client,
        info=info,
        groups=groups,
        themes=themes,
        controller_device_id=device.id,
    )
    _LOGGER.debug("Luxor controller %s detected as %s", info.name, info.model)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: LuxorConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LuxorConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
