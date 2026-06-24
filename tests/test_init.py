"""Setup/unload and coordinator tests for Navien NaviLink."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.navien_navilink_wh.const import DOMAIN
from custom_components.navien_navilink_wh.navilink import (
    AuthenticationError,
    NavilinkError,
)

from .conftest import MockNavilinkClient, setup_integration

CO = "custom_components.navien_navilink_wh.coordinator.NavilinkClient"


async def test_setup_and_unload(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Entry sets up, creates entities, and unloads."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert hass.states.async_entity_ids_count("water_heater") == 1
    assert hass.states.async_entity_ids_count("switch") == 2
    assert hass.states.async_entity_ids_count("sensor") >= 5
    assert hass.states.async_entity_ids_count("binary_sensor") >= 1

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failure(hass: HomeAssistant, mock_config_entry) -> None:
    """An AuthenticationError during connect raises ConfigEntryAuthFailed."""

    class _AuthFail(MockNavilinkClient):
        async def async_connect(self):
            raise AuthenticationError("bad creds")

    with patch(CO, _AuthFail):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_not_ready(hass: HomeAssistant, mock_config_entry) -> None:
    """A connection error during connect raises ConfigEntryNotReady."""

    class _Down(MockNavilinkClient):
        async def async_connect(self):
            raise NavilinkError("server down")

    with patch(CO, _Down):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_no_channels(hass: HomeAssistant, mock_config_entry) -> None:
    """No channels discovered raises ConfigEntryNotReady."""

    class _Empty(MockNavilinkClient):
        async def async_connect(self):
            self.connected = True
            self.channels = {}

    with patch(CO, _Empty):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unsupported_model_creates_issue(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """An unknown unitType raises a repair issue."""

    class _UnknownModel(MockNavilinkClient):
        async def async_connect(self):
            await super().async_connect()
            self.channels[1].info["unitType"] = 99

    with patch(CO, _UnknownModel):
        await setup_integration(hass, mock_config_entry)

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(
        DOMAIN, f"unsupported_model_{mock_config_entry.entry_id}_1"
    ) is not None


async def test_push_update_reflects_in_state(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """A push update refreshes entity state."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    channel = coordinator.client.channels[1]

    channel.status["unitInfo"]["unitStatusList"][0]["currentOutletTemp"] = 99
    coordinator.client.on_update()  # the client's push callback
    await hass.async_block_till_done()

    assert coordinator.data.channels[1].unit(1)["currentOutletTemp"] == 99
