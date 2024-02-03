"""Yeelock button."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import Yeelock, YeelockDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up the Yeelock button platform."""
    yeelock_device: Yeelock = hass.data[DOMAIN][entry.unique_id]
    async_add_entities(
        [
            YeelockQuickUnlockButton(yeelock_device, hass),
            YeelockTimeSyncButton(yeelock_device, hass),
        ]
    )
    return True


class YeelockQuickUnlockButton(YeelockDeviceEntity, ButtonEntity):
    """This button unlocks the device."""

    _attr_name = "Quick Unlock"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self):
        """Handle button pressses."""
        self.hass.async_create_task(self.device.locker('quick_unlock'))


class YeelockTimeSyncButton(YeelockDeviceEntity, ButtonEntity):
    """This button syncs the time of the device."""

    _attr_name = "Time Sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self):
        """Handle button pressses."""
        self.hass.async_create_task(self.device.time_sync())
