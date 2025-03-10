[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Release](https://img.shields.io/github/v/release/jackjpowell/hass-unfoldedcircle)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/jackjpowell/hass-unfoldedcircle/total)
<a href="#"><img src="https://img.shields.io/maintenance/yes/2025.svg"></a>
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee&nbsp;☕-FFDD00?logo=buy-me-a-coffee&logoColor=white&labelColor=grey)](https://buymeacoffee.com/jackpowell)
## hass-unfoldedcircle

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/unfoldedcircle/dark_logo.png">
  <img alt="Unfolded Circle logo" src="https://brands.home-assistant.io/unfoldedcircle/logo.png">
</picture>

## Unfolded Circle for Home Assistant

Home Assistant integration for [Unfolded Circle Remote Two](https://www.unfoldedcircle.com/).

## Installation

There are two main ways to install this custom component within your Home Assistant instance:

1. Using HACS (see https://hacs.xyz/ for installation instructions if you do not already have it installed):

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JackJPowell&repository=hass-unfoldedcircle&category=Integration)

   Or

   1. From within Home Assistant, click on the link to **HACS**
   2. Click on **Integrations**
   3. Search for Unfolded Circle and Install

   Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

2. Manual Installation:
   1. Download or clone this repository
   2. Copy the contents of the folder **custom_components/unfoldedcircle** into the same file structure on your Home Assistant instance
   3. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

While the manual installation above seems like less steps, it's important to note that you will not be able to see updates to this custom component unless you are subscribed to the watch list. You will then have to repeat each step in the process. By using HACS, you'll be able to see that an update is available and easily update the custom component. Trust me, HACS is the worth the small upfront investment to get it setup.

## Configuration

There is a config flow for this integration. After installing the custom component and restarting:

1. You should receive a notification that a new device was discovered.
2. Navigate to **Settings** -> **Devices & Services** and click Configure on the newly discovered Remote Two Device.
3. _You will now begin the configuration flow process_
4. **PIN** can be found on the remote by enabling the web configurator
   1. Enable the web configurator by tapping in the upper right on your profile icon
   2. Make sure the toggle is 'ON' and a PIN will be displayed. If not, click the refresh button
   3. The **PIN** is only required during initial setup. You are free to change it immediately after
5. Click Submit and select your device area.

**Alternatively, if you do not have zeroconf discovery enabled, or your remote was not automatically discovered:**

1. Go to **Settings** -> **Devices & Services** -> **Integrations**
2. Click **+ ADD INTEGRATION** to setup a new integration
3. Search for **Unfolded Circle** and select it
4. _You will now begin the configuration flow process_
5. **PIN** can be found on the remote by enabling the web configurator
   1. Enable the web configurator by tapping in the upper right on your profile icon
   2. Make sure the toggle is 'ON' and a PIN will be displayed. If not, click the refresh button
   3. The **PIN** is only required during initial setup. You are free to change it immediately after
6. **Host** is the IP address or hostname of your remote
   1. _(Optional) If you have a custom api url, you can pass in the full endpoint address_

## Usage

After the device is configured, the integration will expose 22 entities plus the number of activities you have defined on your remote. These are grouped by device. Four of these entities will be disabled by default. These are all diagnostic in nature and report the device stats and if polling of the remote is enabled. (This is only true if any of the three device stat entities are enabled.)

- Sensors
  - Battery Level: Reporting current charge percentage
  - Illuminance: Reporting current lux value from ambient light sensor
  - Resource Usage\*\*: CPU load, Memory, and Storage Statistics
  - Configuration Sensors: All boolean settings are now controllable via the integration
- Binary Sensor
  - Battery Charging Status: Charging state of device: Helpful in automations to tell if the device is charging (online and available)
- Update
  - Verion info: Reports the current and latest version of the remote firware
  - The ability to install Remote Two firmware from within home assistant including progress and release notes
  - If the firmware has not been downloaded when the install is initiated, the first 10% of the progress bar will be used to show download progress. If no progress has been made in 30 seconds, the update will stop and not be applied
- Switches
  - A switch is created for every activity defined that is not apart of an activity group.
    - An option exists to create a switch for each activity regardless of activity group.
  - Settings for each configuration option on the remote are also exposed as switches
- Select
  - A select is created for every activity group defined.
    - An option exists to suppress the creation of activity groups
- Button
  - A button is available to restart the remote.
- Remote
  - A remote is available to send pre-configured IR commands from the dock (See Below). It also provides a select to activate an activity and extra state about the status of activities and media player entities
- Media player
  - A media player entity is created providing controls and information about currently playing media. If multiple media player entities are active, the integration attempts to select the most appropriate based on activity and recency.
    - You can override this behavior by selecting a different media source from the sound mode menu in the Media Player control
    - Options exist to create a media player per activity group or per activity.
  - **Update** The media player controls are now mapped to the selected activity's button mapping on the remote. The default is still the active media player, but if you have defined custom volume, next, previous, or power button commands, those will be executed when interacting with the control within home assistant.
- Number

  - Configuration Controls: All numerical settings are now controllable via the integration.

  \*\* Disabled by default to avoid polling the remote every thirty seconds to read data. If one of these sensors is enabled, polling only for that specific data will also be enabled.

## Dock Support

Dock support has now been added. If you have an existing remote configured, you will be prompted with a repair for each dock associated with your remote. You can also add docks via a configuration flow when adding a remote. Each Dock exposes 4 entities:

- Buttons

  - Reboot Dock: Allows you to remotely reboot the dock
  - Identity: Causes the LED to flash to help you identify which dock is which

- Number
  - LED Brightness: Allows you to set the LED brightness level
  - Ethernet Brightness: Allows you to set the Ethernet LED brightness level

During a config flow, if you are unsure of your password, you can skip adding that dock for the moment by submitting the form without a password supplied. This will cause a repair to be created so you can set it at your leasure.

If you are unsure of the password you set, you can change it via the web configurator. Click on the Integrations and Dock menu and then select the dock you need to change the password for. Once changed, come back to the repair and let home assistant know what you set it to.

## External Entity Management

Home Assistant now has the ability to manage the entities it shares with your Unfolded Circle Remote. When setting up a new device or when reconfiguring an existing device, you will be taken through an optional step to configure which Home Assistant entities are available on the remote. This functionality mirrors the same options on the integrations page of your remote. If you are upgrading to this release, you will get a repair to address on first boot. Complete it to switch over to using the much improved communication method with your remote. 

To get started, add a new device or click the configure button. See the video below for a quick demo.
- You must be running v2.0.0 or greater on your unfolded circle remote for this functionality to be available.
  - v2.2+ is currently in beta (But it's very stable)
- This release should work fine for anyone not running the remote beta, but it has only been lightly tested.

https://github.com/user-attachments/assets/96fa94e8-a5ad-4833-9a49-0bf85373eae0

## Mapped Button Remote Commands

For your running activity, you can now send your mapped button commands from within Home Assistant. Using the
remote.send_command or unfoldedcircle.send_button_command action, just specify the `button` from the list below and any additional options.

**num_repeats** (Optional) The number of times to repeat sending the command.
**delay_secs** (Optional) The number of seconds to wait in between sending commands.
**hold** (Optional) Trigger a long press of the supplied button
**activity** (Optional) Identify which activity the button is mapped under. This is only needed if multiple activities are running.

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

## IR Remote Commands

The remote entity supports sending predefined IR commands using the unfoldedcircle.send_ir_command action.

**device:** will match the case-sensitive name of your remote defined in the web configurator on the remote page. This will be your custom name or the manufacturer name selected.

**codeset** (Optional) If you supplied a manufacturer name, you also need to supply the codeset name you are using.

**command** will match the case-senstitive name of the pre-defined (custom or codeset) command defined for that remote.

**num_repeats** (Optional) The number of times to repeat sending the command.

**dock_name** (Optional) The name of the dock you would like to send the command from. If not supplied, all docks will emit the IR signal.

**port** (Optional) The location on the dock you want the IR signal to be emitted from. If not supplied, all ports are used.

![image](https://github.com/user-attachments/assets/64adaf67-9025-46a8-aaab-f90c82fb8c6e)

Yaml of the above image:

```
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

> [!TIP]
You can still use the standard remote.send_command action, however, only custom defined remote codes can be sent due to a limitation with this action.

## Additional Actions

There is now an action to update defined activities. This will be initially released with the option to enable/disable the 'prevent sleep' option within the selected activity.

```
service: unfoldedcircle.update_activity
target:
  entity_id: switch.remote_two_control_projector
data:
  prevent_sleep: true
```

## IR Learning

You can now rapidly learn IR commands through your dock. To get started, go to your developer tools and then to the services tab and recreate the example below with your data. Start by providing a remote entity of the dock you want to learn through. Then add information about the remote to be created in the Unfolded Circle Software (name, icon, and description). Follow that with your IR dataset. Give it a name and a list of commands you would like to learn.

```
service: unfoldedcircle.learn_ir_command
target:
  entity_id: remote.remote_dock_remote
data:
  remote:
    name: Sony TV
    icon: uc:tv
    description: My Sony TV Remote
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

Finally, run this by clicking call service. This will start the dock listening for your commands. If you check your home assistant notifications, you'll get feedback on which step you are on. Continue by clicking the button on your remote that is shown in the notification while pointing at your dock.

![Screenshot 2024-08-02 at 6 44 12 PM](https://github.com/user-attachments/assets/7b312f16-4c76-4d67-81bc-901f3e07e095)

If you run the above you will end up with the following in your Unfolded Circle Remote's web configurator that you can then assign to virtual or physical buttons:

![Screenshot 2024-08-02 at 6 27 48 PM](https://github.com/user-attachments/assets/c1b37321-3a61-4e22-b0c1-aeef94379e77)

![Screenshot 2024-08-02 at 6 34 13 PM](https://github.com/user-attachments/assets/2722b8ff-9d9d-4e22-a809-f75091372b5d)

## Options

Additional options have been added to the intergration for further customization:

- Activity Options:
  - Create all activities as switches
  - Suppress the creation of activity groups as selects (best combined with the previous option)
- Media Player Options:
  - Create a global media player
  - Create a media player for each activity group on your remote
  - Create a media player for each activity on your remote

## Zeroconf

Your Remote will be automatically discovered on the network.

## Wake on lan

Wake on lan support is now available for remotes running firmware version 2.0.0 or higher. Once your remote has been upgraded, and you've turned the feature on, anytime you take a direct action within home assistant to communicate with the remote, it will first attempt to wake the remote up.

## Future Ideas

- [X] Wake on lan was added by the remote developers and has been implemented

## Notes

- The remote entity does not need to be "on" for it to send commands.
- The Remote Two will go to sleep when unpowered. If you have wake on lan enabled on your remote, Home Assistant will attempt to wake your remote prior to issuing a command. Only commands initiated by you will attempt to wake the remote.
- The remote can now generate its own diagnostic data to aid in debugging via the overflow menu in the Device Info section
- The integration supports multiple Languages: English, French
- The integration will now identify a repair and prompt for a new PIN if it can no longer authenticate to the remote

## About This Project

I am now working with the Unfolded Circle staff but am not affiliated with them, and provide this custom component purely for your own enjoyment and home automation needs. Those guys are still awesome!
