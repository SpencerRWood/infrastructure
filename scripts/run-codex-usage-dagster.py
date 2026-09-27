"""Start the infrastructure-owned Mac Dagster code location with existing dev secrets."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from urllib.parse import quote


def dagster_password(path: Path) -> str:
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o600:
        raise RuntimeError("Infrastructure dev environment must be a mode 0600 file")
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if key == "DAGSTER_POSTGRES_PASSWORD" and separator and value:
            return value
    raise RuntimeError("DAGSTER_POSTGRES_PASSWORD is missing from infrastructure dev environment")


def main() -> None:
    home = Path.home()
    repository = Path(__file__).resolve().parent.parent
    executable = repository / ".venv-codex-usage/bin/dagster"
    if not executable.is_file():
        raise RuntimeError("Install the infrastructure dev dependencies first")
    if not (home / ".dagster/dagster.yaml").is_file():
        raise RuntimeError("The existing Mac Dagster instance configuration is unavailable")
    password = dagster_password(home / ".config/wood/infrastructure/dev.env")
    host = socket.getaddrinfo(
        "swood-server.local", None, family=socket.AF_INET, type=socket.SOCK_STREAM
    )[0][4][0]
    environment = os.environ.copy()
    environment.update(
        DAGSTER_HOME=str(home / ".dagster"),
        DAGSTER_POSTGRES_HOST=host,
        DAGSTER_POSTGRES_PORT="25433",
        DAGSTER_POSTGRES_DB="dagster",
        DAGSTER_POSTGRES_USER="dagster",
        DAGSTER_POSTGRES_PASSWORD=password,
        DAGSTER_POSTGRES_URL=(
            f"postgresql://dagster:{quote(password, safe='')}@{host}:25433/dagster"
        ),
    )
    environment["PATH"] = (
        f"{repository / '.venv-codex-usage/bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    )
    os.execve(
        executable,
        [
            "dagster", "api", "grpc", "-f",
            str(repository / "compose/dagster/app/codex_definitions.py"),
            "-d", str(repository / "compose/dagster/app"),
            "--host", "0.0.0.0", "--port", "4001",
        ],
        environment,
    )


if __name__ == "__main__":
    main()
