"""Entity control + diagnostics tests for Navien NaviLink."""

from __future__ import annotations

import pytest
from homeassistant.components.water_heater import (
    ATTR_OPERATION_MODE,
    DOMAIN as WH_DOMAIN,
    SERVICE_SET_OPERATION_MODE,
    SERVICE_SET_TEMPERATURE,
    STATE_GAS,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.navien_navilink_wh.const import CONF_USERNAME, DOMAIN
from custom_components.navien_navilink_wh.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MAC, setup_integration


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None, f"missing {platform} {unique_id}"
    return entity_id


async def test_switch_power_toggle(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Power switch issues control commands."""
    await setup_integration(hass, mock_config_entry)
    channel = mock_config_entry.runtime_data.client.channels[1]
    entity_id = _entity_id(hass, Platform.SWITCH, f"{MAC}_1_power")

    await hass.services.async_call(
        Platform.SWITCH, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    channel.set_power_state.assert_called_with(False)

    await hass.services.async_call(
        Platform.SWITCH, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    channel.set_power_state.assert_called_with(True)


async def test_switch_hot_button(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Hot-button switch issues on-demand commands."""
    await setup_integration(hass, mock_config_entry)
    channel = mock_config_entry.runtime_data.client.channels[1]
    entity_id = _entity_id(hass, Platform.SWITCH, f"{MAC}_1_hot_button")

    await hass.services.async_call(
        Platform.SWITCH, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    channel.set_hot_button_state.assert_called_with(True)


async def test_command_failure_raises(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """A failed control command surfaces a translated error."""
    await setup_integration(hass, mock_config_entry)
    channel = mock_config_entry.runtime_data.client.channels[1]
    channel.set_power_state.side_effect = RuntimeError("mqtt down")
    entity_id = _entity_id(hass, Platform.SWITCH, f"{MAC}_1_power")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            Platform.SWITCH, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )


async def test_water_heater_set_temperature(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Setting a valid temperature forwards to the channel (F = 1:1)."""
    await setup_integration(hass, mock_config_entry)
    channel = mock_config_entry.runtime_data.client.channels[1]
    entity_id = _entity_id(hass, Platform.WATER_HEATER, f"{MAC}_1")

    await hass.services.async_call(
        WH_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 130},
        blocking=True,
    )
    channel.set_temperature.assert_called_with(130)


async def test_water_heater_temperature_out_of_range(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """An out-of-range temperature raises ServiceValidationError."""
    await setup_integration(hass, mock_config_entry)
    entity_id = _entity_id(hass, Platform.WATER_HEATER, f"{MAC}_1")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            WH_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 50},
            blocking=True,
        )


async def test_water_heater_operation_and_away(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Operation mode and away mode map to power state."""
    await setup_integration(hass, mock_config_entry)
    channel = mock_config_entry.runtime_data.client.channels[1]
    entity_id = _entity_id(hass, Platform.WATER_HEATER, f"{MAC}_1")

    await hass.services.async_call(
        WH_DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPERATION_MODE: STATE_OFF},
        blocking=True,
    )
    channel.set_power_state.assert_called_with(False)

    await hass.services.async_call(
        WH_DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPERATION_MODE: STATE_GAS},
        blocking=True,
    )
    channel.set_power_state.assert_called_with(True)

    await hass.services.async_call(
        WH_DOMAIN,
        "set_away_mode",
        {ATTR_ENTITY_ID: entity_id, "away_mode": True},
        blocking=True,
    )
    channel.set_power_state.assert_called_with(False)


async def test_sensor_state(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """The hot-water temperature sensor reports the live value."""
    await setup_integration(hass, mock_config_entry)
    entity_id = _entity_id(hass, Platform.SENSOR, f"{MAC}_1_1_hot_water_temp")
    assert hass.states.get(entity_id).state == "87"


async def test_capability_gated_sensors(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Combi heating sensors appear only when the unit reports a heat range."""
    from unittest.mock import patch

    from .conftest import MockNavilinkClient

    class _Combi(MockNavilinkClient):
        async def async_connect(self):
            await super().async_connect()
            self.channels[1].info.update(
                {"setupHeatTempMin": 80, "setupHeatTempMax": 140}
            )

    with patch(
        "custom_components.navien_navilink_wh.coordinator.NavilinkClient", _Combi
    ):
        await setup_integration(hass, mock_config_entry)

    ent_reg = er.async_get(hass)
    # combi → heating-loop sensors created
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_1_1_supply_temp")
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_1_heat_setting_temp")
    # no tank sensor on this unit → not created
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_1_1_dhw_tank_temp") is None


async def test_dhw_only_omits_heating_sensors(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """The default DHW-only unit does not create combi heating sensors."""
    await setup_integration(hass, mock_config_entry)
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MAC}_1_1_supply_temp") is None
    # recirculation IS supported (onDemandUse == 1) → created
    assert ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{MAC}_1_1_recirculation_temp"
    )


async def test_diagnostics_redacts(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Diagnostics redact identity + credentials."""
    await setup_integration(hass, mock_config_entry)
    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diag["entry"]["data"][CONF_USERNAME] == "**REDACTED**"
    assert "1" in diag["channels"]
