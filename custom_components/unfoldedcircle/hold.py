# from homeassistant.helpers import device_registry as dr
# from homeassistant.helpers import entity_registry as er, issue_registry

#     @callback
#     def async_migrate_entity_entry(
#         entry: er.RegistryEntry,
#     ) -> dict[str, Any] | None:
#         """Migrate Unfolded Circle entity entries.

#         - Migrates old unique ID's to the new unique ID's
#         """
#         if (
#             entry.domain != Platform.UPDATE
#             and entry.domain != Platform.SWITCH
#             and "ucr" not in entry.unique_id.lower()
#             and "ucd" not in entry.unique_id.lower()
#         ):
#             new = f"{coordinator.api.model_number}_{entry.unique_id}"
#             return {"new_unique_id": entry.unique_id.replace(entry.unique_id, new)}

#         if (
#             entry.domain == Platform.SWITCH
#             and "ucr" not in entry.unique_id.lower()
#             and "ucd" not in entry.unique_id.lower()
#             and "uc.main" not in entry.unique_id
#         ):
#             new = f"{coordinator.api.model_number}_{entry.unique_id}"
#             return {"new_unique_id": entry.unique_id.replace(entry.unique_id, new)}

#         if (
#             entry.domain == Platform.UPDATE
#             and "ucr" not in entry.unique_id.lower()
#             and "ucd" not in entry.unique_id.lower()
#         ):
#             new = f"{coordinator.api.model_number}_{coordinator.api.serial_number}_update_status"
#             return {"new_unique_id": entry.unique_id.replace(entry.unique_id, new)}

#         # No migration needed
#         return None

#     # Migrate unique ID -- Make the ID actually Unique.
#     # Migrate Device Name -- Make the device name match the psn username
#     # We can remove this logic after a reasonable period of time has passed.
#     if entry.version == 1:
#         await er.async_migrate_entries(hass, entry.entry_id, async_migrate_entity_entry)
#         _migrate_device_identifiers(hass, entry.entry_id, coordinator)
#         _update_config_entry(hass, entry, coordinator)
#         hass.config_entries.async_update_entry(entry, version=2)

#     # Synchronize the list of docks from the registry with the docks reported by the remote
#     config_updated = False

#     for config_dock in list(entry.data["docks"]):
#         found = False
#         for dock in remote_api.docks:
#             if config_dock.get("id") == dock.id:
#                 found = True
#                 break
#         if not found:
#             entry.data["docks"].remove(config_dock)
#             config_updated = True

#     for dock in remote_api.docks:
#         found = False
#         for config_dock in entry.data["docks"]:
#             if config_dock.get("id") == dock.id:
#                 found = True
#                 break
#         if not found:
#             entry.data["docks"].append(
#                 {"id": dock.id, "name": dock.name, "password": ""}
#             )
#             config_updated = True
#     if config_updated:
#         hass.config_entries.async_update_entry(entry, data=entry.data)

# async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
#     return True


# def _update_config_entry(
#     hass: HomeAssistant,
#     config_entry: ConfigEntry,
#     coordinator: UnfoldedCircleRemoteCoordinator,
# ) -> bool:
#     """Update config entry with dock information"""
#     if "docks" not in config_entry.data:
#         docks = []
#         for dock in coordinator.api.docks:
#             docks.append({"id": dock.id, "name": dock.name, "password": ""})

#         updated_data = {**config_entry.data}
#         updated_data["docks"] = docks

#         hass.config_entries.async_update_entry(config_entry, data=updated_data)
#     return True


# def _migrate_device_identifiers(
#     hass: HomeAssistant, entry_id: str, coordinator
# ) -> None:
#     """Migrate old device identifiers."""
#     dev_reg = dr.async_get(hass)
#     devices: list[dr.DeviceEntry] = dr.async_entries_for_config_entry(dev_reg, entry_id)
#     for device in devices:
#         old_identifier = list(next(iter(device.identifiers)))
#         if (
#             "ucr" not in old_identifier[1].lower()
#             and "ucd" not in old_identifier[1].lower()
#         ):
#             new_identifier = {
#                 (
#                     DOMAIN,
#                     coordinator.api.model_number,
#                     coordinator.api.serial_number,
#                 )
#             }
#             _LOGGER.debug(
#                 "migrate identifier '%s' to '%s'",
#                 device.identifiers,
#                 new_identifier,
#             )
#             dev_reg.async_update_device(device.id, new_identifiers=new_identifier)
