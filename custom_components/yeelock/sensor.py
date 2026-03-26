"""Yeelock sensors."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import Yeelock, YeelockDeviceEntity


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up the Yeelock sensor platform."""
    device: Yeelock = hass.data[DOMAIN][entry.unique_id]
    battery_sensor = YeelockBatterySensor(device, hass)
    device._battery_sensor = battery_sensor
    async_add_entities([battery_sensor])
    return True


class YeelockBatterySensor(YeelockDeviceEntity, SensorEntity):
    """Yeelock battery level sensor."""

    _attr_name = "Battery"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        await super().async_added_to_hass()
        if self.device.battery_level is not None:
            self._attr_native_value = self.device.battery_level
        await self.device.update_battery()

    async def _update_battery_level(self, new_level: int) -> None:
        """Handle push updates from BLE notifications."""
        _LOGGER.debug("Setting battery state to %s", new_level)
        self._attr_native_value = new_level
        self.async_write_ha_state()
