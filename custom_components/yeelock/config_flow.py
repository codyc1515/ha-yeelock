"""Config flow for the Yeelock integration."""

from __future__ import annotations

import aiohttp
import async_timeout
import socket
import logging
from typing import Any

import voluptuous

from bluetooth_data_tools import human_readable_name
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.const import (
    CONF_COUNTRY_CODE,
    CONF_PASSWORD,
    CONF_NAME,
    CONF_MAC,
    CONF_MODEL,
    CONF_API_KEY,
)
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AUTO_UNLOCK_LOW_BATTERY,
    CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
    CONF_PHONE,
    DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
    DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_ACCOUNT_TYPE = "account_type"
ACCOUNT_TYPE_EMAIL = "email"
ACCOUNT_TYPE_PHONE = "phone"

STEP_USER_DATA_SCHEMA = voluptuous.Schema(
    {
        voluptuous.Required(CONF_PHONE): str,
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

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> YeelockOptionsFlow:
        """Create the options flow."""
        return YeelockOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize Yeelock config flow."""
        self._schema = STEP_USER_DATA_SCHEMA
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._account_type: str = ACCOUNT_TYPE_EMAIL

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

        # If this account was already configured for another lock, try to
        # automatically provision this newly discovered lock.
        if auto_entry := await self._async_try_auto_configure_from_saved_account():
            return auto_entry

        _LOGGER.debug("Handoff to account type step")
        return await self.async_step_account_type()

    def _get_saved_account_data(self) -> dict[str, Any] | None:
        """Get a previously configured Yeelock account payload."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if (
                CONF_PHONE in entry.data
                and CONF_PASSWORD in entry.data
                and entry.data[CONF_PHONE]
                and entry.data[CONF_PASSWORD]
            ):
                return dict(entry.data)
        return None

    async def _async_try_auto_configure_from_saved_account(self) -> FlowResult | None:
        """Try to configure from previously saved credentials."""
        if not self._discovery_info or not self._discovery_info.address:
            return None

        saved = self._get_saved_account_data()
        if not saved:
            return None

        account = saved[CONF_PHONE]
        if CONF_COUNTRY_CODE in saved and saved[CONF_COUNTRY_CODE]:
            account = f"{saved[CONF_COUNTRY_CODE]} {saved[CONF_PHONE]}"

        try:
            token = await self._async_login_and_get_token(account, saved[CONF_PASSWORD])
            lock = await self._async_get_matching_lock(token)
            if lock:
                auto_input: dict[str, Any] = {
                    CONF_PHONE: saved[CONF_PHONE],
                    CONF_PASSWORD: saved[CONF_PASSWORD],
                    CONF_API_KEY: lock["ble_sign_key"],
                    CONF_MAC: self._discovery_info.address,
                    CONF_NAME: lock["name"],
                    CONF_MODEL: lock["type"],
                    CONF_AUTO_UNLOCK_LOW_BATTERY: saved.get(
                        CONF_AUTO_UNLOCK_LOW_BATTERY,
                        DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                    ),
                    CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD: saved.get(
                        CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                        DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                    ),
                }
                if CONF_COUNTRY_CODE in saved:
                    auto_input[CONF_COUNTRY_CODE] = saved[CONF_COUNTRY_CODE]

                _LOGGER.debug("Auto-configured discovered lock using saved account")
                return self.async_create_entry(title=auto_input[CONF_NAME], data=auto_input)
        except YeelockApiError:
            _LOGGER.debug("Saved account auto-configuration attempt failed")

        return None

    async def _async_login_and_get_token(self, account: str, password: str) -> str:
        """Authenticate against cloud and return token."""
        login = await self._api_wrapper(
            method="post",
            url="https://api.yeeloc.com/v2/auth/by/password",
            data={
                "account": account,
                "password": password,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Accept": "*/*",
            },
        )
        token = login.get("data", {}).get("access_token")
        if not token:
            raise YeelockAuthError
        return token

    async def _async_get_matching_lock(self, token: str) -> dict[str, Any] | None:
        """Find the discovered lock in the cloud lock list."""
        if not self._discovery_info:
            return None

        locks_response = await self._api_wrapper(
            method="get",
            url="https://api.yeeloc.com/v2/user/device/list",
            params={"group_id": -1},
            headers={
                "Accept": "*/*",
                "Authorization": token,
            },
        )

        locks = locks_response.get("data", [])
        _LOGGER.debug(locks_response)
        for lock in locks:
            if self._discovery_info.name.removeprefix("EL_") == lock["sn"]:
                return lock
        return None

    async def async_step_account_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask whether the user signs in with email or phone."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._account_type = user_input[CONF_ACCOUNT_TYPE]
            if self._account_type == ACCOUNT_TYPE_PHONE:
                return await self.async_step_cloud_phone()
            return await self.async_step_cloud_email()

        return self.async_show_form(
            step_id="account_type",
            data_schema=voluptuous.Schema(
                {
                    voluptuous.Required(
                        CONF_ACCOUNT_TYPE, default=ACCOUNT_TYPE_EMAIL
                    ): voluptuous.In(
                        {
                            ACCOUNT_TYPE_EMAIL: "Email",
                            ACCOUNT_TYPE_PHONE: "Phone number",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_cloud_email(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle email account credentials."""
        self._schema = voluptuous.Schema(
            {
                voluptuous.Required(CONF_PHONE): str,
                voluptuous.Required(CONF_PASSWORD): str,
                voluptuous.Required(
                    CONF_AUTO_UNLOCK_LOW_BATTERY,
                    default=DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                ): bool,
                voluptuous.Required(
                    CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                    default=DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                ): voluptuous.All(cv.positive_int, voluptuous.Range(min=1, max=100)),
            }
        )
        return await self._async_step_cloud(user_input, is_phone=False)

    async def async_step_cloud_phone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle phone account credentials."""
        self._schema = voluptuous.Schema(
            {
                voluptuous.Required(CONF_COUNTRY_CODE): str,
                voluptuous.Required(CONF_PHONE): str,
                voluptuous.Required(CONF_PASSWORD): str,
                voluptuous.Required(
                    CONF_AUTO_UNLOCK_LOW_BATTERY,
                    default=DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                ): bool,
                voluptuous.Required(
                    CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                    default=DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                ): voluptuous.All(cv.positive_int, voluptuous.Range(min=1, max=100)),
            }
        )
        return await self._async_step_cloud(user_input, is_phone=True)

    async def _async_step_cloud(
        self, user_input: dict[str, Any] | None, is_phone: bool
    ) -> FlowResult:
        """Authenticate and discover device."""
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

            account = user_input[CONF_PHONE]
            if is_phone:
                account = f"{user_input[CONF_COUNTRY_CODE]} {user_input[CONF_PHONE]}"

            try:
                token = await self._async_login_and_get_token(
                    account, user_input[CONF_PASSWORD]
                )
                lock = await self._async_get_matching_lock(token)
                if lock:
                    _LOGGER.debug("Found lock and key")
                    user_input[CONF_API_KEY] = lock["ble_sign_key"]
                    user_input[CONF_MAC] = address
                    user_input[CONF_NAME] = lock["name"]
                    user_input[CONF_MODEL] = lock["type"]

                    return self.async_create_entry(
                        title=user_input[CONF_NAME], data=user_input
                    )
                errors["base"] = "cannot_connect"
            except YeelockAccountNotRegisteredError:
                errors["base"] = "account_not_registered"
            except YeelockAuthError:
                errors["base"] = "invalid_auth"
            except YeelockApiError:
                errors["base"] = "unknown"

            _LOGGER.warning("Failed cloud login")
            return self.async_show_form(
                step_id="cloud_phone" if is_phone else "cloud_email",
                data_schema=self._schema,
                errors=errors,
            )
        else:
            _LOGGER.debug("Showing cloud form")
            return self.async_show_form(
                step_id="cloud_phone" if is_phone else "cloud_email",
                data_schema=self._schema,
                errors=errors,
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
    ) -> Any:
        """Get information from the API."""
        session = async_get_clientsession(self.hass)

        try:
            async with async_timeout.timeout(10):
                response = await session.request(
                    method=method,
                    url=url,
                    data=data,
                    json=json,
                    params=params,
                    headers=headers,
                )
                if response.status in (400, 401, 403):
                    raise YeelockAuthError
                response.raise_for_status()
                response_json = await response.json()

                if isinstance(response_json, dict) and response_json.get("code") == 401:
                    raise YeelockAuthError

                if isinstance(response_json, dict) and response_json.get("code") == 1009:
                    raise YeelockAccountNotRegisteredError

                if isinstance(response_json, dict) and response_json.get(
                    "code"
                ) not in (None, 0):
                    raise YeelockApiError(
                        response_json.get("message", "Error fetching information")
                    )

                return response_json

        except TimeoutError as exception:
            raise YeelockApiError("Timeout error fetching information") from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise YeelockApiError("Error fetching information") from exception


class YeelockApiError(Exception):
    """Base API exception raised by the Yeelock integration."""


class YeelockAuthError(YeelockApiError):
    """Raised when authentication with the Yeelock cloud fails."""


class YeelockAccountNotRegisteredError(YeelockAuthError):
    """Raised when the Yeelock account has not been registered."""


class YeelockOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle options for Yeelock."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage Yeelock options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=voluptuous.Schema(
                {
                    voluptuous.Required(
                        CONF_AUTO_UNLOCK_LOW_BATTERY,
                        default=self.config_entry.options.get(
                            CONF_AUTO_UNLOCK_LOW_BATTERY,
                            self.config_entry.data.get(
                                CONF_AUTO_UNLOCK_LOW_BATTERY,
                                DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                            ),
                        ),
                    ): bool,
                    voluptuous.Required(
                        CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                        default=self.config_entry.options.get(
                            CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                            self.config_entry.data.get(
                                CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                                DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                            ),
                        ),
                    ): voluptuous.All(
                        cv.positive_int,
                        voluptuous.Range(min=1, max=100),
                    ),
                }
            ),
        )
