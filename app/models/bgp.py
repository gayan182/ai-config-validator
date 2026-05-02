from __future__ import annotations

from pydantic import BaseModel, Field


class NeighborAfPolicy(BaseModel):
    """Per-address-family policy for a neighbor session."""

    route_map_in: str | None = Field(None, description="Inbound route-map name")
    route_map_out: str | None = Field(None, description="Outbound route-map name")
    prefix_list_in: str | None = Field(None, description="Inbound prefix-list name")
    prefix_list_out: str | None = Field(None, description="Outbound prefix-list name")


class BgpNeighbor(BaseModel):
    """Canonical BGP neighbor model."""

    peer_ip: str = Field(..., description="Neighbor IP address")
    remote_as: int | None = Field(None, description="Remote AS number")
    description: str | None = Field(None, description="Neighbor description")
    update_source: str | None = Field(None, description="Neighbor update-source interface")
    send_community: bool | str = Field(
        False, description="send-community state (bool or standard/extended/both)"
    )
    af_policies: dict[str, NeighborAfPolicy] = Field(
        default_factory=dict, description='AF policies keyed by name, e.g. "ipv4 unicast"'
    )


class BgpVrfContext(BaseModel):
    """BGP data under a specific VRF context."""

    name: str = Field(..., description="VRF name")
    neighbors: list[BgpNeighbor] = Field(default_factory=list, description="VRF neighbors")


class BgpProcess(BaseModel):
    """Top-level BGP process (typically one per local ASN)."""

    local_as: int = Field(..., description="Local BGP AS number")
    router_id: str | None = Field(None, description="BGP router-id")
    global_neighbors: list[BgpNeighbor] = Field(
        default_factory=list, description="Neighbors in global/default context"
    )
    vrfs: dict[str, BgpVrfContext] = Field(
        default_factory=dict, description="VRF contexts keyed by VRF name"
    )