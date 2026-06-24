"""NaviLink protocol constants, topic builders, and message envelopes.

Endpoints and command codes reverse-engineered from the NaviLink mobile app and
validated against the live broker (see docs/_research/).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

REST_BASE = "https://nlus.naviensmartcontrol.com/api/v2"
IOT_HOST = "a1t30mldyslmuq-ats.iot.us-east-1.amazonaws.com"
IOT_REGION = "us-east-1"
IOT_PORT = 443
# Mirrors the NaviLink Android app MQTT username (ignored by AWS-IoT SigV4 auth).
MQTT_USERNAME = "?SDK=Android&Version=2.16.12"

PROTOCOL_VERSION = 1


class Command(IntEnum):
    """MQTT request command codes (status reads 0x01xxxxxx, control 0x02xxxxxx)."""

    CHANNEL_INFO = 16777217  # 0x01000001
    CHANNEL_STATUS = 16777220  # 0x01000004
    POWER = 33554433  # 0x02000001
    DHW_TEMPERATURE = 33554435  # 0x02000003
    ON_DEMAND = 33554437  # 0x02000005


class Mode(IntEnum):
    """Control parameter encoding (1 = on, 2 = off)."""

    OFF = 2
    ON = 1


@dataclass(frozen=True, slots=True)
class Topics:
    """Per-session MQTT topic builder."""

    device_type: int
    mac: str
    home_seq: str
    user_seq: str
    client_id: str

    @property
    def req(self) -> str:
        return f"cmd/{self.device_type}/navilink-{self.mac}/"

    @property
    def res(self) -> str:
        return f"cmd/{self.device_type}/{self.home_seq}/{self.user_seq}/{self.client_id}/res/"

    # request topics
    @property
    def start(self) -> str:
        return self.req + "status/start"

    @property
    def channel_status_req(self) -> str:
        return self.req + "status/channelstatus"

    @property
    def control(self) -> str:
        return self.req + "control"

    # response topics (device → us)
    @property
    def channel_info_res(self) -> str:
        return self.res + "channelinfo"

    @property
    def channel_status_res(self) -> str:
        return self.res + "channelstatus"

    @property
    def channel_info_sub(self) -> str:
        return self.req + "res/channelinfo"

    @property
    def channel_status_sub(self) -> str:
        return self.req + "res/channelstatus"

    @property
    def control_fail(self) -> str:
        return self.req + "res/controlfail"

    @property
    def connection(self) -> str:
        return self.req + "connection"

    @property
    def app_connection(self) -> str:
        return f"evt/1/navilink-{self.mac}/app-connection"

    @property
    def subscriptions(self) -> tuple[str, ...]:
        """All topics to subscribe to on connect."""
        return (
            self.channel_info_res,
            self.channel_info_sub,
            self.channel_status_res,
            self.channel_status_sub,
            self.control_fail,
            self.connection,
        )


def _envelope(client_id: str, mac: str, additional_value: str, device_type: int,
              command: Command, *, request_topic: str, response_topic: str,
              extra: dict | None = None) -> dict:
    request = {
        "additionalValue": additional_value,
        "command": int(command),
        "deviceType": device_type,
        "macAddress": mac,
    }
    if extra:
        request.update(extra)
    return {
        "clientID": client_id,
        "protocolVersion": PROTOCOL_VERSION,
        "request": request,
        "requestTopic": request_topic,
        "responseTopic": response_topic,
        "sessionID": "",
    }


def channel_info_msg(t: Topics, additional_value: str) -> dict:
    """Build a channel-info request."""
    return _envelope(t.client_id, t.mac, additional_value, t.device_type,
                     Command.CHANNEL_INFO,
                     request_topic=t.start, response_topic=t.channel_info_res)


def channel_status_msg(t: Topics, additional_value: str, channel: int,
                       unit_count: int) -> dict:
    """Build a channel-status request."""
    return _envelope(t.client_id, t.mac, additional_value, t.device_type,
                     Command.CHANNEL_STATUS,
                     request_topic=t.channel_status_req,
                     response_topic=t.channel_status_res,
                     extra={"status": {"channelNumber": channel,
                                       "unitNumberStart": 1,
                                       "unitNumberEnd": unit_count}})


def _control_msg(t: Topics, additional_value: str, command: Command,
                 channel: int, mode: str, param: list) -> dict:
    return _envelope(t.client_id, t.mac, additional_value, t.device_type, command,
                     request_topic=t.control,
                     response_topic=t.channel_status_res,
                     extra={"control": {"channelNumber": channel, "mode": mode,
                                        "param": param}})


def power_msg(t: Topics, additional_value: str, channel: int, on: bool) -> dict:
    """Build a power on/off control message."""
    return _control_msg(t, additional_value, Command.POWER, channel, "power",
                        [int(Mode.ON if on else Mode.OFF)])


def on_demand_msg(t: Topics, additional_value: str, channel: int, on: bool) -> dict:
    """Build an on-demand (recirculation) control message."""
    return _control_msg(t, additional_value, Command.ON_DEMAND, channel, "onDemand",
                        [int(Mode.ON if on else Mode.OFF)])


def temperature_msg(t: Topics, additional_value: str, channel: int, temp: int) -> dict:
    """Build a DHW target-temperature control message."""
    return _control_msg(t, additional_value, Command.DHW_TEMPERATURE, channel,
                        "DHWTemperature", [temp])


def last_will_msg(t: Topics, additional_value: str) -> dict:
    """Build the MQTT last-will payload."""
    return {
        "clientID": t.client_id,
        "event": {"additionalValue": additional_value,
                  "connection": {"os": "A", "status": 0},
                  "deviceType": t.device_type, "macAddress": t.mac},
        "protocolVersion": PROTOCOL_VERSION,
        "requestTopic": t.app_connection,
        "sessionID": "",
    }
