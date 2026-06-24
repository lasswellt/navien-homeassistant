"""Base entity for the Navien NaviLink integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import NavienChannelData, NavienDataUpdateCoordinator


class NavienChannelEntity(CoordinatorEntity[NavienDataUpdateCoordinator]):
    """Base class for entities backed by a single NaviLink channel."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: NavienDataUpdateCoordinator, channel_number: int
    ) -> None:
        """Initialize the entity for a NaviLink channel."""
        super().__init__(coordinator)
        self._channel_number = channel_number
        mac = coordinator.gateway_mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{mac}_{channel_number}")},
            manufacturer=MANUFACTURER,
            model=coordinator.channel_model(channel_number),
            name=f"{coordinator.gateway_name} CH{channel_number}",
        )

    @property
    def _channel(self) -> NavienChannelData:
        """Return the current channel snapshot."""
        return self.coordinator.data.channels[self._channel_number]

    @property
    def available(self) -> bool:
        """Return True if the coordinator and channel are both healthy."""
        return (
            super().available
            and self._channel_number in self.coordinator.data.channels
            and self._channel.available
        )
