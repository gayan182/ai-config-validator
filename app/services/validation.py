from app.models.device import DeviceConfig


def bgp_update_source_validation(device_config: DeviceConfig) -> list[str]:
    """Validate if all iBGP peers have a valid update-source."""

    if not device_config.bgp_processes:
        return ["No BGP processes found"]

    findings = []

    for bgp_process in device_config.bgp_processes:

        # Global/default BGP neighbors
        for global_neighbor in bgp_process.global_neighbors:
            if global_neighbor.remote_as == bgp_process.local_as:
                if global_neighbor.update_source is None:
                    findings.append(
                        f"{device_config.hostname}: Global iBGP neighbor "
                        f"{global_neighbor.peer_ip} is missing update-source"
                    )

        # VRF BGP neighbors
        if not bgp_process.vrfs:
            continue

        for vrf_name, neighbors_data in bgp_process.vrfs.items():
            for neighbor in neighbors_data.neighbors:
                if neighbor.remote_as == bgp_process.local_as:
                    if neighbor.update_source is None:
                        findings.append(
                            f"{device_config.hostname}: VRF {vrf_name} iBGP neighbor "
                            f"{neighbor.peer_ip} is missing update-source"
                        )

    if not findings:
        return ["PASS: All iBGP peers have update-source configured"]

    return findings
