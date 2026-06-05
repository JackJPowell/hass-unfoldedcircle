# unfurled

An async Python library for controlling [Unfolded Circle](https://www.unfoldedcircle.com/) Remote Two and Remote 3 devices.

---

## Features

- Async-first design built on `aiohttp` and `websockets`
- Full REST API coverage via `CoreAPI`
- Real-time WebSocket event stream with auto-reconnect
- High-level `Remote` class for common operations (activities, IR, media, docks)
- `Dock` class for IR learning, firmware updates, and codeset management
- mDNS discovery via `zeroconf`
- Clean exception hierarchy
- Typed with mypy

---

## Installation

```bash
# Using uv (recommended)
uv add unfurled

# Or pip
pip install unfurled
```

To install for development:

```bash
git clone https://github.com/you/unfurled
cd unfurled
uv venv --python 3.11
uv pip install -e ".[dev]"
```

---

## Quick Start

```python
import asyncio
from unfurled.remote import Remote

async def main():
    remote = Remote("http://192.168.1.100:80", api_key="your-api-key")
    await remote.init()

    print(remote.name)                # "My Remote Two" (or auto-derived)
    print(remote.info.model_name)     # "Remote Two"
    print(remote.info.hw_revision)    # "Revision 2"
    print(remote.sw_version)          # "2.1.0"

    # List activities
    for act in remote.activities:
        print(act.name, "-", "ON" if act.is_on else "off")

    # Turn on an activity
    await remote.find_activity("my-activity-id").turn_on()

asyncio.run(main())
```

---

## Discovery

Find remotes on the local network via mDNS:

```python
from unfurled.discovery import discover_remotes

async def main():
    devices = await discover_remotes(timeout=5)
    for d in devices:
        print(d.hostname, d.address, d.port)
```

---

## Remote

### Construction

```python
# API key (preferred)
remote = Remote("http://192.168.1.100:80", api_key="your-api-key")

# PIN
remote = Remote("http://192.168.1.100:80", pin="1234")
```

### Initialisation

`await remote.init()` fetches the full device state in one call:
configuration, activities, entities, docks, IR emitters, update info.

### Key Properties

| Property | Description |
|---|---|
| `name` | Device display name (falls back to model name) |
| `info.model_name` | Marketing model name (e.g. `"Remote Two"`) |
| `info.hw_revision` | Human-readable hardware revision (e.g. `"Revision 2"`) |
| `info.serial_number` | Device serial number |
| `sw_version` | Currently running firmware |
| `latest_sw_version` | Latest available firmware |
| `available_update` | `True` when an update is ready |
| `settings.network.wifi_enabled` | Wi-Fi radio state |
| `settings.network.bt_enabled` | Bluetooth radio state |
| `settings.display.brightness` | Display brightness (0-100) |
| `settings.power_saving.standby_sec` | Display sleep timeout (seconds) |
| `activities` | `list[Activity]` |
| `docks` | `list[Dock]` |

### Activities

```python
# List
for act in remote.activities:
    print(act.name, act.state)

# Find and control
act = remote.find_activity("activity-id")
await act.turn_on()
await act.turn_off()

# All off
await remote.turn_off_all_activities()
```

### Settings

Configuration is grouped under `remote.settings`:

```python
# Adjust display brightness
await remote.settings.update_display(brightness=80)

# Enable Wi-Fi wake-on-LAN
await remote.settings.update_network(wake_on_wlan=True)

# Change sound volume
await remote.settings.update_sound(volume=60)
```

### IR

```python
# Send a raw HEX or PRONTO code
await remote.ir.send(
    code="0000 006C ...",
    format="PRONTO",
    emitter_name="Dock IR",   # or emitter_id="device-id"
    repeat=1,
)

# Send from a loaded codeset
await remote.ir.send_from_codeset("Samsung TV", "VOLUME_UP")

# List available emitters
for e in remote.ir.emitters:
    print(e.name, e.device_id)
```

### Integrations / External Systems

```python
# Find a specific integration driver instance
instance = await remote.integrations.get_by_driver("hass")

# Set an API token for an external system (e.g. Home Assistant)
await remote.auth.set_external_token(
    system="hass",
    token_id="primary",
    token="long-lived-token",
    name="Home Assistant",
)
```

### Authentication / API Keys

```python
# Create a persistent API key
key = await remote.auth.create_key()
print(key["api_key"])

# Revoke a key
await remote.auth.revoke_key(key["key_id"])
```

### Firmware Updates

```python
# Force an update check
result = await remote.api.post_force_update_check()

# Current status
print(remote.update_info.in_progress, remote.update_info.update_percent)
```

### WebSocket Events

```python
from unfurled.websocket import RemoteWebSocketClient

async def on_message(msg: str):
    print("WS event:", msg)

ws = RemoteWebSocketClient(api_url, api_key)
ws.on_message(on_message)
await ws.connect()
```

Or use the built-in client on `Remote`:

```python
remote.add_listener(my_callback)   # raw WS message handler
await remote.connect_websocket()
```

---

## Dock

```python
dock = remote.docks[0]

# Refresh state
await dock.update()

# IR learning
result = await dock.start_ir_learning()
await dock.stop_ir_learning()

# Firmware update
info = await dock.get_update_status()
if info.get("update_available"):
    await dock.update_firmware()

# Custom codesets
codesets = await dock.get_custom_codesets()
await dock.delete_custom_codeset("my-codeset-id")
```

---

## Exceptions

| Exception | When raised |
|---|---|
| `AuthenticationError` | Wrong API key / PIN |
| `HTTPError` | Non-2xx response |
| `RemoteIsSleeping` | Device is asleep; wake it first |
| `ExternalSystemNotSupported` | Unknown external system ID |

---

## Interactive Tester

A built-in REPL tester is included:

```bash
uv run main.py
```

It discovers remotes on the local network, prompts for credentials, then
offers a numbered menu to inspect state and send commands.

---

## Development

```bash
# Run tests
uv run pytest

# Type checking
uv run mypy unfurled/

# Lint / format
uv run ruff check unfurled/
uv run ruff format unfurled/
```

---

## Licence

MIT
