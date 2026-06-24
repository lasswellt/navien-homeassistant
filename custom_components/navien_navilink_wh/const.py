"""Constants for the Navien NaviLink Water Heater integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "navien_navilink_wh"

# Config entry schema version (bump + add async_migrate_entry on breaking changes)
CONFIG_VERSION: Final = 1

# Config / options keys
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_DEVICE_INDEX: Final = "device_index"
CONF_POLLING_INTERVAL: Final = "polling_interval"

# Polling bounds (seconds) — NaviLink throttles aggressive polling
DEFAULT_POLLING_INTERVAL: Final = 15
MIN_POLLING_INTERVAL: Final = 10
MAX_POLLING_INTERVAL: Final = 120

MANUFACTURER: Final = "Navien"
