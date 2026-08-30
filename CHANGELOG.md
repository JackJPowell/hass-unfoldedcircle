# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Fixed

- The `send_ir_command` action again accepts the user-visible Remote name.
- Firmware-update failures now explain when an HTTP 503 is likely caused by the Remote battery being below 50%.

## v2.0.2

### Fixed

- Integration now requires `unfurled` 0.4.0, which provides the required Remote entity API.
- Media-player artwork larger than 5 MB is now downloaded and resized instead of being rejected.

## v2.0.1

### Added

- Optional resizing of media-player artwork before it is sent to the Remote.
- Optional automatic configuration of newly shared Home Assistant entities.

### Changed

- Battery icons now reflect charge level and charging method.
- Media-player controls follow the active activity and advertise only supported volume and mute controls.

### Fixed

- Media-player refreshes no longer create an unhandled error when the Remote disconnects.
