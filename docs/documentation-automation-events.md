# Documentation Automation approval access

Use the existing wood-notify service, bot, callback and request responder policy.
The dedicated `documentation-automation` producer has only `notifications:read`
and `notifications:write`. Store its single random token in Infisical dev
`/documentation-automation/DOCUMENTATION_AUTOMATION_EVENTS_TOKEN` and the matching
entry in `/events-service/WES_PRODUCER_CREDENTIALS`; preserve every other entry.
The existing Telegram routing and private owner identity are reused.

`https://dev-events-api.woodhost.cloud` is DNS-only, pointing to the existing LAN
address. Edge Caddy obtains and renews its certificate through the existing
Cloudflare DNS challenge. Its route accepts GET/POST notification paths only
from actual LAN/VPN TCP peers, independently of forwarded headers. Other peers
receive403. The same-host private proxy forwards only notification paths to
wood-notify. The public callback hostname and its restrictions are unchanged.

`ansible/playbooks/documentation-automation-events.yml` is deliberately scoped:
require dev/apply/approval reference and all three observed images plus the exact
released notifier reference. Inject both credential values only into the Ansible
process. All secret handling is no_log with pipelining; never pass values in CLI
arguments, write them in Git or retain secret-bearing diagnostics. Only one line
of the existing protected notifier input changes. Reconcile that one service with
no dependencies/builds/pulls and require health; retain its immutable image. Hot
reload the two existing proxies. Do not invoke general dev.yml, migrations or
PostgreSQL, or activate Dagster/worker/schedules.

Candidate Caddy configurations are validated by the running pinned binaries
before mutation. Existing route conflicts are rejected. Apply failure removes
only newly introduced fragments, reloads the former route set and restores the
prior credential line/notifier configuration. Infisical entries and the DNS record
are retained for attended diagnosis rather than blindly deleted or recreated.
The credential/DNS provisioner must create-or-verify its exact target and reject
conflicting values. After an uncertain API result, read back before retrying.

Verify real certificate validation and authenticated, source-scoped API reads from
the MacBook; verify missing credentials fail and forwarded-header spoofing from an
untrusted peer gets403. Compare every unrelated container ID and notifier image,
and repeat the playbook to establish zero changes. Keep the Events credential,
body and Authorization headers out of proxy access logs. Once verified, the
existing one-shot approval job sends the exact PR/SHA request. Only the actual
owner's Telegram Approve & Merge response authorizes protected merging.
