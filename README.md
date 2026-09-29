# ContextForge UBI 9 builder

Unofficial amd64 builds of IBM ContextForge for machines that cannot run its
UBI 10 / x86-64-v3 image. Intended repository:
`glitchassassin/contextforge-builder`.

## Publishing

Push these files to the `main` branch of a new public GitHub repository. The
workflow builds upstream stable releases starting at **v1.0.11**, the current
release when this builder was created. It checks daily at **09:23 UTC**, skips
versions already published, and processes all missing releases above that floor.
It also runs when workflow/build scripts change. No NAS deployment occurs.

Images are published as:

```text
ghcr.io/glitchassassin/contextforge:1.0.11-ubi9
ghcr.io/glitchassassin/contextforge:latest
```

Publishing uses `GITHUB_TOKEN`, with package write permission only in the build
job. No personal access token is required. After the first publication, set the
GHCR package to **Public** in its package settings; making the repository public
does not automatically make a new package public.

Run **Actions → Build ContextForge on UBI 9 → Run workflow** to check now.
Provide an exact stable upstream release tag to force rebuilding that version.
Manual version rebuilds do not update `latest`; a normal discovery run does.
To rebuild existing versions after a base-image security update, use this manual
input. Routine daily checks only build new upstream releases.

GitHub may disable scheduled workflows in public repositories after 60 days
without repository activity. Re-enable the schedule if this happens; manual
dispatch remains available. Scheduled runs can be delayed by GitHub.

## Build and validation

The workflow checks out the upstream release tag and records its resolved commit
in image labels. It uses the upstream Containerfile, overriding its builder,
Node.js builder, and runtime to Red Hat UBI 9 images. Rust and FIPS are disabled.
UBI base tags float to their latest patches; published version tags can be
replaced by an explicit manual rebuild. Pin an image digest for deployment if
you need immutable rollback targets.

Before publishing, it verifies the runtime identifies itself as UBI 9 and starts
ContextForge with temporary SQLite storage and random test credentials. A health
check must pass. The test uses the same single-process Uvicorn entrypoint used
for the personal TrueNAS deployment. Upstream's default entrypoint is preserved
in the published image, so keep the Uvicorn override in the TrueNAS configuration.

The hosted runner supports newer CPU instructions: passing this smoke test does
not prove compatibility with the NAS CPU. Verify the first image on the NAS.
This workflow has been statically checked but has not yet completed a GitHub
build. Future upstream changes may require adjustments to the UBI 9 overrides.

Source: https://github.com/IBM/mcp-context-forge (Apache-2.0).
This repository contains build automation, not a maintained source-code fork.
