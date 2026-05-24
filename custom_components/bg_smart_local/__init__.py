"""The BG Smart Local Control integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, DEFAULT_POLLING_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]
SCAN_INTERVAL = timedelta(seconds=DEFAULT_POLLING_INTERVAL)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the BG Smart Local Control component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BG Smart Local Control from a config entry."""
    
    # 1. Retrieve connection data
    host = entry.data["host"]
    port = entry.data.get("port", 8080)
    node_id = entry.data.get("node_id", "")
    pop = entry.data["pop"]
    
    # Always use Sec1 security for BG Smart devices
    security_type = 1
    
    # 2. Initialize the connection
    device = ESPLocalDevice(host, port, node_id, pop, security_type)
    
    # 3. Setup Polling (Hardcoded to Default 30s)
    poll_interval_sec = DEFAULT_POLLING_INTERVAL
    scan_interval = timedelta(seconds=poll_interval_sec)
    
    _LOGGER.debug("Setting up coordinator with polling interval: %s seconds", poll_interval_sec)

    # 4. Create the Data Coordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="bg_smart_local",
        update_method=device.get_params,
        update_interval=scan_interval,
    )
    
    # 5. Perform initial refresh
    await coordinator.async_config_entry_first_refresh()
    
    # 6. Store everything in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "device": device,
        "coordinator": coordinator,
        "host": host,
        "port": port
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
