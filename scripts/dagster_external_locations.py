"""Generated external Dagster ownership metadata shared by lifecycle commands."""
import json
import os
import pathlib
import re
import tempfile


CURRENT = pathlib.Path('/etc/infrastructure/dagster-external-locations.json')
OWNED = frozenset({
    'dagster-user-code', 'dagster-codex-usage', 'dagster-webserver', 'dagster-daemon',
})
SERVICE = re.compile(r'[a-z][a-z0-9-]*\Z')
LOCATION = re.compile(r'[a-z][a-z0-9_]*\Z')


def locations_from_json(value):
    if not isinstance(value, list):
        raise ValueError('external Dagster metadata must be a list')
    result = {}
    names = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('invalid external Dagster location metadata')
        service, name, port = item.get('service_name'), item.get('name'), item.get('port')
        if (not isinstance(service, str) or not SERVICE.fullmatch(service)
                or not isinstance(name, str) or not LOCATION.fullmatch(name)
                or not isinstance(port, int) or isinstance(port, bool)
                or not 1 <= port <= 65535 or service in OWNED
                or service in result or name in names):
            raise ValueError('invalid or infrastructure-owned external Dagster service')
        result[service] = item
        names.add(name)
    return result


def read_locations(path=CURRENT, *, missing_ok=False):
    if missing_ok and not path.exists():
        return {}
    return locations_from_json(json.loads(path.read_text()))


def obsolete_services(previous, desired, desired_compose_services=()):
    # Inputs are generated from the canonical declaration, never inferred from
    # container characteristics. The explicit exclusion guards corrupted data.
    return set(previous) - set(desired) - set(desired_compose_services) - OWNED


def publish_locations(path, locations):
    """Atomically record the ownership set after successful reconciliation."""
    content = (json.dumps(list(locations), indent=2) + '\n').encode()
    fd, tmp = tempfile.mkstemp(prefix='.dagster-locations-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
