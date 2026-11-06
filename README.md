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

## How it works in Home Assistant

**Lights.** Each Luxor group becomes a light named after the group. Extra attributes:

| Attribute | Meaning |
|---|---|
| `luxor_group` | Group number on the controller |
| `luxor_color` | Color slot of the group (0 = monochrome, 1–250 = color list, 251–260 = color wheel) |
| `dmx_control` | `true` while the group is under DMX control (Luxor 2); it cannot be switched then |
| `color_wheel` | `true` if the group runs a color wheel; Home Assistant then shows no fixed color |

**Scenes.** Each Luxor theme becomes a scene. On a new installation, Home Assistant puts the controller name in front, so a theme "All On" on controller `lxtwo-1234` becomes `scene.lxtwo_1234_all_on`. Existing installations keep their scene IDs. Attributes: `luxor_theme` (theme number) and `theme_on`.

**Adding and removing groups.** A group you create in the Luxor app shows up as a new light on the next update (60 s by default), without a restart. A group you delete there becomes *unavailable*; you can then delete its device under *Settings → Devices & services → Devices*.

**Colors.** On color controllers, groups with color fixtures get a color picker. The controller keeps colors in a list of 250 slots: a color that is already in the list is reused, a new one takes a free slot.

**Changes made elsewhere.** The controller never reports changes by itself. Switching from the Luxor app, a controller schedule or the facepack shows up in Home Assistant on the next update. Lower the *Light update interval* (for example to 20 s) if you want that sooner.

## Tips and examples

### Switch many groups at once: use a theme

Every switching command takes about a second, so turning on ten groups one by one takes about ten seconds. A Luxor theme does the same with **one** command. Build the combinations you need as themes in the Luxor app and call the scenes from Home Assistant.

A power button that toggles the whole garden. `light.garden_all` is a light group you create in Home Assistant with your Luxor lights:

```yaml
alias: Garden on/off
mode: single
sequence:
  - if:
      - condition: state
        entity_id: light.garden_all
        state: "on"
    then:
      - action: scene.turn_on
        target:
          entity_id: scene.lxtwo_1234_all_off
    else:
      - action: scene.turn_on
        target:
          entity_id: scene.lxtwo_1234_all_on
```

Make sure your "off" theme switches off **every** group your "on" theme switches on. Otherwise some groups stay lit after "off".

### Light groups in Home Assistant

You can put Luxor lights into a Home Assistant light group. Turning it on or off sends one command per group, about one per second. If the group contains **every** group of the controller, "off" becomes a single "all off" command (option *Switch all groups off with one command*).

### Set a color

```yaml
action: light.turn_on
target:
  entity_id: light.hedge_front
data:
  hs_color: [240, 100]   # hue 0-360, saturation 0-100
  brightness_pct: 80
```

Pick saturation 100 for strong colors; lower values give pastel shades.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Setup says it cannot connect | The controller's IP address, and that Home Assistant can reach it on port 80. A fixed IP address (DHCP reservation) for the controller avoids trouble later. |
| Lights become *unavailable* | The controller did not answer three attempts in a row. Check its network connection. On weak Wi-Fi, raise *Timeout per request*. Lights recover by themselves once the controller answers again. |
| Switching many lights is slow | Expected: one command per second. Use a theme instead (see above). |
| Some commands still get lost | Raise *Minimum pause between switching commands*, for example to 1.5 s. |
| Error "under DMX control" | The group is controlled by DMX right now. Switch it from your DMX system, or end DMX control first. |
| A light shows no color although it is lit | The group runs a color wheel. Its color changes over time, so there is no single color to show. |
| A group was deleted in the Luxor app but is still listed | It shows as *unavailable*. Delete the device under *Settings → Devices & services → Devices*. |

### Debug logging

To see what the integration sends and receives, open *Settings → Devices & services → FXLuminaire Luxor*, choose **Enable debug logging**, reproduce the problem, then choose **Disable debug logging**. Home Assistant offers the log as a download.

Or in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.luxor: debug
```

### Reporting a problem

Please [open an issue](https://github.com/Insastephan/hass-luxor/issues/new/choose) and attach a debug log. The form asks for your controller type, which helps a lot, especially for ZD and ZDC controllers.

## Credits and license

Originally written by [David Cramer](https://github.com/dcramer), based on the integration blueprint by [Joakim Sørensen](https://github.com/ludeeus). MIT licensed, see [LICENSE](LICENSE).

[luxor]: https://www.fxl.com/product/transformers/designer/luxor
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
