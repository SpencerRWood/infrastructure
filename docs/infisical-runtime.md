# Infrastructure Dev runtime secrets

`Infrastructure Dev` is a separate Infisical Secrets Management project with a
`dev` environment and service paths `/dagster`, `/keycloak`, `/openwebui`, and
`/portfolio-website`. `dev-deployer` uses Universal Auth, organization
`no-access`, and the built-in project `Viewer` role. Viewer read access is
intentionally project-wide within this deployment trust domain. The identity
has no Homelab project membership; `homelab-deployer` has no Infrastructure Dev
membership.

The deployer bootstrap lives outside Git at
`/srv/infrastructure/secrets/bootstrap/infisical-dev.json`, root:root mode
`0600` under root:root mode `0700` directories. It contains only the API URL,
project ID, client ID, and client secret. Application containers do not receive
these values.

`resolve-infrastructure-infisical-env` ports the Homelab generic resolver: it
validates the requested environment, path, keys, and Infisical project; writes
only required keys to a root-owned mode `0600` file under
`/srv/infrastructure/secrets/runtime`; replaces the file atomically; and leaves
the previous file untouched on any failure. Errors and Compose output are
sanitized. `deploy-infrastructure-infisical-service` resolves before Compose
validation and service reconciliation. The
`infrastructure-infisical@.service` template retries when Infisical is not yet
available at boot.

The service definitions in `environments/dev.yml` identify required keys,
Compose services, runtime paths, and rollback sources. Dagster's external
application code locations may reference separate runtime environments in the
same manifest; the Dagster service reconciler resolves these files before
starting the code servers. Deploy one service with
`ansible/playbooks/dev-infisical.yml` and
`infrastructure_infisical_selected_services` set to its name. Select only one
service at a time. The playbook retains the previous deployed Compose file
before the first switch. Each Infisical Compose definition combines a protected
static file for unmigrated settings with a protected runtime file containing
only the imported keys. The existing legacy env file remains intact for
rollback. The normal Dev Ansible roles resolve the Infisical keys and retain
the Infisical Compose definitions on subsequent deployments; they do not write
the migrated values from local env files.
For Dagster, the normal `dev.yml` role also publishes current derived runtime
metadata and installs the reconciler, so adding or removing an external code
location needs no separate `dev-infisical.yml` run. Unreferenced application
runtime mappings are not resolved. The Dagster reconciler removes obsolete
external code servers after starting desired services.

`rollback-infrastructure-infisical-service SERVICE` accepts `dagster`,
`keycloak`, `openwebui`, or `portfolio-website`. It validates the retained
Compose definition, disables only that service's Infisical boot unit, restores
the previous Compose file, and recreates only its declared services with the
retained legacy source. Rollback does not remove application state or Infisical
secrets. Validate the rollback configuration before invoking it against a
healthy service.
Dagster rollback uses a protected copy of the Compose interpolation env from
the snapshot's era, checks every required variable, and removes external code
servers absent from the rollback snapshot after its services start. It also
removes their generated workspace entries before recreating the webserver. It does
not use broad Compose orphan removal.

Infisical's own startup secrets remain in its independent bootstrap file.
GitHub Actions and other CI/CD credentials, generated GitHub credentials,
ephemeral OIDC tokens, and application-managed media keys are outside this
runtime migration.
