# Shared PostgreSQL service

This directory reserves ownership for the shared PostgreSQL runtime service.
The initial Compose topology intentionally starts no services. When PostgreSQL
is introduced, its Compose definition belongs in the relevant environment and
uses the least-privilege bootstrap model in `../../postgres/`.

Normal applications use their runtime role; migrations use their migration
role; neither receives PostgreSQL superuser credentials.
