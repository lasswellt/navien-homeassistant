"""Fixtures for Navien NaviLink tests."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.navien_navilink_wh.const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

MAC = "AABBCCDDEEFF"
UNIQUE_ID = f"navien_user@example.com_{MAC}"

DEVICE_LIST = [
    {
        "deviceInfo": {
            "macAddress": MAC,
            "deviceName": "Test Heater",
            "homeSeq": "1",
            "deviceType": 1,
            "additionalValue": "AV",
        },
        "descaling": {
            "descalingStartTime": "2026-06-01T00:00:00",
            "descalingEndTime": "2027-06-01T00:00:00",
        },
    }
]

CHANNEL_INFO = {
    "unitType": 11,
    "unitCount": 1,
    "temperatureType": 2,
    "setupDHWTempMin": 97,
    "setupDHWTempMax": 185,
    "onDemandUse": 1,
}

CHANNEL_STATUS = {
    "powerStatus": True,
    "onDemandUseFlag": False,
    "avgCalorie": 0.0,
    "DHWSettingTemp": 120,
    "unitType": 11,
    "unitInfo": {
        "unitStatusList": [
            {
                "unitNumber": 1,
                "currentOutletTemp": 87,
                "currentInletTemp": 83,
                "DHWFlowRate": 0.0,
                "gasInstantUsage": 0.0,
                "accumulatedGasUsage": 116.5,
                "errorCode": 0,
                "subErrorCode": 0,
                "freezeProtectionStatus": 0,
                "controllerVersion": 3079,
                "panelVersion": 6912,
                "currentRecirculationTemp": 0,
                "numOfWaterUse": 0,
                "daysFilterUsed": 0,
            }
        ]
    },
}

DEVICE_STATUS = {"swVersion": 4352, "wifiRssi": -55, "countryCode": 1}

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "secret",
    CONF_DEVICE_INDEX: 0,
}


class MockChannel:
    """Mock NavilinkChannel."""

    def __init__(self, number: int) -> None:
        """Initialize the mock channel."""
        self.number = number
        self.info = deepcopy(CHANNEL_INFO)
        self.status = deepcopy(CHANNEL_STATUS)
        self.set_power_state = AsyncMock()
        self.set_temperature = AsyncMock()
        self.set_hot_button_state = AsyncMock()

    def is_available(self) -> bool:
        """Return availability."""
        return True


class MockNavilinkClient:
    """Mock NavilinkClient."""

    def __init__(self, username, password, *, session=None, device_index=0,
                 poll_interval=15) -> None:
        """Initialize with no connection."""
        self._username = username
        self.device_info: dict = {}
        self.device_status: dict = {}
        self.connected: bool = False
        self.channels: dict[int, MockChannel] = {}
        self.on_update = None

    async def async_login(self) -> list[dict]:
        """Return the device list."""
        return deepcopy(DEVICE_LIST)

    async def async_connect(self) -> None:
        """Connect and discover one channel."""
        self.device_info = deepcopy(DEVICE_LIST[0])
        self.device_status = deepcopy(DEVICE_STATUS)
        self.connected = True
        self.channels = {1: MockChannel(1)}

    async def async_disconnect(self) -> None:
        """Disconnect (no-op)."""
        self.connected = False


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    yield


@pytest.fixture(autouse=True)
def _mock_clientsession():
    """Avoid building a real aiohttp session (aiodns spawns a pycares thread)."""
    from unittest.mock import MagicMock

    with (
        patch(
            "custom_components.navien_navilink_wh.coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.navien_navilink_wh.config_flow.async_get_clientsession",
            return_value=MagicMock(),
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _us_customary_units(hass):
    """Align HA units with the °F test device so values are 1:1."""
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={CONF_POLLING_INTERVAL: 15},
        unique_id=UNIQUE_ID,
        title="Test Heater",
    )


@pytest.fixture
def mock_navilink() -> Generator[type[MockNavilinkClient]]:
    """Patch NavilinkClient in both the coordinator and config flow."""
    with (
        patch(
            "custom_components.navien_navilink_wh.coordinator.NavilinkClient",
            MockNavilinkClient,
        ),
        patch(
            "custom_components.navien_navilink_wh.config_flow.NavilinkClient",
            MockNavilinkClient,
        ),
    ):
        yield MockNavilinkClient


async def setup_integration(hass, entry) -> None:
    """Add and set up the config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
