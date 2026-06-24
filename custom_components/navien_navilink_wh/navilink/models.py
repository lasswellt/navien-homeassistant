"""NaviLink data models, enums, exceptions, and value scaling.

The raw broker payloads encode temperatures in half-degree steps (Celsius mode)
and gas/flow with device-type-dependent factors. ``scale_status`` /
``scale_info`` normalise a raw payload into the dict shape the HA entities read.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class DeviceSorting(IntEnum):
    """Navien product families (``unitType``)."""

    NO_DEVICE = 0
    NPE = 1
    NCB = 2
    NHB = 3
    CAS_NPE = 4
    CAS_NHB = 5
    NFB = 6
    CAS_NFB = 7
    NFC = 8
    NPN = 9
    CAS_NPN = 10
    NPE2 = 11
    CAS_NPE2 = 12
    NCB_H = 13
    NVW = 14
    CAS_NVW = 15


class TemperatureType(IntEnum):
    """Unit temperature system."""

    UNKNOWN = 0
    CELSIUS = 1
    FAHRENHEIT = 2


# Units whose gas-instant-usage uses the high scaling factor.
_HIGH_GIU = frozenset({DeviceSorting.NFC, DeviceSorting.NCB_H,
                       DeviceSorting.NFB, DeviceSorting.NVW})
# Units that apply gas/flow/temperature scaling at all (everything but the
# heat-only boilers and the no-device sentinel).
_SCALED = frozenset(DeviceSorting) - {
    DeviceSorting.NO_DEVICE, DeviceSorting.NHB, DeviceSorting.CAS_NHB,
}


class NavilinkError(Exception):
    """Base error."""


class AuthenticationError(NavilinkError):
    """Invalid NaviLink credentials."""


class ConnectionError(NavilinkError):  # noqa: A001 — domain-specific
    """Transient connection / API failure."""


class NoDevicesError(NavilinkError):
    """No NaviLink devices on the account."""


def scale_info(info: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of channel_info with setpoint bounds normalised."""
    out = dict(info)
    if info.get("temperatureType") == TemperatureType.CELSIUS:
        for key in ("setupDHWTempMin", "setupDHWTempMax"):
            if key in out:
                out[key] = round(out[key] / 2.0, 1)
    return out


def scale_status(status: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised copy of a raw channelStatus.channel payload.

    Booleans decoded, temperatures/gas/flow scaled per temperatureType + unitType.
    """
    out = dict(status)
    out["powerStatus"] = status.get("powerStatus") == 1
    out["onDemandUseFlag"] = status.get("onDemandUseFlag") == 1
    if "avgCalorie" in out:
        out["avgCalorie"] = out["avgCalorie"] / 2.0

    unit_type = status.get("unitType")
    temp_type = status.get("temperatureType")
    # temperatureType isn't always echoed in status; callers pass it via info.
    if temp_type is None:
        temp_type = out.get("_temperatureType")

    if unit_type not in _SCALED:
        return out

    units = out.get("unitInfo", {}).get("unitStatusList", [])

    if temp_type == TemperatureType.CELSIUS:
        giu = 100 if unit_type in _HIGH_GIU else 10
        for key in ("DHWSettingTemp", "avgInletTemp", "avgOutletTemp"):
            if key in out:
                out[key] = round(out[key] / 2.0, 1)
        for u in units:
            _scale_unit_c(u, giu)
    elif temp_type == TemperatureType.FAHRENHEIT:
        giu = 10 if unit_type in _HIGH_GIU else 1
        for u in units:
            _scale_unit_f(u, giu)
    return out


def _scale_unit_c(u: dict[str, Any], giu: int) -> None:
    if "gasInstantUsage" in u:
        u["gasInstantUsage"] = round(u["gasInstantUsage"] * giu / 10.0, 1)
    if "accumulatedGasUsage" in u:
        u["accumulatedGasUsage"] = round(u["accumulatedGasUsage"] / 10.0, 1)
    if "DHWFlowRate" in u:
        u["DHWFlowRate"] = round(u["DHWFlowRate"] / 10.0, 1)
    for key in ("currentOutletTemp", "currentInletTemp"):
        if key in u:
            u[key] = round(u[key] / 2.0, 1)


def _scale_unit_f(u: dict[str, Any], giu: int) -> None:
    if "gasInstantUsage" in u:
        u["gasInstantUsage"] = round(u["gasInstantUsage"] * giu * 3.968, 1)
    if "accumulatedGasUsage" in u:
        u["accumulatedGasUsage"] = round(u["accumulatedGasUsage"] * 35.314667 / 10.0, 1)
    if "DHWFlowRate" in u:
        u["DHWFlowRate"] = round(u["DHWFlowRate"] / 37.85, 1)
