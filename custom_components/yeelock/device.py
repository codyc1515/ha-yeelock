"""Yeelock device."""

import asyncio
import hashlib
import hmac
import logging
import uuid
from binascii import hexlify
from time import time

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.const import CONF_API_KEY, CONF_MAC, CONF_MODEL, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, LOCKER_KIND, UUID_COMMAND, UUID_NOTIFY


_LOGGER = logging.getLogger(__name__)


class YeelockDeviceEntity:
    """Entity class for the Yeelock devices."""

    _attr_has_entity_name = True

    def __init__(self, yeelock_device, hass: HomeAssistant):
        """Init entity with the device."""
        self.hass = hass
        self.device: Yeelock = yeelock_device
        self._attr_unique_id = f"{yeelock_device.mac}_{self.__class__.__name__}"
        self._last_action = None  # Track last requested action

    @property
    def device_info(self):
        """Shared device info information."""
        return {
            "identifiers": {(DOMAIN, self.device.mac)},
            "connections": {(dr.CONNECTION_NETWORK_MAC, self.device.mac)},
            "name": self.device.name,
            "manufacturer": self.device.manufacturer,
            "model": self.device.model,
        }


class Yeelock:
    """Yeelock class."""

    def __init__(self, config: dict, hass: HomeAssistant) -> None:
        """Initialize device."""
        self._hass = hass
        self._device = None
        self._lock = None
        self._battery_sensor = None
        self._client = None
        self._connecting = False
        self._connect_lock = asyncio.Lock()
        self._connected = False
        self.mac = config.get(CONF_MAC)
        self.name = config.get(CONF_NAME)
        self.key = config.get(CONF_API_KEY)
        self.model = config.get(CONF_MODEL, None)
        self.manufacturer = "Yeelock"
        self.battery_level = None
        self._last_action = None

    async def disconnect(self):
        """Disconnect from the device."""
        _LOGGER.debug("Disconnected from %s", self.mac)
        if (self._client is not None) and self._client.is_connected:
            await self._client.disconnect()

    async def _connect(self):
        """Connect to the device.

        :raises BleakError: if the device is not found
        """
        async with self._connect_lock:
            if self._client is not None and self._client.is_connected:
                return

            self._connecting = True
            try:
                self._device = bluetooth.async_ble_device_from_address(
                    self._hass, self.mac, connectable=True
                )
                if not self._device:
                    raise BleakError(
                        f"A device with address {self.mac} could not be found."
                    )
                _LOGGER.debug("Connecting to %s", self.mac)
                self._client = await establish_connection(
                    BleakClient,
                    self._device,
                    self.mac,
                    max_attempts=3,
                )
                _LOGGER.debug("Connected to %s", self.mac)
                await self._client.start_notify(
                    uuid.UUID(UUID_NOTIFY), self._handle_data
                )
                _LOGGER.debug("Listening for notifications", self.mac)
            finally:
                self._connecting = False

    async def _handle_data(self, sender, value):
        """Handle data notifications."""
        _LOGGER.debug("Received %s from %s", hexlify(value, " "), sender)  # noqa: E501
        new_state = None

        # Hex the received message
        received_message = hexlify(value, " ")

        # Extract the first element (index 0) and convert it to an integer
        first_byte = hex(int(received_message.split()[0], 16))

        # Lock change successes
        # Unlocking
        if first_byte == hex(0x2):
            new_state = "unlocking"

        # Unlocked
        elif first_byte == hex(0x3):
            new_state = "unlocked"

        # Locking
        elif first_byte == hex(0x4):
            new_state = "locking"

        # Locked
        elif first_byte == hex(0x5):
            new_state = "locked"

        # Lock change failures
        # Invalid signing key
        elif first_byte == hex(0xFF):
            _LOGGER.error("Invalid signing key")
            new_state = "jammed"

        # Time needs to be synced
        elif first_byte == hex(0x9):
            _LOGGER.info("Lock reported time drift; syncing time")
            await self.time_sync()
            if self._last_action:
                _LOGGER.debug("Retrying last action after time sync: %s", self._last_action)
                await self.locker(self._last_action)
                self._last_action = None

        # Battery response notification
        elif first_byte == hex(0x7):
            if len(value) > 6:
                self.battery_level = value[6]
                _LOGGER.debug("Received battery level: %s%%", self.battery_level)
                if self._battery_sensor is not None:
                    await self._battery_sensor._update_battery_level(self.battery_level)
            else:
                _LOGGER.warning("Battery notification too short: %s", received_message)

        # Unknown notification received
        else:
            _LOGGER.warning("Unknown notification received (%s)", first_byte)

        # Update to the new lock state, if we have one
        if new_state is not None:
            _LOGGER.debug("Notified of %s", new_state)
            await self._lock._update_lock_state(new_state)

    def _encrypt_command(
        self, command: int, admin_identification_mode: int, payload: bytes = b""
    ) -> bytes:
        """Encrypt a command packet.

        The protocol frames are 20 bytes long and include:
        command + admin mode + timestamp + optional payload + HMAC-SHA1 fragment.
        """
        key = bytearray.fromhex(self.key)
        timestamp = int(time())

        message = (
            command.to_bytes(1, "big")
            + admin_identification_mode.to_bytes(1, "big")
            + timestamp.to_bytes(4, "big")
            + payload
        )
        signature_length = 20 - len(message)
        hmac_result = bytearray.fromhex(
            hmac.new(key, message, hashlib.sha1).hexdigest()
        )[:signature_length]
        return message + hmac_result

    def _encrypt(self, unlock_mode):
        """Encrypt lock and unlock command packets."""
        output_value = self._encrypt_command(
            command=0x01,
            admin_identification_mode=0x50,
            payload=int(unlock_mode, 16).to_bytes(1, "big"),
        )
        _LOGGER.debug("Sent transactional msg %s", output_value)
        return output_value

    def _encrypt_time(self):
        """Encrypt the time sync command packet."""
        output_value = self._encrypt_command(command=0x08, admin_identification_mode=0x40)
        _LOGGER.debug("Sent time sync msg %s", output_value)
        return output_value

    def _encrypt_battery(self):
        """Encrypt the battery request command packet."""
        output_value = self._encrypt_command(command=0x06, admin_identification_mode=0x40)
        _LOGGER.debug("Sent battery msg %s", output_value)
        return output_value

    async def locker(self, kind) -> None:
        """Lock, unlock and quick unlock the device."""
        self._last_action = kind  # Save action before attempting
        await self._connect()
        try:
            _LOGGER.debug("Locking")
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt(LOCKER_KIND[kind]))
            )
        except BleakError as error:
            self._connected = False
            _LOGGER.error("BleakError: %s", error)
        finally:
            # Refresh battery after lock activity when the battery entity exists.
            if self._battery_sensor is not None:
                await self.update_battery()

    async def time_sync(self) -> None:
        """Time sync and retry."""
        await self._connect()
        try:
            # Sync the time
            _LOGGER.debug("Time sync start")
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt_time())
            )
        except BleakError as error:
            self._connected = False
            _LOGGER.error("BleakError: %s", error)

    async def update_battery(self) -> None:
        """Request battery level from the lock over BLE."""
        try:
            await self._connect()
            _LOGGER.debug("Requesting battery level")
            await self._client.write_gatt_char(
                uuid.UUID(UUID_COMMAND), bytearray(self._encrypt_battery())
            )
        except BleakError as error:
            self._connected = False
            _LOGGER.error("BleakError: %s", error)
        except Exception as error:  # pragma: no cover - backend-specific transient failures
            self._connected = False
            _LOGGER.warning("Unable to update battery for %s: %s", self.mac, error)
