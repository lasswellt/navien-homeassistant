"""Sensor platform for Navien NaviLink.

Values are already unit-scaled by ``navien_api`` per the channel's
``temperatureType``; descriptions carry only HA-facing metadata. The native
unit follows the channel's unit system (imperial when ``temperatureType`` is
Fahrenheit, otherwise metric).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NavienChannelData, NavienConfigEntry
from .entity import NavienChannelEntity
from .navien_api import TemperatureType

PARALLEL_UPDATES = 0

POWER_KCAL_PER_HOUR = "kcal/h"


@dataclass(frozen=True, kw_only=True)
class NavienChannelSensorEntityDescription(SensorEntityDescription):
    """Channel-level sensor description."""

    value_fn: Callable[[NavienChannelData], StateType]
    unit_imperial: str | None = None
    unit_metric: str | None = None


@dataclass(frozen=True, kw_only=True)
class NavienUnitSensorEntityDescription(SensorEntityDescription):
    """Per-unit (cascade) sensor description."""

    value_fn: Callable[[dict], StateType]
    unit_imperial: str | None = None
    unit_metric: str | None = None


CHANNEL_SENSORS: tuple[NavienChannelSensorEntityDescription, ...] = (
    NavienChannelSensorEntityDescription(
        key="heating_power",
        translation_key="heating_power",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.status.get("avgCalorie"),
    ),
)

UNIT_SENSORS: tuple[NavienUnitSensorEntityDescription, ...] = (
    NavienUnitSensorEntityDescription(
        key="hot_water_temp",
        translation_key="hot_water_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfTemperature.FAHRENHEIT,
        unit_metric=UnitOfTemperature.CELSIUS,
        value_fn=lambda u: u.get("currentOutletTemp"),
    ),
    NavienUnitSensorEntityDescription(
        key="inlet_temp",
        translation_key="inlet_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfTemperature.FAHRENHEIT,
        unit_metric=UnitOfTemperature.CELSIUS,
        value_fn=lambda u: u.get("currentInletTemp"),
    ),
    NavienUnitSensorEntityDescription(
        key="flow_rate",
        translation_key="flow_rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        unit_metric=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        value_fn=lambda u: u.get("DHWFlowRate"),
    ),
    NavienUnitSensorEntityDescription(
        key="gas_current",
        translation_key="gas_current",
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfPower.BTU_PER_HOUR,
        unit_metric=POWER_KCAL_PER_HOUR,
        value_fn=lambda u: u.get("gasInstantUsage"),
    ),
    NavienUnitSensorEntityDescription(
        key="gas_cumulative",
        translation_key="gas_cumulative",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_imperial=UnitOfVolume.CUBIC_FEET,
        unit_metric=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda u: u.get("accumulatedGasUsage"),
    ),
    NavienUnitSensorEntityDescription(
        key="recirculation_temp",
        translation_key="recirculation_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfTemperature.FAHRENHEIT,
        unit_metric=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("currentRecirculationTemp"),
    ),
    NavienUnitSensorEntityDescription(
        key="water_use_count",
        translation_key="water_use_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("numOfWaterUse"),
    ),
    NavienUnitSensorEntityDescription(
        key="days_filter_used",
        translation_key="days_filter_used",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("daysFilterUsed"),
    ),
    NavienUnitSensorEntityDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("errorCode"),
    ),
    NavienUnitSensorEntityDescription(
        key="controller_version",
        translation_key="controller_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("controllerVersion"),
    ),
    NavienUnitSensorEntityDescription(
        key="panel_version",
        translation_key="panel_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("panelVersion"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavienConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navien sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for channel in coordinator.data.channels.values():
        entities.extend(
            NavienChannelSensor(coordinator, channel.number, desc)
            for desc in CHANNEL_SENSORS
        )
        for unit in channel.units:
            unit_number = unit.get("unitNumber")
            entities.extend(
                NavienUnitSensor(coordinator, channel.number, unit_number, desc)
                for desc in UNIT_SENSORS
            )
    async_add_entities(entities)


class _NavienUnitMixin:
    """Shared imperial/metric unit resolution."""

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, following the channel's temperatureType system."""
        desc = self.entity_description
        if desc.unit_imperial is None and desc.unit_metric is None:
            return desc.native_unit_of_measurement
        fahrenheit = (
            self._channel.info.get("temperatureType")
            == TemperatureType.FAHRENHEIT.value
        )
        return desc.unit_imperial if fahrenheit else desc.unit_metric


class NavienChannelSensor(_NavienUnitMixin, NavienChannelEntity, SensorEntity):
    """A channel-level sensor."""

    entity_description: NavienChannelSensorEntityDescription

    def __init__(
        self,
        coordinator,
        channel_number: int,
        description: NavienChannelSensorEntityDescription,
    ) -> None:
        """Initialize the channel sensor."""
        super().__init__(coordinator, channel_number)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.gateway_mac}_{channel_number}_{description.key}"
        )

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self._channel)


class NavienUnitSensor(_NavienUnitMixin, NavienChannelEntity, SensorEntity):
    """A per-unit sensor (supports cascade installations)."""

    entity_description: NavienUnitSensorEntityDescription

    def __init__(
        self,
        coordinator,
        channel_number: int,
        unit_number: int | None,
        description: NavienUnitSensorEntityDescription,
    ) -> None:
        """Initialize the per-unit sensor."""
        super().__init__(coordinator, channel_number)
        self._unit_number = unit_number
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.gateway_mac}_{channel_number}_{unit_number}_{description.key}"
        )

    @property
    def native_value(self) -> StateType:
        """Return the sensor value for this unit."""
        return self.entity_description.value_fn(self._channel.unit(self._unit_number))
