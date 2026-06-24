"""Diagnostics support for Navien NaviLink."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME
from .coordinator import NavienConfigEntry

# NaviLink device/list leaks identity + home address; redact aggressively.
TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "macAddress",
    "additionalValue",
    "homeSeq",
    "userSeq",
    "serialNumber",
    "deviceName",
    "token",
    "accessToken",
    "refreshToken",
    "accessKeyId",
    "secretKey",
    "sessionToken",
    "location",
    "address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NavienConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device_info": async_redact_data(data.device_info, TO_REDACT),
        "channels": {
            str(number): {
                "info": async_redact_data(channel.info, TO_REDACT),
                "status": async_redact_data(channel.status, TO_REDACT),
                "available": channel.available,
            }
            for number, channel in data.channels.items()
        },
    }
