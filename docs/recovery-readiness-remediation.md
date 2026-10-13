# OP-500 comprehensive recovery readiness remediation

This correction does not publish images, provision credentials or deploy services.
Provider PR22 and infrastructure PR140 are integrated. The expanded source batch
adds explicit immutable artifact catalogs, complete secret-name catalogs, required
probe configuration and group-bound daily/weekly evidence. Keep the three schedules,
both sensors, Telegram routing and append-only history unchanged during delivery.

## Reviewed source selection

After approved consumer commits, stage clean clones of those exact revisions.
Generate the reviewable runtime selection with the supported preparation mode:

```sh
python3 scripts/verify-recovery-consumers.py \
  --configuration /path/to/current-reviewed-orchestration.json \
  --checkout-directory /path/to/staged-clean-consumers --prepare
```

The output's configuration preserves schedules, policy, notifications and cutoff.
Preparation permits revision/configuration advancement only for the same consumer
ID and owning repository. It writes nothing. Review the resulting configuration
before deploying; the existing deployment mode requires an exact match. Do not
insert a future or invented revision into the checked-in deployment manifest.

## Artifact evidence

`recovery/artifacts.v1.json` enumerates all selected application images, including
the PostgreSQL, MongoDB, Redis, Infisical, Keycloak, OpenWebUI and Caddy dependencies
omitted by the old `_image_ref`-only inventory. Registry references must contain
an exact SHA256 digest. Defaults are resolved from canonical declarations and
installed selections; no floating tag can satisfy this catalog. A build reference
identifies source requiring an independently retained immutable image or image
publication; source presence alone is unavailable recovery-artifact evidence.

The infrastructure Dagster and Overleaf images currently have only local image IDs.
Their registry publication or verified encrypted image exports need a separate
review. Do not count a daemon cache or Dockerfile as independent image custody.
Homelab has the analogous Caddy/code-server requirements. No publication URL or
digest is invented for those images. Verify actual resulting artifacts before
replacing build requirements with approved immutable OCI references.

## Required probe access and exact authorization dependency

The non-secret preparation contract is `recovery/probe-access.v1.json`. Project
selectors were read from installed deployer configuration; CI uses its existing
consumer declaration. Required values are resolved through Infrastructure Dev,
`dev`, `/recovery-verification`, using the existing protected runtime resolver:

- RECOVERY_INFISICAL_URL: `https://dev-infisical.woodhost.cloud`
- RECOVERY_INFISICAL_PROJECTS: the verified mapping in probe-access.v1.json
- RECOVERY_INFISICAL_TOKEN: dedicated scoped metadata identity access token
- RECOVERY_GHCR_USERNAME / RECOVERY_GHCR_TOKEN: dedicated GHCR reader

The deployment secret contract requires these inputs, so an unconfigured probe
cannot silently become an accepted deployment. Token creation, permissions,
storage and rollout are privileged actions requiring separate approval. The
current authenticated identity returned HTTP403 for organization discovery and
metadata-only secret listing in both projects. The verifier has none of these
probe inputs. The host's declared GHCR Docker config is absent; five private
image requests therefore remain unverified. No application values were requested.

An administrator must approve/create or select the dedicated identity and grant
only secret-name/metadata inspection at the exact environments/paths/names listed
in the consumer catalogs, including CI `/github/WEBSITE_PORTFOLIO_GHCR_TOKEN`.
Use the installed server's metadata-only permission action; do not substitute a
project-wide Viewer grant that includes reading values. Requests always specify
viewSecretValue=false, expansion=false and personal overrides=false. Test the
issued identity against each scope before provisioning. Provide token expiry and
rotation compatible with unattended cadence through the existing secret refresh
process. Never store an operator session token as a permanent recovery credential.

GHCR requires read:packages and read access to the five private packages; no
publication/deletion permission is requested. Basic authentication is confined to
the HTTPS ghcr.io/token endpoint and exchanged for a repository pull token in
memory. Do not forward credentials to arbitrary registry challenge hosts.
Publication uses a separate reviewed writer identity and separate approval.

## Group identity and custody

Daily preflight records the validated completed manifest hash and time. Successful
weekly restoration records the same group identity plus the selected database
artifact checksum. A successor group with identical database bytes still has its
own manifest identity; earlier restore evidence cannot attest to that successor.
Failed attempts retain the validated group identity without claiming restoration.
Consumer subchecks are preserved through provider evidence using the existing
check wire format. No archive schema/default changes or history migration occur.

Independent custody is a separate native prerequisite. The producer's canonical
independent_custody_verified attestation may be enabled only by OP-543 after actual
independent retrieval/roundtrip/cleanup evidence. The current false attestation
produces an explicit failed prerequisite even when ciphertext integrity passes.
Temporary MacBook custody is not independent custody. This batch copies no key,
changes no custody flag and does not duplicate OP-543's physical implementation.

## Monthly external prerequisite and implementation boundary

OP-498's generic SDK implements ordered provisioning/bootstrap/dependency/secret/
recovery/restore/workload/validation/cleanup phases with fail-stop and independent
cleanup handling. Both consumers currently export bootstrap plans; their normal
host roles address real NAS, production networks and deployment credentials.
Those roles cannot safely be repurposed as a monthly drill by inventing an inventory.

Before consumer VM bindings can be implemented and verified, an operator must
select and approve a disposable Linux provider/VM identity, isolated network,
resource limits, expiry/destruction API and drill-only secret access. No such
provider is declared or approved in either repository. The open selection request
is an external dependency, not an implemented monthly capability. Keep supported
false and report strongest actual weekly verification while it is unresolved.
See `recovery/monthly-onboarding.json` for the exact proposed bounded execution
inputs and approval checklist. No production inventory, Docker socket, writer
pause or real deployment is authorized by that proposal. Do not report fixtures
or a syntax-only playbook as completed monthly bootstrap.
