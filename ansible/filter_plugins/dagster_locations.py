"""Validate declarations for externally published Dagster code servers."""

import re

from ansible.errors import AnsibleFilterError


RESERVED_NAMES = {
    "wood-data-platform", "synthetic_website_poc", "infrastructure_codex_usage"
}
RESERVED_SERVICES = {
    "dagster-user-code", "dagster-codex-usage", "dagster-webserver", "dagster-daemon"
}
IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
SERVICE = re.compile(r"[a-z][a-z0-9-]*\Z")


def valid_dagster_locations(locations, runtime_environments):
    if not isinstance(locations, list) or not isinstance(runtime_environments, dict):
        raise AnsibleFilterError("Dagster locations and runtime environments must be collections")
    names = set()
    services = set()
    for location in locations:
        if not isinstance(location, dict) or not {"name", "service_name", "image", "port"} <= location.keys():
            raise AnsibleFilterError("Dagster location requires name, service_name, image, and port")
        if set(location) - {"name", "service_name", "image", "port", "runtime_env", "capabilities"}:
            raise AnsibleFilterError("Unknown Dagster location field")
        name = location["name"]
        service = location["service_name"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names or name in RESERVED_NAMES:
            raise AnsibleFilterError("Invalid or duplicate Dagster location name")
        if not isinstance(service, str) or not SERVICE.fullmatch(service) or service in services or service in RESERVED_SERVICES:
            raise AnsibleFilterError("Invalid or duplicate Dagster service name")
        if not isinstance(location["image"], str) or not IMAGE.fullmatch(location["image"]):
            raise AnsibleFilterError("External Dagster image must be digest pinned")
        port = location["port"]
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise AnsibleFilterError("Invalid Dagster gRPC port")
        if "runtime_env" in location and location["runtime_env"] not in runtime_environments:
            raise AnsibleFilterError("Unknown Dagster application runtime environment")
        capabilities = location.get("capabilities", {})
        if not isinstance(capabilities, dict) or set(capabilities) - {"outbound_network"} or type(capabilities.get("outbound_network", False)) is not bool:
            raise AnsibleFilterError("Invalid Dagster capability")
        names.add(name)
        services.add(service)
    return True


def referenced_dagster_runtime_environments(runtime_environments, locations):
    """Select only runtime mappings actually requested by external locations."""
    if not isinstance(runtime_environments, dict) or not isinstance(locations, list):
        return {}
    names = {location['runtime_env'] for location in locations
             if isinstance(location, dict)
             and isinstance(location.get('runtime_env'), str)
             and location['runtime_env'] in runtime_environments}
    return {name: runtime_environments[name] for name in sorted(names)}


class FilterModule:
    def filters(self):
        return {
            "valid_dagster_locations": valid_dagster_locations,
            "referenced_dagster_runtime_environments": referenced_dagster_runtime_environments,
        }
