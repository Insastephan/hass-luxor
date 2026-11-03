"""Luxor groups as Home Assistant lights."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import COLOR_LIST_SIZE, LuxorError, LuxorGroup
from .const import DOMAIN, LIGHT_DEVICE_DOMAIN, MANUFACTURER
from .coordinator import LuxorConfigEntry, LuxorGroupCoordinator, LuxorRuntimeData

_LOGGER = logging.getLogger(__name__)

# HA 2026.8 replaced DeviceInfo "via_device" with "via_device_id"; the old key
# stops working in 2027.8. Use whichever the running version understands.
_HAS_VIA_DEVICE_ID = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 8)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a light for every group, including groups added later."""
    data = entry.runtime_data
    known: set[int] = set()

    @callback
    def _add_new_groups() -> None:
        new = [
            LuxorLight(data, number)
            for number in data.groups.data
            if number not in known
        ]
        if new:
            known.update(light.group_number for light in new)
            async_add_entities(new)

    _add_new_groups()
    entry.async_on_unload(data.groups.async_add_listener(_add_new_groups))


def intensity_to_brightness(intensity: int) -> int:
    return round(255 * intensity / 100)


def brightness_to_intensity(brightness: int) -> int:
    # Never turn a light off by rounding a small but non-zero brightness down.
    return max(1, min(100, round(100 * brightness / 255)))


class LuxorLight(CoordinatorEntity[LuxorGroupCoordinator], LightEntity):
    """One Luxor group."""

    _attr_should_poll = False

    def __init__(self, data: LuxorRuntimeData, group_number: int) -> None:
        super().__init__(data.groups)
        self._data = data
        self.group_number = group_number
        # Same unique ID as the original integration, so entities survive the
        # switch to this fork.
        self._attr_unique_id = f"LUXOR_LIGHT_{group_number}"

    # ---------------------------------------------------------------- state

    @property
    def _group(self) -> LuxorGroup | None:
        return self.coordinator.data.get(self.group_number)

    @property
    def available(self) -> bool:
        return super().available and self._group is not None

    @property
    def name(self) -> str:
        group = self._group
        return group.name if group else f"Luxor group {self.group_number}"

    @property
    def _intensity(self) -> int:
        expected = self._data.client.expected_intensity(self.group_number)
        if expected is not None:
            return expected
        group = self._group
        return group.intensity if group else 0

    @property
    def is_on(self) -> bool:
        return self._intensity > 0

    @property
    def brightness(self) -> int:
        return intensity_to_brightness(self._intensity)

    @property
    def _has_color(self) -> bool:
        group = self._group
        return bool(self._data.info.has_color and group and group.is_color)

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        return {ColorMode.HS} if self._has_color else {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.HS if self._has_color else ColorMode.BRIGHTNESS

    @property
    def hs_color(self) -> tuple[float, float] | None:
        group = self._group
        if not self._has_color or group is None or group.color > COLOR_LIST_SIZE:
            return None  # color wheels (251-260) have no fixed color
        hue_sat = self.coordinator.colors.get(group.color)
        if hue_sat is None:
            return None
        return (float(hue_sat[0]) % 360, float(hue_sat[1]))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self._group
        attrs: dict[str, Any] = {"luxor_group": self.group_number}
        if group is not None:
            attrs["luxor_color"] = group.color
            attrs["dmx_control"] = group.is_dmx
            attrs["color_wheel"] = group.is_color_wheel
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            # The original integration used the group number as an int here;
            # keep it so existing device registry entries still match.
            identifiers={(LIGHT_DEVICE_DOMAIN, self.group_number)},  # type: ignore[arg-type]
            manufacturer=MANUFACTURER,
            name=self.name,
        )
        if _HAS_VIA_DEVICE_ID and self._data.controller_device_id:
            info["via_device_id"] = self._data.controller_device_id
        else:
            info["via_device"] = (DOMAIN, self._data.info.name)
        return info

    # ------------------------------------------------------------- commands

    def _ensure_controllable(self) -> None:
        group = self._group
        if group is None:
            raise HomeAssistantError(
                f"Luxor group {self.group_number} is not known to the controller"
            )
        if group.is_dmx:
            raise HomeAssistantError(
                f"Luxor group '{group.name}' is under DMX control and cannot be "
                "changed from Home Assistant"
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._ensure_controllable()
        hs = kwargs.get(ATTR_HS_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        try:
            if hs is not None and self._has_color:
                await self._async_set_color(hs)
        except LuxorError as err:
            raise HomeAssistantError(str(err)) from err

        # A pure color change on a lit group keeps its brightness.
        if brightness is None and not (hs is not None and self.is_on):
            brightness = 255
        if brightness is not None:
            await self._async_set_intensity(brightness_to_intensity(brightness))
        else:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._ensure_controllable()
        await self._async_set_intensity(0)

    async def _async_set_intensity(self, intensity: int) -> None:
        client = self._data.client
        try:
            sent = client.queue_group_intensity(self.group_number, intensity)
        except LuxorError as err:
            raise HomeAssistantError(str(err)) from err
        # The change is queued now: show the expected state right away
        # instead of waiting for the controller to be polled.
        self.async_write_ha_state()
        try:
            await sent
        except LuxorError as err:
            self.async_write_ha_state()
            raise HomeAssistantError(str(err)) from err
        if not client.busy:
            await self.coordinator.async_request_refresh()
        else:
            self.async_write_ha_state()

    async def _async_set_color(self, hs: tuple[float, float]) -> None:
        group = self._group
        target = (round(hs[0]) % 360, round(hs[1]))
        colors = self.coordinator.colors
        slot = next((c for c, v in colors.items() if v == target), None)
        if slot is None:
            slot = next(
                (c for c in range(1, COLOR_LIST_SIZE + 1) if c not in colors), None
            )
            if slot is None:
                raise HomeAssistantError("The Luxor color list is full")
            await self._data.client.async_set_color_slot(slot, target[0], target[1])
            colors[slot] = target
        await self._data.client.async_set_group_color(group.name, group.number, slot)
        group.color = slot
