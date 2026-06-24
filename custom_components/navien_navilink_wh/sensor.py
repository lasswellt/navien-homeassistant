"""Sensor platform for Navien NaviLink (temps, flow, gas usage)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import NavienConfigEntry
from .entity import NavienChannelEntity
from .navien_api import TemperatureType

_LOGGER = logging.getLogger(__name__)

POWER_KCAL_PER_HOUR = "kcal/hr"
FLOW_GALLONS_PER_MIN = "gal/min"
FLOW_LITERS_PER_MIN = "L/min"

UNIT_SENSOR_TYPES = (
    "gasInstantUsage",
    "accumulatedGasUsage",
    "DHWFlowRate",
    "currentInletTemp",
    "currentOutletTemp",
)


@dataclass
class GenericSensorDescription:
    """Scalar sensor with a metric/imperial conversion factor."""

    state_class: SensorStateClass
    native_unit_of_measurement: str
    name: str
    conversion_factor: float
    device_class: SensorDeviceClass | None = None

    def convert(self, val: float) -> float:
        """Apply the conversion factor."""
        return round(val * self.conversion_factor, 1)


@dataclass
class TempSensorDescription:
    """Temperature sensor with directional unit conversion."""

    state_class: SensorStateClass
    native_unit_of_measurement: str
    name: str
    convert_to: str
    device_class: SensorDeviceClass | None = None

    def convert(self, temp: float) -> float:
        """Convert the temperature to the target HA unit."""
        if self.convert_to == UnitOfTemperature.CELSIUS:
            return round((temp - 32) * 5 / 9, 1)
        if self.convert_to == UnitOfTemperature.FAHRENHEIT:
            return round((temp * 9 / 5) + 32)
        return temp


def get_description(hass_units: str, navien_units: str, sensor_type: str):
    """Build the description for a sensor type given the unit systems."""
    same = hass_units == navien_units
    descriptions = {
        "gasInstantUsage": GenericSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=(
                POWER_KCAL_PER_HOUR if hass_units == "metric" else UnitOfPower.BTU_PER_HOUR
            ),
            name="Current gas use",
            conversion_factor=(
                1 if same else 3.96567 if hass_units == "us_customary" else 0.2521646022
            ),
        ),
        "accumulatedGasUsage": GenericSensorDescription(
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=(
                UnitOfVolume.CUBIC_METERS if hass_units == "metric" else UnitOfVolume.CUBIC_FEET
            ),
            name="Cumulative gas use",
            conversion_factor=(
                1 if same else 35.3147 if hass_units == "us_customary" else 0.0283168732
            ),
            device_class=SensorDeviceClass.GAS,
        ),
        "DHWFlowRate": GenericSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=(
                FLOW_LITERS_PER_MIN if hass_units == "metric" else FLOW_GALLONS_PER_MIN
            ),
            name="Hot water flow",
            conversion_factor=(
                1 if same else 0.264172 if hass_units == "us_customary" else 3.78541
            ),
        ),
        "currentInletTemp": TempSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=(
                UnitOfTemperature.CELSIUS if hass_units == "metric" else UnitOfTemperature.FAHRENHEIT
            ),
            name="Inlet temp",
            convert_to=(
                "None" if same else UnitOfTemperature.FAHRENHEIT if hass_units == "us_customary" else UnitOfTemperature.CELSIUS
            ),
            device_class=SensorDeviceClass.TEMPERATURE,
        ),
        "currentOutletTemp": TempSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=(
                UnitOfTemperature.CELSIUS if hass_units == "metric" else UnitOfTemperature.FAHRENHEIT
            ),
            name="Hot water temp",
            convert_to=(
                "None" if same else UnitOfTemperature.FAHRENHEIT if hass_units == "us_customary" else UnitOfTemperature.CELSIUS
            ),
            device_class=SensorDeviceClass.TEMPERATURE,
        ),
    }
    return descriptions.get(sensor_type)


def _unit_systems(hass: HomeAssistant, channel) -> tuple[str, str]:
    """Return (hass_units, navien_units) as 'metric' / 'us_customary'."""
    hass_units = (
        "us_customary"
        if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
        else "metric"
    )
    navien_units = (
        "us_customary"
        if channel.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value
        else "metric"
    )
    return hass_units, navien_units


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien sensors from a config entry."""
    coordinator = entry.runtime_data
    sensors: list[SensorEntity] = []
    for channel in coordinator.channels.values():
        hass_units, navien_units = _unit_systems(hass, channel)
        sensors.append(NavienHeatingPowerSensor(coordinator, channel))
        unit_list = channel.channel_status.get("unitInfo", {}).get("unitStatusList", [])
        for unit_info in unit_list:
            for sensor_type in UNIT_SENSOR_TYPES:
                sensors.append(
                    NavienUnitSensor(
                        coordinator,
                        channel,
                        unit_info,
                        sensor_type,
                        get_description(hass_units, navien_units, sensor_type),
                    )
                )
    async_add_entities(sensors)


class NavienHeatingPowerSensor(NavienChannelEntity, SensorEntity):
    """Average heating power (avgCalorie) for a channel."""

    _attr_name = "Heating power"
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def unique_id(self) -> str:
        """Return a stable unique id."""
        return f"{self._mac}{self.channel.channel_number}avgCalorie"

    @property
    def native_value(self) -> StateType:
        """Return the average heating power."""
        return self.channel.channel_status.get("avgCalorie", 0)


class NavienUnitSensor(NavienChannelEntity, SensorEntity):
    """A per-unit measurement (temp / flow / gas) for a channel."""

    def __init__(self, coordinator, channel, unit_info, sensor_type, description) -> None:
        """Initialize the per-unit sensor."""
        super().__init__(coordinator, channel)
        self.unit_info = unit_info
        self.sensor_type = sensor_type
        self.description = description
        self.unit_number = unit_info.get("unitNumber", "")

    async def async_added_to_hass(self) -> None:
        """Subscribe with a refresh-then-write callback."""
        self.channel.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the refresh callback."""
        self.channel.deregister_callback(self._handle_update)

    def _handle_update(self) -> None:
        """Refresh cached unit_info / description, then write state."""
        hass_units, navien_units = _unit_systems(self.hass, self.channel)
        for unit_info in self.channel.channel_status.get("unitInfo", {}).get(
            "unitStatusList", []
        ):
            if unit_info.get("unitNumber", "") == self.unit_number:
                self.unit_info = unit_info
        self.description = get_description(hass_units, navien_units, self.sensor_type)
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return a unit-qualified entity name."""
        if self.unit_number:
            return f"Unit {self.unit_number} {self.description.name}"
        return self.description.name

    @property
    def unique_id(self) -> str:
        """Return a stable unique id."""
        return (
            f"{self._mac}{self.channel.channel_number}"
            f"{self.unit_info.get('unitNumber', '')}{self.sensor_type}"
        )

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the sensor device class."""
        return self.description.device_class

    @property
    def state_class(self) -> SensorStateClass:
        """Return the sensor state class."""
        return self.description.state_class

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the native unit of measurement."""
        return self.description.native_unit_of_measurement

    @property
    def native_value(self) -> StateType:
        """Return the converted measured value."""
        return self.description.convert(self.unit_info.get(self.sensor_type, 0))
