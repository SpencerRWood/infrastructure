# Future Terraform ownership

Terraform implementation begins in Step 7, not in this repository foundation.
When introduced, Terraform will own:

- DigitalOcean compute
- firewall and networking configuration
- volumes
- DNS where Terraform management is appropriate

## State and outputs

Select and document a remote state backend before the first apply. Keep state,
state backups, provider credentials, and generated variable files out of Git.
Expose only deployment-relevant outputs (for example host addresses, volume
identifiers, and firewall identifiers), and consume them through protected
deployment configuration rather than copying them into application code.

No Terraform resources are declared, imported, or applied by Step 6.
