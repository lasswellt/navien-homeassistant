"""High-level NaviLink client: auth + transport + protocol orchestration."""

from __future__ import annotations

import asyncio
import itertools
import logging
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp

from . import auth, protocol
from .models import (
    AuthenticationError,
    ConnectionError as NavilinkConnectionError,
    NoDevicesError,
    scale_info,
    scale_status,
)
from .transport import NavilinkMqtt

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 15


class NavilinkChannel:
    """A single heating channel; control methods publish to the broker."""

    def __init__(self, client: NavilinkClient, number: int, info: dict[str, Any]) -> None:
        """Initialize the channel with its (scaled) info."""
        self._client = client
        self.number = number
        self.info: dict[str, Any] = info
        self.status: dict[str, Any] = {}

    def is_available(self) -> bool:
        """Return True while the client is connected."""
        return self._client.connected

    async def set_power_state(self, on: bool) -> None:
        """Turn the channel on/off."""
        await self._client.async_control(protocol.power_msg, self.number, on)

    async def set_hot_button_state(self, on: bool) -> None:
        """Toggle on-demand recirculation."""
        await self._client.async_control(protocol.on_demand_msg, self.number, on)

    async def set_temperature(self, temp: int) -> None:
        """Set the DHW target temperature."""
        await self._client.async_control(protocol.temperature_msg, self.number, temp)


class NavilinkClient:
    """Owns one NaviLink account/device session."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        session: aiohttp.ClientSession,
        device_index: int = 0,
        poll_interval: int = 15,
    ) -> None:
        """Initialize the client (no I/O)."""
        self._username = username
        self._password = password
        self._session = session
        self._device_index = device_index
        self._poll_interval = poll_interval

        self.devices: list[dict[str, Any]] = []
        self.device_info: dict[str, Any] = {}
        self.device_status: dict[str, Any] = {}
        self.channels: dict[int, NavilinkChannel] = {}
        self.on_update: Callable[[], None] | None = None

        self._creds: auth.Credentials | None = None
        self._topics: protocol.Topics | None = None
        self._mqtt: NavilinkMqtt | None = None
        self._poll_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutting_down = False
        self._session_ids = itertools.count(1)

    @property
    def connected(self) -> bool:
        """Return True if the MQTT session is up."""
        return self._mqtt is not None and self._mqtt.connected

    def _session_id(self) -> str:
        return str(next(self._session_ids))

    # ----- REST-only (config flow) -----

    async def async_login(self) -> list[dict[str, Any]]:
        """Validate credentials and return the device list (no MQTT)."""
        creds = await auth.async_sign_in(self._session, self._username, self._password)
        self.devices = await auth.async_get_devices(
            self._session, creds.access_token, self._username
        )
        return self.devices

    # ----- full connect -----

    async def async_connect(self) -> None:
        """Sign in, connect MQTT, discover channels, and start polling.

        Raises:
            AuthenticationError, NoDevicesError, NavilinkConnectionError.
        """
        self._shutting_down = False
        self._creds = await auth.async_sign_in(
            self._session, self._username, self._password
        )
        self.devices = await auth.async_get_devices(
            self._session, self._creds.access_token, self._username
        )
        if self._device_index >= len(self.devices):
            raise NoDevicesError("Configured device index is out of range")
        self.device_info = self.devices[self._device_index]
        di = self.device_info.get("deviceInfo", {})

        self._topics = protocol.Topics(
            device_type=int(di.get("deviceType", 1)),
            mac=di.get("macAddress", ""),
            home_seq=str(di.get("homeSeq", "")),
            user_seq=self._creds.user_seq,
            client_id=str(uuid.uuid4()),
        )
        additional_value = di.get("additionalValue", "")
        self._mqtt = NavilinkMqtt(
            self._creds, self._topics,
            last_will=(self._topics.app_connection,
                       protocol.last_will_msg(self._topics, additional_value)),
            on_message=self._handle_message,
            on_disconnect=self._handle_disconnect,
        )
        await self._mqtt.async_connect()
        self._mqtt.subscribe(*self._topics.subscriptions)

        # Initial channel info + status.
        await self._mqtt.request(
            self._topics.start,
            protocol.channel_info_msg(self._topics, additional_value),
            self._session_id(),
        )
        if not self.channels:
            raise NavilinkConnectionError("No channels returned by NaviLink")
        await self._poll_once()

        self._poll_task = asyncio.get_running_loop().create_task(self._poll_loop())

    async def async_disconnect(self) -> None:
        """Stop polling and disconnect."""
        self._shutting_down = True
        for task in (self._poll_task, self._reconnect_task):
            if task:
                task.cancel()
        if self._mqtt:
            await self._mqtt.async_disconnect()

    # ----- control -----

    async def async_control(self, builder, channel_number: int, *args) -> None:
        """Publish a control command then refresh status."""
        if not (self._mqtt and self._topics):
            raise NavilinkConnectionError("Not connected")
        di = self.device_info.get("deviceInfo", {})
        msg = builder(self._topics, di.get("additionalValue", ""), channel_number, *args)
        await self._mqtt.request(self._topics.control, msg, self._session_id())
        await self._poll_once()

    # ----- polling -----

    async def _poll_once(self) -> None:
        if not (self._mqtt and self._topics):
            return
        di = self.device_info.get("deviceInfo", {})
        add_val = di.get("additionalValue", "")
        for channel in list(self.channels.values()):
            await self._mqtt.request(
                self._topics.channel_status_req,
                protocol.channel_status_msg(
                    self._topics, add_val, channel.number,
                    channel.info.get("unitCount", 1),
                ),
                self._session_id(),
            )

    async def _poll_loop(self) -> None:  # pragma: no cover — timing loop
        try:
            while not self._shutting_down:
                await asyncio.sleep(self._poll_interval)
                if self.connected:
                    await self._poll_once()
        except asyncio.CancelledError:
            raise

    # ----- message handling -----

    def _handle_message(self, topic: str, body: dict[str, Any]) -> None:
        response = body.get("response", {})
        if not isinstance(response, dict):
            return
        # Retain device-level fields (swVersion, wifiRssi, countryCode, …).
        self.device_status = {
            k: v for k, v in response.items()
            if k not in ("channelInfo", "channelStatus", "weeklySchedule")
        }
        if "channelInfo" in response:
            self._update_channels(response["channelInfo"])
        if "channelStatus" in response:
            self._update_status(response["channelStatus"])
        if self.on_update:
            self.on_update()

    def _update_channels(self, channel_info: dict[str, Any]) -> None:
        for entry in channel_info.get("channelList", []):
            number = entry.get("channelNumber", 0)
            info = scale_info(entry.get("channel", {}))
            if number in self.channels:
                self.channels[number].info = info
            else:
                self.channels[number] = NavilinkChannel(self, number, info)

    def _update_status(self, channel_status: dict[str, Any]) -> None:
        number = channel_status.get("channelNumber", 0)
        channel = self.channels.get(number)
        if channel is None:
            return
        raw = dict(channel_status.get("channel", {}))
        # Status payloads omit temperatureType; inject it from channel_info so
        # the scaler can pick the right factors.
        raw.setdefault("temperatureType", channel.info.get("temperatureType"))
        channel.status = scale_status(raw)

    # ----- reconnect -----

    def _handle_disconnect(self) -> None:
        if self.on_update:
            self.on_update()
        if self._shutting_down or (self._reconnect_task and not self._reconnect_task.done()):
            return
        self._reconnect_task = asyncio.get_running_loop().create_task(self._reconnect())

    async def _reconnect(self) -> None:  # pragma: no cover — reconnect timing loop
        while not self._shutting_down and not self.connected:
            await asyncio.sleep(RECONNECT_DELAY)
            if self._shutting_down:
                return
            try:
                _LOGGER.debug("Reconnecting to NaviLink")
                await self.async_connect()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Reconnect failed: %s", err)
