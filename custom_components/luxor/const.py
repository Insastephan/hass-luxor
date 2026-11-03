"""Constants for the FXLuminaire Luxor integration."""
from homeassistant.const import Platform

NAME = "FXLuminaire Luxor"
DOMAIN = "luxor"
MANUFACTURER = "FXLuminaire"
ISSUE_URL = "https://github.com/Insastephan/hass-luxor/issues"

# Kept from the original integration so existing devices keep their identity.
LIGHT_DEVICE_DOMAIN = "luxor_light"

PLATFORMS = [Platform.LIGHT, Platform.SCENE]

# Configuration (entry.data) and options (entry.options)
CONF_HOST = "host"
CONF_GROUP_INTERVAL = "group_interval"
CONF_THEME_INTERVAL = "theme_interval"
CONF_SEND_INTERVAL = "send_interval"
CONF_REQUEST_TIMEOUT = "request_timeout"
CONF_COALESCE_EXTINGUISH = "coalesce_extinguish"

DEFAULT_GROUP_INTERVAL = 60
DEFAULT_THEME_INTERVAL = 600
DEFAULT_SEND_INTERVAL = 1.0
DEFAULT_REQUEST_TIMEOUT = 3.0
DEFAULT_COALESCE_EXTINGUISH = True

# Wait before re-reading the controller after a scene was switched, so the
# fixtures have reached their new intensities.
SCENE_SETTLE_DELAY = 1.5
