"""DataUpdateCoordinator for the Navien NaviLink integration.

The vendored :class:`NavilinkConnect` client is push-based: it polls the NaviLink
AWS-IoT MQTT broker on its own interval and fires per-channel callbacks. This
coordinator owns the connection lifecycle, builds an immutable :class:`NavienData`
snapshot on every push, and feeds it to entities via ``async_set_updated_data``.
``update_interval`` is therefore ``None`` (pure push); the initial snapshot is
produced in :meth:`_async_setup`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import certifi
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
)
from .navien_api import (
    DeviceSorting,
    NavilinkConnect,
    NoNavienDevices,
    NoResponseData,
    UnableToConnect,
    UserNotFound,
)

_LOGGER = logging.getLogger(__name__)

type NavienConfigEntry = ConfigEntry[NavienDataUpdateCoordinator]


@dataclass(frozen=True)
class NavienChannelData:
    """Immutable per-channel snapshot exposed to entities via value_fn."""

    number: int
    info: dict[str, Any]
    status: dict[str, Any]
    available: bool

    @property
    def units(self) -> list[dict[str, Any]]:
        """Return the per-unit status list (cascade units, usually 1)."""
        return self.status.get("unitInfo", {}).get("unitStatusList", [])

    def unit(self, unit_number: int) -> dict[str, Any]:
        """Return a single unit's status dict by unit number."""
        for u in self.units:
            if u.get("unitNumber") == unit_number:
                return u
        return {}


@dataclass(frozen=True)
class NavienData:
    """Immutable snapshot of the whole gateway for one coordinator update."""

    device_info: dict[str, Any]
    channels: dict[int, NavienChannelData] = field(default_factory=dict)


class NavienDataUpdateCoordinator(DataUpdateCoordinator[NavienData]):
    """Owns the NaviLink connection and publishes typed snapshots."""

    config_entry: NavienConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NavienConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=None,  # pure push; fed via async_set_updated_data
        )
        # AWS IoT TLS validates the broker against a root CA. Amazon Root CA 1
        # ships in the certifi bundle (bundled with Home Assistant).
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

    # ----- gateway-level convenience (device registry) -----

    @property
    def _gateway(self) -> dict[str, Any]:
        return (self.navilink.device_info or {}).get("deviceInfo", {})

    @property
    def gateway_mac(self) -> str:
        """Return the gateway MAC address (device identity root)."""
        return self._gateway.get("macAddress", "unknown")

    @property
    def gateway_name(self) -> str:
        """Return the gateway display name."""
        return self._gateway.get("deviceName", "Navien")

    def channel_model(self, number: int) -> str | None:
        """Return the product-line model name for a channel, if known."""
        channel = self.navilink.channels.get(number)
        if channel is None:
            return None
        try:
            return DeviceSorting(channel.channel_info.get("unitType")).name
        except ValueError:
            return None

    def channel_client(self, number: int):
        """Return the live channel object for issuing control commands."""
        return self.navilink.channels[number]

    # ----- lifecycle -----

    async def _async_setup(self) -> None:
        """Log in, connect, discover channels, and wire push callbacks."""
        try:
            await self.navilink.start()
        except UserNotFound as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (UnableToConnect, NoResponseData, NoNavienDevices) as err:
            raise ConfigEntryNotReady(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(f"Unexpected NaviLink setup error: {err}") from err

        if not self.navilink.channels:
            raise ConfigEntryNotReady("NaviLink returned no channels for this gateway")

        for channel in self.navilink.channels.values():
            channel.register_callback(self._handle_push)

    async def _async_update_data(self) -> NavienData:
        """Return the current snapshot (also the initial first-refresh value)."""
        if not self.navilink.channels:
            raise UpdateFailed("NaviLink connection has no channels")
        return self._build_snapshot()

    @callback
    def _handle_push(self) -> None:
        """Rebuild the snapshot when the push client reports new status."""
        self.async_set_updated_data(self._build_snapshot())

    def _build_snapshot(self) -> NavienData:
        """Construct an immutable snapshot from the live client state."""
        return NavienData(
            device_info=self.navilink.device_info or {},
            channels={
                number: NavienChannelData(
                    number=number,
                    info=dict(channel.channel_info),
                    status=dict(channel.channel_status),
                    available=channel.is_available(),
                )
                for number, channel in self.navilink.channels.items()
            },
        )

    async def async_disconnect(self) -> None:
        """Disconnect from the NaviLink broker (best effort)."""
        try:
            await self.navilink.disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Error during NaviLink disconnect: %s", err)
