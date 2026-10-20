# Security Policy

## Supported versions

ratelimit-io follows semantic versioning. Security fixes target the latest
released minor of the current major.

| Version | Supported |
| ------- | --------- |
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately through GitHub's
[private vulnerability reporting](https://github.com/bagowix/ratelimit-io/security/advisories/new),
or by email to **galushko355@gmail.com**. Include a description, affected
versions, and a reproduction if you have one.

You can expect an acknowledgement within a few days. Once a fix is ready we will
release it and credit the reporter unless you prefer to stay anonymous.

## Supply chain

- **Trusted publishing.** `.github/workflows/release.yml` builds and publishes
  through PyPI's OIDC trusted publisher; there is no long-lived API token that
  could leak.
- **Signed provenance.** Every artefact carries a Sigstore-backed
  [PEP 740](https://peps.python.org/pep-0740/) attestation generated at publish
  time.
- **Pinned actions.** Every `uses:` in `.github/workflows/` is pinned to a full
  commit SHA with the version in a trailing comment; Dependabot bumps both,
  after a seven-day cooldown.
- **Audited workflows.** [zizmor](https://docs.zizmor.sh) checks `.github/` on
  every pull request. Suppressions live in `.github/zizmor.yml`, each with a
  reason.
- **One dependency.** The package depends on redis-py only.
