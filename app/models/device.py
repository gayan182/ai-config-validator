from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .bgp import BgpNeighbor, BgpProcess
    from .interface import Interface
#    from .policy import CommunityList, PrefixList, RouteMap


class DeviceConfig(BaseModel):
    """Root structured model for a single device configuration."""

    hostname: str | None = None

    interfaces: list["Interface"] = Field(default_factory=list)

    # Multiple BGP processes may exist (for different local ASNs).
    bgp_processes: list["BgpProcess"] = Field(default_factory=list)

    #route_maps: dict [str, "RouteMap"] = Field(default_factory=dict)
    #prefix_lists: dict[str, "PrefixList"] = Field(default_factory=dict)
    #community_lists: dict[str, "CommunityList"] = Field(default_factory=dict)

    # Optional provider alias dictionary, e.g. {"telstra": ["as4637", "telstra-ip"]}.
    provider_aliases: dict[str, list[str]] = Field(default_factory=dict)

    def bgp_processes_for_vrf(self, vrf: str) -> list["BgpProcess"]:
        """Return BGP processes that contain the requested VRF context."""
        vrf_norm = vrf.strip().lower()
        matches: list["BgpProcess"] = []

        for process in self.bgp_processes:
            vrfs = getattr(process, "vrfs", {})
            if any(name.strip().lower() == vrf_norm for name in vrfs.keys()):
                matches.append(process)

        return matches

    def all_bgp_neighbors(self, vrf: str | None = None) -> list["BgpNeighbor"]:
        """Return all neighbors, optionally constrained to a specific VRF."""
        processes = self.bgp_processes if vrf is None else self.bgp_processes_for_vrf(vrf)
        neighbors: list["BgpNeighbor"] = []

        for process in processes:
            # Process-level (global/default) neighbors.
            neighbors.extend(getattr(process, "global_neighbors", []))

            # Per-VRF neighbors.
            for context_name, context in getattr(process, "vrfs", {}).items():
                if vrf is None or context_name.strip().lower() == vrf.strip().lower():
                    neighbors.extend(getattr(context, "neighbors", []))

        return neighbors


from .bgp import BgpNeighbor, BgpProcess  # noqa: E402
from .interface import Interface  # noqa: E402

DeviceConfig.model_rebuild()
