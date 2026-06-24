"""Native NaviLink client (REST auth + AWS-IoT MQTT over WebSocket).

A self-contained, asyncio-native client for the Navien NaviLink cloud service.
No third-party AWS SDK: SigV4 signing is implemented in :mod:`.sigv4`, and the
MQTT transport drives ``paho-mqtt`` on the event loop via a socket-pump.
"""

from __future__ import annotations

from .client import NavilinkChannel, NavilinkClient
from .models import (
    AuthenticationError,
    ConnectionError,
    DeviceSorting,
    NavilinkError,
    NoDevicesError,
    TemperatureType,
)

__all__ = [
    "NavilinkClient",
    "NavilinkChannel",
    "NavilinkError",
    "AuthenticationError",
    "ConnectionError",
    "NoDevicesError",
    "DeviceSorting",
    "TemperatureType",
]
