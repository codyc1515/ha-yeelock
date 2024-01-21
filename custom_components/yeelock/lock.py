import logging

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import Yeelock, YeelockDeviceEntity


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    yeelock_device: Yeelock = hass.data[DOMAIN][entry.unique_id]
    lock_entity = YeelockLock(yeelock_device, hass)
    yeelock_device.lock_entity = lock_entity  # Pass the reference
    async_add_entities([lock_entity])
    return True


class YeelockLock(YeelockDeviceEntity, LockEntity):
    """This button locks the device"""

    _attr_name = "Lock"
    _attr_state = "locked"  # Assume locked state on load

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
        return self._attr_state == "locked"

    async def _update_lock_state(self, new_state):
        _LOGGER.debug("Setting state to %s", new_state)
        self._attr_state = new_state
        self.async_write_ha_state()

    async def async_lock(self):
        await self.hass.async_create_task(self.device.lock())

    async def async_unlock(self):
        await self.hass.async_create_task(self.device.unlock())
