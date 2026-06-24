"""Switch platform for Navien NaviLink (power + on-demand recirculation)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NavienChannelData, NavienConfigEntry
from .entity import NavienChannelEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NavienSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Navien switch."""

    value_fn: Callable[[NavienChannelData], bool]
    set_fn: Callable[[Any, bool], Coroutine[Any, Any, None]]
    available_fn: Callable[[NavienChannelData], bool] = lambda c: True


SWITCHES: tuple[NavienSwitchEntityDescription, ...] = (
    NavienSwitchEntityDescription(
        key="power",
        translation_key="power",
        value_fn=lambda c: c.status.get("powerStatus", False),
        set_fn=lambda channel, state: channel.set_power_state(state),
    ),
    NavienSwitchEntityDescription(
        key="hot_button",
        translation_key="hot_button",
        value_fn=lambda c: c.status.get("onDemandUseFlag", False),
        set_fn=lambda channel, state: channel.set_hot_button_state(state),
        available_fn=lambda c: c.info.get("onDemandUse") == 1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien switches from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        NavienSwitch(coordinator, channel.number, desc)
        for channel in coordinator.data.channels.values()
        for desc in SWITCHES
        if desc.available_fn(channel)
    )


class NavienSwitch(NavienChannelEntity, SwitchEntity):
    """A Navien NaviLink switch."""

    entity_description: NavienSwitchEntityDescription

    def __init__(
        self,
        coordinator,
        channel_number: int,
        description: NavienSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, channel_number)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.gateway_mac}_{channel_number}_{description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return the switch state."""
        return self.entity_description.value_fn(self._channel)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.async_send_command(
            self.entity_description.set_fn(
                self.coordinator.channel_client(self._channel_number), True
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.async_send_command(
            self.entity_description.set_fn(
                self.coordinator.channel_client(self._channel_number), False
            )
        )
