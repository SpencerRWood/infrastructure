#!/usr/bin/env bash
set -euo pipefail

# Execute the health logic through the system Ansible installed on the
# control host so the root-owned wrapper does not depend on the Actions PATH.
/usr/bin/ansible --connection=local -i ansible/inventory/dev infrastructure_hosts -b \
  -m script -a scripts/health-check-dev-remote.sh
