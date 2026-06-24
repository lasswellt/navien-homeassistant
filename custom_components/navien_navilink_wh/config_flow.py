"""Config and options flow for the Navien NaviLink integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    CONFIG_VERSION,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
)
from .navien_api import NavilinkConnect

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

POLLING_SELECTOR = vol.All(
    vol.Coerce(int), vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL)
)


async def _validate_credentials(
    username: str, password: str
) -> list[dict[str, Any]]:
    """Return the NaviLink device list, raising on bad credentials."""
    navien = NavilinkConnect(username, password, polling_interval=0)
    return await navien.login()


def _gateway_choices(device_info: list[dict[str, Any]]) -> dict[int, str]:
    """Map device index → display name for the gateway picker."""
    return {
        idx: device.get("deviceInfo", {}).get("deviceName", "UNKNOWN")
        for idx, device in enumerate(device_info)
    }


def _unique_id(username: str, device: dict[str, Any]) -> str:
    """Return the per-gateway unique id."""
    mac = device.get("deviceInfo", {}).get("macAddress", "UNKNOWN")
    return f"navien_{username}_{mac}"


class NavienConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the NaviLink account + gateway setup flow."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        """Initialize transient flow state."""
        self._username: str = ""
        self._password: str = ""
        self._device_info: list[dict[str, Any]] | None = None
        self._device_index: int = 0

    # ----- initial setup -----

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate NaviLink credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._device_info = await _validate_credentials(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except Exception:  # noqa: BLE001 — any failure is auth/connection
                errors["base"] = "invalid_auth"
            else:
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                return await self.async_step_pick_gateway()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_pick_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose which gateway to add (new entry)."""
        assert self._device_info is not None

        if user_input is not None:
            self._device_index = user_input[CONF_DEVICE_INDEX]
            device = self._device_info[self._device_index]
            await self.async_set_unique_id(_unique_id(self._username, device))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=device.get("deviceInfo", {}).get("deviceName", "Navien"),
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_INDEX: self._device_index,
                },
                options={CONF_POLLING_INTERVAL: DEFAULT_POLLING_INTERVAL},
            )

        return self.async_show_form(
            step_id="pick_gateway",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_INDEX, default=0): vol.In(
                        _gateway_choices(self._device_info)
                    )
                }
            ),
        )

    # ----- reauth -----

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when stored credentials stop working."""
        self._username = entry_data.get(CONF_USERNAME, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for new credentials and validate them against NaviLink."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_credentials(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except Exception:  # noqa: BLE001
                errors["base"] = "invalid_auth"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self._username
                        or reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    # ----- reconfigure -----

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-validate credentials for an existing entry."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._device_info = await _validate_credentials(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except Exception:  # noqa: BLE001
                errors["base"] = "invalid_auth"
            else:
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                return await self.async_step_reconfigure_pick()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=reconfigure_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the gateway and update the existing entry."""
        assert self._device_info is not None
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            self._device_index = user_input[CONF_DEVICE_INDEX]
            device = self._device_info[self._device_index]
            await self.async_set_unique_id(_unique_id(self._username, device))
            self._abort_if_unique_id_mismatch(reason="unique_id_mismatch")
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_INDEX: self._device_index,
                },
            )

        return self.async_show_form(
            step_id="reconfigure_pick",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_INDEX,
                        default=reconfigure_entry.data.get(CONF_DEVICE_INDEX, 0),
                    ): vol.In(_gateway_choices(self._device_info))
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NavienOptionsFlow:
        """Return the options flow handler."""
        return NavienOptionsFlow()


class NavienOptionsFlow(OptionsFlow):
    """Handle NaviLink options (polling interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLLING_INTERVAL, default=current
                    ): POLLING_SELECTOR
                }
            ),
        )
