"""Support for BG Smart Local Control lights."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    DEFAULT_ENABLE_BRIGHTNESS_MAPPING,
    BRIGHTNESS_GAMMA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BG Smart lights from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    device = data["device"]
    coordinator = data["coordinator"]
    
    try:
        # Get device parameters from coordinator
        params = coordinator.data
        
        if not params:
            _LOGGER.error("No params found in device properties")
            return
        
        entities = []
        for device_name, device_params in params.items():
            # Check for dimmer capabilities
            if isinstance(device_params, dict) and "Power" in device_params and "brightness" in device_params:
                entities.append(BGSmartDimmer(coordinator, device, device_name, device_params, entry))
        
        if entities:
            async_add_entities(entities)
            
    except Exception as ex:
        _LOGGER.error("Failed to set up lights: %s", ex, exc_info=True)


class BGSmartDimmer(CoordinatorEntity, LightEntity):
    """Representation of a BG Smart Dimmer."""
    
    def __init__(
        self, 
        coordinator: DataUpdateCoordinator,
        device, 
        device_name: str, 
        device_params: dict, 
        entry: ConfigEntry
    ) -> None:
        """Initialize the dimmer."""
        super().__init__(coordinator)
        
        self._device = device
        self._device_name = device_name
        self._entry = entry
        
        # Friendly Name
        friendly_name = device_params.get("Name", device_name)
        
        self._attr_unique_id = f"{entry.entry_id}_{device_name}"
        self._attr_name = friendly_name
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS
        
        # Default min brightness (1%) until updated from params
        self._device_min = 1
        
        # Set initial state from device_params
        self._update_from_params(device_params)
        
        _LOGGER.info(
            "Initialized dimmer: %s (device: %s) - Power: %s, Brightness: %s%%",
            friendly_name, device_name, self._attr_is_on, 
            int((self._attr_brightness / 255) * 100) if self._attr_brightness else 0
        )
    
    def _update_from_params(self, device_params: dict) -> None:
        """Update entity state from device parameters."""
        # Power is a boolean directly
        self._attr_is_on = bool(device_params.get("Power", False))
        
        # Update minimum brightness if the device reports it
        # Based on device output, the key is "min brightness" (with space)
        if "min brightness" in device_params:
            self._device_min = int(device_params["min brightness"])
        elif "min_brightness" in device_params:
            self._device_min = int(device_params["min_brightness"])
        elif "minBrightness" in device_params:
            self._device_min = int(device_params["minBrightness"])
        elif "minLevel" in device_params:
            self._device_min = int(device_params["minLevel"])
        elif "trim" in device_params:
            self._device_min = int(device_params["trim"])
            
        # Ensure min is within safe bounds (1-99)
        self._device_min = max(1, min(99, self._device_min))

        # Device gives 1-100
        dev_brightness = device_params.get("brightness", 100)
        
        # Scale device brightness to HA brightness
        self._attr_brightness = self._scale_device_to_ha(dev_brightness)
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
    
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and self._device_name in self.coordinator.data:
            device_params = self.coordinator.data[self._device_name]
            self._update_from_params(device_params)
            _LOGGER.debug(
                "%s updated from coordinator - Power: %s, Brightness: %s%%", 
                self._device_name, self._attr_is_on,
                int((self._attr_brightness / 255) * 100) if self._attr_brightness else 0
            )
        self.async_write_ha_state()
    
    def _scale_ha_to_device(self, ha_val: int) -> int:
        """Scale Home Assistant brightness (0-255) to Device brightness (min-100) using Gamma curve."""
        if ha_val == 0:
            return 0
            
        use_mapping = DEFAULT_ENABLE_BRIGHTNESS_MAPPING
        if not use_mapping:
             return max(1, int((ha_val / 255) * 100))
        
        min_b = self._device_min
        
        # Normalize HA value 0.0 - 1.0
        normalized_ha = (ha_val - 1) / 254.0
        
        # Apply Gamma correction
        # This makes the curve start shallow (less sensitive at low end) and get steeper
        curved_ha = normalized_ha ** BRIGHTNESS_GAMMA
        
        # Map to device range
        percentage = min_b + curved_ha * (100 - min_b)
        
        return int(percentage)

    def _scale_device_to_ha(self, dev_val: int) -> int:
        """Scale Device brightness (min-100) to Home Assistant brightness (0-255) using inverse Gamma."""
        if dev_val == 0:
            return 0
            
        use_mapping = DEFAULT_ENABLE_BRIGHTNESS_MAPPING
        if not use_mapping:
            return int((dev_val / 100) * 255)
            
        min_b = self._device_min
        
        # If device reports below its set minimum (safe fallback)
        if dev_val <= min_b:
            return 1 
            
        # Normalize device value 0.0 - 1.0
        normalized_dev = (dev_val - min_b) / (100.0 - min_b)
        
        # Apply inverse Gamma to match linear HA slider
        linear_dev = normalized_dev ** (1.0 / BRIGHTNESS_GAMMA)
        
        # Map to HA range
        ha_val = 1 + linear_dev * 254.0
        
        return int(ha_val)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        ha_brightness = kwargs.get(ATTR_BRIGHTNESS)
        
        _LOGGER.debug("Turn on %s, brightness=%s", self._device_name, ha_brightness)
        
        try:
            # Determine target brightness using mapping
            if ha_brightness is not None:
                target_pct = self._scale_ha_to_device(ha_brightness)
            else:
                # No brightness specified - use current or default to 100%
                if self._attr_brightness:
                    target_pct = self._scale_ha_to_device(self._attr_brightness)
                else:
                    target_pct = 100
                    
            # Safety clamp
            target_pct = max(1, min(100, target_pct))
            
            _LOGGER.info("Setting %s: Power=True, brightness=%s%% (HA=%s, Min=%s)", 
                         self._device_name, target_pct, ha_brightness, self._device_min)
            
            # Set brightness first
            success = await self._device.set_param(
                self._device_name,
                "brightness",
                target_pct
            )
            
            if not success:
                _LOGGER.error("Failed to set brightness for %s", self._device_name)
                return
            
            # Ensure power is on
            success = await self._device.set_param(
                self._device_name,
                "Power",
                True
            )
            
            if not success:
                _LOGGER.error("Failed to turn on power for %s", self._device_name)
                return
            
            # Update state immediately (don't wait for coordinator)
            self._attr_is_on = True
            if ha_brightness is not None:
                self._attr_brightness = ha_brightness
            else:
                # Map back the calculated target percent to HA scale
                self._attr_brightness = self._scale_device_to_ha(target_pct)
                
            self.async_write_ha_state()
            
            # Request coordinator refresh
            await self.coordinator.async_request_refresh()
            
            _LOGGER.info("Successfully turned on %s at brightness %s%%", 
                        self._device_name, target_pct)
            
        except Exception as ex:
            _LOGGER.error("Error turning on %s: %s", self._device_name, ex, exc_info=True)
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        try:
            await self._device.set_param(self._device_name, "Power", False)
            
            self._attr_is_on = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
            
        except Exception as ex:
            _LOGGER.error("Error turning off %s: %s", self._device_name, ex)
