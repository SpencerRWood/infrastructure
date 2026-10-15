# Wood Design System initial deployment (Story 551)

This is a dormant catalog proposal: services.wood_design_system is false and wood_design_system_image_ref is empty. No fabricated bootstrap artifact is used. Only explicit WDS selection installs its route fragments, after its digest-qualified container becomes healthy. The generic Caddy catalog does not install these fragments. Production is unchanged.

After WDS's approved main release, a reviewed onboarding PR must pin ghcr.io/spencerrwood/wood-design-system:vX.Y.Z@sha256:<verified-digest> and enable the service. Supply a dedicated pull-only WDS_GHCR_TOKEN through the existing protected infrastructure runner input. Host-side registry configuration is root-owned and separate from application environment. The static portal receives no secrets, database or state volume.

The container joins only infrastructure-dev-proxy, exposes 8080 internally, runs as 101:101 with a read-only root, /tmp tmpfs, no capabilities and no-new-privileges. Its image supplies HEALTHCHECK. Infrastructure Caddy selects dev-design.woodhost.cloud; the edge fragment uses existing Cloudflare TLS, security headers and the admin allowlist. DNS currently resolves through Cloudflare proxy addresses; origin selection, TLS issuance and end-to-end access remain runtime checks.

The current infrastructure release/deployment workflows require separate approved dispatches. Preserve this manual policy exception. Initial onboarding exceeds the existing promoter's one-image-line replacement contract and therefore requires its separately reviewed PR and deployment authorization. Once a genuine prior image is pinned, the existing promoter supports subsequent replacements. Do not invent an old image or silently change platform release policy.

Preparation checks render Compose with fixture values, validate Caddy, syntax-check Ansible and exercise the local WDS container. Runtime checks must verify health, all nine application/documentation routes, manifest, built assets, approved revision and image digest. WDS scripts/smoke.mjs performs HTTP probes; UI behavior remains covered by its browser suite.

The initial previous configuration has no WDS role and cannot automatically remove a newly added container. scripts/rollback-wood-design-system.sh requires explicit authorization, stops only WDS, removes only its two route fragments, and validates/reloads both proxies. Restore the reviewed disabled manifest before later deployment. Future rollback restores the prior infrastructure tag and immutable image. No data volumes are deleted.

WDS repository promotion/readiness secrets are absent. Runner credential presence could not be verified because the read-only SSH attempt could not authenticate. No values were exposed. No live registry, DNS, protection or infrastructure mutation occurred.
