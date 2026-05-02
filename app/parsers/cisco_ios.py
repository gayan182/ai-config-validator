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

from app.models.bgp import BgpNeighbor, BgpProcess, BgpVrfContext, NeighborAfPolicy
from app.models.device import DeviceConfig
from app.models.interface import Interface


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


def _interface_block_has_l3(block_lines: list[str]) -> bool:
    for raw in block_lines:
        line = raw.strip().lower()
        if line.startswith("no ip address"):
            continue
        if line.startswith("ip address"):
            return True
        if line.startswith("ipv6 address"):
            return True
    return False


_RE_IPV4_ADDR_MASK = re.compile(
    r"^ip\s+address\s+(\S+)\s+(\S+)(?:\s+(secondary))?\s*$",
    re.IGNORECASE,
)


def _parse_interface_lines(name: str, block_lines: list[str]) -> Interface | None:
    if not _interface_block_has_l3(block_lines):
        return None

    description: str | None = None
    vrf: str | None = None
    shutdown = False
    ip_addresses: list[str] = []

    for raw in block_lines:
        line = raw.strip()
        low = line.lower()
        if low.startswith("description ") and len(line) > len("description "):
            description = line.split(maxsplit=1)[1].strip()
            continue
        if low.startswith("vrf forwarding ") and len(line) > len("vrf forwarding "):
            vrf = line.split(maxsplit=2)[2].strip()
            continue
        if low.startswith("ip vrf forwarding ") and len(line) > len("ip vrf forwarding "):
            vrf = line.split(maxsplit=3)[3].strip()
            continue
        if low == "shutdown":
            shutdown = True
            continue
        if low == "no shutdown":
            shutdown = False
            continue

        m = _RE_IPV4_ADDR_MASK.match(line)
        if m:
            addr, mask, _sec = m.groups()
            try:
                iface = ipaddress.ip_interface(f"{addr}/{mask}")
                ip_addresses.append(f"{iface.ip}/{iface.network.prefixlen}")
            except ValueError:
                continue
            continue

        if low.startswith("ipv6 address "):
            rest = line[len("ipv6 address ") :].strip()
            token = rest.split()[0] if rest else ""
            if "/" in token:
                ip_addresses.append(token)
            continue

    return Interface(
        name=name,
        description=description,
        ip_addresses=ip_addresses,
        vrf=vrf,
        shutdown=shutdown,
    )


def parse_interfaces(config_text: str) -> list[Interface]:
    """Parse interface stanzas into ``Interface`` models (L3-only)."""
    interfaces: list[Interface] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_lines
        if current_name is None:
            return
        parsed = _parse_interface_lines(current_name, current_lines)
        if parsed is not None:
            interfaces.append(parsed)
        current_name = None
        current_lines = []

    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line.lower().startswith("interface "):
            flush()
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                current_name = parts[1].strip()
            continue
        if current_name is not None:
            current_lines.append(raw_line)

    flush()
    return interfaces


def _slice_router_bgp_blocks(lines: list[str]) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    i = 0
    pat = re.compile(r"^\s*router\s+bgp\s+(\d+)\s*$", re.I)
    while i < len(lines):
        m = pat.match(lines[i])
        if not m:
            i += 1
            continue
        asn = int(m.group(1))
        inner: list[str] = []
        i += 1
        while i < len(lines):
            raw = lines[i]
            if raw.strip() and not raw[0].isspace():
                break
            inner.append(raw)
            i += 1
        blocks.append((asn, inner))
    return blocks


def _neighbor_accumulate(peers: dict[str, dict[str, Any]], line: str) -> None:
    s = line.strip()

    m = re.match(r"neighbor\s+(\S+)\s+remote-as\s+(\d+)", s, re.I)
    if m:
        ip = m.group(1)
        peers.setdefault(ip, {})["remote_as"] = int(m.group(2))
        return

    m = re.match(r"neighbor\s+(\S+)\s+description\s+(.+)", s, re.I)
    if m:
        peers.setdefault(m.group(1), {})["description"] = m.group(2).strip()
        return

    m = re.match(r"neighbor\s+(\S+)\s+update-source\s+(\S+)", s, re.I)
    if m:
        peers.setdefault(m.group(1), {})["update_source"] = m.group(2)
        return

    m = re.match(r"neighbor\s+(\S+)\s+send-community(?:\s+(\S+))?", s, re.I)
    if m:
        ip = m.group(1)
        mode = m.group(2)
        val: bool | str = mode if mode else True
        peers.setdefault(ip, {})["send_community"] = val
        return

    m = re.match(r"neighbor\s+(\S+)\s+route-map\s+(\S+)\s+(in|out)", s, re.I)
    if m:
        ip, rmap, direction = m.group(1), m.group(2), m.group(3).lower()
        bucket = peers.setdefault(ip, {})
        key = "route_map_in" if direction == "in" else "route_map_out"
        bucket[key] = rmap
        return


def _finalize_neighbors(peers: dict[str, dict[str, Any]]) -> list[BgpNeighbor]:
    out: list[BgpNeighbor] = []
    for peer_ip, data in sorted(peers.items()):
        rm_in = data.get("route_map_in")
        rm_out = data.get("route_map_out")
        af_policies: dict[str, NeighborAfPolicy] = {}
        if rm_in or rm_out:
            af_policies["ipv4 unicast"] = NeighborAfPolicy(
                route_map_in=rm_in,
                route_map_out=rm_out,
            )
        out.append(
            BgpNeighbor(
                peer_ip=peer_ip,
                remote_as=data.get("remote_as"),
                description=data.get("description"),
                update_source=data.get("update_source"),
                send_community=data.get("send_community", False),
                af_policies=af_policies,
            )
        )
    return out


def _parse_router_bgp_inner(lines: list[str], local_as: int) -> BgpProcess:
    router_id: str | None = None
    global_peers: dict[str, dict[str, Any]] = defaultdict(dict)
    vrfs: dict[str, BgpVrfContext] = {}

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        low = stripped.lower()

        if low.startswith("bgp router-id ") and len(stripped.split()) >= 3:
            router_id = stripped.split()[2].strip()
            i += 1
            continue

        m_af_vrf = re.match(r"address-family\s+ipv4\s+vrf\s+(\S+)", stripped, re.I)
        if m_af_vrf:
            vrf_name = m_af_vrf.group(1)
            peers: dict[str, dict[str, Any]] = defaultdict(dict)
            i += 1
            while i < len(lines):
                inner = lines[i].strip()
                if re.match(r"exit-address-family\s*$", inner, re.I):
                    i += 1
                    break
                _neighbor_accumulate(peers, inner)
                i += 1
            vrfs[vrf_name] = BgpVrfContext(
                name=vrf_name,
                neighbors=_finalize_neighbors(dict(peers)),
            )
            continue

        m_af4 = re.match(r"address-family\s+ipv4\s*$", stripped, re.I)
        if m_af4:
            i += 1
            while i < len(lines):
                inner = lines[i].strip()
                if re.match(r"exit-address-family\s*$", inner, re.I):
                    i += 1
                    break
                _neighbor_accumulate(global_peers, inner)
                i += 1
            continue

        if re.match(r"address-family\s+", stripped, re.I):
            i += 1
            while i < len(lines):
                inner = lines[i].strip()
                if re.match(r"exit-address-family\s*$", inner, re.I):
                    i += 1
                    break
                i += 1
            continue

        _neighbor_accumulate(global_peers, stripped)
        i += 1

    return BgpProcess(
        local_as=local_as,
        router_id=router_id,
        global_neighbors=_finalize_neighbors(dict(global_peers)),
        vrfs=vrfs,
    )


def parse_bgp_processes(config_text: str) -> list[BgpProcess]:
    lines = config_text.splitlines()
    return [_parse_router_bgp_inner(inner, asn) for asn, inner in _slice_router_bgp_blocks(lines)]


def parse_interface_l3(config_text: str) -> list[str]:
    """Names of interfaces that have L3 addressing (same selection as ``parse_interfaces``)."""
    return [i.name for i in parse_interfaces(config_text)]


def parse_cisco_ios(config_text: str) -> DeviceConfig:
    """Parse a Cisco IOS / IOS-XE style configuration into ``DeviceConfig``."""
    return DeviceConfig(
        hostname=parse_hostname(config_text),
        interfaces=parse_interfaces(config_text),
        bgp_processes=parse_bgp_processes(config_text),
    )


if __name__ == "__main__":
    file_path = Path(__file__).parent / "configuration_test.txt"
    config = file_path.read_text()
    dc = parse_cisco_ios(config)
    print(dc.model_dump_json(indent=2))
