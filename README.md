## hass-unfolded-circle

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
      - An easy way to do this is using the [Samba add-on](https://www.home-assistant.io/getting-started/configuration/#editing-configuration-via-sambawindows-networking), but feel free to do so however you want
   3. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

While the manual installation above seems like less steps, it's important to note that you will not be able to see updates to this custom component unless you are subscribed to the watch list. You will then have to repeat each step in the process. By using HACS, you'll be able to see that an update is available and easily update the custom component. Trust me, HACS is the worth the small upfront investment to get it setup.

## Configuration

There is a config flow for this integration. After installing the custom component:

1. Go to **Configuration**->**Integrations**
2. Click **+ ADD INTEGRATION** to setup a new integration
3. Search for **Unfolded Circle** and click on it
4. You will now begin the configuration flow process
5. PIN can be found on the remote by enabling the web configurator
6. Host is the IP address or hostname your remote
7. If you have a custom api url, you can pass in the full endpoint address

##Usage

After the device is configured, the integration will expose 4 entities plus the number of activities you have defined on your remote. These are grouped by device.

- Sensors
    - Battery: Reporting current charge percentage
    - Illuminance: Reporting current lux value from ambient light sensor
- Binary Sensor
    - Battery Charging Status: Charging state of device: Helpful in automations to tell if the device is charging (online and available)
- Update
    - Verion info: Reports current version and latest version
        - The ability to install Remote Two firmware from within home assistant is implemented but currently disabled.
- Switches
    - A switch is created for every activity defined

## Future Ideas

- Implement a remote entity to send IR commands (Easy)
- Implement a service entity to send power commands to the remote itself (Easy)
- Provide the ability to adjust settings on the remote from with home assistant (Useful?)

## About This Project

I am not associated with Unfolded Circle, and provide this custom component purely for your own enjoyment and home automation needs. Those guys are awesome though! Keep on killing it!