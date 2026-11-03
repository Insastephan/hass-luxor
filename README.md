# FXLuminaire Luxor for Home Assistant

[![hacs][hacsbadge]][hacs]

Integrates [FXLuminaire Luxor][luxor] landscape lighting controllers with Home Assistant over the local network.

- Every Luxor **group** becomes a `light` entity with brightness, and with color on color controllers.
- Every Luxor **theme** becomes a `scene` entity.

This is a maintained fork of [dcramer/hass-luxor](https://github.com/dcramer/hass-luxor). It keeps the original unique IDs, so existing installations can switch to it and keep their entities.

## Supported controllers

| Controller | Detected by name | Brightness | Color | Themes | Status |
|---|---|---|---|---|---|
| Luxor 2 | `lxtwo-…` | ✓ | ✓ | 40 | main target, used by the maintainer |
| Luxor ZDC | `lxzdc-…` | ✓ | ✓ | 26 | implemented from the protocol, **untested** |
| Luxor ZD | `luxor-…` | ✓ | – | 26 | implemented from the protocol, **untested** |

If you run a ZD or ZDC controller, feedback is very welcome. Please open an issue and attach a debug log (`logger: custom_components.luxor: debug`).

## Why this fork

The Luxor controller is slow and strict. Its protocol allows only **one switching command per second**, it closes every connection after answering, and it never reports changes on its own. The original integration sent commands in parallel, so some of them were silently dropped. This fork:

- sends all requests through **one queue per controller**, with at least one second between switching commands;
- uses a fresh connection for every request, **retries** unanswered requests up to three times, and checks every status code (errors are reported in plain text, e.g. "242 Bad Group Number");
- replaces a pending command for the same group with the newest value, so a brightness slider does not flood the controller;
- switches every group off with a single "all off" command when all groups are turned off at once (optional);
- shows the new state immediately and reads the real state back after switching, including after activating a scene;
- understands the different data formats of ZD, ZDC and Luxor 2 controllers;
- protects groups under **DMX control** (Luxor 2) from being switched;
- no longer depends on the unmaintained `luxor-openapi-asyncio` library.

## Installation

1. In HACS, add `https://github.com/Insastephan/hass-luxor` as a custom repository (category *Integration*).
2. Install **FXLuminaire Luxor** and restart Home Assistant.
3. Go to *Settings → Devices & services → Add integration → FXLuminaire Luxor* and enter the controller's IP address.

Switching from dcramer/hass-luxor: remove that repository from HACS **without** removing the integration, add this one, install and restart. Entities, devices and dashboards should stay as they are; make a backup first anyway.

## Options

*Settings → Devices & services → FXLuminaire Luxor → Configure*

| Option | Default | Meaning |
|---|---|---|
| Light update interval | 60 s | How often group intensities are read |
| Scene update interval | 600 s | How often the theme list is read |
| Minimum pause between switching commands | 1.0 s | Raise it if commands still get lost |
| Timeout per request | 3.0 s | Raise it for controllers on weak Wi-Fi |
| Switch all groups off with one command | on | Uses "ExtinguishAll" when every group is turned off at once |

Switching many groups one by one takes about a second per group. For several groups at once, a Luxor theme (scene) is faster: it is a single command.

## Credits and license

Originally written by [David Cramer](https://github.com/dcramer), based on the integration blueprint by [Joakim Sørensen](https://github.com/ludeeus). MIT licensed, see [LICENSE](LICENSE).

[luxor]: https://www.fxl.com/product/transformers/designer/luxor
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
