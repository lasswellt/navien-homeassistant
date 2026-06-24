"""Unit tests for the native navilink client package."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.navien_navilink_wh.navilink import (
    AuthenticationError,
    ConnectionError as NavilinkConnectionError,
    DeviceSorting,
    NavilinkClient,
    NoDevicesError,
    TemperatureType,
)
from custom_components.navien_navilink_wh.navilink import auth, models, protocol
from custom_components.navien_navilink_wh.navilink.sigv4 import presign_iot_path

# ----- sigv4 -----

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
_HOST = "a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com"


def test_presign_structure_and_determinism():
    path = presign_iot_path(_HOST, "us-east-1", "AKID", "SECRET", "TOKEN", _NOW)
    assert path.startswith("/mqtt?")
    for part in ("X-Amz-Algorithm=AWS4-HMAC-SHA256", "X-Amz-Credential=",
                 "X-Amz-Date=20260624T120000Z", "X-Amz-SignedHeaders=host",
                 "X-Amz-Signature=", "X-Amz-Security-Token=TOKEN"):
        assert part in path
    # deterministic for identical inputs
    assert path == presign_iot_path(_HOST, "us-east-1", "AKID", "SECRET", "TOKEN", _NOW)


def test_presign_signature_changes_with_secret():
    a = presign_iot_path(_HOST, "us-east-1", "AKID", "S1", "T", _NOW)
    b = presign_iot_path(_HOST, "us-east-1", "AKID", "S2", "T", _NOW)
    assert a.split("X-Amz-Signature=")[1] != b.split("X-Amz-Signature=")[1]


def test_presign_omits_token_when_empty():
    assert "X-Amz-Security-Token" not in presign_iot_path(
        _HOST, "us-east-1", "AKID", "SECRET", "", _NOW
    )


# ----- models / scaling -----


def test_scale_status_fahrenheit_keeps_temps():
    raw = {
        "powerStatus": 1, "onDemandUseFlag": 2, "avgCalorie": 4,
        "unitType": DeviceSorting.NPE2, "temperatureType": TemperatureType.FAHRENHEIT,
        "DHWSettingTemp": 120,
        "unitInfo": {"unitStatusList": [
            {"currentOutletTemp": 120, "accumulatedGasUsage": 39, "DHWFlowRate": 38}
        ]},
    }
    out = models.scale_status(raw)
    assert out["powerStatus"] is True
    assert out["onDemandUseFlag"] is False
    assert out["avgCalorie"] == 2.0
    u = out["unitInfo"]["unitStatusList"][0]
    assert u["currentOutletTemp"] == 120  # F: temps not divided


def test_scale_status_celsius_halves_temps():
    raw = {
        "powerStatus": 1, "onDemandUseFlag": 1, "avgCalorie": 0,
        "unitType": DeviceSorting.NPE2, "temperatureType": TemperatureType.CELSIUS,
        "DHWSettingTemp": 110, "avgInletTemp": 80, "avgOutletTemp": 90,
        "unitInfo": {"unitStatusList": [
            {"currentOutletTemp": 100, "currentInletTemp": 80,
             "accumulatedGasUsage": 50, "DHWFlowRate": 30}
        ]},
    }
    out = models.scale_status(raw)
    assert out["DHWSettingTemp"] == 55.0
    u = out["unitInfo"]["unitStatusList"][0]
    assert u["currentOutletTemp"] == 50.0
    assert u["DHWFlowRate"] == 3.0


def test_scale_info_celsius_halves_bounds():
    out = models.scale_info({
        "temperatureType": TemperatureType.CELSIUS,
        "setupDHWTempMin": 80, "setupDHWTempMax": 120,
    })
    assert out["setupDHWTempMin"] == 40.0
    assert out["setupDHWTempMax"] == 60.0


def test_scale_status_skips_unscaled_unit_type():
    out = models.scale_status({"powerStatus": 1, "onDemandUseFlag": 2,
                               "unitType": DeviceSorting.NHB})
    assert out["powerStatus"] is True  # booleans still decoded


# ----- protocol -----


def _topics():
    return protocol.Topics(device_type=1, mac="MAC", home_seq="H",
                           user_seq="U", client_id="CID")


def test_topics():
    t = _topics()
    assert t.req == "cmd/1/navilink-MAC/"
    assert t.res == "cmd/1/H/U/CID/res/"
    assert t.start == "cmd/1/navilink-MAC/status/start"
    assert t.control == "cmd/1/navilink-MAC/control"
    assert t.channel_info_res == "cmd/1/H/U/CID/res/channelinfo"
    assert len(t.subscriptions) == 6


def test_message_command_codes():
    t = _topics()
    assert protocol.channel_info_msg(t, "AV")["request"]["command"] == 16777217
    assert protocol.channel_status_msg(t, "AV", 1, 1)["request"]["command"] == 16777220
    power = protocol.power_msg(t, "AV", 1, True)
    assert power["request"]["command"] == 33554433
    assert power["request"]["control"]["param"] == [1]
    assert protocol.power_msg(t, "AV", 1, False)["request"]["control"]["param"] == [2]
    temp = protocol.temperature_msg(t, "AV", 1, 130)
    assert temp["request"]["command"] == 33554435
    assert temp["request"]["control"]["param"] == [130]
    od = protocol.on_demand_msg(t, "AV", 1, True)
    assert od["request"]["command"] == 33554437


def test_last_will():
    will = protocol.last_will_msg(_topics(), "AV")
    assert will["event"]["macAddress"] == "MAC"


# ----- auth (mocked aiohttp) -----


class _Resp:
    def __init__(self, payload):
        self._p = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._p


class _Session:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def post(self, url, **kw):
        self.calls += 1
        return _Resp(self._payload)


async def test_sign_in_success():
    session = _Session({"data": {
        "token": {"accessToken": "AT", "accessKeyId": "AK",
                  "secretKey": "SK", "sessionToken": "ST"},
        "userInfo": {"userSeq": 42},
    }})
    creds = await auth.async_sign_in(session, "u", "p")
    assert creds.access_key_id == "AK"
    assert creds.user_seq == "42"


async def test_sign_in_bad_credentials():
    session = _Session({"msg": "USER_NOT_FOUND"})
    with pytest.raises(AuthenticationError):
        await auth.async_sign_in(session, "u", "p")


async def test_sign_in_no_data():
    with pytest.raises(NavilinkConnectionError):
        await auth.async_sign_in(_Session({}), "u", "p")


async def test_get_devices_empty():
    with pytest.raises(NoDevicesError):
        await auth.async_get_devices(_Session({"data": []}), "AT", "u")


# ----- client message parsing -----


def _client():
    return NavilinkClient("u", "p", session=object())


def test_client_handle_channel_info_and_status():
    client = _client()
    client._handle_message("topic", {"response": {
        "swVersion": 4352, "wifiRssi": -50,
        "channelInfo": {"channelList": [
            {"channelNumber": 1, "channel": {"unitType": 11,
                                             "temperatureType": 2, "unitCount": 1}}
        ]},
    }})
    assert 1 in client.channels
    assert client.device_status["swVersion"] == 4352

    client._handle_message("topic", {"response": {"channelStatus": {
        "channelNumber": 1,
        "channel": {"powerStatus": 1, "onDemandUseFlag": 2, "unitType": 11,
                    "unitInfo": {"unitStatusList": [{"currentOutletTemp": 110}]}},
    }}})
    status = client.channels[1].status
    assert status["powerStatus"] is True
    assert status["unitInfo"]["unitStatusList"][0]["currentOutletTemp"] == 110


def test_client_on_update_fires():
    client = _client()
    fired = []
    client.on_update = lambda: fired.append(1)
    client._handle_message("t", {"response": {"swVersion": 1}})
    assert fired == [1]


def test_client_update_existing_channel():
    client = _client()
    client._handle_message("t", {"response": {"channelInfo": {"channelList": [
        {"channelNumber": 1, "channel": {"unitType": 11, "temperatureType": 2}}]}}})
    client._handle_message("t", {"response": {"channelInfo": {"channelList": [
        {"channelNumber": 1, "channel": {"unitType": 11, "temperatureType": 2,
                                         "setupDHWTempMin": 90}}]}}})
    assert client.channels[1].info["setupDHWTempMin"] == 90  # updated in place


async def test_client_handle_disconnect_schedules_reconnect():
    client = _client()
    fired = []
    client.on_update = lambda: fired.append(1)
    client._handle_disconnect()
    assert fired == [1]
    assert client._reconnect_task is not None
    client._reconnect_task.cancel()


# ----- client orchestration (fake transport) -----


class _FakeMqtt:
    def __init__(self, creds, topics, *, last_will, on_message, on_disconnect):
        self._on_message = on_message
        self.on_disconnect = on_disconnect
        self.connected = False
        self.published: list[tuple[str, dict]] = []

    async def async_connect(self, timeout=20.0):
        self.connected = True

    async def async_disconnect(self):
        self.connected = False

    def subscribe(self, *topics):
        pass

    async def request(self, topic, payload, session_id, timeout=15.0):
        self.published.append((topic, payload))
        if topic.endswith("status/start"):
            self._on_message("res", {"response": {"swVersion": 4352, "channelInfo": {
                "channelList": [{"channelNumber": 1, "channel": {
                    "unitType": 11, "temperatureType": 2, "unitCount": 1}}]}}})
        elif topic.endswith("status/channelstatus"):
            self._on_message("res", {"response": {"channelStatus": {
                "channelNumber": 1, "channel": {
                    "powerStatus": 1, "onDemandUseFlag": 2, "unitType": 11,
                    "unitInfo": {"unitStatusList": [{"currentOutletTemp": 100}]}}}}})


async def test_client_connect_poll_control(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.navien_navilink_wh.navilink import client as client_mod
    from custom_components.navien_navilink_wh.navilink.auth import Credentials

    from .conftest import DEVICE_LIST

    creds = Credentials("AT", "AK", "SK", "ST", "42")
    monkeypatch.setattr(client_mod.auth, "async_sign_in", AsyncMock(return_value=creds))
    monkeypatch.setattr(client_mod.auth, "async_get_devices",
                        AsyncMock(return_value=DEVICE_LIST))
    monkeypatch.setattr(client_mod, "NavilinkMqtt", _FakeMqtt)

    client = NavilinkClient("u", "p", session=object(), poll_interval=9999)
    await client.async_connect()
    assert client.connected
    assert 1 in client.channels
    assert client.channels[1].status["powerStatus"] is True

    await client.channels[1].set_power_state(True)
    assert any(topic.endswith("control") for topic, _ in client._mqtt.published)

    await client.async_disconnect()
    assert not client.connected


async def test_client_login_only(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.navien_navilink_wh.navilink import client as client_mod
    from custom_components.navien_navilink_wh.navilink.auth import Credentials

    from .conftest import DEVICE_LIST

    monkeypatch.setattr(client_mod.auth, "async_sign_in",
                        AsyncMock(return_value=Credentials("AT", "AK", "SK", "ST", "1")))
    monkeypatch.setattr(client_mod.auth, "async_get_devices",
                        AsyncMock(return_value=DEVICE_LIST))
    client = NavilinkClient("u", "p", session=object())
    assert await client.async_login() == DEVICE_LIST
