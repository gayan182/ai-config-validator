"""Tools for exposing the parsed device config to the LLM."""

import sys
from pathlib import Path

from langchain_core.tools import tool

# Running this file directly puts only `.../app/langchain_tools` on sys.path, so
# `import app` fails unless the repository root is prepended.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models.device import DeviceConfig
from app.services.validation import bgp_update_source_validation

CURRENT_DEVICE: DeviceConfig | None = None
CURRENT_DEVICES: list[dict] = []


def set_device(device: DeviceConfig) -> None:
    global CURRENT_DEVICE
    global CURRENT_DEVICES
    CURRENT_DEVICE = device
    CURRENT_DEVICES = [{"source": None, "config": device}]


def set_devices(devices: list[dict]) -> None:
    global CURRENT_DEVICE
    global CURRENT_DEVICES
    CURRENT_DEVICES = devices
    CURRENT_DEVICE = devices[0]["config"] if devices else None


def require_device() -> DeviceConfig:
    if CURRENT_DEVICE is None:
        raise ValueError("No device config loaded")
    return CURRENT_DEVICE


@tool
def get_device_config() -> dict:
    """Return all loaded parsed Cisco device configurations."""
    if CURRENT_DEVICES:
        return {
            "devices": [
                {
                    "source": loaded.get("source"),
                    "config": loaded["config"].model_dump(),
                }
                for loaded in CURRENT_DEVICES
            ]
        }

    device = require_device()
    return {"devices": [{"source": None, "config": device.model_dump()}]}


@tool
def validate_bgp_update_sources() -> dict:
    """Validate that all iBGP peers have update-source configured."""
    if CURRENT_DEVICES:
        return {
            "results": [
                {
                    "source": loaded.get("source"),
                    "hostname": loaded["config"].hostname,
                    "findings": bgp_update_source_validation(loaded["config"]),
                }
                for loaded in CURRENT_DEVICES
            ]
        }

    device = require_device()
    return {
        "results": [
            {
                "source": None,
                "hostname": device.hostname,
                "findings": bgp_update_source_validation(device),
            }
        ]
    }
