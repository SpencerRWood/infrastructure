# CHANGELOG

<!-- version list -->

## v0.11.0 (2026-09-27)

### Features

- **ci**: Resolve GHCR deploy token from isolated Infisical identity
  ([`f8404b1`](https://github.com/SpencerRWood/infrastructure/commit/f8404b1b2346ae30796332289c61d3e774892740))


## v0.10.0 (2026-09-27)

### Features

- **infisical**: Establish external bootstrap path
  ([`58f3431`](https://github.com/SpencerRWood/infrastructure/commit/58f343171cd0d4771f77f7dea3e75d27eff852ac))

- **secrets**: Migrate dev runtime services to Infisical
  ([`0e3fb93`](https://github.com/SpencerRWood/infrastructure/commit/0e3fb93c0d6fd2f51bf7de589545375133a6fd18))


## v0.9.17 (2026-09-26)

### Chores

- **deps**: Update portfolio-website to v0.9.0
  ([`4efe77c`](https://github.com/SpencerRWood/infrastructure/commit/4efe77c7e43fe69613c67bb1186ced151b5743c7))


## v0.9.16 (2026-09-25)

### Bug Fixes

- **ci**: Skip superseded infrastructure deployment
  ([`8e9b8eb`](https://github.com/SpencerRWood/infrastructure/commit/8e9b8eb6bafbcf205b044d45efdfea3110ce69c5))


## v0.9.15 (2026-09-25)

### Chores

- **deps**: Update redis:8.10.2-alpine docker digest to 3811787
  ([#40](https://github.com/SpencerRWood/infrastructure/pull/40),
  [`90913c2`](https://github.com/SpencerRWood/infrastructure/commit/90913c2963505c48c42ddcb4157a99dfd7f5c7a5))


## v0.9.14 (2026-09-24)

### Bug Fixes

- **keycloak**: Restore normal startup after migration
  ([#39](https://github.com/SpencerRWood/infrastructure/pull/39),
  [`7ee5cd2`](https://github.com/SpencerRWood/infrastructure/commit/7ee5cd2a9eb568e9b0348c9414f4e2bcb03de28e))


## v0.9.13 (2026-09-24)

### Bug Fixes

- **keycloak**: Bypass realm cache during 26.7 migration
  ([#38](https://github.com/SpencerRWood/infrastructure/pull/38),
  [`22612bd`](https://github.com/SpencerRWood/infrastructure/commit/22612bd7cdb0c6bff70b41b0a72c9e4c54d9d808))


## v0.9.12 (2026-09-24)

### Bug Fixes

- **keycloak**: Restore version before upstream migration bug
  ([#36](https://github.com/SpencerRWood/infrastructure/pull/36),
  [`040d700`](https://github.com/SpencerRWood/infrastructure/commit/040d7005301b6903d288782753209d175ef343b3))


## v0.9.11 (2026-09-24)

### Chores

- **deps**: Update quay.io/keycloak/keycloak docker tag to v26.7.4
  ([#21](https://github.com/SpencerRWood/infrastructure/pull/21),
  [`181ae0c`](https://github.com/SpencerRWood/infrastructure/commit/181ae0caa56d8be81f289666bee343f53e390cb9))


## v0.9.10 (2026-09-24)

### Bug Fixes

- **keycloak**: Verify readiness and retain failure diagnostics
  ([#35](https://github.com/SpencerRWood/infrastructure/pull/35),
  [`6e7cd45`](https://github.com/SpencerRWood/infrastructure/commit/6e7cd451fb3e5662ba75464f383bd04a763d638c))


## v0.9.9 (2026-09-24)

### Chores

- **deps**: Update infisical/infisical docker tag to v0.165.16
  ([#17](https://github.com/SpencerRWood/infrastructure/pull/17),
  [`702b46c`](https://github.com/SpencerRWood/infrastructure/commit/702b46c7936de49511c8f90c5e6fc6d95f9d6791))


## v0.9.8 (2026-09-23)

### Chores

- **deps**: Update portfolio-website to v0.8.4
  ([`32de7f2`](https://github.com/SpencerRWood/infrastructure/commit/32de7f259d38b4df011979311e757e664766f4a0))


## v0.9.7 (2026-09-23)

### Chores

- **deps**: Update portfolio-website to v0.8.3
  ([`878210d`](https://github.com/SpencerRWood/infrastructure/commit/878210d25f2949435d3db9dd9dd387bfcdfb9815))


## v0.9.6 (2026-09-23)

### Chores

- **deps**: Update website portfolio to v0.8.2
  ([`0a2d412`](https://github.com/SpencerRWood/infrastructure/commit/0a2d412b828c747242b3888bab831d3125b38987))


## v0.9.5 (2026-09-23)

### Chores

- **deps**: Update website portfolio to v0.8.1
  ([`29f5538`](https://github.com/SpencerRWood/infrastructure/commit/29f5538396bea6b654d74f0d0b973073dd6c00f4))


## v0.9.4 (2026-09-23)

### Chores

- **deps**: Update website portfolio to v0.8.0
  ([`c93f814`](https://github.com/SpencerRWood/infrastructure/commit/c93f814ccfd27766ac280ca790d0d2de31e86373))


## v0.9.3 (2026-09-23)

### Chores

- **deps**: Update website portfolio to v0.7.0
  ([`361d544`](https://github.com/SpencerRWood/infrastructure/commit/361d544ddf9235a8a8685371f307b1baf41b29f7))


## v0.9.2 (2026-09-23)

### Chores

- **deps**: Update caddy:2.11.4-alpine docker digest to 6aeddd4
  ([#23](https://github.com/SpencerRWood/infrastructure/pull/23),
  [`b86e2fc`](https://github.com/SpencerRWood/infrastructure/commit/b86e2fcfea851918fc7303246e99c95f9da982b6))


## v0.9.1 (2026-09-23)

### Bug Fixes

- **runner**: Avoid root-owned Python cache during validation
  ([`36e20f8`](https://github.com/SpencerRWood/infrastructure/commit/36e20f8d5d1da5b3e0ebe788b061c3a67815c0ee))


## v0.9.0 (2026-09-23)

### Features

- **services**: Deploy website portfolio container
  ([`6e4bdd5`](https://github.com/SpencerRWood/infrastructure/commit/6e4bdd589c3ff60dd3ed48257738161f718e1e8e))


## v0.8.8 (2026-09-22)

### Chores

- **deps**: Update quay.io/keycloak/keycloak docker tag to v26.7.4
  ([#18](https://github.com/SpencerRWood/infrastructure/pull/18),
  [`4953f88`](https://github.com/SpencerRWood/infrastructure/commit/4953f88ce95869db5ae687f07c8956d1224c62fa))


## v0.8.7 (2026-09-22)

### Bug Fixes

- **deploy**: Wait for application readiness
  ([`2af7332`](https://github.com/SpencerRWood/infrastructure/commit/2af7332c436f154bccff11ed37be6b2fb65bcbe4))

### Chores

- **deps**: Update redis docker tag to v8.10.2
  ([#15](https://github.com/SpencerRWood/infrastructure/pull/15),
  [`8d3d466`](https://github.com/SpencerRWood/infrastructure/commit/8d3d466e50d4b2a3849674723e9f67e4897fcfba))


## v0.8.6 (2026-09-22)

### Chores

- **deps**: Update pgvector/pgvector docker tag to v0.8.6
  ([#14](https://github.com/SpencerRWood/infrastructure/pull/14),
  [`71119d0`](https://github.com/SpencerRWood/infrastructure/commit/71119d0ec77f05ab5f8eda9ebfc765b571abb0df))


## v0.8.5 (2026-09-22)

### Bug Fixes

- **release**: Deploy Renovate dependency patches
  ([`e436d36`](https://github.com/SpencerRWood/infrastructure/commit/e436d36d04bfa036be7ec897eb1d0fb625a93878))

### Chores

- **deps**: Pin dependencies ([#9](https://github.com/SpencerRWood/infrastructure/pull/9),
  [`054bf6c`](https://github.com/SpencerRWood/infrastructure/commit/054bf6c45d4aea2523fd9d2e8f5641a04c32aef6))


## v0.8.4 (2026-09-22)

### Bug Fixes

- **deps**: Allow digest pinning automerge
  ([`b27b222`](https://github.com/SpencerRWood/infrastructure/commit/b27b2222b4e48d03a403c41f560cddff33cd4953))

- **deps**: Make infrastructure automerge conservative
  ([`ffca92e`](https://github.com/SpencerRWood/infrastructure/commit/ffca92e8507f754dadac09885b519c365b6068a1))


## v0.8.3 (2026-09-22)

### Bug Fixes

- Use deployed Caddy endpoint for health checks
  ([`686f011`](https://github.com/SpencerRWood/infrastructure/commit/686f0111af4bd54595c12edf01202080ed3d473b))


## v0.8.2 (2026-09-22)

### Bug Fixes

- Run deployment health checks without uv
  ([`417e4ce`](https://github.com/SpencerRWood/infrastructure/commit/417e4ce45573efca426398f4564613397d45d07c))


## v0.8.1 (2026-09-22)

### Bug Fixes

- Configure runner Ansible deployment
  ([`ca4b834`](https://github.com/SpencerRWood/infrastructure/commit/ca4b8346411b49ade6eec9ed848b3a940de44240))

- Harden infrastructure deployment state
  ([`0bdaaee`](https://github.com/SpencerRWood/infrastructure/commit/0bdaaee324f3ab915fcf1fd140ca4f0e71b6320a))

- Preserve runner-local deployment input
  ([`83941d6`](https://github.com/SpencerRWood/infrastructure/commit/83941d6ef93d633c11d47c761877382f91a1c7b6))

- Provision deployment state ownership
  ([`0a96fd8`](https://github.com/SpencerRWood/infrastructure/commit/0a96fd8ef9f4782855f399499e9a212fa114ba71))

- Reconcile infrastructure runner labels
  ([`9b86e91`](https://github.com/SpencerRWood/infrastructure/commit/9b86e91b1e1a2dc0b63a85892c0bb3050e8fab9e))


## v0.8.0 (2026-09-22)

### Bug Fixes

- Complete isolated infrastructure runner deployment
  ([`0713ff8`](https://github.com/SpencerRWood/infrastructure/commit/0713ff8d01c063216d22039bb35cbf7e0f79a602))

- Run infrastructure health checks remotely
  ([`ad75fe0`](https://github.com/SpencerRWood/infrastructure/commit/ad75fe0e3b78be213a0152e54a61a56b3f1c68bf))

### Features

- Deploy released infrastructure dev configuration
  ([`27cd4ce`](https://github.com/SpencerRWood/infrastructure/commit/27cd4cebef3b7a6be428d0a2cee03282eeb9439a))

- Provision isolated Beelink infrastructure runner
  ([`7de024a`](https://github.com/SpencerRWood/infrastructure/commit/7de024ad1bfb0a895c50c0205082bc82c02f4582))


## v0.7.0 (2026-09-21)

### Features

- Migrate portfolio database to infrastructure dev
  ([`61a9f93`](https://github.com/SpencerRWood/infrastructure/commit/61a9f93ff91360acb797db4a203a230c2cf6e268))


## v0.6.0 (2026-09-21)

### Features

- Drain remaining legacy postgres workload
  ([`fa1df2d`](https://github.com/SpencerRWood/infrastructure/commit/fa1df2ddf914f3ca6d59e9cb58af57b599f3e071))


## v0.5.0 (2026-09-21)

### Features

- Migrate remaining dev services
  ([`8666703`](https://github.com/SpencerRWood/infrastructure/commit/86667034513d897f46c1c30f69ca70e415e8ddbb))


## v0.4.0 (2026-09-21)

### Features

- Migrate dagster to infrastructure dev
  ([`c58b8f8`](https://github.com/SpencerRWood/infrastructure/commit/c58b8f82b1abad2b0148bebf0939ad7b74f80716))


## v0.3.0 (2026-09-21)

### Features

- Expose infrastructure caddy on dev lan ports
  ([`ba3681c`](https://github.com/SpencerRWood/infrastructure/commit/ba3681cf3147593e2ce973485549985f25bda270))


## v0.2.0 (2026-09-21)

### Features

- Add reusable caddy component
  ([`97dbfb2`](https://github.com/SpencerRWood/infrastructure/commit/97dbfb2691b175e8bd0f2398400aa42394d43993))


## v0.1.0 (2026-09-21)

- Initial Release

## v0.1.0

- Initial infrastructure foundation.
