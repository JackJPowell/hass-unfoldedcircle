[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Release](https://img.shields.io/github/v/release/jackjpowell/hass-unfoldedcircle)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/jackjpowell/hass-unfoldedcircle/total)

## hass-unfoldedcircle

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/unfoldedcircle/dark_logo.png">
  <img alt="Unfolded Circle logo" src="https://brands.home-assistant.io/unfoldedcircle/logo.png">
</picture>

## Unfolded Circle for Home Assistant

Home Assistant integration for [Unfolde Circle Remote Two](https://www.unfoldedcircle.com/).

## Installation

There are two main ways to install this custom component within your Home Assistant instance:

1. Using HACS (see https://hacs.xyz/ for installation instructions if you do not already have it installed):

   1. From within Home Assistant, click on the link to **HACS**
   2. Click on **Integrations**
   3. Click on the vertical ellipsis in the top right and select **Custom repositories**
   4. Enter the URL for this repository in the section that says _Add custom repository URL_ and select **Integration** in the _Category_ dropdown list
   5. Click the **ADD** button
   6. Close the _Custom repositories_ window
   7. You should now be able to see the _Unfolde Circle_ card on the HACS Integrations page. Click on **INSTALL** and proceed with the installation instructions.
   8. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

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
  - A reminder: The controls are acting solely on the entity that is being displayed and not the activity that is running. For instance, if the media player doesn't control your volume, e.g. your receiver does, adjusting the volume via the media player controls will not have the desired effect.
- Number

  - Configuration Controls: All numerical settings are now controllable via the integration.

  \*\* Disabled by default to avoid polling the remote every thirty seconds to read data. If one of these sensors is enabled, polling only for that specific data will also be enabled.

## IR Remote Commands

How to interact with the Remote Service:
The remote entity supports sending IR commands using the remote.send_command service.

```
service: remote.send_command
data:
  device: Receiver
  command: Power
target:
  entity_id: remote.remote_two_remote
```

> [!TIP] > **device:** will match the case-sensitive name of your remote defined in the web configurator on the remote page. **command** will match the case-senstitive name of the pre-defined (custom or codeset) command defined for that remote. **num_repeats** is optional.

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

Your Remote Two will now be automatically discovered on the network.
**Zeroconf handling has been significantly improved and should now properly detect when a device has already been configured.**

## Future Ideas

- [x] Implement a remote entity to send IR commands (Easy)
- [x] Implement a service entity to send power commands to the remote itself (Easy)
- [x] Add support for zeroconf discovery
- [x] Implement Home Assistant Coordinator Class to have some empathy for the machine
- [x] Provide the ability to adjust settings on the remote from within home assistant (Useful?)
- [x] Provide the ability to reconfigure the integration from the UI
- [ ] Once WOL is added by the remote developers, implement it in the hass integration to wake the remote prior to sending commands

## Notes

- The remote entity does not need to be "on" for it to send commands.
- The Remote Two will go to sleep when unpowered. When this occurs, Home Assistant is unable to communicate with the remote and retrieve updates.
- The remote can now generate its own diagnostic data to submit to aid in debugging via the overflow menu in the Device Info section
- The integration supports multiple Languages: English, French
- The integration will now identify a repair and prompt for a new PIN if it can no longer authenticate to the remote

## About This Project

I am not associated with Unfolded Circle, and provide this custom component purely for your own enjoyment and home automation needs. Those guys are awesome though!
