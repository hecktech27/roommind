"""Temperature unit conversion utilities for RoomMind."""

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant


def ha_temp_to_celsius(hass: HomeAssistant, value: float) -> float:
    """Convert temperature from HA unit system to Celsius."""
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        return (value - 32) * 5 / 9
    return value


def celsius_to_ha_temp(hass: HomeAssistant, value: float) -> float:
    """Convert temperature from Celsius to HA unit system."""
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        return value * 9 / 5 + 32
    return value


def celsius_delta_to_ha(hass: HomeAssistant, delta: float) -> float:
    """Convert a temperature delta from Celsius to HA unit system (factor only)."""
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        return delta * 9 / 5
    return delta


def ha_temp_unit_str(hass: HomeAssistant) -> str:
    """Return '°C' or '°F' based on HA config."""
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        return "°F"
    return "°C"
