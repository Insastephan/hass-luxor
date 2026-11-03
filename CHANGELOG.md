# Changelog

## 0.1.0 (unreleased)

First release of the fork.

### Fixed
- Commands no longer get lost: all requests go through one queue per controller, with at least one second between switching commands, as required by the Luxor protocol.
- Dropped connections ("Cannot connect", "Server disconnected") are retried with a fresh connection.
- Non-zero status codes from the controller are reported instead of ignored.
- Lights update right after a scene is activated instead of after the next poll.
- Warning about the blocking SSL call during startup.
- Deprecated `via_device` usage (stops working in Home Assistant 2027.8).

### Added
- Color support for groups on color controllers.
- Support for the GroupList format of monochrome ZD controllers.
- Controller type detection (ZD, ZDC, Luxor 2) and model shown on the device.
- "Last write wins" per group and an optional single "all off" command.
- Immediate state feedback while commands are queued.
- DMX-controlled groups (Luxor 2) are protected and flagged.
- Options for poll intervals, command spacing, request timeout and "all off".
- German translation.

### Changed
- Removed the dependency on `luxor-openapi-asyncio`.
- Minimum Home Assistant version is 2025.1.
