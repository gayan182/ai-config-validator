from __future__ import annotations

import ipaddress
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Running `python app/parsers/cisco_ios.py` puts only `.../app/parsers` on sys.path, so
# `import app` fails unless the repository root is prepended.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ciscoconfparse import CiscoConfParse
from app.models.interface import Interface
from app.models.bgp import BgpProcess, BgpNeighbor, BgpVrfContext, NeighborAfPolicy


    


def parse_hostname(config_text: str) -> str | None:
    """Return hostname from a Cisco-style running config.
    Example line: 'hostname R1'"""
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line.lower().startswith("hostname "):
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return None

def parse_interfaces(config_file: str) -> list[Interface]:
    parse = CiscoConfParse(config_file.splitlines(), syntax="ios")

    interfaces = []

    for intf in parse.find_objects(r"^interface"):
        name = intf.text.split()[1]

        # --- description ---
        desc_obj = intf.re_search_children(r"^\s+description")
        description = desc_obj[0].text.split(" ", 1)[1] if desc_obj else None

        # --- VRF ---
        vrf_obj = intf.re_search_children(r"^\s+vrf forwarding")
        vrf = vrf_obj[0].text.split()[-1] if vrf_obj else None

        # --- shutdown ---
        shutdown = bool(intf.re_search_children(r"^\s+shutdown"))

        # --- IP addresses ---
        ip_addresses = []
        ip_objs = intf.re_search_children(r"^\s+ip address")

        for ip_line in ip_objs:
            parts = ip_line.text.split()
            if len(parts) >= 4:
                ip = parts[2]
                mask = parts[3]

                # Convert to CIDR
                import ipaddress
                cidr = str(ipaddress.IPv4Network(f"{ip}/{mask}", strict=False))
                ip_addresses.append(cidr)

        # --- create model ---
        interface = Interface(
            name=name,
            description=description,
            ip_addresses=ip_addresses,
            vrf=vrf,
            shutdown=shutdown
        )

        interfaces.append(interface)

    return interfaces

def parse_bgp(config_file: str) -> list[BgpProcess]:
    """Parse all BGP processes from Cisco IOS config text.

    Keep this function as the coordinator:
    - find each ``router bgp`` block
    - parse process-level values like ASN and router-id
    - parse global and VRF address-family neighbor contexts
    - build and return nested Pydantic ``BgpProcess`` models
    """
    parse = CiscoConfParse(config_file.splitlines(), syntax="ios")

    bgp_processes: list[BgpProcess] = []

    for bgp_conf in parse.find_objects(r"^router bgp"):
        local_as = parse_local_as(bgp_conf)
        router_id = parse_bgp_router_id(bgp_conf)

        global_peers: dict[str, dict[str, Any]] = {}
        vrfs: dict[str, BgpVrfContext] = {}

        af_blocks = bgp_conf.re_search_children(r"^\s+address-family")
        for af_block in af_blocks:
            af_name = parse_address_family_name(af_block)
            vrf_name = parse_address_family_vrf(af_block)
            peers = collect_bgp_neighbors(af_block.children)

            if vrf_name:
                vrfs[vrf_name] = BgpVrfContext(
                    name=vrf_name,
                    neighbors=build_bgp_neighbors(peers, af_name),
                )
            else:
                global_peers.update(peers)

        bgp_processes.append(
            BgpProcess(
                local_as=local_as,
                router_id=router_id,
                global_neighbors=build_bgp_neighbors(global_peers),
                vrfs=vrfs,
            )
        )

    return bgp_processes


def parse_local_as(bgp_conf: Any) -> int:
    """Return the ASN from a line like ``router bgp 65506``."""
    return int(bgp_conf.text.split()[2])

def parse_bgp_router_id(bgp_conf: Any) -> str | None:
    """Return the BGP router-id from a BGP process block, if present."""
    router_id_obj = bgp_conf.re_search_children(r"^\s+bgp router-id")
    return router_id_obj[0].text.split()[-1] if router_id_obj else None


def parse_address_family_name(af_block: Any) -> str:
    """Return a normalized address-family name for policy keys.

    Examples:
    - "address-family ipv4" -> "ipv4 unicast"
    - "address-family ipv4 vrf vrf-enx-edge" -> "ipv4 unicast"
    """
    line = af_block.text.strip().lower()

    if line.startswith("address-family ipv4"):
        return "ipv4 unicast"

    if line.startswith("address-family ipv6"):
        return "ipv6 unicast"

    return line.replace("address-family ", "")




def parse_address_family_vrf(af_block: Any) -> str | None:
    """Return the VRF name from an address-family block, if it is VRF-scoped."""
    parts = af_block.text.strip().split()
    for idx, part in enumerate(parts):
        if part.lower() == "vrf" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def collect_bgp_neighbors(lines: list[Any]) -> dict[str, dict[str, Any]]:
    """Collect raw neighbor settings grouped by peer IP.

    Expected temporary shape:
    {
        "10.0.2.130": {
            "remote_as": 65530,
            "description": "...",
            "update_source": "Loopback0",
            "send_community": True,
            "route_map_in": "RM-IN",
            "route_map_out": "RM-OUT",
        }
    }
    """
    peers: dict[str, dict[str, Any]] = {}

    for line_obj in lines:
        line = line_obj.text.strip()
        collect_bgp_neighbor_line(peers, line)

    return peers


def collect_bgp_neighbor_line(peers: dict[str, dict[str, Any]], line: str) -> None:
    """Parse one neighbor line and update the peer dictionary in-place."""
    m = re.match(r"neighbor\s+(\S+)\s+remote-as\s+(\d+)", line, re.I)
    if m:
        peers.setdefault(m.group(1), {})["remote_as"] = int(m.group(2))
        return

    m = re.match(r"neighbor\s+(\S+)\s+description\s+(.+)", line, re.I)
    if m:
        peers.setdefault(m.group(1), {})["description"] = m.group(2).strip()
        return

    m = re.match(r"neighbor\s+(\S+)\s+update-source\s+(\S+)", line, re.I)
    if m:
        peers.setdefault(m.group(1), {})["update_source"] = m.group(2)
        return

    m = re.match(r"neighbor\s+(\S+)\s+send-community(?:\s+(\S+))?", line, re.I)
    if m:
        mode = m.group(2)
        peers.setdefault(m.group(1), {})["send_community"] = mode if mode else True
        return

    m = re.match(r"neighbor\s+(\S+)\s+route-map\s+(\S+)\s+(in|out)", line, re.I)
    if m:
        direction = m.group(3).lower()
        key = "route_map_in" if direction == "in" else "route_map_out"
        peers.setdefault(m.group(1), {})[key] = m.group(2)
        return


def build_bgp_neighbors(
    peers: dict[str, dict[str, Any]],
    af_name: str = "ipv4 unicast",
) -> list[BgpNeighbor]:
    """Convert collected peer dictionaries into nested Pydantic models."""
    neighbors: list[BgpNeighbor] = []

    for peer_ip, peer_data in peers.items():
        af_policies = build_neighbor_af_policies(peer_data, af_name)

        neighbors.append(
            BgpNeighbor(
                peer_ip=peer_ip,
                remote_as=peer_data.get("remote_as"),
                description=peer_data.get("description"),
                update_source=peer_data.get("update_source"),
                send_community=peer_data.get("send_community", False),
                af_policies=af_policies,
            )
        )

    return neighbors


def build_neighbor_af_policies(
    peer_data: dict[str, Any],
    af_name: str,
) -> dict[str, NeighborAfPolicy]:
    """Build per-address-family policy objects for one neighbor."""
    policies: dict[str, NeighborAfPolicy] = {}

    route_map_in = peer_data.get("route_map_in")
    route_map_out = peer_data.get("route_map_out")
    if route_map_in or route_map_out:
        policies[af_name] = NeighborAfPolicy(
            route_map_in=route_map_in,
            route_map_out=route_map_out,
        )

    return policies


if __name__ == "__main__":
    file_path = Path(__file__).parent / "configuration_test.txt"
    config = file_path.read_text()

    int_data = parse_interfaces(config)

    bgp_config = parse_bgp(config)

    for bgp in bgp_config:
        print(bgp.model_dump_json(indent=2))
