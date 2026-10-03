# Events Service deployment

`compose/events-service/compose.yml` is the platform-owned runtime definition.
Both applications use one released Events image pinned by digest. They join the
environment's external PostgreSQL and proxy networks; stable `wood-broker` and
`wood-notify` aliases also let Dagster and machine producers reach the private API.
Host-loopback ports 18000/18001 permit health checks and SSH forwarding.

The role resolves separate broker and notify secret files, validates Compose,
pulls the exact pin, runs the one-shot migration image, and starts both services
with `--wait`. Application migrations serialize with a transaction advisory lock
and a 60-second lock timeout. A failed migration prevents application startup.
Migrations and health probes never print database credentials.

Before the first deployment:

1. Finish the existing application database provisioning work; verify the dedicated
   `events_service` role and its isolation. The canonical URL is in dev
   `/events-service`, not a new password secret. Infrastructure's current separate
   PostgreSQL provisioning changes are a prerequisite, outside this isolated diff.
2. Install the protected bootstrap identity at
   `/srv/infrastructure/secrets/bootstrap/infisical-<environment>.json`, root:root
   mode 0600. The existing dev identity must have read access to `/events-service`
   in project `7ea10433-2eeb-4c57-95a9-b793dd40c7a4`. Production requires its own
   verified environment/project mapping; do not reuse dev state or identity.
3. Add the required Telegram event policy and workflow credential scopes through
   the secret owner. Review the role's required-key lists. To enable ntfy or SMTP,
   add the complete provider key set to `events_service_optional_provider_keys`;
   their absence is supported by the default Telegram-only contract. Add
   `TELEGRAM_ALLOWED_USER_IDS` there when restricting responders.
4. Verify host GHCR authentication can pull the private image. Bootstrap
   `events_service_image_ref` using the actual released tag and validated digest;
   set `services.events_service: true` in a reviewed environment change. Empty pins
   are deliberate and fail if the component is enabled.
5. Review the proposed `dev-events-service.woodhost.cloud` DNS and public HTTPS
   exposure. Edge Caddy retains public 443 and forwards only POST
   `/v1/telegram/callbacks` to Infrastructure Caddy. All other paths return 404;
   producer APIs remain private. The callback bypasses the administrator IP
   allowlist so Telegram can reach it, and the application authenticates callbacks
   with the secret header, signature, chat, message and optional user allowlist.

Use the existing immutable Infrastructure release deployment, not an application
SSH deployment or a second runner. `scripts/health-check-dev-remote.sh` checks both
running application image references and live/ready endpoints once the protected
Compose input exists. The application-owned `deployed-runtime` Wood check separately
checks the real schema, public route restrictions and Telegram webhook configuration.
It does not prove the deployed digest; retain the platform image observations too.

After a compatible prior successful Events deployment exists, the existing shared
`deploy-ansible.yml` path reapplies the previous successful Infrastructure release
once on apply/health failure. Keep the previous immutable image available. Exercise
that recovery contract before accepting #461. Never automatically downgrade the
database or restore old database state over accepted events/responses.

The first introduction has no previous Events runtime to restore. A rollback to a
release predating this role cannot remove newly created resources. Treat first
deployment as attended: stop `wood-broker`/`wood-notify`, remove the newly introduced
callback route through its owner, and preserve PostgreSQL state and protected inputs
if recovery requires withdrawing the service. Review that concrete procedure before
execution. Later rollback is permitted only when the previous application supports
the current schema; otherwise stop and investigate rather than claim recovery.

Dev and production are both disabled in this implementation diff until reviewed
bootstrap. Production is not automatically promoted and has no selected host here.
The app's downstream promotion job is enabled only after a valid initial pin and
scoped promotion token exist. It updates the pin only, so selection and secret or
network changes remain separately reviewed Infrastructure changes.
