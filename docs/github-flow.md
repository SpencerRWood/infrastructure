# GitHub Flow

Main is this repository's only permanent Git branch. Start feature, fix,
maintenance and Renovate branches from fetched main; open PRs into main and
delete short-lived branches after successful merging. Existing required
validation/routing checks and main protection apply to every normal change.

Root Wood metadata declares strategy = "trunk". The shared workflow capability
file declares branching.policy = "infrastructure". Routine work requires no
OpenProject planning release and no development-to-main promotion. Existing
OpenProject project/initiative mappings remain for work tracking. A running
Story must reconcile its saved base/target before resuming under this policy;
never rewrite an active claim or discard its worktree.

Conventional Commits still determine semantic versions. Semantic-release publishes
only main, retaining tags and GitHub Releases. Validation never publishes.
Existing automatic releases, repository-specific automatic/manual deployment
selection, environment approvals, health checks, idempotence and deterministic
rollback remain in force. Runtime environment names such as dev/development do
not name Git integration branches.

The 2026-10-16 migration retains all historical commits and outstanding work.
Development is retired only after its tip is an ancestor of main and no open PR
or checked-out worktree depends on that branch. Existing unrelated local
worktrees are retained. Migration merges temporarily hold the release workflow
through GitHub's existing disable/enable API, with validation/protection active,
so the migration itself publishes and deploys nothing. Future main changes
resume the normal delivery path; no permanent extra approval gate is added.

Application repositories retain their development/main release-promotion policy.
See the shared [policy and caller templates](https://github.com/SpencerRWood/workflows/blob/main/docs/branching-policies.md).

## Publication and deployment

For an explicitly authorized release of a validated main revision that was held
during migration, use the existing Release workflow's main dispatch with
release_approved=true. Verify the exact release tag and its commit before using
the Deploy workflow's main dispatch with deployment_approved=true and that tag.
Manual publication and deployment are separate operations; dispatching a release
does not bypass runtime approval, backup, health or rollback checks.

Ordinary main changes retain the repository's existing automatic behavior.
Infrastructure deployment remains separately approved; Homelab's automatic path
retains its protected-change checks. Never bypass a failed recovery or migration
gate. Retain rollback state and known-good images through health verification.
Remove only completed clean worktrees and merged short-lived branches after
delivery evidence is saved; preserve unfinished or actively owned work.
