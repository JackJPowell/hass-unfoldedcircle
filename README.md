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
There is a config flow for this integration. After installing the custom component:

1. Go to **Settings** -> **Devices & Services** -> **Integrations**
2. Click **+ ADD INTEGRATION** to setup a new integration
3. Search for **Unfolded Circle** and select it
4. *You will now begin the configuration flow process*
5. **PIN** can be found on the remote by enabling the web configurator
   1. Enable the web configurator by tapping in the upper right on your profile icon
   2. Make sure the toggle is 'ON' and a PIN will be displayed. If not, click the refresh button
   3. The **PIN** is only required during initial setup. You are free to change it immediately after
7. **Host** is the IP address or hostname of your remote
   1. *(Optional) If you have a custom api url, you can pass in the full endpoint address*


## Usage
After the device is configured, the integration will expose 4 entities plus the number of activities you have defined on your remote. These are grouped by device.

- Sensors
    - Battery: Reporting current charge percentage
    - Illuminance: Reporting current lux value from ambient light sensor
    - Resource Usage: CPU load, Memory, and Storage Statistics
- Binary Sensor
    - Battery Charging Status: Charging state of device: Helpful in automations to tell if the device is charging (online and available)
- Update
    - Verion info: Reports current version and latest version
        - The ability to install Remote Two firmware from within home assistant is implemented but currently disabled.
- Switches
    - A switch is created for every activity defined
- Button
    - A button is available to restart the remote
- Remote
    - A remote is available to send pre-configured IR commands from the dock (See Below)


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
> [!TIP]
> **device:** will match the case-sensitive name of your remote defined in the web configurator on the remote page. **command** will match the case-senstitive name of the pre-defined (custom or codeset) command defined for that remote. **num_repeats** is optional.


## Zeroconf
Your Remote Two will now be automatically discovered on the network. If you have already configured the remote two integration, you can ignore this discovery. 
Currently, there is insufficient data sent in the mdns broadcast to identify if you have previosly added this device to home assistant. Until that changes, a single click of ignore will hide the request from view. 

## Future Ideas
- [x] Implement a remote entity to send IR commands (Easy)
- [x] Implement a service entity to send power commands to the remote itself (Easy)
- [x] Add support for zeroconf discovery
- [ ] Once WOL is added by the remote developers, implement it in the hass integration to wake the remote prior to sending commands
- [ ] Provide the ability to adjust settings on the remote from within home assistant (Useful?)
- [ ] Provide the ability to reconfigure the integration from the UI


## Notes
- The remote entity does not need to be "on" for it to send commands.
- The Remote Two will go to sleep when unpowered. When this occurs, Home Assistant is unable to communicate with the remote and retrieve updates.


## About This Project

I am not associated with Unfolded Circle, and provide this custom component purely for your own enjoyment and home automation needs. Those guys are awesome though!
