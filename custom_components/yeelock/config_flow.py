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
from homeassistant.helpers.storage import Store
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
CONF_ACCOUNT_ID = "account_id"

ACCOUNT_STORE_KEY = f"{DOMAIN}_accounts"
ACCOUNT_STORE_VERSION = 1

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

    @staticmethod
    def _build_account_id(account: str) -> str:
        """Build a stable account id."""
        return account.strip().lower()

    @staticmethod
    def _build_login_account(saved_account: dict[str, Any]) -> str:
        """Build the cloud login account string for API auth."""
        if saved_account.get(CONF_COUNTRY_CODE):
            return f"{saved_account[CONF_COUNTRY_CODE]} {saved_account[CONF_PHONE]}"
        return saved_account[CONF_PHONE]

    @staticmethod
    def _sanitize_account_for_store(saved_account: dict[str, Any]) -> dict[str, Any]:
        """Persist only account fields that should be reused by auto-discovery."""
        sanitized: dict[str, Any] = {
            CONF_ACCOUNT_ID: saved_account[CONF_ACCOUNT_ID],
            CONF_PHONE: saved_account[CONF_PHONE],
            CONF_PASSWORD: saved_account[CONF_PASSWORD],
        }
        if saved_account.get(CONF_COUNTRY_CODE):
            sanitized[CONF_COUNTRY_CODE] = saved_account[CONF_COUNTRY_CODE]
        return sanitized

    async def _async_get_saved_accounts_data(self) -> list[dict[str, Any]]:
        """Get all previously saved Yeelock account payloads."""
        store = Store[dict[str, Any]](self.hass, ACCOUNT_STORE_VERSION, ACCOUNT_STORE_KEY)
        stored_data = await store.async_load() or {}
        stored_accounts = stored_data.get("accounts", [])
        if stored_accounts:
            return [
                account
                for account in stored_accounts
                if account.get(CONF_PHONE) and account.get(CONF_PASSWORD)
            ]

        # Legacy fallback: first configured lock entry used to hold cloud credentials.
        migrated_accounts: list[dict[str, Any]] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if (
                CONF_PHONE in entry.data
                and CONF_PASSWORD in entry.data
                and entry.data[CONF_PHONE]
                and entry.data[CONF_PASSWORD]
            ):
                account: dict[str, Any] = {
                    CONF_PHONE: entry.data[CONF_PHONE],
                    CONF_PASSWORD: entry.data[CONF_PASSWORD],
                }
                if entry.data.get(CONF_COUNTRY_CODE):
                    account[CONF_COUNTRY_CODE] = entry.data[CONF_COUNTRY_CODE]
                account_id = self._build_account_id(self._build_login_account(account))
                account[CONF_ACCOUNT_ID] = account_id
                migrated_accounts.append(self._sanitize_account_for_store(account))

        if migrated_accounts:
            await store.async_save({"accounts": migrated_accounts})
            _LOGGER.debug("Migrated %s Yeelock cloud account(s) to account store", len(migrated_accounts))

        return migrated_accounts

    async def _async_save_account_data(self, account_data: dict[str, Any]) -> None:
        """Save or update account credentials in persistent account store."""
        store = Store[dict[str, Any]](self.hass, ACCOUNT_STORE_VERSION, ACCOUNT_STORE_KEY)
        stored_data = await store.async_load() or {}
        accounts = stored_data.get("accounts", [])
        account_id = account_data[CONF_ACCOUNT_ID]

        sanitized = self._sanitize_account_for_store(account_data)
        updated = False
        for index, existing in enumerate(accounts):
            if existing.get(CONF_ACCOUNT_ID) == account_id:
                accounts[index] = sanitized
                updated = True
                break
        if not updated:
            accounts.append(sanitized)

        await store.async_save({"accounts": accounts})

    @staticmethod
    def _normalize_identifier(value: str | None) -> str:
        """Normalize lock identifiers for reliable comparisons."""
        if not value:
            return ""
        normalized = value.strip().upper()
        if normalized.startswith("EL_"):
            normalized = normalized.removeprefix("EL_")
        return normalized.replace(":", "").replace("-", "").replace("_", "")

    async def _async_try_auto_configure_from_saved_account(self) -> FlowResult | None:
        """Try to configure from previously saved credentials."""
        if not self._discovery_info or not self._discovery_info.address:
            _LOGGER.debug("Auto-config skipped: discovery info missing")
            return None

        saved_accounts = await self._async_get_saved_accounts_data()
        if not saved_accounts:
            _LOGGER.debug("Auto-config skipped: no previously saved credentials found")
            return None

        for saved in saved_accounts:
            account = self._build_login_account(saved)
            try:
                token = await self._async_login_and_get_token(account, saved[CONF_PASSWORD])
                lock = await self._async_get_matching_lock(token)
                if lock:
                    auto_input: dict[str, Any] = {
                        CONF_ACCOUNT_ID: saved[CONF_ACCOUNT_ID],
                        CONF_API_KEY: lock["ble_sign_key"],
                        CONF_MAC: self._discovery_info.address,
                        CONF_NAME: lock["name"],
                        CONF_MODEL: lock["type"],
                        CONF_AUTO_UNLOCK_LOW_BATTERY: DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                        CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD: DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                    }
                    _LOGGER.debug("Auto-configured discovered lock using saved account")
                    return self.async_create_entry(title=auto_input[CONF_NAME], data=auto_input)
            except YeelockApiError:
                _LOGGER.debug("Saved account auto-configuration attempt failed")

        _LOGGER.debug(
            "Auto-config skipped: discovered device name %s did not match any cloud lock",
            self._discovery_info.name,
        )

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
        discovered_name = self._discovery_info.name
        discovered_address = self._discovery_info.address
        normalized_discovered_name = self._normalize_identifier(discovered_name)
        normalized_discovered_address = self._normalize_identifier(discovered_address)
        if not discovered_name:
            _LOGGER.debug("Unable to match lock: discovered bluetooth device name is missing")

        for lock in locks:
            lock_identifiers = {
                self._normalize_identifier(lock.get("sn")),
                self._normalize_identifier(lock.get("name")),
                self._normalize_identifier(lock.get("mac")),
                self._normalize_identifier(lock.get("ble_mac")),
                self._normalize_identifier(lock.get("bluetooth_mac")),
                self._normalize_identifier(lock.get("bt_mac")),
            }
            lock_identifiers.discard("")

            if (
                normalized_discovered_name
                and normalized_discovered_name in lock_identifiers
            ) or (
                normalized_discovered_address
                and normalized_discovered_address in lock_identifiers
            ):
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
                    account_id = self._build_account_id(account)
                    account_data = {
                        CONF_ACCOUNT_ID: account_id,
                        CONF_PHONE: user_input[CONF_PHONE],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    if is_phone:
                        account_data[CONF_COUNTRY_CODE] = user_input[CONF_COUNTRY_CODE]
                    await self._async_save_account_data(account_data)

                    entry_data: dict[str, Any] = {
                        CONF_ACCOUNT_ID: account_id,
                        CONF_AUTO_UNLOCK_LOW_BATTERY: user_input.get(
                            CONF_AUTO_UNLOCK_LOW_BATTERY,
                            DEFAULT_AUTO_UNLOCK_LOW_BATTERY,
                        ),
                        CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD: user_input.get(
                            CONF_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                            DEFAULT_AUTO_UNLOCK_LOW_BATTERY_THRESHOLD,
                        ),
                    }
                    entry_data[CONF_MAC] = address
                    entry_data[CONF_NAME] = lock["name"]
                    entry_data[CONF_MODEL] = lock["type"]
                    entry_data[CONF_API_KEY] = lock["ble_sign_key"]

                    return self.async_create_entry(
                        title=entry_data[CONF_NAME], data=entry_data
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
        super().__init__(config_entry)

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
