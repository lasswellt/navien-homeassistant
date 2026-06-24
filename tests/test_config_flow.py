"""Config flow tests for Navien NaviLink."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.navien_navilink_wh.const import (
    CONF_DEVICE_INDEX,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .conftest import DEVICE_LIST, ENTRY_DATA, MockNavilink

CREDS = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
CF = "custom_components.navien_navilink_wh.config_flow.NavilinkConnect"


class _BadLogin(MockNavilink):
    async def login(self):
        raise RuntimeError("invalid")


class _OtherGateway(MockNavilink):
    async def login(self):
        return [
            {"deviceInfo": {**DEVICE_LIST[0]["deviceInfo"], "macAddress": "ZZ9988776655"}}
        ]


async def test_user_flow_success(hass: HomeAssistant, mock_navilink) -> None:
    """Full happy path: user → pick_gateway → create."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["step_id"] == "pick_gateway"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_INDEX: 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "user@example.com"
    assert result["options"][CONF_POLLING_INTERVAL] == 15


async def test_user_flow_invalid_auth_then_recover(
    hass: HomeAssistant, mock_navilink
) -> None:
    """Invalid auth shows error, then a valid retry succeeds."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # mock_navilink patches CF=MockNavilink; override to fail just this step.
    with patch(CF, _BadLogin):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDS
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_INDEX: 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """A duplicate gateway aborts."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_INDEX: 0}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_success(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Reauth updates credentials and reloads."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "new@example.com", CONF_PASSWORD: "newpass"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_USERNAME] == "new@example.com"


async def test_reauth_invalid_auth(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Reauth with bad credentials shows an error."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    with patch(CF, _BadLogin):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDS
        )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_success(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Reconfigure re-validates and updates the entry."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["step_id"] == "reconfigure_pick"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_INDEX: 0}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_invalid_auth(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Reconfigure with bad credentials shows an error."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch(CF, _BadLogin):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDS
        )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_unique_id_mismatch(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Reconfigure to a different gateway aborts on mismatch."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch(CF, _OtherGateway):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDS
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_INDEX: 0}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_options_flow(
    hass: HomeAssistant, mock_navilink, mock_config_entry
) -> None:
    """Options flow updates the polling interval."""
    from .conftest import setup_integration

    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLLING_INTERVAL: 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POLLING_INTERVAL] == 30
