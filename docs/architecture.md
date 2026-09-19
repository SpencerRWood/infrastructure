# Architecture and ownership

## Ownership boundaries

| Owner | Responsibilities |
| --- | --- |
| Application repositories | Source code, Dockerfiles, tests, migrations, application releases |
| `workflows` | Reusable GitHub release automation |
| `infrastructure` | Environment topology, Compose composition, shared PostgreSQL, future Terraform, deployment-facing configuration, provisioning scripts, and infrastructure validation |

Application source code is never copied into this repository. Applications
publish immutable images; infrastructure later selects the image digest or
version to run in each environment.

## Runtime model

Docker Compose is the runtime composition mechanism for both environments.
`dev` targets the local/home-server environment and `prod` targets future
DigitalOcean hosts. Kubernetes is not part of this platform architecture.

Shared PostgreSQL is infrastructure, not an application-private sidecar. Each
application receives its own database and least-privilege runtime and migration
roles through the provisioning process described in
[database-provisioning.md](database-provisioning.md).

## Future deployment boundary

```text
application release
  -> immutable container image
  -> deployment workflow
  -> runtime host (/srv/wood)
  -> docker compose update
  -> health check
  -> success or rollback
```

The image version or digest is the deployment input. Do not use `latest` as a
production source of truth. Deployment automation, health checks, and rollback
are deliberately deferred beyond this foundation.
