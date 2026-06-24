"""Setup/unload and coordinator tests for Navien NaviLink."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.navien_navilink_wh.const import DOMAIN
from custom_components.navien_navilink_wh.navien_api import (
    UnableToConnect,
    UserNotFound,
)

from .conftest import MockChannel, MockNavilink, setup_integration

CO = "custom_components.navien_navilink_wh.coordinator.NavilinkConnect"


async def test_setup_and_unload(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Entry sets up, creates entities, and unloads."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    # Primary + enabled entities exist across platforms.
    assert hass.states.async_entity_ids_count("water_heater") == 1
    assert hass.states.async_entity_ids_count("switch") == 2  # power + hot_button
    assert hass.states.async_entity_ids_count("sensor") >= 5
    assert hass.states.async_entity_ids_count("binary_sensor") >= 1

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failure(hass: HomeAssistant, mock_config_entry) -> None:
    """A UserNotFound during start raises ConfigEntryAuthFailed."""

    class _AuthFail(MockNavilink):
        async def start(self):
            raise UserNotFound("bad creds")

    with patch(CO, _AuthFail):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_not_ready(hass: HomeAssistant, mock_config_entry) -> None:
    """A connection error during start raises ConfigEntryNotReady."""

    class _Down(MockNavilink):
        async def start(self):
            raise UnableToConnect("server down")

    with patch(CO, _Down):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_no_channels(hass: HomeAssistant, mock_config_entry) -> None:
    """No channels discovered raises ConfigEntryNotReady."""

    class _Empty(MockNavilink):
        async def start(self):
            self.device_info = {"deviceInfo": {"macAddress": "AABBCCDDEEFF"}}
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

    class _UnknownModel(MockNavilink):
        async def start(self):
            self.device_info = MockNavilink().device_info
            await super().start()
            self.channels[1].channel_info["unitType"] = 99

    with patch(CO, _UnknownModel):
        await setup_integration(hass, mock_config_entry)

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(
        DOMAIN, f"unsupported_model_{mock_config_entry.entry_id}_1"
    )
    assert issue is not None


async def test_push_update_reflects_in_state(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """A push callback updates entity state."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    channel = coordinator.navilink.channels[1]

    # Mutate the live status and fire the registered push callback.
    channel.channel_status["unitInfo"]["unitStatusList"][0]["currentOutletTemp"] = 99
    for cb in channel.callbacks:
        cb()
    await hass.async_block_till_done()

    assert coordinator.data.channels[1].unit(1)["currentOutletTemp"] == 99
