"""Binary sensor platform for Navien NaviLink (faults, freeze protection)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NavienConfigEntry, NavienData
from .entity import NavienChannelEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NavienDeviceBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a gateway/device-level binary sensor."""

    is_on_fn: Callable[[NavienData], bool]


DEVICE_BINARY_SENSORS: tuple[NavienDeviceBinarySensorEntityDescription, ...] = (
    NavienDeviceBinarySensorEntityDescription(
        key="connection",
        translation_key="connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.connected,
    ),
)


@dataclass(frozen=True, kw_only=True)
class NavienBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Navien per-unit binary sensor."""

    is_on_fn: Callable[[dict], bool]
    attrs_fn: Callable[[dict], dict] | None = None


UNIT_BINARY_SENSORS: tuple[NavienBinarySensorEntityDescription, ...] = (
    NavienBinarySensorEntityDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda u: bool(u.get("errorCode")),
        attrs_fn=lambda u: {
            "error_code": u.get("errorCode", 0),
            "sub_error_code": u.get("subErrorCode", 0),
        },
    ),
    NavienBinarySensorEntityDescription(
        key="freeze_protection",
        translation_key="freeze_protection",
        device_class=BinarySensorDeviceClass.COLD,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda u: bool(u.get("freezeProtectionStatus")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien binary sensors from a config entry."""
    coordinator = entry.runtime_data
    channels = coordinator.data.channels
    first_channel = min(channels) if channels else None
    entities: list[BinarySensorEntity] = [
        NavienBinarySensor(coordinator, channel.number, unit.get("unitNumber"), desc)
        for channel in channels.values()
        for unit in channel.units
        for desc in UNIT_BINARY_SENSORS
    ]
    if first_channel is not None:
        entities.extend(
            NavienDeviceBinarySensor(coordinator, first_channel, desc)
            for desc in DEVICE_BINARY_SENSORS
        )
    async_add_entities(entities)


class NavienBinarySensor(NavienChannelEntity, BinarySensorEntity):
    """A per-unit Navien binary sensor."""

    entity_description: NavienBinarySensorEntityDescription

    def __init__(
        self,
        coordinator,
        channel_number: int,
        unit_number: int | None,
        description: NavienBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, channel_number)
        self._unit_number = unit_number
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.gateway_mac}_{channel_number}_{unit_number}_{description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the condition is active."""
        return self.entity_description.is_on_fn(self._channel.unit(self._unit_number))

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes (e.g. raw fault codes)."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self._channel.unit(self._unit_number))


class NavienDeviceBinarySensor(NavienChannelEntity, BinarySensorEntity):
    """A gateway/device-level binary sensor."""

    entity_description: NavienDeviceBinarySensorEntityDescription

    def __init__(
        self,
        coordinator,
        channel_number: int,
        description: NavienDeviceBinarySensorEntityDescription,
    ) -> None:
        """Initialize the device binary sensor."""
        super().__init__(coordinator, channel_number)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gateway_mac}_{description.key}"

    @property
    def available(self) -> bool:
        """Connectivity must report even when the channel is unavailable."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        """Return the connection state."""
        return self.entity_description.is_on_fn(self.coordinator.data)
