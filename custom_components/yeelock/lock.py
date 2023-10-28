from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import Yeelock, YeelockDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
):
    yeelock_device: Yeelock = hass.data[DOMAIN][entry.unique_id]
    async_add_entities(
        [
            YeelockLock(yeelock_device, hass)
        ]
    )
    return True


class YeelockLock(YeelockDeviceEntity, LockEntity):
    """This button locks the device"""

    _attr_name = 'Lock'
    _attr_state = 'locked' # Assume locked state on load
    
    @property
    def is_locking(self):
        """Return true if lock is locking."""
        return self._attr_state == "locking"

    @property
    def is_unlocking(self):
        """Return true if lock is unlocking."""
        return self._attr_state == "unlocking"

    @property
    def is_jammed(self):
        """Return true if lock is jammed."""
        return self._attr_state == "jammed"

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        return self._attr_state in "locked"

    async def async_lock(self):
        self._attr_state = "locking"
        self.async_write_ha_state()
        
        await self.hass.async_create_task(self.device.lock())
        
        self._attr_state = "locked"
        self.async_write_ha_state()

    async def async_unlock(self):
        self._attr_state = "unlocking"
        self.async_write_ha_state()
        
        await self.hass.async_create_task(self.device.unlock())
        
        self._attr_state = "unlocked"
        self.async_write_ha_state()
