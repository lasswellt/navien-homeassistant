"""Switch platform for Navien NaviLink (power + on-demand recirculation)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NavienConfigEntry
from .entity import NavienChannelEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien switch entities from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for channel in coordinator.channels.values():
        if channel.channel_info.get("onDemandUse", 2) == 1:
            entities.append(NavienOnDemandSwitch(coordinator, channel))
        entities.append(NavienPowerSwitch(coordinator, channel))
    async_add_entities(entities)


class NavienOnDemandSwitch(NavienChannelEntity, SwitchEntity):
    """Hot-button / on-demand recirculation switch."""

    _attr_name = "Hot button"

    @property
    def unique_id(self) -> str:
        """Return a stable unique id."""
        return f"{self._mac}{self.channel.channel_number}hot_button"

    @property
    def is_on(self) -> bool:
        """Return the on-demand state."""
        return self.channel.channel_status.get("onDemandUseFlag", False)

    async def async_turn_on(self, **kwargs) -> None:
        """Trigger on-demand recirculation."""
        await self.channel.set_hot_button_state(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Stop on-demand recirculation."""
        await self.channel.set_hot_button_state(False)


class NavienPowerSwitch(NavienChannelEntity, SwitchEntity):
    """Channel power switch."""

    _attr_name = "Power"

    @property
    def unique_id(self) -> str:
        """Return a stable unique id."""
        return f"{self._mac}{self.channel.channel_number}power_button"

    @property
    def is_on(self) -> bool:
        """Return the power state."""
        return self.channel.channel_status.get("powerStatus", False)

    async def async_turn_on(self, **kwargs) -> None:
        """Power the channel on."""
        await self.channel.set_power_state(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Power the channel off."""
        await self.channel.set_power_state(False)
