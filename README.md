[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Release](https://img.shields.io/github/v/release/jackjpowell/hass-unfoldedcircle)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/jackjpowell/hass-unfoldedcircle/total)
![Maintenance](https://img.shields.io/maintenance/yes/2025.svg)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee%20☕-FFDD00?logo=buy-me-a-coffee&logoColor=white&labelColor=555)](https://buymeacoffee.com/jackpowell)

# Unfolded Circle Integration

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/unfoldedcircle/dark_logo.png">
  <img alt="Unfolded Circle logo" src="https://brands.home-assistant.io/unfoldedcircle/logo.png">
</picture>

Home Assistant integration for the [Unfolded Circle Remote Two / Remote 3](https://www.unfoldedcircle.com/) and associated docks.
A rich integration providing activity control, remote settings and diagnostics, firmware management, IR transmission & learning, wake features, dock management, wireless charging control and advanced automation hooks.

---

## Table of Contents
- [Key Features](#key-features)
- [Supported Devices & Concepts](#supported-devices--concepts)
- [Installation](#installation)
  - [HACS (Recommended)](#hacs-recommended)
  - [Manual Installation](#manual-installation)
- [Configuration](#configuration)
  - [Manual Setup](#manual-setup)
- [Entities Overview](#entities-overview)
- [Dock Support](#dock-support)
- [External Entity Management](#external-entity-management)
- [Mapped Button Remote Commands](#mapped-button-remote-commands)
- [IR Remote Commands](#ir-remote-commands)
- [Activity Update Actions](#activity-update-actions)
- [IR Learning](#ir-learning)
- [Options](#options)
- [Zeroconf](#zeroconf)
- [Wake on LAN](#wake-on-lan)
- [Planned / Future Ideas](#planned--future-ideas)
- [Notes & Behavior](#notes--behavior)
- [Services & Actions Summary](#services--actions-summary)
- [Troubleshooting & Support](#troubleshooting--support)
- [Localization](#localization)
- [About This Project](#about-this-project)
- [License](#license)
- [Support the Project](#support-the-project)

---

## Key Features
- Automatic device & dock discovery (zeroconf)
- Guided configuration flow and options flow
- Flexible entity exposure: activities, groups, media players (global / per group / per activity)
- Firmware update control with progress reporting
- External Entity Management (select which HA entities are exposed back to the remote)
- IR send (codeset/custom) with dock & port targeting
- IR learning workflow that builds ready-to-use codesets
- Mapped button command dispatch (long press, repeats, delays, activity scoping)
- Activity maintenance services (e.g., prevent sleep toggling, standby inhibitors)
- Wake on LAN for Remote Two (Remote 3 when firmware supports it)
- Resource usage sensors (opt-in polling)
- Docks as sub-entries: IR, brightness, identity, reboot, firmware
- Button backlight Light entity (brightness + color control)
- Multi-language support (EN, Partial (FR, PT))

---

## Supported Devices & Concepts
| Component | Description |
|-----------|-------------|
| Remote Two / Remote 3 | Primary handheld device defining activities, buttons, media surface. |
| Dock | IR emission, LED brightness, reboot, identity flash, firmware update. |
| Activity / Activity Group | Logical usage contexts exposed as switches/selects with optional media players. |
| Firmware | Update entity supports version awareness & install execution. |
| IR Dataset | Learned or manufacturer-based sets of IR commands. |
| Button Backlight | Light entity allowing dynamic brightness and color adjustment of remote button illumination. |
| Wireless Charging | Toggle wireless charging on and off to control battery setpoint. |

---

## Installation

### HACS (Recommended)

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JackJPowell&repository=hass-unfoldedcircle&category=Integration)

1. Install [HACS](https://hacs.xyz/) if not already.
2. Home Assistant → HACS → Integrations.
3. Search “Unfolded Circle” → Install.
4. Restart Home Assistant.
5. Continue with [Configuration](#configuration).

### Manual Installation
1. Clone or download this repository.
2. Copy `custom_components/unfoldedcircle` into your HA `custom_components/` directory.
3. Restart HA.
4. Proceed to [Configuration](#configuration).

Manual installs won’t auto-notify updates—watch the repo if you go this route.

---

## Configuration

After restart (HACS or manual):
1. A discovery notification should appear.
2. Go to **Settings** → **Devices & Services** → **Configure** and click Configure on the newly discovered Unfolded Circle Device.
3. Enter PIN (from remote web configurator).
   - On the remote: profile icon (upper-right) → enable web configurator → **PIN** appears (refresh if needed).
   - **PIN** only needed initially; you can change it after pairing.
4. Assign an Area.

### Manual Setup
If not discovered:
1. Settings → Devices & Services → Integrations → + Add Integration.
2. Search “Unfolded Circle”.
3. Supply PIN and Host (IP/hostname).

---

## Entities Overview
| Category | Examples / Notes |
|----------|------------------|
| Sensors | Battery, Illuminance, Resource Usage (CPU/Mem/Storage)*, Config flags |
| Binary Sensor | Charging status |
| Update | Firmware reporting + install |
| Switch | Activities (configurable), configuration toggles |
| Select | Activity groups (optional) |
| Button | Restart remote |
| Remote | Mapped button & IR dispatch |
| Media Player | Global and/or per group / per activity |
| Number | Numeric configuration, dock LEDs |
| Light | Button backlight (brightness + color control) |
| Dock Sub-Entities | Remote (IR), Buttons (Reboot, Identity), Update, Brightness controls |

*Resource usage sensors disabled by default; enabling one enables selective polling.

### Button Backlight Light Entity
A `light` entity exposes remote button backlight control:
- Adjustable brightness
- Adjustable color (depending on device capabilities)
- Suitable for themes/ambience automations (e.g., dim during night mode)

Example automation:
```yaml
automation:
  - alias: Dim remote backlight at night
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: light.turn_on
        target:
          entity_id: light.remote_two_button_backlight
        data:
          brightness_pct: 10
          rgb_color: [255, 80, 10]
```

---

### Wireless Charging Switch
A switch entity enables and disables the wireless charger on your Remote 3. 

Example Automation:
```yaml
alias: Preserve Battery
description: "Toggle wireless charging functionality based on battery percentage"
triggers:
  - trigger: numeric_state
    entity_id:
      - sensor.remote_3_battery
    above: 80
    id: "OFF"
  - trigger: numeric_state
    entity_id:
      - sensor.remote_3_battery
    below: 60
    id: "ON"
conditions: []
actions:
  - if:
      - condition: trigger
        id:
          - "OFF"
    then:
      - action: switch.turn_off
        metadata: {}
        data: {}
        target:
          entity_id: switch.remote_3_wireless_charging
  - if:
      - condition: trigger
        id:
          - "OFF"
    then:
      - action: switch.turn_on
        metadata: {}
        data: {}
        target:
          entity_id: switch.remote_3_wireless_charging
mode: single
```

## Dock Support
- Docks are Sub-entries
- One-time migration cleans legacy definitions & repairs.
- Removed reliance on dock passwords 🎉

Each dock exposes:
- Remote (IR)
- Buttons: Reboot, Identity flash
- Numbers: LED Brightness
- Update: Firmware visibility

---

## External Entity Management
Select which HA entities are shared to the remote (Options flow).

Requirements:
- Remote firmware ≥ 2.0.0 (≥ 2.6.9 recommended; Remote 3 currently beta but stable)

Demo video:
[Watch the demo](https://github.com/user-attachments/assets/7e653b3f-3edb-484c-9cd6-efcd21886b87)

---

## Mapped Button Remote Commands
Preferred service: `unfoldedcircle.send_button_command`
Options: `num_repeats`, `delay_secs`, `hold`, `activity`

Supported buttons:

    - BACK
    - HOME
    - VOICE
    - VOLUME_UP
    - VOLUME_DOWN
    - GREEN
    - DPAD_UP
    - YELLOW
    - DPAD_LEFT
    - DPAD_MIDDLE
    - DPAD_RIGHT
    - RED
    - DPAD_DOWN
    - BLUE
    - CHANNEL_UP
    - CHANNEL_DOWN
    - MUTE
    - PREV
    - PLAY
    - PAUSE
    - NEXT
    - POWER

---

## IR Remote Commands

The remote entity supports sending predefined or (HEX/PRONTO) IR commands using the unfoldedcircle.send_ir_command action.

**device:** will match the case-sensitive name of your remote defined in the web configurator on the remote page. This will be your custom name or the manufacturer name selected.

**codeset** (Optional) If you supplied a manufacturer name, you also need to supply the codeset name you are using.

**command** will match the case-senstitive name of the pre-defined (custom or codeset) or (Hex or Pronto) command defined for the remote.

**num_repeats** (Optional) The number of times to repeat sending the command.

**dock_name** (Optional) The name of the dock you would like to send the command from. If not supplied, all docks will emit the IR signal.

**port** (Optional) The location on the dock you want the IR signal to be emitted from. If not supplied, all ports are used.

![image](https://github.com/user-attachments/assets/64adaf67-9025-46a8-aaab-f90c82fb8c6e)

Yaml of the above image:

```yaml
action: unfoldedcircle.send_ir_command
data:
  device: Samsung
  codeset: Generic TV 1
  command: POWER_TOGGLE
  dock: Remote Dock
  port: Ext 1
target:
  entity_id: remote.remote_two_remote
```

> TIP: Core `remote.send_command` only supports custom codes (platform limitation).

---

## Activity Update Actions
Service: `unfoldedcircle.update_activity`

```yaml
service: unfoldedcircle.update_activity
target:
  entity_id: switch.remote_two_control_projector
data:
  prevent_sleep: true
```

Currently supports `prevent_sleep` (more may follow).

---

## IR Learning
Service: `unfoldedcircle.learn_ir_command`

```
service: unfoldedcircle.learn_ir_command
target:
  entity_id: remote.remote_dock_remote
data:
  remote:
    name: Sony TV
    icon: uc:tv
    description: My Sony TV Remote
  dock: R3 Dock
  ir_dataset:
    name: Sony A95L
    command:
      - direction_up
      - direction_right
      - direction_down
      - direction_left
      - menu
      - back
      - home
```

Follow HA notifications for capture steps. Resulting dataset appears in remote web configurator.

Screenshots:

![Learning Step](https://github.com/user-attachments/assets/7b312f16-4c76-4d67-81bc-901f3e07e095)

![Configurator Result 1](https://github.com/user-attachments/assets/c1b37321-3a61-4e22-b0c1-aeef94379e77)
![Configurator Result 2](https://github.com/user-attachments/assets/2722b8ff-9d9d-4e22-a809-f75091372b5d)

---

## Options
Access via Integration → Configure:

**Control local settings**
- Activity:
  - Create all activities as switches
  - Suppress activity groups as selects
- Media Player:
  - Global media player
  - Per activity group
  - Per activity

- Remote start
  - Define which activity starts when toggling the remote entity (Good fit with HomeKit Bridge)

** Configure connection settings**

- Update remote hostname
- Update Home Assistant websocket URL
---

## Zeroconf
Automatic network discovery; no manual intervention required.

---

## Wake on LAN
Available for Remote Two (firmware ≥ 2.0.0).
Remote 3 support will follow once the firmware adds the feature.

Behavior:
- HA attempts wake before user-triggered commands when needed.

---

## Planned / Future Ideas
- [X] Raw IR command sending via core `remote.send_command`

---

## Notes & Behavior
- Remote entity does not need to be “on” to send commands.
- The Remote Two will go to sleep when unpowered. If you have wake on lan enabled on your remote, Home Assistant will attempt to wake your remote prior to issuing a command. Only commands initiated by you will attempt to wake the remote.
- Diagnostics available via Device Info overflow menu.
- Authentication loss triggers a repair to re-enter PIN.
- Resource usage polling is opt-in per sensor.

---

## Services & Actions Summary
| Service | Purpose | Key Fields |
|---------|---------|-----------|
| `unfoldedcircle.send_button_command` | Send mapped remote button | `button`, `activity?`, `num_repeats?`, `delay_secs?`, `hold?` |
| `unfoldedcircle.send_ir_command` | Emit predefined IR command | `device`, `codeset?`, `command`, `dock_name?`, `port?`, `num_repeats?` |
| `unfoldedcircle.learn_ir_command` | Start IR learning workflow | `remote{}`, `ir_dataset{}` |
| `unfoldedcircle.update_activity` | Modify activity attributes | `prevent_sleep?` |
| `unfoldedcircle.inhibit_standby` | Create a new standby inhibitor | `reason?`, `duration` |

Confirm exact service IDs in Developer Tools → Services.

---

## Troubleshooting & Support
| Issue | Resolution |
|-------|------------|
| Not discovered | Ensure zeroconf and network visibility; try manual add. |
| PIN failing | Regenerate PIN in remote web configurator. |
| IR not firing | Verify device/codeset names & dock availability. |

Join the community on Discord (link at top).

---

## Localization
Supported: English, French, Portuguese.
Contribute additional translations via PR (follow HA localization format).

---

## About This Project
Independent community-driven integration built in collaboration (not affiliation) with Unfolded Circle. Hardware team is awesome. Consider supporting both the platform and this integration.

---

## License
See [LICENSE](LICENSE) for details.

---

## Support the Project
- Star the repository
- Open constructive issues / PRs
- Share ideas for roadmap
- [Buy Me A Coffee](https://buymeacoffee.com/jackpowell)

---
