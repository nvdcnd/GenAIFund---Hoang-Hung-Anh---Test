"""Resolve the configured LinkedIn driver by name."""
from __future__ import annotations

from config import LINKEDIN_DRIVER
from drivers.linkedin_base import LinkedInProvider
from drivers.mock_driver import MockLinkedInDriver


def get_driver(name: str = "") -> LinkedInProvider:
    key = (name or LINKEDIN_DRIVER or "mock").lower().strip()
    if key == "mock":
        return MockLinkedInDriver()
    if key == "phantombuster":
        from drivers.phantombuster_driver import PhantomBusterDriver
        return PhantomBusterDriver()
    if key == "dripify":
        from drivers.dripify_driver import DripifyDriver
        return DripifyDriver()
    if key == "tinyfish":
        from drivers.tinyfish_driver import TinyFishDriver
        return TinyFishDriver()
    raise ValueError(f"Unknown LinkedIn driver: {key!r}")
