"""AWS SigV4 presigned-URL signing for AWS IoT MQTT-over-WebSocket.

Self-contained (stdlib only) — no boto3. Produces the ``/mqtt?...`` request path
for a WebSocket connection authenticated with temporary IAM credentials.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from urllib.parse import quote

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "iotdevicegateway"
_CANONICAL_URI = "/mqtt"
_UNRESERVED = "-_.~"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret_key: str, datestamp: str, region: str) -> bytes:
    k_date = _sign(f"AWS4{secret_key}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, _SERVICE)
    return _sign(k_service, "aws4_request")


def presign_iot_path(
    host: str,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str,
    now: datetime,
) -> str:
    """Return the SigV4-presigned ``/mqtt?...`` WebSocket request path.

    Args:
        host: AWS IoT ATS endpoint (e.g. ``xxxx-ats.iot.us-east-1.amazonaws.com``).
        region: AWS region of the endpoint.
        access_key/secret_key/session_token: temporary STS credentials.
        now: signing time (UTC).

    The Host header sent by the client must equal ``host`` (no port) for the
    signature to validate.
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{_SERVICE}/aws4_request"

    query = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{k}={quote(v, safe=_UNRESERVED)}" for k, v in sorted(query.items())
    )
    canonical_request = (
        f"GET\n{_CANONICAL_URI}\n{canonical_qs}\n"
        f"host:{host}\n\nhost\n"
        f"{hashlib.sha256(b'').hexdigest()}"
    )
    string_to_sign = (
        f"{_ALGORITHM}\n{amz_date}\n{scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    canonical_qs += f"&X-Amz-Signature={signature}"
    if session_token:
        canonical_qs += "&X-Amz-Security-Token=" + quote(session_token, safe=_UNRESERVED)
    return f"{_CANONICAL_URI}?{canonical_qs}"
