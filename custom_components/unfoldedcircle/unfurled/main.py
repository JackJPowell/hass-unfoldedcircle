"""Interactive tester for the unfurled library.

Discovers or connects to an Unfolded Circle Remote, then exposes a simple
REPL-style menu to inspect state and send commands.

Usage::

    uv run main.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from unfurled import AuthenticationError, HTTPError, Remote, discover_remotes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pp(data: Any) -> None:
    """Pretty-print any JSON-serialisable value."""
    try:
        print(json.dumps(data, indent=2, default=str))
    except TypeError:
        print(data)


def _prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{message}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return value or default


def _choose(options: list[str], prompt: str = "Choose") -> int:
    """Print a numbered menu and return the 0-based index of the choice."""
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = _prompt(prompt, "1")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("  Invalid choice, try again.")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


async def _connect() -> Remote:
    """Discover or manually enter a remote address, then authenticate."""
    print("\n=== unfurled - interactive tester ===\n")

    print("Discovering remotes on the local network (3 s) …")
    found = await discover_remotes(timeout=3)

    if found:
        options = [f"{d.name}  ({d.host})" for d in found] + ["Enter manually"]
        idx = _choose(options, "Select remote")
        if idx < len(found):
            device = found[idx]
            endpoint = f"http://{device.host}:{device.port}"
        else:
            endpoint = _prompt("Remote URL", "http://192.168.1.x:80")
    else:
        print("No remotes found via mDNS.")
        endpoint = _prompt("Remote URL", "http://192.168.1.x:80")

    pin = _prompt("PIN (leave blank to use API key instead)", "1234")
    if pin:
        remote = Remote(endpoint, pin=pin)
    else:
        api_key = _prompt("API key")
        remote = Remote(endpoint, api_key=api_key)

    print("\nConnecting …")
    try:
        await remote.init()
    except AuthenticationError:
        print("Authentication failed - check your API key / PIN.")
        sys.exit(1)
    except Exception as exc:
        print(f"Connection error: {exc}")
        sys.exit(1)

    print(f"\nConnected to: {remote.device.name}  (FW {remote.device.sw_version})")
    return remote


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------


async def _show_summary(remote: Remote) -> None:
    print("\n--- Device summary ---")
    pp(
        {
            "name": remote.device.name,
            "model": remote.device.model_name,
            "serial": remote.device.serial_number,
            "hw_revision": remote.device.hw_revision,
            "firmware": remote.device.sw_version,
            "latest_firmware": remote.system.update_info.latest_version,
            "update_available": remote.system.update_info.available,
            "memory_total_mb": remote.system.stats.memory_total,
            "storage_total_mb": remote.system.stats.storage_total,
            "wifi_enabled": remote.settings.network.wifi_enabled,
            "bt_enabled": remote.settings.network.bt_enabled,
        }
    )


async def _list_activities(remote: Remote) -> None:
    print(f"\n--- Activities ({len(remote.activities)}) ---")
    for act in remote.activities:
        state_icon = "ON " if act.is_on else "OFF"
        print(f"  [{state_icon}] {act.name!r}  (id={act.id})")


async def _toggle_activity(remote: Remote) -> None:
    if not remote.activities:
        print("No activities found.")
        return
    options = [f"{a.name} ({'ON' if a.is_on else 'off'})" for a in remote.activities]
    idx = _choose(options, "Activity to toggle")
    act = remote.activities[idx]
    if act.is_on:
        print(f"Turning off {act.name!r} …")
        await act.turn_off()
    else:
        print(f"Turning on {act.name!r} …")
        await act.turn_on()
    print("Done.")


async def _list_docks(remote: Remote) -> None:
    print(f"\n--- Docks ({len(remote.docks)}) ---")
    if not remote.docks:
        print("  (none)")
        return
    for dock in remote.docks:
        print(f"  {dock.device.name!r}  model={dock.device.model_name}  state={dock.state}")


async def _list_ir_emitters(remote: Remote) -> None:
    emitters = remote.ir_emitters
    print(f"\n--- IR emitters ({len(emitters)}) ---")
    for e in emitters:
        print(f"  {e.name!r}  type={e.type}  state={e.state}  id={e.device_id}")


async def _list_unused_entities(remote: Remote) -> None:
    print("\n--- Unused activity entities ---")
    unused = await remote.helpers.find_unused_activity_entities()
    if not unused:
        print("No unused entities found.")
        return
    for entity in unused:
        print(f"  {entity['entity_id']} in activity {entity['activity_name']}")


async def _list_orphaned_entities(remote: Remote) -> None:
    print("\n--- Orphaned activity entities ---")
    orphaned = await remote.helpers.find_orphaned_entities()
    if not orphaned:
        print("No orphaned entities found.")
        return
    for entity in orphaned:
        print(f"  {entity['entity_id']} in activity {entity['activity_name']}")


async def _send_ir(remote: Remote) -> None:
    emitters = remote.ir_emitters
    if not emitters:
        print("No IR emitters found.")
        return
    options = [f"{e.name!r}  (id={e.device_id})" for e in emitters]
    idx = _choose(options, "Emitter to use")
    emitter_id = emitters[idx].device_id

    fmt = _prompt("Format (HEX/PRONTO)", "HEX")
    code = _prompt("IR code")
    if not code:
        print("No code entered, skipping.")
        return

    ok = await remote.ir.send(code, fmt, emitter_id=emitter_id)
    print("Sent!" if ok else "Send failed.")


async def _poll_update(remote: Remote) -> None:
    print("Polling remote for state update …")
    await remote.polling_update()
    print("Done.")
    await _show_summary(remote)


async def _raw_api_call(remote: Remote) -> None:
    path = _prompt("API path (e.g. cfg/system)")
    try:
        result = await remote.api._get(path)
        pp(result)
    except HTTPError as exc:
        print(f"HTTP error {exc}")


async def _check_update(remote: Remote) -> None:
    print("Checking for firmware update …")
    try:
        result = await remote.system.force_update_check()
        pp(result)
    except Exception as exc:
        print(f"Error: {exc}")


async def _list_entities(remote: Remote) -> None:
    entities = remote._entities
    print(f"\n--- Media player entities ({len(entities)}) ---")
    for entity in entities.values():
        print(f"  {entity.name!r}  state={entity.state}  id={entity.id}")


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

MENU: list[tuple[str, Any]] = [
    ("Show device summary", _show_summary),
    ("List activities", _list_activities),
    ("Toggle activity on/off", _toggle_activity),
    ("List docks", _list_docks),
    ("List IR emitters", _list_ir_emitters),
    ("Send IR code", _send_ir),
    ("List media player entities", _list_entities),
    ("List unused activity entities", _list_unused_entities),
    ("List orphaned activity entities", _list_orphaned_entities),
    ("Poll state update", _poll_update),
    ("Check for firmware update", _check_update),
    ("Raw API call (GET)", _raw_api_call),
    ("Quit", None),
]


async def main() -> None:
    """Entry point - connect to a remote and run the interactive menu."""
    remote = await _connect()

    while True:
        print()
        labels = [label for label, _ in MENU]
        idx = _choose(labels, "Action")
        label, action = MENU[idx]
        if action is None:
            print("Bye!")
            break
        try:
            await action(remote)
        except KeyboardInterrupt:
            print()
        except Exception as exc:
            print(f"Error: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
