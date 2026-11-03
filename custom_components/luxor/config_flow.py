"""Config and options flow for the Luxor integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ControllerInfo, LuxorClient, LuxorError
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
)

GROUP_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=5, max=3600))
THEME_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=60, max=86400))


class LuxorFlowHandler(ConfigFlow, domain=DOMAIN):
    """Set up a Luxor controller."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            info = await self._async_probe(host)
            if info is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.name)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=info.name, data={**user_input, CONF_HOST: host}
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                    vol.Required(
                        CONF_GROUP_INTERVAL,
                        default=user_input.get(CONF_GROUP_INTERVAL, DEFAULT_GROUP_INTERVAL),
                    ): GROUP_INTERVAL,
                    vol.Required(
                        CONF_THEME_INTERVAL,
                        default=user_input.get(CONF_THEME_INTERVAL, DEFAULT_THEME_INTERVAL),
                    ): THEME_INTERVAL,
                }
            ),
            errors=errors,
        )

    async def _async_probe(self, host: str) -> ControllerInfo | None:
        client = LuxorClient(async_get_clientsession(self.hass), host)
        try:
            return await client.async_get_info()
        except LuxorError:
            return None
        finally:
            await client.async_close()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LuxorOptionsFlow()


class LuxorOptionsFlow(OptionsFlow):
    """Tune polling and the pace of commands sent to the controller."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        entry = self.config_entry

        def current(key: str, default: Any) -> Any:
            return entry.options.get(key, entry.data.get(key, default))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_GROUP_INTERVAL,
                        default=current(CONF_GROUP_INTERVAL, DEFAULT_GROUP_INTERVAL),
                    ): GROUP_INTERVAL,
                    vol.Required(
                        CONF_THEME_INTERVAL,
                        default=current(CONF_THEME_INTERVAL, DEFAULT_THEME_INTERVAL),
                    ): THEME_INTERVAL,
                    vol.Required(
                        CONF_SEND_INTERVAL,
                        default=current(CONF_SEND_INTERVAL, DEFAULT_SEND_INTERVAL),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
                    vol.Required(
                        CONF_REQUEST_TIMEOUT,
                        default=current(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                    ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=15.0)),
                    vol.Required(
                        CONF_COALESCE_EXTINGUISH,
                        default=current(
                            CONF_COALESCE_EXTINGUISH, DEFAULT_COALESCE_EXTINGUISH
                        ),
                    ): bool,
                }
            ),
        )
