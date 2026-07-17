"""Reusable GSVpiko setup presets."""

from __future__ import annotations

from importlib import import_module

_SETUP_MODULES = {
    "ONE_GSV_ONE_SENSOR_1_3": ".setup_one_gsv_one_sensor_1_3",
    "ONE_GSV_ONE_SENSOR_1_6": ".setup_one_gsv_one_sensor_1_6",
    "ONE_GSV_TWO_SENSORS": ".setup_one_gsv_two_sensors",
    "THREE_GSVS_FOUR_SENSORS": ".setup_three_gsvs_four_sensors",
    "TWO_GSVS_ONE_SENSOR_EACH": ".setup_two_gsvs_one_sensor_each",
    "TWO_GSVS_TWO_SENSORS_EACH": ".setup_two_gsvs_two_sensors_each",
    "SETUP_TEMPLATE": ".setup_template",
}


def __getattr__(
    name: str,
):
    """Return the SETUP mapping from a configured setup module."""
    if name not in _SETUP_MODULES:
        raise AttributeError(name)

    module = import_module(_SETUP_MODULES[name], __name__)
    return getattr(module, "SETUP", getattr(module, "SETUP_TEMPLATE", None))


__all__ = tuple(_SETUP_MODULES)
