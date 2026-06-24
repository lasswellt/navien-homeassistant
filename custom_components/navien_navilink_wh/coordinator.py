"""DataUpdateCoordinator for the Navien NaviLink integration.

Wraps the native :class:`NavilinkClient` (REST auth + AWS-IoT MQTT over
WebSocket). The client polls on its own interval and pushes status; this
coordinator builds an immutable :class:`NavienData` snapshot on each push and
feeds it to entities via ``async_set_updated_data``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
)
from .navilink import (
    AuthenticationError,
    DeviceSorting,
    NavilinkClient,
    NavilinkError,
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
    device_status: dict[str, Any] = field(default_factory=dict)
    connected: bool = False
    channels: dict[int, NavienChannelData] = field(default_factory=dict)


class NavienDataUpdateCoordinator(DataUpdateCoordinator[NavienData]):
    """Owns the NaviLink client and publishes typed snapshots."""

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
        self.client = NavilinkClient(
            entry.data.get(CONF_USERNAME, ""),
            entry.data.get(CONF_PASSWORD, ""),
            session=async_get_clientsession(hass),
            device_index=entry.data.get(CONF_DEVICE_INDEX, 0),
            poll_interval=entry.options.get(
                CONF_POLLING_INTERVAL,
                entry.data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
            ),
        )

    # ----- gateway-level convenience -----

    @property
    def _gateway(self) -> dict[str, Any]:
        return (self.client.device_info or {}).get("deviceInfo", {})

    @property
    def gateway_mac(self) -> str:
        """Return the gateway MAC address (device identity root)."""
        return self._gateway.get("macAddress", "unknown")

    @property
    def gateway_name(self) -> str:
        """Return the gateway display name."""
        return self._gateway.get("deviceName", "Navien")

    @property
    def gateway_sw_version(self) -> str | None:
        """Return the gateway firmware version, if captured."""
        version = self.client.device_status.get("swVersion")
        return str(version) if version is not None else None

    def channel_model(self, number: int) -> str | None:
        """Return the product-line model name for a channel, if known."""
        channel = self.client.channels.get(number)
        if channel is None:
            return None
        try:
            return DeviceSorting(channel.info.get("unitType")).name
        except ValueError:
            return None

    def channel_client(self, number: int):
        """Return the live channel object for issuing control commands."""
        return self.client.channels[number]

    async def async_send_command(self, coro) -> None:
        """Await a control coroutine, surfacing failures as a translated error."""
        try:
            await coro
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from err

    # ----- lifecycle -----

    async def _async_setup(self) -> None:
        """Connect, discover channels, and wire the push callback."""
        self.client.on_update = self._handle_push
        try:
            await self.client.async_connect()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NavilinkError as err:
            raise ConfigEntryNotReady(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(f"Unexpected NaviLink setup error: {err}") from err

        if not self.client.channels:
            raise ConfigEntryNotReady("NaviLink returned no channels for this gateway")

        for number, channel in self.client.channels.items():
            self._check_model_support(number, channel.info.get("unitType"))

    def _check_model_support(self, number: int, unit_type: Any) -> None:
        """Raise a repair issue when the unit type is not recognised."""
        issue_id = f"unsupported_model_{self.config_entry.entry_id}_{number}"
        if self.channel_model(number) is None:
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="unsupported_model",
                translation_placeholders={"unit_type": str(unit_type)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _async_update_data(self) -> NavienData:
        """Return the current snapshot (also the initial first-refresh value)."""
        if not self.client.channels:
            raise UpdateFailed("NaviLink connection has no channels")
        return self._build_snapshot()

    @callback
    def _handle_push(self) -> None:
        """Rebuild the snapshot when the client reports new status."""
        self.async_set_updated_data(self._build_snapshot())

    def _build_snapshot(self) -> NavienData:
        """Construct an immutable snapshot from the live client state."""
        return NavienData(
            device_info=self.client.device_info or {},
            device_status=dict(self.client.device_status or {}),
            connected=self.client.connected,
            channels={
                number: NavienChannelData(
                    number=number,
                    info=dict(channel.info),
                    status=dict(channel.status),
                    available=channel.is_available(),
                )
                for number, channel in self.client.channels.items()
            },
        )

    async def async_disconnect(self) -> None:
        """Disconnect the NaviLink client (best effort)."""
        try:
            await self.client.async_disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Error during NaviLink disconnect: %s", err)
