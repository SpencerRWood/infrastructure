#!/usr/bin/env bash
set -euo pipefail

# Execute the health logic remotely so Docker output is never parsed as an
# Ansible/Jinja template.
uv run ansible -i ansible/inventory/dev infrastructure_hosts -b \
  -m script -a scripts/health-check-dev-remote.sh
