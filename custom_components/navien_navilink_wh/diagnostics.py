"""Diagnostics support for Navien NaviLink."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NavienConfigEntry
from .const import CONF_PASSWORD, CONF_USERNAME

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "macAddress", "token", "accessToken"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NavienConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device_info": async_redact_data(coordinator.device_info, TO_REDACT),
        "channels": {
            str(num): {
                "channel_info": channel.channel_info,
                "channel_status": channel.channel_status,
                "available": channel.is_available(),
            }
            for num, channel in coordinator.channels.items()
        },
    }
