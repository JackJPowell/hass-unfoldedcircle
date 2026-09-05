# Changelog

All notable changes to this project are documented in this file.

## Unreleased

## 2.1.1

### Fixed

- Some battery sensor icon states were not being rendered correctly

## v2.1.0

### Added

- An Activities option can automatically synchronize activity state changes to other configured Remotes. It is located in the option menu `Configure local settings`
- Activity states can now be synchronized across configured Remotes using the **Sync Activity States** button.
- The `update_activity` action now supports setting an activity state (`ON` or `OFF`) without running its activity sequence.

### Changed

- Expanded German, French, and Portuguese translations for configuration, Dock, WebSocket, and error-recovery flows.

### Fixed

- Restored reliable entity-configuration setup by revalidating and reconnecting the Home Assistant driver before refreshing entities.
- Manual setup of a Remote already discovered through mDNS no longer surfaces an unexpected in-progress-flow error.


## v2.0.3

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
