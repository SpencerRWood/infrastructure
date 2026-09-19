# Secrets and credentials

No real secrets are stored in this repository. `.env.example` files document
names only, and `.env` files are ignored by Git.

## Credential timing

1. **GitHub auth** — required now to create and push this repository.
2. **DigitalOcean API token** — create before Step 7 when Terraform begins to
   manage or import infrastructure.
3. **SSH deployment identity** — create later, before automated host
   deployment.
4. **PostgreSQL bootstrap/admin credential** — create when shared PostgreSQL
   is actually deployed.
5. **Application runtime/migration credentials** — create during each
   service/database onboarding.
6. **Cloudflare token** — create only if DNS is later managed through
   Terraform or automation.

## Handling rules

- Keep real values in an untracked environment file or approved secret store.
- Never place credentials in Compose YAML, docs, scripts, Git history, or
  Terraform variables files.
- Give runtime applications and migrations distinct database credentials.
- Rotate a credential if it is ever accidentally committed or exposed.
