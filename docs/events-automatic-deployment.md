# Automatic Events Service development deployment

The owner approved Events main releases to promote and deploy the exact published
image to Infrastructure dev in the Codex conversation on 2026-10-27. Production
and unrelated service changes retain their existing approval requirements.

The chain is Events development → approved Events main merge → pinned container
release → exact `events_service_image_ref` promotion PR → Infrastructure validation
and protected main merge → Infrastructure release → Events-only deployment.

Events requires `EVENTS_SERVICE_PROMOTION_ENABLED=true` and the repository secret
`INFRASTRUCTURE_PROMOTION_TOKEN`. The credential is limited to Infrastructure with
Contents and Pull requests write, Commit statuses read, and mandatory Metadata
read. Do not reuse a broad operator credential. The existing pinned promotion
workflow checks the `infrastructure-validation` status; Infrastructure publishes
that status using the reusable validator's supported interface for trusted source
PRs only. Main pushes and forks retain read-only validation.

`deploy-events.yml` follows a successful Infrastructure Release on main. It checks
the exact released revision and unique stable release tag, then requires that the
only file change is `environments/dev.yml` and that the only semantic YAML change
is a forward Events version/digest pin. Service flags, other pins, configuration,
rollback pins, unrelated files and unpublished revisions cannot authorize deploy.
The published Infrastructure release is checked before the privileged job starts.

The root-owned runner wrapper exposes Events-only check, apply, health and guarded
rollback operations. They share the existing development deployment concurrency
gate. The Events Ansible role resolves its existing credentials, pulls the exact
digest, runs serialized packaged migrations, starts broker and notify, and waits
for readiness. Health verifies both container image references, Docker health and
both live/ready endpoints. Other infrastructure services are not selected.
Events records use a dedicated deployment state file so a scoped update cannot
overwrite the last-known-good record for the complete Infrastructure environment.

Before the first promotion, install the reviewed root-owned wrapper update using
the existing `phase6_ci` Ansible tag; this does not re-register or restart the
runner. Keep the existing last-known-good deployment metadata. Rollback selects
the previous released Events image and reads its packaged migration head without
network access. Automatic schema rollback is limited to the reviewed 0005/0006
transition. Both Events writers are stopped before the guarded schema operation
so an edit cannot race its retention checks. Migration 0006 refuses downgrade when message-edit or closed-response
evidence exists; an unreviewed schema or retained evidence stops rollback for
operator recovery instead of deleting data. Image-only rollback at schema 0006
retains schema 0006. A refused downgrade attempts to resume the current runtime
and remains a failed rollback observation. Never assume an image rollback has
reverted the database.

After deployment, inspect the real Alembic revision and `notify_message_edits`
table, both digest-pinned containers, and Events' canonical read-only runtime
verification through process-only Infisical injection. A release job or a successful
promotion PR alone does not establish deployed schema or runtime health.
