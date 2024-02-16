"""Platform for Switch integration."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNFOLDED_CIRCLE_COORDINATOR
from .coordinator import UnfoldedCircleRemoteCoordinator
from .pyUnfoldedCircleRemote.const import RemoteUpdateType

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Switch platform."""
    # Setup connection with devices
    coordinator = hass.data[DOMAIN][config_entry.entry_id][UNFOLDED_CIRCLE_COORDINATOR]

    activity_ids = []
    for activity_group in coordinator.api.activity_groups:
        activity_ids.extend(activity_group.activities)

    async_add_entities(
        UCRemoteSwitch(coordinator, switch) for switch in filter(lambda a: a._id not in activity_ids, coordinator.api.activities)
    )


class UCRemoteSwitch(CoordinatorEntity[UnfoldedCircleRemoteCoordinator], SwitchEntity):
    """Class representing an unfolded circle activity."""

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.coordinator.api.serial_number)
            },
            name=self.coordinator.api.name,
            manufacturer=self.coordinator.api.manufacturer,
            model=self.coordinator.api.model_name,
            sw_version=self.coordinator.api.sw_version,
            hw_version=self.coordinator.api.hw_revision,
            configuration_url=self.coordinator.api.configuration_url,
        )

    def __init__(self, coordinator, switch) -> None:
        """Initialize a switch."""
        super().__init__(self, coordinator)
        self.coordinator = coordinator
        self.switch = switch
        self._name = f"{self.coordinator.api.name} {switch.name}"
        self._attr_name = f"{self.coordinator.api.name} {switch.name}"
        self._attr_unique_id = switch._id
        self._state = switch.state
        self._attr_icon = "mdi:remote-tv"
        self._attr_native_value = "OFF"


    # HA BUG ? uncommenting stops callback _handle_coordinator_update calls
    # async def async_added_to_hass(self):
    #     """Run when this Entity has been added to HA."""
    #     self.coordinator.subscribe_events["entity_activity"] = True
    #     self.coordinator.subscribe_events["activity_groups"] = True

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._state in ("ON", "RUNNING")

    async def async_turn_on(self, **kwargs) -> None:
        """Instruct the switch to turn on."""
        await self.switch.turn_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Instruct the switch to turn off."""
        await self.switch.turn_off()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            last_update_type = self.coordinator.api.last_update_type
            if last_update_type != RemoteUpdateType.ACTIVITY:
                return
        except (KeyError, IndexError):
            return
        self._state = self.switch.state
        self.async_write_ha_state()
