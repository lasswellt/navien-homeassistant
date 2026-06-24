"""Sensor platform for Navien NaviLink.

Categorisation:
- Primary measurements (temperatures, flow, gas, heating power) have no entity
  category and are enabled.
- Capability-dependent measurements (combi heating loop, tank, recirculation,
  air handler) are created only on units that report the capability, and enabled
  when created.
- Technical/status fields (firmware, error/status codes, signal, PoE, CIP
  descaling) are EntityCategory.DIAGNOSTIC; the noisy ones are disabled by
  default.

Values are unit-scaled by ``navien_api`` per the channel ``temperatureType``;
descriptions carry HA-facing metadata only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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
from homeassistant.util import dt as dt_util

from .coordinator import NavienChannelData, NavienConfigEntry, NavienData
from .entity import NavienChannelEntity
from .navien_api import TemperatureType

PARALLEL_UPDATES = 0

POWER_KCAL_PER_HOUR = "kcal/h"
_DIAG = EntityCategory.DIAGNOSTIC

# Capability predicates (channel_info flags) — gate which entities are created.
ALWAYS: Callable[[NavienChannelData], bool] = lambda c: True


def _has_heating(c: NavienChannelData) -> bool:
    """True when the unit exposes a usable space-heating loop (combi)."""
    return c.info.get("setupHeatTempMax", 0) > c.info.get("setupHeatTempMin", 0)


def _has_recirc(c: NavienChannelData) -> bool:
    """True when the unit supports recirculation / on-demand hot water."""
    return c.info.get("onDemandUse") == 1 or c.info.get("recirculationUse") == 1


def _has_tank(c: NavienChannelData) -> bool:
    """True when the unit has a DHW storage tank sensor."""
    return c.info.get("DHWTankUse") == 1 or c.info.get("DHWTankSensorUse") == 1


def _has_air(c: NavienChannelData) -> bool:
    """True for air-handler style units."""
    return bool(c.info.get("airSupplyReturnType"))


@dataclass(frozen=True, kw_only=True)
class NavienChannelSensorEntityDescription(SensorEntityDescription):
    """Channel-level sensor description."""

    value_fn: Callable[[NavienChannelData], StateType]
    unit_imperial: str | None = None
    unit_metric: str | None = None
    supported_fn: Callable[[NavienChannelData], bool] = ALWAYS


@dataclass(frozen=True, kw_only=True)
class NavienUnitSensorEntityDescription(SensorEntityDescription):
    """Per-unit (cascade) sensor description."""

    value_fn: Callable[[dict], StateType]
    unit_imperial: str | None = None
    unit_metric: str | None = None
    supported_fn: Callable[[NavienChannelData], bool] = ALWAYS


@dataclass(frozen=True, kw_only=True)
class NavienDeviceSensorEntityDescription(SensorEntityDescription):
    """Gateway/device-level sensor description."""

    value_fn: Callable[[NavienData], StateType | datetime]


# ----- builders -----

_TEMP_KW = dict(
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    unit_imperial=UnitOfTemperature.FAHRENHEIT,
    unit_metric=UnitOfTemperature.CELSIUS,
)


def _ctemp(key, sk, *, enabled=False, supported=ALWAYS):
    return NavienChannelSensorEntityDescription(
        key=key, translation_key=key, **_TEMP_KW,
        entity_registry_enabled_default=enabled, supported_fn=supported,
        value_fn=lambda c, k=sk: c.status.get(k),
    )


def _cdiag(key, sk, *, enabled=False):
    return NavienChannelSensorEntityDescription(
        key=key, translation_key=key, entity_category=_DIAG,
        entity_registry_enabled_default=enabled,
        value_fn=lambda c, k=sk: c.status.get(k),
    )


def _utemp(key, sk, *, enabled=False, supported=ALWAYS):
    return NavienUnitSensorEntityDescription(
        key=key, translation_key=key, **_TEMP_KW,
        entity_registry_enabled_default=enabled, supported_fn=supported,
        value_fn=lambda u, k=sk: u.get(k),
    )


def _udiag(key, sk, *, enabled=False):
    return NavienUnitSensorEntityDescription(
        key=key, translation_key=key, entity_category=_DIAG,
        entity_registry_enabled_default=enabled,
        value_fn=lambda u, k=sk: u.get(k),
    )


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed


CHANNEL_SENSORS: tuple[NavienChannelSensorEntityDescription, ...] = (
    NavienChannelSensorEntityDescription(
        key="heating_power",
        translation_key="heating_power",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.status.get("avgCalorie"),
    ),
    # combi heating loop — created + enabled only on units with a heat range
    _ctemp("avg_supply_temp", "avgSupplyTemp", enabled=True, supported=_has_heating),
    _ctemp("avg_return_temp", "avgReturnTemp", enabled=True, supported=_has_heating),
    _ctemp("heat_setting_temp", "heatSettingTemp", enabled=True, supported=_has_heating),
    # recirculation / tank setpoints — created only when supported
    _ctemp("recirculation_setting_temp", "recirculationSettingTemp", supported=_has_recirc),
    _ctemp("dhw_tank_setting_temp", "DHWTankSettingTemp", supported=_has_tank),
    # outdoor temp exists on many units but often reads 0 — measurement, off
    _ctemp("outdoor_temp", "outdoorTemperature"),
    # status codes
    _cdiag("operation_unit_count", "operationUnitCount"),
    _cdiag("heat_status", "heatStatus"),
    _cdiag("weekly_control", "weeklyControl"),
)

UNIT_SENSORS: tuple[NavienUnitSensorEntityDescription, ...] = (
    # primary measurements (enabled, always)
    NavienUnitSensorEntityDescription(
        key="hot_water_temp", translation_key="hot_water_temp", **_TEMP_KW,
        value_fn=lambda u: u.get("currentOutletTemp"),
    ),
    NavienUnitSensorEntityDescription(
        key="inlet_temp", translation_key="inlet_temp", **_TEMP_KW,
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
    # recirculation temp — enabled when the unit recirculates
    _utemp("recirculation_temp", "currentRecirculationTemp", enabled=True, supported=_has_recirc),
    # combi heating loop per-unit temps
    _utemp("supply_temp", "currentSupplyTemp", enabled=True, supported=_has_heating),
    _utemp("return_temp", "currentReturnTemp", enabled=True, supported=_has_heating),
    NavienUnitSensorEntityDescription(
        key="heat_flow_rate",
        translation_key="heat_flow_rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_imperial=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        unit_metric=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        supported_fn=_has_heating,
        value_fn=lambda u: u.get("currentHeatFlowRate"),
    ),
    # tank temp — enabled when a tank sensor is present
    _utemp("dhw_tank_temp", "currentDHWTankTemp", enabled=True, supported=_has_tank),
    # air-handler temps — created only on air units, off by default
    _utemp("supply_air_temp", "currentSupplyAirTemp", supported=_has_air),
    _utemp("return_air_temp", "currentReturnAirTemp", supported=_has_air),
    # cumulative water — measurement, off (raw scaling unverified)
    NavienUnitSensorEntityDescription(
        key="water_cumulative",
        translation_key="water_cumulative",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_imperial=UnitOfVolume.GALLONS,
        unit_metric=UnitOfVolume.LITERS,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("accumulatedWaterUsage"),
    ),
    # diagnostics (technical/status — disabled by default)
    NavienUnitSensorEntityDescription(
        key="days_filter_used",
        translation_key="days_filter_used",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
        value_fn=lambda u: u.get("daysFilterUsed"),
    ),
    _udiag("filter_status", "filterStatus"),
    _udiag("water_use_count", "numOfWaterUse"),
    _udiag("short_water_use_count", "numOfShortWaterUse"),
    _udiag("error_code", "errorCode"),
    _udiag("sub_error_code", "subErrorCode"),
    _udiag("operation_mode", "operationMode"),
    _udiag("thermostat_status", "thermostatStatus"),
    _udiag("water_level", "waterLevel"),
    _udiag("blower_cfm", "blowerCFM"),
    _udiag("tds_value", "currentOutputTDSValue"),
    _udiag("poe_status", "PoEStatus"),
    _udiag("controller_version", "controllerVersion"),
    _udiag("panel_version", "panelVersion"),
    _udiag("cip_status", "CIPStatus"),
    _udiag("cip_solution_remained", "CIPSolutionRemained"),
    _udiag("cip_operation_hour", "CIPOperationTimeHour"),
    _udiag("cip_operation_min", "CIPOperationTimeMin"),
)

DEVICE_SENSORS: tuple[NavienDeviceSensorEntityDescription, ...] = (
    NavienDeviceSensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        entity_category=_DIAG,
        value_fn=lambda d: d.device_status.get("wifiRssi"),
    ),
    NavienDeviceSensorEntityDescription(
        key="country_code",
        translation_key="country_code",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.device_status.get("countryCode"),
    ),
    NavienDeviceSensorEntityDescription(
        key="descaling_start",
        translation_key="descaling_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=_DIAG,
        value_fn=lambda d: _parse_dt(
            d.device_info.get("descaling", {}).get("descalingStartTime")
        ),
    ),
    NavienDeviceSensorEntityDescription(
        key="descaling_end",
        translation_key="descaling_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=_DIAG,
        value_fn=lambda d: _parse_dt(
            d.device_info.get("descaling", {}).get("descalingEndTime")
        ),
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
    channels = coordinator.data.channels
    first_channel = min(channels) if channels else None
    for channel in channels.values():
        entities.extend(
            NavienChannelSensor(coordinator, channel.number, desc)
            for desc in CHANNEL_SENSORS
            if desc.supported_fn(channel)
        )
        for unit in channel.units:
            unit_number = unit.get("unitNumber")
            entities.extend(
                NavienUnitSensor(coordinator, channel.number, unit_number, desc)
                for desc in UNIT_SENSORS
                if desc.supported_fn(channel)
            )
        if channel.number == first_channel:
            entities.extend(
                NavienDeviceSensor(coordinator, channel.number, desc)
                for desc in DEVICE_SENSORS
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

    def __init__(self, coordinator, channel_number, description) -> None:
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

    def __init__(self, coordinator, channel_number, unit_number, description) -> None:
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


class NavienDeviceSensor(NavienChannelEntity, SensorEntity):
    """A gateway/device-level sensor."""

    entity_description: NavienDeviceSensorEntityDescription

    def __init__(self, coordinator, channel_number, description) -> None:
        """Initialize the device sensor."""
        super().__init__(coordinator, channel_number)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gateway_mac}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the device-level value."""
        return self.entity_description.value_fn(self.coordinator.data)
