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
from app.models.bgp import BgpProcess,BgpNeighbor,BgpVrfContext


    


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
    parse = CiscoConfParse(config_file.splitlines(), syntax="ios")

    bgp_peers = []
    for bgp_conf in parse.find_objects(r"^router bgp"):
        local_as_no = bgp_conf.text.split()[2]
        print(local_as_no) 
        router_id_obj = bgp_conf.re_search_children(r"^\s+bgp router-id")
        router_id = router_id_obj[0].text.split()[-1] if router_id_obj else None
        print(router_id)
        af_blocks = bgp_conf.re_search_children(r"^\s+address-family")
        vrf = af_blocks[0].text.split()[-1] if af_blocks else None
        print(vrf)
        




        


if __name__ == "__main__":
    file_path = Path(__file__).parent / "configuration_test.txt"
    config = file_path.read_text()

    int_data = parse_interfaces(config)

    bgp_config = parse_bgp(config)

    #for intf in int_data:
    #    print(intf.model_dump_json(indent=2))



