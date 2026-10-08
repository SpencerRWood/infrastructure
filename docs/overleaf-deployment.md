# Overleaf and CLSI development deployment

Story #431 replaces the homelab Overleaf stack with fresh infrastructure dev
state. No saved documents, MongoDB/Redis state, or compiler cache is migrated.
Production remains disabled. This is a trusted internal Community Edition
deployment: it does not isolate mutually untrusted LaTeX authors. Neither runtime
mounts the Docker socket; the standalone compiler is non-root with resource limits.
The 16 GiB dev host runs other workloads: editor/compiler memory limits are
1536/1024 MiB, MongoDB/Redis limits are 512/128 MiB, and CLSI admits at most two
concurrent compiles. The retired suite is stopped before the replacement starts.
Container liveness uses CLSI's `/status`; authenticated compilation establishes
readiness. The optional upstream `/health_check` requires its own shell-command
self-test and is not used here. CLSI's default two-day process-age limit is
disabled for the persistent Compose service.

## Services and ingress

`compose/overleaf/` builds the digest-pinned Overleaf 6.1.0 base with the frozen
TeX Live 2025 final repository and full package scheme. Both the editor and the
standalone CLSI use that recipe, tagged by its SHA256. Downloads occur during
the image build, never at container startup. Upgrades require a reviewed base
digest/TeX repository change, a fresh build, compilation verification and a
compatible MongoDB upgrade plan. The derived image is local infrastructure
configuration, following the existing Dagster build convention.

MongoDB is temporarily held at the verified 8.0.16 version and Redis on 7.4;
Renovate permits MongoDB digest updates and Redis patch/digest updates for this
component only. Moving either dependency outside these limits requires a
separate compatibility review. The MongoDB hold also defers newer security
patches, so revisit it after validating a compatible image/kernel combination.
On 2026-10-08 the pinned MongoDB 9.0.2 binary refused to start on Beelink's
`7.0.0-34-generic` kernel, reporting the Linux 6.19+ incompatibility tracked in
[SERVER-121912](https://jira.mongodb.org/browse/SERVER-121912). Release v0.27.5
failed and rolled back to v0.27.3. MongoDB 8.0.16 and Redis 7.4.11 are the
verified restored versions; no MongoDB 9 data migration was performed. Renovate
subsequently automerged MongoDB 8.0.32, whose isolated binary probe produced the
same kernel incompatibility, motivating the exact-version hold.
Before changing component directories or persistent state, the role now runs
the selected MongoDB binary's `--version` in a disposable, network-isolated
container with no host mounts. A kernel guard failure stops deployment with a
visible diagnostic. This preflight does not prove data-format compatibility
or application readiness; the normal startup and compilation probes still apply.

`overleaf.woodhost.cloud` routes to the editor. `clsi.woodhost.cloud` routes to
a dedicated Caddy gateway. The existing edge Caddy supplies TLS and administrator
IP allowlisting; it forwards to the independent infrastructure listener on
`192.168.1.21:8080`. The networks remain separate. The gateway authenticates
every compiler request, health check and output download with HTTP Basic auth,
then removes the credential before forwarding. No container publishes host
ports. MongoDB and Redis share an internal database network; CLSI shares only
an internal network with its gateway. Its control/load ports are not routed.

## Required secrets

Provision the Infrastructure Dev Infisical folders before deployment:

| Folder | Keys | Consumer |
| --- | --- | --- |
| `/overleaf` | `OVERLEAF_INVITE_TOKEN_SECRET` | Editor only |
| `/clsi` | `CLSI_USERNAME`, `CLSI_PASSWORD_HASH` | Gateway only |
| `/clsi` | `CLSI_USERNAME`, `CLSI_PASSWORD` | Root-only verification input |

Use a distinct strong compiler password and its matching Caddy bcrypt hash.
Generate/hash in a protected process without command-line plaintext or logs.
The password/hash must match; the authenticated smoke test detects drift.
Resolved files are root-owned mode `0600`; bootstrap credentials never enter
containers. Clients must use HTTPS, Basic auth on every request (including
output downloads), and validate certificates. The public URLs are dev-backed
as requested by this Story; no production host or production services are enabled.
Docker Compose 2.30 or later is required for raw environment-file parsing, which
preserves bcrypt dollar signs and secret values without interpolation.

## Attended fresh-start cutover

Deliver the homelab removal first so later homelab releases cannot recreate the
retired stack. Before applying infrastructure routes, run the separately reviewed
one-time removal from the infrastructure release checkout:

```sh
ANSIBLE_CONFIG=ansible/ansible.cfg uv run ansible-playbook \
  -i ansible/inventory/dev ansible/playbooks/remove-homelab-overleaf.yml \
  -e overleaf_discard_homelab_state=true
```

This playbook rejects unrelated services/storage in Compose project `docs`,
removes only the discovered Overleaf/Mongo/Redis/init containers, Mongo config
volumes and the initializer's anonymous data volume, deletes the three retired data directories and Compose payloads, and
removes the old `docs.caddy` route. It never deletes replacement infrastructure
state or runs during normal deploy/rollback. Removing containers also releases
their endpoints; the empty retired Docker network can be left for Docker to
manage. The old documents are deliberately unrecoverable; no old-data rollback
or backup is part of this explicitly requested fresh start.

Then deploy the infrastructure dev release through its standard Ansible workflow.
The role creates `/srv/infrastructure/state/overleaf-dev/{editor,mongo,mongo-config,
redis,compiler}`; this fresh namespace does not reuse homelab paths.
The editor mount root is private to its `www-data` runtime (UID/GID 33); its
parent remains root-only on the host. Root ownership with mode `0700` on the
mounted editor directory prevents web services from accessing their data.
MongoDB is a single-node replica set and initialization waits for a writable primary. Redis
uses AOF persistence. Initial image construction installs the full TeX distribution
and may take substantially longer than container readiness (bounded to 180s).
Database mount roots remain private to their image runtime accounts: MongoDB
uses UID/GID 999/999 and Redis uses 999/1000. Ordinary deployments preserve these
owners rather than resetting live database directories to root, which causes
MongoDB permission failures and process termination before Compose can converge.
The role manages only the mount roots; it does not recursively rewrite database
files or remove state.
Create the initial editor administrator using Overleaf's supported admin-user
script in the new editor container. Self-signup and anonymous editing are disabled.

## Independent verification, backups and rollback

```sh
sudo /usr/local/sbin/verify-infrastructure-overleaf \
  --credentials /srv/infrastructure/secrets/runtime/clsi-verification.env
```

Run this from the intended wood-reports execution environment with a protected
credential input and allowlisted network access as well as on Beelink. It validates
the editor TLS route, anonymous compiler denial, authenticated health, a real
LuaLaTeX compile with required font/table packages, authenticated PDF download
from the same HTTPS origin and cleanup of its unique test project. The standard
dev release health script also checks the selected image and healthy editor/CLSI
containers before running the probe. No report-domain client or PDF acceptance
rules are introduced; those remain in wood-reports Stories #432–#435.

The probe identifies every request as `Wood-Infrastructure-Verification/1.0`,
including the editor check and project cleanup. The default Python urllib user
agent is rejected by the edge browser-integrity check (HTTP 403, error 1010).
The explicit client identity preserves TLS, IP allowlisting and compiler
authentication; it requires no ingress-policy exception or browser interaction.

Future dev documents require coordinated backups: stop editor and compiler writes,
take a MongoDB dump and copy editor/Redis state together, encrypt the backup and
store it off-host, then restart and verify. Compiler state is disposable. Restore
to an isolated dev namespace and verify a document compile before treating a
backup as usable. Retain daily backups for 7 days and weekly backups for 4 weeks;
schedule and prove this before relying on the new service for retained documents.

Standard release rollback reapplies the previous configuration; it cannot restore
discarded homelab documents or reverse MongoDB schema changes. For a failed fresh
cutover, stop the replacement stack and remove/disable its two new edge routes,
validate/reload edge Caddy, and diagnose before retrying. Preserve new state on
ordinary rollback. Never enable the retired homelab payload as a fallback.
