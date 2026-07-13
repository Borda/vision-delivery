# Release Policy

Sentinel follows semantic versioning for repository-owned public behavior:

- **Patch:** compatible fixes, documentation corrections, and evidence clarifications.
- **Minor:** backward-compatible skills, routes, fields, or integrations.
- **Major:** incompatible plugin interfaces, artifact schemas, commands, or behavior contracts.

Upstream Roboflow behavior is not versioned by this project. A release must name any tested upstream assumptions rather than imply they are frozen.

## Release gate

Before a human publishes a release:

1. reconcile versions in all plugin manifests and generated records,
2. run strict documentation, link, eval, hook, and pre-commit checks,
3. validate supported host manifests and exact install commands,
4. review permissions, secrets, paid actions, and data-flow disclosures,
5. verify every changed headline claim against committed evidence,
6. list mocked, private, single-run, and pending evidence,
7. update the [changelog](https://github.com/Borda/vision-delivery/blob/main/CHANGELOG.md) and compatibility notes,
8. inspect the built package or plugin from a clean environment.

Remote publication, tags, releases, marketplace changes, and branch protection are human-owned operations. Their existence must not be claimed until verified on the remote service.

GitHub Pages deployment additionally requires a maintainer to select **GitHub Actions** as the Pages source in the repository settings. Required checks and branch protection must be configured on the remote repository before they can be described as enforced.

## Evidence policy

A release note may call a route "proven" only when the exact claim has a versioned fixture or study, reproducible command, result, environment, sample size, and material limitations. A workflow with instructions but without comparable live evidence is "guided." Platform-specific claims remain delegated to current official Roboflow sources.

Security fixes may be prepared privately and disclosed after users have a practical remediation path. See the repository [security policy](https://github.com/Borda/vision-delivery/blob/main/.github/SECURITY.md).
