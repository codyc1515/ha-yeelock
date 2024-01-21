"""Constants for the Yeelock integration."""
from homeassistant.const import Platform

DOMAIN = "yeelock"

PLATFORMS: list[str] = [
    Platform.BUTTON,
    Platform.LOCK,
    # Platform.BINARY_SENSOR,
    # Platform.SENSOR,
    # Platform.SELECT,
    # Platform.SWITCH,
    # Platform.TEXT,
    # Platform.DEVICE_TRACKER
]

CONF_PHONE = "phone"
