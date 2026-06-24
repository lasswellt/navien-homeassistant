"""NaviLink REST authentication (sign-in + device list)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .models import AuthenticationError, ConnectionError, NoDevicesError
from .protocol import REST_BASE


@dataclass(frozen=True, slots=True)
class Credentials:
    """Temporary IAM credentials + identity returned by sign-in."""

    access_token: str
    access_key_id: str
    secret_key: str
    session_token: str
    user_seq: str


async def async_sign_in(
    session: aiohttp.ClientSession, username: str, password: str
) -> Credentials:
    """Sign in to the NaviLink REST API and return credentials.

    Raises:
        AuthenticationError: bad credentials.
        ConnectionError: unexpected response / network failure.
    """
    try:
        async with session.post(
            f"{REST_BASE}/user/sign-in",
            json={"userId": username, "password": password},
        ) as resp:
            body = await resp.json()
    except aiohttp.ClientError as err:
        raise ConnectionError(f"Sign-in request failed: {err}") from err

    if body.get("msg") == "USER_NOT_FOUND":
        raise AuthenticationError("Invalid NaviLink credentials")
    data = body.get("data")
    if not data:
        raise ConnectionError("Sign-in returned no data")

    token = data.get("token", {})
    try:
        return Credentials(
            access_token=token["accessToken"],
            access_key_id=token["accessKeyId"],
            secret_key=token["secretKey"],
            session_token=token["sessionToken"],
            user_seq=str(data["userInfo"]["userSeq"]),
        )
    except KeyError as err:
        raise ConnectionError(f"Sign-in response missing field: {err}") from err


async def async_get_devices(
    session: aiohttp.ClientSession, access_token: str, username: str
) -> list[dict[str, Any]]:
    """Return the raw device list for the account."""
    try:
        async with session.post(
            f"{REST_BASE}/device/list",
            headers={"Authorization": access_token},
            json={"offset": 0, "count": 20, "userId": username},
        ) as resp:
            body = await resp.json()
    except aiohttp.ClientError as err:
        raise ConnectionError(f"Device-list request failed: {err}") from err

    devices = body.get("data")
    if not devices:
        raise NoDevicesError("No NaviLink devices found for this account")
    return devices
