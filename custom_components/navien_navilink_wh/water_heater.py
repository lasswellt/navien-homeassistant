"""Water heater platform for Navien NaviLink."""

from __future__ import annotations

import logging

from homeassistant.components.water_heater import (
    STATE_GAS,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NavienConfigEntry
from .entity import NavienChannelEntity
from .navien_api import TemperatureType

_LOGGER = logging.getLogger(__name__)

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
        NavienWaterHeaterEntity(coordinator, channel)
        for channel in coordinator.channels.values()
    )


class NavienWaterHeaterEntity(NavienChannelEntity, WaterHeaterEntity):
    """A NaviLink water heater channel."""

    _attr_name = None  # use the device name
    _attr_supported_features = SUPPORT_FLAGS
    _attr_operation_list = [STATE_OFF, STATE_GAS]

    @property
    def unique_id(self) -> str:
        """Return a stable unique id."""
        return f"{self._mac}{self.channel.channel_number}"

    @property
    def temperature_unit(self) -> str:
        """Return the channel's temperature unit."""
        if self.channel.channel_info["temperatureType"] == TemperatureType.FAHRENHEIT.value:
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def is_away_mode_on(self) -> bool:
        """Return True when the heater is powered off (away)."""
        return not self.channel.channel_status.get("powerStatus", False)

    @property
    def current_operation(self) -> str:
        """Return the current operation mode."""
        if self.channel.channel_status.get("powerStatus", False):
            return STATE_GAS
        return STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the averaged current outlet temperature across units."""
        unit_list = self.channel.channel_status.get("unitInfo", {}).get(
            "unitStatusList", []
        )
        if not unit_list:
            _LOGGER.debug("No unit status available for %s", self._device_name)
            return None
        return round(
            sum(u.get("currentOutletTemp", 0) for u in unit_list) / len(unit_list)
        )

    @property
    def target_temperature(self) -> float:
        """Return the DHW target temperature."""
        return self.channel.channel_status.get("DHWSettingTemp", 0)

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature."""
        return self.channel.channel_info.get("setupDHWTempMin", 0)

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature."""
        return self.channel.channel_info.get("setupDHWTempMax", 0)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set the DHW target temperature."""
        target = kwargs.get(ATTR_TEMPERATURE)
        if target is None:
            return
        hass_units = (
            "us_customary"
            if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
            else "metric"
        )
        navien_units = (
            "us_customary"
            if self.channel.channel_info.get("temperatureType", 2)
            == TemperatureType.FAHRENHEIT.value
            else "metric"
        )
        if hass_units == navien_units and self.temperature_unit == UnitOfTemperature.CELSIUS:
            # NaviLink expects Celsius in half-degree steps.
            target = round(2 * target)
        await self.channel.set_temperature(target)

    async def async_turn_away_mode_on(self) -> None:
        """Power the heater off (enter away mode)."""
        await self.channel.set_power_state(False)

    async def async_turn_away_mode_off(self) -> None:
        """Power the heater on (leave away mode)."""
        await self.channel.set_power_state(True)

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Map the operation mode to power state."""
        await self.channel.set_power_state(operation_mode == STATE_GAS)
