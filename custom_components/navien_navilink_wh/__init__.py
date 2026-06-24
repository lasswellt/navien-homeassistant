"""The Navien NaviLink Water Heater integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import NavienCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.SENSOR,
    Platform.SWITCH,
]

# entry.runtime_data holds the live coordinator
type NavienConfigEntry = ConfigEntry[NavienCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: NavienConfigEntry) -> bool:
    """Set up Navien NaviLink from a config entry."""
    coordinator = NavienCoordinator(hass, entry)
    await coordinator.async_setup()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when options (e.g. polling interval) change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NavienConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: NavienConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
