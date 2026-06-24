"""Base entity for the Navien NaviLink integration.

Centralizes device-registry info, availability, and the per-channel push
callback wiring that the reference integration duplicated across every entity.
"""

from __future__ import annotations

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .coordinator import NavienCoordinator


class NavienChannelEntity(Entity):
    """Base class for entities backed by a single NaviLink channel."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: NavienCoordinator, channel) -> None:
        """Initialize the entity for a NaviLink channel."""
        self.coordinator = coordinator
        self.channel = channel
        self._navilink = coordinator.navilink

    @property
    def _mac(self) -> str:
        """Return the gateway MAC address (device identity root)."""
        return self.coordinator.device_info.get("deviceInfo", {}).get(
            "macAddress", "unknown"
        )

    @property
    def _device_name(self) -> str:
        """Return the human-facing gateway/channel device name."""
        base = self.coordinator.device_info.get("deviceInfo", {}).get(
            "deviceName", "Navien"
        )
        return f"{base} CH{self.channel.channel_number}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this channel."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._mac}_{self.channel.channel_number}")},
            manufacturer=MANUFACTURER,
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return True if the channel reports itself online."""
        return self.channel.is_available()

    async def async_added_to_hass(self) -> None:
        """Subscribe to push updates for this channel."""
        self.channel.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from push updates for this channel."""
        self.channel.deregister_callback(self.async_write_ha_state)
