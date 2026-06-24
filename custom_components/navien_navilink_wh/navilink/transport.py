"""Async MQTT-over-WebSocket transport for AWS IoT.

Drives ``paho-mqtt`` with an asyncio socket-pump (``add_reader``/``add_writer`` +
periodic ``loop_misc``) so all ongoing I/O runs on the event loop with no
background network thread. Only the initial blocking TLS/WebSocket handshake runs
in an executor. Compatible with paho-mqtt 1.6.x and 2.x.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from datetime import datetime, timezone

import certifi
import paho.mqtt.client as mqtt

from .auth import Credentials
from .models import ConnectionError as NavilinkConnectionError
from .protocol import IOT_HOST, IOT_PORT, IOT_REGION, MQTT_USERNAME, Topics
from .sigv4 import presign_iot_path

_LOGGER = logging.getLogger(__name__)

MessageHandler = Callable[[str, dict], None]


def _new_client(client_id: str) -> mqtt.Client:
    """Create a paho client using v1 callback signatures on either paho major."""
    if hasattr(mqtt, "CallbackAPIVersion"):  # paho-mqtt >= 2.0
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
            transport="websockets",
            clean_session=True,
        )
    return mqtt.Client(  # paho-mqtt 1.6.x
        client_id=client_id, transport="websockets", clean_session=True
    )


class NavilinkMqtt:
    """A single AWS-IoT MQTT-over-WebSocket session."""

    def __init__(
        self,
        credentials: Credentials,
        topics: Topics,
        *,
        last_will: tuple[str, dict] | None,
        on_message: MessageHandler,
        on_disconnect: Callable[[], None],
    ) -> None:
        """Initialize the transport."""
        self._creds = credentials
        self._topics = topics
        self._on_message = on_message
        self._on_disconnect_cb = on_disconnect
        self._loop = asyncio.get_running_loop()
        self._pending: dict[str, asyncio.Event] = {}
        self._connect_future: asyncio.Future[int] | None = None
        self._misc_task: asyncio.Task | None = None
        self.connected = False

        self._client = _new_client(topics.client_id)
        self._client.username_pw_set(MQTT_USERNAME, None)
        if last_will is not None:
            topic, payload = last_will
            self._client.will_set(topic, json.dumps(payload, separators=(",", ":")), qos=1)
        ctx = ssl.create_default_context(cafile=certifi.where())
        self._client.tls_set_context(ctx)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message_raw
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write

    # ----- lifecycle -----

    async def async_connect(self, timeout: float = 20.0) -> None:
        """Sign the WebSocket URL and connect; resolves on CONNACK."""
        now = datetime.now(timezone.utc)
        path = presign_iot_path(
            IOT_HOST, IOT_REGION, self._creds.access_key_id,
            self._creds.secret_key, self._creds.session_token, now,
        )
        # Host header must match the signed host (paho would append :443).
        self._client.ws_set_options(path=path, headers={"Host": IOT_HOST})

        self._connect_future = self._loop.create_future()
        try:
            # Blocking TLS+WS handshake — the only off-loop step (setup only).
            await self._loop.run_in_executor(
                None, self._client.connect, IOT_HOST, IOT_PORT, 60
            )
        except Exception as err:  # noqa: BLE001
            raise NavilinkConnectionError(f"MQTT connect failed: {err}") from err

        self._misc_task = self._loop.create_task(self._misc_loop())
        try:
            rc = await asyncio.wait_for(self._connect_future, timeout)
        except asyncio.TimeoutError as err:
            raise NavilinkConnectionError("MQTT CONNACK timeout") from err
        if rc != 0:
            raise NavilinkConnectionError(
                f"MQTT connection rejected: {mqtt.connack_string(rc)}"
            )

    async def async_disconnect(self) -> None:
        """Disconnect and stop the socket pump."""
        self.connected = False
        if self._misc_task:
            self._misc_task.cancel()
        try:
            self._client.disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MQTT disconnect error: %s", err)

    # ----- subscribe / publish -----

    def subscribe(self, *topics: str) -> None:
        """Subscribe to topics (QoS 1)."""
        for topic in topics:
            self._client.subscribe(topic, qos=1)

    async def request(self, topic: str, payload: dict, session_id: str,
                      timeout: float = 15.0) -> None:
        """Publish a request and await its correlated response (best effort)."""
        payload = {**payload, "sessionID": session_id}
        event = asyncio.Event()
        self._pending[session_id] = event
        try:
            self._publish(topic, payload)
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except asyncio.TimeoutError:
                _LOGGER.debug("No response for session %s on %s", session_id, topic)
        finally:
            self._pending.pop(session_id, None)

    def _publish(self, topic: str, payload: dict) -> None:
        self._client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1)

    # ----- paho callbacks -----

    def _on_connect(self, client, userdata, flags, rc) -> None:
        self.connected = rc == 0
        if self._connect_future and not self._connect_future.done():
            self._connect_future.set_result(rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self.connected = False
        self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    def _on_message_raw(self, client, userdata, msg) -> None:
        try:
            body = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        session_id = body.get("sessionID")
        if session_id and (event := self._pending.get(session_id)):
            event.set()
        self._on_message(msg.topic, body)

    # ----- asyncio socket pump (thread-safe registration) -----

    def _on_socket_open(self, client, userdata, sock) -> None:
        self._loop.call_soon_threadsafe(self._loop.add_reader, sock, client.loop_read)

    def _on_socket_close(self, client, userdata, sock) -> None:
        self._loop.call_soon_threadsafe(self._safe_remove_reader, sock)

    def _on_socket_register_write(self, client, userdata, sock) -> None:
        self._loop.call_soon_threadsafe(self._loop.add_writer, sock, client.loop_write)

    def _on_socket_unregister_write(self, client, userdata, sock) -> None:
        self._loop.call_soon_threadsafe(self._safe_remove_writer, sock)

    def _safe_remove_reader(self, sock) -> None:
        """Remove the read-watcher, tolerating an already-closed fd."""
        try:
            self._loop.remove_reader(sock)
        except (OSError, ValueError):  # fd already closed
            pass

    def _safe_remove_writer(self, sock) -> None:
        """Remove the write-watcher, tolerating an already-closed fd."""
        try:
            self._loop.remove_writer(sock)
        except (OSError, ValueError):  # fd already closed
            pass

    async def _misc_loop(self) -> None:
        """Drive paho keepalive/timeouts on the event loop."""
        try:
            while True:
                self._client.loop_misc()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
