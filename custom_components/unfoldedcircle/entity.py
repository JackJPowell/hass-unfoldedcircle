import math

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import UnfoldedCircleRemoteCoordinator
from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
import logging

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    # async_add_entities(
    #     UnfoldedCircleSensor(coordinator, description)
    #     for description in UNFOLDED_CIRCLE_ENTITY
    # )


class UnfoldedCircleEntity(CoordinatorEntity[UnfoldedCircleRemoteCoordinator]):
    """Common entity class for all UC entities"""

    def __init__(
            self, coordinator
    ) -> None:
        """Initialize Unfolded Circle Sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.coordinator.entities.append(self)

    @property
    def should_poll(self) -> bool:
        return False
