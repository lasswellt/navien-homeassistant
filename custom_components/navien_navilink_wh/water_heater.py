"""Water heater platform for Navien NaviLink."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    STATE_GAS,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NavienConfigEntry
from .entity import NavienChannelEntity
from .navien_api import TemperatureType

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SUPPORT_FLAGS = (
    WaterHeaterEntityFeature.AWAY_MODE
    | WaterHeaterEntityFeature.TARGET_TEMPERATURE
    | WaterHeaterEntityFeature.OPERATION_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien water heater entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        NavienWaterHeater(coordinator, channel.number)
        for channel in coordinator.data.channels.values()
    )


class NavienWaterHeater(NavienChannelEntity, WaterHeaterEntity):
    """A NaviLink water heater channel (the primary device entity)."""

    _attr_name = None  # primary entity → uses the device name
    _attr_supported_features = SUPPORT_FLAGS
    _attr_operation_list = [STATE_OFF, STATE_GAS]

    def __init__(self, coordinator, channel_number: int) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator, channel_number)
        self._attr_unique_id = f"{coordinator.gateway_mac}_{channel_number}"

    @property
    def temperature_unit(self) -> str:
        """Return the channel's temperature unit."""
        if (
            self._channel.info.get("temperatureType")
            == TemperatureType.FAHRENHEIT.value
        ):
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def is_away_mode_on(self) -> bool:
        """Return True when the heater is powered off (away)."""
        return not self._channel.status.get("powerStatus", False)

    @property
    def current_operation(self) -> str:
        """Return the current operation mode."""
        return STATE_GAS if self._channel.status.get("powerStatus", False) else STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the averaged current outlet temperature across units."""
        units = self._channel.units
        if not units:
            return None
        return round(
            sum(u.get("currentOutletTemp", 0) for u in units) / len(units)
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the DHW target temperature."""
        return self._channel.status.get("DHWSettingTemp")

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature."""
        return self._channel.info.get("setupDHWTempMin", 0)

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature."""
        return self._channel.info.get("setupDHWTempMax", 0)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the DHW target temperature."""
        target = kwargs.get(ATTR_TEMPERATURE)
        if target is None:
            return
        # NaviLink expects Celsius in half-degree steps; Fahrenheit is 1:1.
        if self.temperature_unit == UnitOfTemperature.CELSIUS:
            target = round(2 * target)
        await self.coordinator.channel_client(self._channel_number).set_temperature(
            target
        )

    async def async_turn_away_mode_on(self) -> None:
        """Power the heater off (enter away mode)."""
        await self.coordinator.channel_client(self._channel_number).set_power_state(
            False
        )

    async def async_turn_away_mode_off(self) -> None:
        """Power the heater on (leave away mode)."""
        await self.coordinator.channel_client(self._channel_number).set_power_state(
            True
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Map the operation mode to power state."""
        await self.coordinator.channel_client(self._channel_number).set_power_state(
            operation_mode == STATE_GAS
        )
