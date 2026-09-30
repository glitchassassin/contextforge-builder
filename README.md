# ContextForge UBI 9 builder

Unofficial amd64 builds of IBM ContextForge for machines that cannot run its
UBI 10 / x86-64-v3 image. Repository: `glitchassassin/contextforge-builder`.

## Publishing

The workflow builds upstream stable releases starting at **v1.0.11**, the current
release when this builder was created. It checks daily at **09:23 UTC**, skips
versions already published, and processes all missing releases above that floor.
It also runs when workflow, scripts, patches, or regression tests change, rebuilding the newest release
so those changes are tested even if that version was already published. No NAS
deployment occurs.

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

The workflow checks out the upstream release tag and applies the compatibility
patches in `patches/`. Patch application fails if the source has changed
incompatibly. Review the patch when upstream incorporates an equivalent fix.
Image labels record the upstream commit, builder commit, and patch digest.
It uses the upstream Containerfile, overriding its builder,
Node.js builder, and runtime to Red Hat UBI 9 images. Rust and FIPS are disabled.
UBI base tags float to their latest patches; published version tags can be
replaced by an explicit manual rebuild. Pin an image digest for deployment if
you need immutable rollback targets.

Before publishing, it verifies the runtime identifies itself as UBI 9 and tests
both the default Gunicorn entrypoint (two workers) and the single-process Uvicorn
entrypoint used for TrueNAS. Each test uses disposable SQLite storage and random
Base64 credentials, with the admin UI and authentication enabled. Both must
return a healthy JSON payload, render the admin login page, and have no matched
startup errors in their logs. Startup logs are retained as workflow artifacts.
Both startup modes also verify OAuth scope challenges over HTTP against a
temporary virtual server. Container regression tests use fresh RSA keys to check
signed access tokens, rejection paths, and database-derived user permissions.
These tests run without network access or production data.

All external Actions are pinned to commit SHAs. Syft generates an SPDX SBOM,
and Grype blocks publication on HIGH or CRITICAL vulnerabilities with available
fixes (`only-fixed: true`). Unfixed vulnerabilities are outside that gate. The
SBOM is retained for 30 days. These checks use this rebuilt UBI 9 image, not the
upstream UBI 10 image. The image is not currently signed with Cosign.

The hosted runner supports newer CPU instructions: passing this smoke test does
not prove compatibility with the NAS CPU. Verify the first image on the NAS.
Future upstream changes may require adjustments to the UBI 9 overrides and patches.

## OAuth scope compatibility patch

ContextForge v1.0.11 omits scope guidance from its `WWW-Authenticate` challenges.
Its missing-email response also omits the OAuth challenge entirely. Auth0 requires
an `email` grant before an Action can add the plain `email` access-token claim.
A client that requests no email scope can therefore authenticate at Auth0 and
then fail MCP discovery with `OAuth token missing valid email claim`.

The patch advertises each virtual server's configured `scopes_supported` (or
legacy `scopes`) in initial and rejected-token challenges. Configure the minimal
list `["openid", "email"]` for the Auth0 endpoint. The resulting challenge includes
`scope="openid email"`. It omits `offline_access`, which is a client refresh-token
request rather than a resource requirement, and rejects unsafe scope strings.
No scopes are hard-coded for servers without this configuration.

Keep the existing Auth0 Action that adds `email` to the access token for the MCP
API. A fresh authorization grant is required; an existing token will not acquire
the missing claim. The patch does not invent an email, auto-create users, or
change signature, issuer, audience, expiration, local-account, or RBAC validation.

The container tests validate challenge behavior and signed-token authentication.
They do not prove that a particular ChatGPT/Auth0 authorization flow requested
and granted the scopes. Verify that separately after deployment by reconnecting
the MCP integration with a fresh authorization.

References:
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- https://auth0.com/docs/troubleshoot/product-lifecycle/past-migrations/custom-claims-migration

Source: https://github.com/IBM/mcp-context-forge (Apache-2.0).
This repository contains build automation, not a maintained source-code fork.
