"""Configured sensor presets.

This package exposes selected sensor presets through lazy attribute access.
Only real, known sensor presets should be listed here. Generic examples belong
in sensor_template.py instead of this package initializer.
"""

from __future__ import annotations

from importlib import import_module

_SENSOR_MODULES = {
    "K3D40_24200767": ".sensor_k3d40_24200767",
    "K3D40_24200770": ".sensor_k3d40_24200770",
    "K3D40_25202514": ".sensor_k3d40_25202514",
    "K3D40_25202515": ".sensor_k3d40_25202515",
}


def __getattr__(
    name: str,
):
    """Return the SENSOR mapping from a configured sensor module."""
    if name not in _SENSOR_MODULES:
        raise AttributeError(name)

    module = import_module(_SENSOR_MODULES[name], __name__)
    return module.SENSOR


__all__ = tuple(_SENSOR_MODULES)
