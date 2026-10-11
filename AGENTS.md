# Repository Guidance

## Purpose and boundaries
- This repo owns portable infrastructure topology and runtime components; application source, migrations, and releases stay in application repos.
- Git and the environment manifests are the source of truth for service selection.

## Development
- Terraform provisions infrastructure; Ansible configures hosts and deploys payloads; Compose defines service lifecycle.
- Keep `dev` and `prod` selection explicit in `environments/`; read `docs/architecture.md` and `docs/environments.md` before changing ownership.

## Validation
- Run `bash scripts/validate.sh` and `uv run pre-commit run --all-files` for repository checks.
- Use the inventory and playbook syntax commands in `README.md` for the changed environment.

## Architecture constraints
- A component's presence in `compose/` does not enable it in an environment.
- Keep protected environment values outside Git; follow `docs/secrets.md`.

## Safety
- Review Terraform state changes, database migration, backup, and rollback plans before applying infrastructure changes.
- Treat production selection and destructive operations as separately reviewed actions.

## Branching strategy

- This repository uses **trunk-based development**. Create short-lived change branches from current `main` and target PRs to `main`.
- Follow the [canonical branching and delivery policy](https://github.com/SpencerRWood/codex-config/blob/main/docs/branching-policy.md), available through the installed codex-config source path. Verify the strategy, release association, fetched base and PR target before implementation and record them in Story evidence. Story completion does not authorize publication or deployment; retain existing review, CI, security and rollback requirements.
