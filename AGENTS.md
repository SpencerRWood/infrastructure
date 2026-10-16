## Development lifecycle

This repository uses GitHub Flow: main is the only permanent branch. Create
short-lived feature, fix, maintenance and Renovate branches from fetched main;
validate and merge PRs into protected main, then delete merged branches. Root
[tool.wood.branching] uses strategy = "trunk" and .github/release.toml declares
the infrastructure policy. No planning release or development promotion is
required. Preserve existing main-only publication, deployment approvals, health
checks and rollback. A task that excludes publication/deployment must hold the
release workflow during its migration merge and restore it afterward.
