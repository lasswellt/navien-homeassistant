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


class NavienConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the NaviLink account + gateway setup flow."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        """Initialize transient flow state."""
        self._username: str = ""
        self._password: str = ""
        self._device_info: list[dict[str, Any]] | None = None
        self._device_index: int = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate NaviLink credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                navien = NavilinkConnect(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    polling_interval=0,
                )
                self._device_info = await navien.login()
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
        """Let the user choose which gateway to add."""
        assert self._device_info is not None

        if user_input is not None:
            self._device_index = user_input[CONF_DEVICE_INDEX]
            return await self._async_create_or_update()

        gateways = {
            idx: device.get("deviceInfo", {}).get("deviceName", "UNKNOWN")
            for idx, device in enumerate(self._device_info)
        }
        return self.async_show_form(
            step_id="pick_gateway",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_INDEX, default=0): vol.In(gateways)}
            ),
        )

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
        reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert reauth_entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                navien = NavilinkConnect(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    polling_interval=0,
                )
                await navien.login()
            except Exception:  # noqa: BLE001 — any failure is auth/connection
                errors["base"] = "invalid_auth"
            else:
                self.hass.config_entries.async_update_entry(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

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

    async def _async_create_or_update(self) -> ConfigFlowResult:
        """Create the entry, deduping on gateway MAC."""
        assert self._device_info is not None
        device = self._device_info[self._device_index]
        mac = device.get("deviceInfo", {}).get("macAddress", "UNKNOWN")

        await self.async_set_unique_id(f"navien_{self._username}_{mac}")
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
