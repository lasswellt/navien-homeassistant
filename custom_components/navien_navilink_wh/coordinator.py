"""Coordinator for the Navien NaviLink integration.

Wraps the push-based :class:`NavilinkConnect` AWS IoT client. The underlying
client polls the NaviLink MQTT broker on its own interval and fires per-channel
callbacks; entities subscribe to those callbacks directly via the base entity.
This coordinator owns the connection lifecycle (start / shutdown) and is stored
on ``entry.runtime_data``.
"""

from __future__ import annotations

import logging

import certifi
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DEFAULT_POLLING_INTERVAL,
)
from .navien_api import (
    NavilinkConnect,
    NoNavienDevices,
    NoResponseData,
    UnableToConnect,
    UserNotFound,
)

_LOGGER = logging.getLogger(__name__)

class NavienCoordinator:
    """Owns the NaviLink connection and exposes channels to platforms."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        self.hass = hass
        self.entry = entry

        # AWS IoT TLS validates the broker against a root CA. Amazon Root CA 1
        # ships in the certifi bundle (bundled with Home Assistant), so point at
        # it instead of vendoring a copy of the public cert.
        self.navilink = NavilinkConnect(
            userId=entry.data.get(CONF_USERNAME, ""),
            passwd=entry.data.get(CONF_PASSWORD, ""),
            device_index=entry.data.get(CONF_DEVICE_INDEX, 0),
            polling_interval=entry.options.get(
                CONF_POLLING_INTERVAL,
                entry.data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
            ),
            aws_cert_path=certifi.where(),
        )

    @property
    def channels(self) -> dict:
        """Return the discovered NaviLink channels keyed by channel number."""
        return self.navilink.channels

    @property
    def device_info(self) -> dict:
        """Return the raw NaviLink gateway device_info payload."""
        return self.navilink.device_info or {}

    async def async_setup(self) -> None:
        """Log in, connect, and discover devices.

        Raises:
            ConfigEntryAuthFailed: Credentials rejected by NaviLink.
            ConfigEntryNotReady: Transient connection / discovery failure.
        """
        try:
            await self.navilink.start()
        except UserNotFound as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (UnableToConnect, NoResponseData, NoNavienDevices) as err:
            raise ConfigEntryNotReady(str(err)) from err
        except Exception as err:  # noqa: BLE001 — surface anything else as not-ready
            raise ConfigEntryNotReady(f"Unexpected NaviLink setup error: {err}") from err

        if not self.channels:
            raise ConfigEntryNotReady("NaviLink returned no channels for this gateway")

    async def async_shutdown(self) -> None:
        """Disconnect from the NaviLink broker."""
        try:
            await self.navilink.disconnect()
        except Exception as err:  # noqa: BLE001 — best-effort teardown
            _LOGGER.debug("Error during NaviLink disconnect: %s", err)
