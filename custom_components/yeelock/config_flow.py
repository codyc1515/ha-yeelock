"""Config flow for the Yeelock integration."""

from __future__ import annotations

import aiohttp
import async_timeout
import asyncio
import socket
import logging
from typing import Any

import voluptuous

from bluetooth_data_tools import human_readable_name
from homeassistant import config_entries
from homeassistant.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_NAME,
    CONF_MAC,
    CONF_MODEL,
    CONF_API_KEY,
)
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = voluptuous.Schema(
    {
        voluptuous.Required(CONF_EMAIL): str,
        voluptuous.Required(CONF_PASSWORD): str,
        voluptuous.Required(CONF_NAME): str,
        voluptuous.Required(CONF_MAC): str,
        voluptuous.Required(CONF_MODEL): str,
        voluptuous.Required(CONF_API_KEY): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yeelock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize Yeelock config flow."""
        self._session = None  # Avoids unclosed client session
        self._schema = STEP_USER_DATA_SCHEMA
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Starting bluetooth step")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        self.context["title_placeholders"] = {
            "name": human_readable_name(
                None, discovery_info.name, discovery_info.address
            )
        }

        self._schema = voluptuous.Schema(
            {
                voluptuous.Required(CONF_EMAIL): str,
                voluptuous.Required(CONF_PASSWORD): str,
            }
        )

        _LOGGER.debug("Handoff to cloud step")
        return await self.async_step_cloud()

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            _LOGGER.debug("Starting user login")

            if self._discovery_info and self._discovery_info.address:
                address = self._discovery_info.address
            else:
                _LOGGER.debug("Integration must be set-up from auto-discovery")
                return self.async_abort(reason="no_devices_found")

            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            # Get OAuth token
            _LOGGER.debug("Get token")
            login = await self._api_wrapper(
                method="post",
                url="https://api.yeeloc.com/v2/auth/by/password",
                params={
                    "account": user_input[CONF_EMAIL],
                    "password": user_input[CONF_PASSWORD],
                },
                headers={
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8"
                },
            )

            try:
                if login.get("data").get("access_token"):
                    access_token = login.get("data").get("access_token")
                    # Get locks
                    _LOGGER.debug("Get locks")
                    locks = await self._api_wrapper(
                        method="get",
                        url="https://api.yeeloc.com/lock",
                        headers={"Authorization": "Bearer " + access_token},
                    )

                    _LOGGER.debug(locks)
                    for lock in locks:
                        if (
                            self._discovery_info.name.removeprefix("EL_")
                            == lock["lock_sn"]
                        ):
                            _LOGGER.debug("Found lock and key")

                            user_input[CONF_API_KEY] = lock["ble_sign_key"]
                            user_input[CONF_MAC] = address
                            user_input[CONF_NAME] = lock["lock_name"]
                            user_input[CONF_MODEL] = lock["lock_type"]

                            await self._session.close()

                            return self.async_create_entry(
                                title=user_input[CONF_NAME], data=user_input
                            )
                    errors["base"] = "cannot_connect"
                else:
                    errors["base"] = "auth_error"
            except KeyError:
                errors["base"] = "unknown"

            _LOGGER.warning("Failed cloud login")
            return self.async_show_form(step_id="cloud", data_schema=self._schema)
        else:
            _LOGGER.debug("Showing cloud form")
            return self.async_show_form(
                step_id="cloud", data_schema=self._schema, errors=errors
            )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        _LOGGER.debug("Integration must be set-up from auto-discovery")
        return self.async_abort(reason="no_devices_found")

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> any:
        """Get information from the API."""
        if self._session is None:
            self._session = aiohttp.ClientSession()

        try:
            async with async_timeout.timeout(10):
                response = await self._session.request(
                    method=method,
                    url=url,
                    data=data,
                    json=json,
                    params=params,
                    headers=headers,
                )
                if response.status in (400, 401, 403):
                    raise Exception(
                        "Invalid credentials",
                    )
                response.raise_for_status()
                return await response.json()

        except asyncio.TimeoutError as exception:
            raise Exception(
                "Timeout error fetching information: %s", exception
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise Exception("Error fetching information: %s", exception) from exception
        except Exception as exception:  # pylint: disable=broad-except
            raise Exception(
                "Something really wrong happened! %s", exception
            ) from exception
