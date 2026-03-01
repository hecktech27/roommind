"""RoomSense – Holistic room climate management for Home Assistant."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, VERSION
from .coordinator import RoomSenseCoordinator
from .store import RoomSenseStore
from .websocket_api import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the RoomSense integration (YAML, runs once)."""
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RoomSense from a config entry."""
    # Ensure the store is created and loaded (once across all entries)
    store = hass.data[DOMAIN].get("store")
    if not store:
        store = RoomSenseStore(hass)
        await store.async_load()
        hass.data[DOMAIN]["store"] = store

    coordinator = RoomSenseCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    hass.data[DOMAIN]["coordinator"] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_register_panel(hass)
    _check_version_mismatch(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a RoomSense config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop("coordinator", None)

    # Remove panel if no entries remain
    if not hass.data[DOMAIN]:
        async_remove_panel(hass, "roomsense")

    return unload_ok


def _check_version_mismatch(hass: HomeAssistant) -> None:
    """Compare in-memory VERSION (from boot) with manifest.json on disk."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        disk_version = json.loads(manifest_path.read_text())["version"]
    except Exception:  # noqa: BLE001
        return

    if disk_version != VERSION:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "restart_required",
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="restart_required",
            translation_placeholders={"version": disk_version},
        )
        _LOGGER.warning(
            "RoomSense on disk is %s but running %s – restart required",
            disk_version,
            VERSION,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "restart_required")


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the RoomSense custom panel in the sidebar."""
    if hass.data[DOMAIN].get("panel_registered"):
        return

    panel_js = Path(__file__).parent / "frontend" / "roomsense-panel.js"
    if not panel_js.exists():
        _LOGGER.warning(
            "RoomSense panel JS not found at %s – sidebar panel not registered",
            panel_js,
        )
        return

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/roomsense/roomsense-panel.js", str(panel_js), False)]
        )
    except RuntimeError:
        _LOGGER.debug("RoomSense static path already registered")

    try:
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="RoomSense",
            sidebar_icon="mdi:home-thermometer",
            frontend_url_path="roomsense",
            config={
                "_panel_custom": {
                    "name": "roomsense-panel",
                    "embed_iframe": False,
                    "trust_external": False,
                    "js_url": "/roomsense/roomsense-panel.js",
                }
            },
        )
    except ValueError:
        _LOGGER.debug("RoomSense panel already registered")

    hass.data[DOMAIN]["panel_registered"] = True
    _LOGGER.info("RoomSense panel registered in sidebar")
