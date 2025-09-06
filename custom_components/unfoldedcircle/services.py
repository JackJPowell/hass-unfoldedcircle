"""Unfolded Circle services."""

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from custom_components.unfoldedcircle.coordinator import UnfoldedCircleConfigEntry

from .const import DOMAIN, INHIBIT_STANDBY_SERVICE, UPDATE_ACTIVITY_SERVICE

INHIBIT_STANDBY_SERVICE_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("duration"): int,
        vol.Optional("why", default="User Action"): str,
    }
)

PREVENT_SLEEP_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional("prevent_sleep", default=False): cv.boolean}
)


SUPPORTED_SERVICES = (INHIBIT_STANDBY_SERVICE, UPDATE_ACTIVITY_SERVICE)
SERVICE_TO_SCHEMA = {
    INHIBIT_STANDBY_SERVICE: INHIBIT_STANDBY_SERVICE_SCHEMA,
    UPDATE_ACTIVITY_SERVICE: PREVENT_SLEEP_SCHEMA,
}


@callback
def async_setup_services(
    hass: HomeAssistant, config_entry: UnfoldedCircleConfigEntry
) -> None:
    """Set up services for Unfolded Circle integration."""

    services = {
        INHIBIT_STANDBY_SERVICE: async_inhibit_standby,
        UPDATE_ACTIVITY_SERVICE: async_prevent_sleep,
    }

    async def async_call_unfolded_circle_service(service_call: ServiceCall) -> None:
        """Call correct Unfolded Circle service."""
        await services[service_call.service](hass, service_call, config_entry)

    for service in SUPPORTED_SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            async_call_unfolded_circle_service,
            schema=SERVICE_TO_SCHEMA.get(service),
        )


async def async_inhibit_standby(
    hass: HomeAssistant,
    service_call: ServiceCall,
    config_entry: UnfoldedCircleConfigEntry,
) -> None:
    """Inhibit standby on the Unfolded Circle Remote."""

    duration = service_call.data["duration"]
    if duration is None:
        return

    why = service_call.data["why"]
    if why is None:
        why = "User Requested"

    inhibitors = (
        await config_entry.runtime_data.coordinator.api.get_standby_inhibitors()
    )
    length = len(inhibitors)
    inhibitor_id = f"HA{length}"

    await config_entry.runtime_data.coordinator.api.set_standby_inhibitor(
        inhibitor_id, "Home Assistant", why=why, delay=duration
    )


async def async_prevent_sleep(
    hass: HomeAssistant,
    service_call: ServiceCall,
    config_entry: UnfoldedCircleConfigEntry,
) -> None:
    """Handle dispatched services."""
    entity_registry = er.async_get(hass)
    for selected_entity in service_call.data.get("entity_id", []):
        entities = [
            entity
            for entity in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
            if entity.entity_id == selected_entity
        ]
        if not entities:
            continue

        for entity in entities:
            if service_call.service == UPDATE_ACTIVITY_SERVICE:
                coordinator = config_entry.runtime_data.coordinator
                await coordinator.api.get_activity_by_id(entity.unique_id).edit(
                    service_call.data
                )
