"""Yeelock device description"""
import asyncio
import datetime
import hashlib
import hmac
import logging
import uuid
from binascii import hexlify
from time import time

from bleak import BleakClient
from bleak.exc import BleakDBusError, BleakError
from homeassistant.backports.enum import StrEnum
from homeassistant.components import bluetooth
from homeassistant.const import CONF_API_KEY, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

UUID_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
UUID_COMMAND = "58af3dca-6fc0-4fa3-9464-74662f043a3b"
UUID_NOTIFY = "58af3dca-6fc0-4fa3-9464-74662f043a3a"

_LOGGER = logging.getLogger(__name__)


class YeelockDeviceEntity:
    """Entity class for the Yeelock devices"""

    _attr_has_entity_name = True

    def __init__(self, yeelock_device, hass: HomeAssistant):
        """Init entity with the device"""
        self._attr_unique_id = f'{yeelock_device.mac}_{self.__class__.__name__}'  # noqa: E501
        self.device: Yeelock = yeelock_device
        self.hass = hass

    @property
    def device_info(self):
        """Shared device info information"""
        return {
            'identifiers': {(DOMAIN, self.device.mac)},
            'connections': {(dr.CONNECTION_NETWORK_MAC, self.device.mac)},
            'name': self.device.name,
            'manufacturer': 'Xiaomi',
            'model': self.device.model,
        }


class Yeelock:
    """Yeelock class"""

    def __init__(self, config: dict, hass: HomeAssistant) -> None:
        """Initialize device"""
        self._device_status = None
        self._client = None
        self._hass = hass
        self._device = None
        self._connecting = False
        self.mac = config.get(CONF_MAC)
        self.name = config.get(CONF_NAME)
        self.key = config.get(CONF_API_KEY)
        self.hostname = ''
        self.model = 'Yeelock'
        self.friendly_name = ''
        self.connected = False
        self.notify = False
        self.service = 0
        self.is_on = False

    async def disconnect(self):
        """Disconnect from the device"""
        _LOGGER.debug('Disconnected from %s', self.mac)
        if (self._client is not None) and self._client.is_connected:
            await self._client.disconnect()

    async def _connect(self):
        """
        Connect to the device
        :raises BleakError: if the device is not found
        """
        self._connecting = True
        try:
            if (self._client is None) or (not self._client.is_connected):
                self._device = bluetooth.async_ble_device_from_address(
                    self._hass, self.mac, connectable=True
                )
                if not self._device:
                    raise BleakError(
                        f'A device with address {self.mac} \
                            could not be found.'
                    )
                self._client = BleakClient(self._device)
                _LOGGER.debug('Connecting to %s', self.mac)
                await self._client.connect()
                await self._client.start_notify(
                    uuid.UUID(UUID_NOTIFY), self._handle_data
                )
        except Exception as error:
            self._connecting = False
            raise error
        self._connecting = False

    async def _handle_data(self, sender, value):
        _LOGGER.debug('Received %s from %s', hexlify(value, ' '), sender)  # noqa: E501
        #await self._event_trigger(value)

    def _encrypt(self, unlock_mode):
        # Given values
        unlock_command = 0x01
        admin_identification_mode = 0x50
        key = bytearray.fromhex(self.key)
        variant = hashlib.sha1

        # Convert epoch time to a human-readable date and time
        timestamp = int(time())

        # Generate the HMAC
        message = unlock_command.to_bytes(1, "big") \
                + admin_identification_mode.to_bytes(1, "big") \
                + timestamp.to_bytes(4, 'big') \
                + int(unlock_mode, 16).to_bytes(1, 'big')
        hmac_result = bytearray.fromhex(hmac.new(key, message[:7], hashlib.sha1).hexdigest())[:13]

        # Concatenate all the parts to create the output value as a bytearray
        output_value = unlock_command.to_bytes(1, "big") \
                     + admin_identification_mode.to_bytes(1, "big") \
                     + timestamp.to_bytes(4, 'big') \
                     + int(unlock_mode, 16).to_bytes(1, 'big') \
                     + hmac_result

        _LOGGER.debug('Sent %s', output_value)
        return output_value

    async def lock(self) -> None:
        """Lock the device."""
        await self._connect()
        try:
            _LOGGER.debug('Locking')
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt("02"))
            )
        except BleakError as error:
            self.connected = False
            _LOGGER.error('BleakError: %s', error)

    async def unlock(self) -> None:
        """Unlock the device."""
        await self._connect()
        try:
            _LOGGER.debug('Unlocking')
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt("01"))
            )
        except BleakError as error:
            self.connected = False
            _LOGGER.error('BleakError: %s', error)

    async def unlock_quick(self) -> None:
        """Unlock the device then relock again quickly."""
        await self._connect()
        try:
            _LOGGER.debug('Unlocking the device then relocking again quickly')
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt("00"))
            )
        except BleakError as error:
            self.connected = False
            _LOGGER.error('BleakError: %s', error)