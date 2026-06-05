"""Helper functions for scanning activities on the Remote for orphaned or unused entities."""

import logging
from typing import Any

import aiohttp

from ..submodules.base import RemoteModule

_LOG = logging.getLogger(__name__)


class Helpers(RemoteModule):
    """Manages all remote helper functions.

    Accessed via ``remote.helpers``. Populated automatically during
    :meth:`~unfurled.remote.Remote.init`. Individual helper functions can be used
    directly.

    Example::

        await remote.helpers.find_orphaned_entities(remote_url="http://192.168.1.100",
        api_key="your-api-key-here")
    """

    async def find_orphaned_entities(
        self,
    ) -> list[dict[str, Any]]:
        """
        Find orphaned entities in activities on the Remote.

        Scans all activities and identifies entities that are marked as unavailable
        (available=false). These are typically entities that were deleted or renamed
        but still referenced in activity configurations.

        Authentication can be done via PIN (Basic Auth) or API key (Bearer token).
        One of `pin` or `api_key` must be provided. API key is preferred over PIN.

        :return: List of orphaned entity dictionaries (with entity_commands
        and simple_commands removed)
        :raises ValueError: If neither pin nor api_key is provided

        Example:
            orphaned = await find_orphaned_entities()

            for entity in orphaned:
                print(f"Orphaned entity: {entity['entity_id']} in activity {entity['activity_id']}")
        """

        orphaned_entities: list[dict[str, Any]] = []

        try:
            activities_list = await self._api.get_activities()

            # Step 2: Fetch full activity details and check for orphaned entities
            for activity_summary in activities_list:
                activity_id = activity_summary.get("entity_id")
                if not activity_id:
                    continue

                # Get full activity details
                activity = await self._api.get_activity(activity_id)

                # Get activity name - try summary first, then full activity
                activity_name = activity_summary.get("name") or activity.get("name", {})

                _LOG.debug(
                    "Processing activity %s, name: %s",
                    activity_id,
                    activity_name.get("en", "no name")
                    if isinstance(activity_name, dict)
                    else activity_name,
                )

                # Check included_entities for orphaned entities
                options = activity.get("options", {})
                included_entities = options.get("included_entities", [])

                for entity in included_entities:
                    # Check if entity is marked as unavailable
                    # Note: 'available' property only exists when it's False
                    if "available" in entity and entity["available"] is False:
                        # Create a copy of the entity dict without entity_commands
                        # and simple_commands
                        orphaned_entity = {
                            k: v
                            for k, v in entity.items()
                            if k not in ("entity_commands", "simple_commands")
                        }
                        # Add activity context for reference
                        orphaned_entity["activity_id"] = activity_id
                        orphaned_entity["activity_name"] = activity_name

                        orphaned_entities.append(orphaned_entity)
                        _LOG.debug(
                            "Found orphaned entity: %s in activity %s (%s)",
                            entity.get("entity_id"),
                            activity_name.get("en", activity_id)
                            if isinstance(activity_name, dict)
                            else activity_id,
                            activity_id,
                        )

            _LOG.info("Found %d orphaned entities", len(orphaned_entities))
            return orphaned_entities

        except aiohttp.ClientError as err:
            _LOG.error("Network error while scanning for orphaned entities: %s", err)
            return orphaned_entities
        except Exception as err:  # pylint: disable=broad-except
            _LOG.error("Unexpected error while scanning for orphaned entities: %s", err)
            return orphaned_entities

    def _extract_used_entity_ids(self, activity: dict[str, Any]) -> set[str]:
        """
        Extract all entity IDs that are actively used in an activity's sequences,
        button_mapping, and user_interface.

        :param activity: Full activity dict from GET /api/activities/{id}
        :return: Set of entity_id strings that are referenced
        """
        used: set[str] = set()
        options = activity.get("options", {})

        # sequences: on/off lists of steps; each step may have command.entity_id
        sequences = options.get("sequences", {})
        for steps in sequences.values():
            if not isinstance(steps, list):
                continue
            for step in steps:
                cmd = step.get("command", {})
                if isinstance(cmd, dict) and cmd.get("entity_id"):
                    used.add(cmd["entity_id"])

        # button_mapping: list of {short_press, long_press} each with entity_id
        for mapping in options.get("button_mapping", []):
            for press_key in ("short_press", "long_press"):
                press = mapping.get(press_key, {})
                if isinstance(press, dict) and press.get("entity_id"):
                    used.add(press["entity_id"])

        # user_interface: pages → items; entity IDs hide in several fields
        ui = options.get("user_interface", {})
        for page in ui.get("pages", []):
            for item in page.get("items", []):
                # Direct command entity
                cmd = item.get("command", {})
                if isinstance(cmd, dict) and cmd.get("entity_id"):
                    used.add(cmd["entity_id"])
                # media_player_id
                if item.get("media_player_id"):
                    used.add(item["media_player_id"])
                # sensor_id
                sensor = item.get("sensor", {})
                if isinstance(sensor, dict) and sensor.get("sensor_id"):
                    used.add(sensor["sensor_id"])
                # select_id
                select = item.get("select", {})
                if isinstance(select, dict) and select.get("select_id"):
                    used.add(select["select_id"])

        return used

    async def find_unused_activity_entities(
        self,
    ) -> list[dict[str, Any]]:
        """
        Find entities included in activities that are never actually used.

        An entity is "unused" when it appears in ``included_entities`` but has no
        reference in sequences, button_mapping, or user_interface (commands, media
        player widgets, sensor widgets, or select widgets).

        Authentication can be done via PIN (Basic Auth) or API key (Bearer token).
        One of ``pin`` or ``api_key`` must be provided.

        :param remote_url: The Remote's base URL (e.g., "http://192.168.1.100")
        :param pin: Remote's web-configurator PIN for Basic Auth
        :param api_key: Remote's API key for Bearer token authentication
        :return: List of dicts with activity context and the unused entity info
        :raises ValueError: If neither pin nor api_key is provided
        """
        unused: list[dict[str, Any]] = []

        try:
            activities_list = await self._api.get_activities()

            for activity_summary in activities_list:
                activity_id = activity_summary.get("entity_id")
                if not activity_id:
                    continue

                activity = await self._api.get_activity(activity_id)

                activity_name = activity_summary.get("name") or activity.get("name", {})
                options = activity.get("options", {})
                included_entities = options.get("included_entities", [])

                if not included_entities:
                    continue

                included_ids = {e["entity_id"] for e in included_entities if e.get("entity_id")}
                used_ids = self._extract_used_entity_ids(activity)
                truly_unused = included_ids - used_ids

                for entity in included_entities:
                    eid = entity.get("entity_id")
                    if eid in truly_unused:
                        record = {
                            k: v
                            for k, v in entity.items()
                            if k not in ("entity_commands", "simple_commands")
                        }
                        record["activity_id"] = activity_id
                        record["activity_name"] = activity_name
                        unused.append(record)
                        _LOG.debug("Unused entity %s in activity %s", eid, activity_id)

            _LOG.info("Found %d unused activity entities", len(unused))
            return unused

        except aiohttp.ClientError as err:
            _LOG.error("Network error while scanning for unused entities: %s", err)
            return unused
        except Exception as err:  # pylint: disable=broad-except
            _LOG.error("Unexpected error while scanning for unused entities: %s", err)
            return unused
