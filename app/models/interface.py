from __future__ import annotations

from pydantic import BaseModel, Field


class Interface(BaseModel):
    """Canonical L3 interface model."""

    name: str = Field(..., description="Interface name, e.g. GigabitEthernet0/0")
    description: str | None = Field(None, description="Operator description")
    ip_addresses: list[str] = Field(
        default_factory=list, description="One or more interface IPs in CIDR format"
    )
    vrf: str | None = Field(None, description="VRF name")
    shutdown: bool = Field(False, description="Administrative shutdown state")
