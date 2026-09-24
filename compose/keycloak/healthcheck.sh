#!/usr/bin/env bash
set -euo pipefail

# The application port may open before migrations and initialization finish.
exec 3<>/dev/tcp/127.0.0.1/9000
printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
IFS= read -r response <&3
[[ $response == $'HTTP/1.1 200 OK\r' ]]
