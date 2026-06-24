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
        }
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

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "secret",
    CONF_DEVICE_INDEX: 0,
}


class MockChannel:
    """Mock NavilinkChannel."""

    def __init__(self, number: int) -> None:
        """Initialize the mock channel."""
        self.channel_number = number
        self.channel_info = deepcopy(CHANNEL_INFO)
        self.channel_status = deepcopy(CHANNEL_STATUS)
        self.callbacks: list = []
        self.set_power_state = AsyncMock()
        self.set_temperature = AsyncMock()
        self.set_hot_button_state = AsyncMock()

    def register_callback(self, cb) -> None:
        """Register a push callback."""
        self.callbacks.append(cb)

    def deregister_callback(self, cb) -> None:
        """Deregister a push callback."""
        if cb in self.callbacks:
            self.callbacks.remove(cb)

    def is_available(self) -> bool:
        """Return availability."""
        return True


class MockNavilink:
    """Mock NavilinkConnect client."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize with no connection."""
        self.device_info: dict | None = None
        self.device_status: dict = {}
        self.connected: bool = False
        self.channels: dict[int, MockChannel] = {}

    async def login(self) -> list[dict]:
        """Return the device list."""
        self.device_info = DEVICE_LIST[0]
        return DEVICE_LIST

    async def start(self) -> None:
        """Connect and discover one channel."""
        self.device_info = {
            **DEVICE_LIST[0],
            "descaling": {
                "descalingStartTime": "2026-06-01T00:00:00",
                "descalingEndTime": "2027-06-01T00:00:00",
            },
        }
        self.device_status = {"swVersion": 4352, "wifiRssi": -55, "countryCode": 1}
        self.connected = True
        self.channels = {1: MockChannel(1)}

    async def disconnect(self) -> None:
        """Disconnect (no-op)."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
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
def mock_navilink() -> Generator[type[MockNavilink]]:
    """Patch NavilinkConnect in both the coordinator and config flow."""
    with (
        patch(
            "custom_components.navien_navilink_wh.coordinator.NavilinkConnect",
            MockNavilink,
        ),
        patch(
            "custom_components.navien_navilink_wh.config_flow.NavilinkConnect",
            MockNavilink,
        ),
    ):
        yield MockNavilink


async def setup_integration(hass, entry) -> None:
    """Add and set up the config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
