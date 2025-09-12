"""Platform for light integration."""

from dataclasses import dataclass

from homeassistant.const import EntityCategory
from homeassistant.components.light import (
    LightEntity,
    LightEntityDescription,
    ColorMode,
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
)
from homeassistant.util.color import value_to_brightness
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import StateType

from .entity import UnfoldedCircleEntity
from . import UnfoldedCircleConfigEntry

BRIGHTNESS_SCALE = (1, 100)


@dataclass(frozen=True)
class UnfoldedCircleLightEntityDescription(LightEntityDescription):
    """Class describing Unfolded Circle Remote light entities."""

    unique_id: str = ""


UNFOLDED_CIRCLE_LIGHT: tuple[UnfoldedCircleLightEntityDescription, ...] = (
    UnfoldedCircleLightEntityDescription(
        key="button_backlight",
        name="Button Backlight",
        unique_id="button_backlight",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: UnfoldedCircleConfigEntry, async_add_entities
):
    """Add lights for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_entities(
        UnfoldedCircleLight(coordinator, description)
        for description in UNFOLDED_CIRCLE_LIGHT
    )


class UnfoldedCircleLight(UnfoldedCircleEntity, LightEntity):
    """Unfolded Circle Light Class."""

    entity_description = UNFOLDED_CIRCLE_LIGHT

    def __init__(
        self,
        coordinator,
        description: UnfoldedCircleLightEntityDescription,
    ) -> None:
        """Initialize Unfolded Circle Light."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.coordinator.api.model_number}_{self.coordinator.api.serial_number}_{description.unique_id}"
        self.entity_description = description
        self._state: StateType = None

        if "RGB_COLOR" in self.coordinator.api.button_features:
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        else:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self.coordinator.api.button_backlight_brightness > 10

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return value_to_brightness(
            BRIGHTNESS_SCALE, self.coordinator.api.button_backlight_brightness
        )

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the rgb color value [int, int, int]."""
        if "RGB_COLOR" not in self.coordinator.api.button_features:
            return None
        return (
            tuple(self.coordinator.api.button_static_color["rgb"])
            if "rgb" in self.coordinator.api.button_static_color
            else tuple(255, 255, 255)
        )

    async def async_turn_on(self, **kwargs):
        """Turn the light on."""
        rgb = {}
        if ATTR_RGB_COLOR in kwargs:
            rgb["rgb"] = kwargs[ATTR_RGB_COLOR]
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = int((kwargs.get(ATTR_BRIGHTNESS, 0) / 255) * 100)
        await self.coordinator.api.patch_remote_button_settings(
            brightness=self._attr_brightness, static_color=rgb
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        await self.coordinator.api.patch_remote_button_settings(brightness=0)
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the coordinator."""
        self._attr_is_on = self.coordinator.api.button_backlight_brightness > 10
        self._attr_brightness = self.coordinator.api.button_backlight_brightness
        if "RGB_COLOR" in self.coordinator.api.button_features:
            self._attr_rgb_color = (
                tuple(self.coordinator.api.button_static_color["rgb"])
                if "rgb" in self.coordinator.api.button_static_color
                else tuple(255, 255, 255)
            )
        self.async_write_ha_state()
