# Release & Version Bump Workflow

How to release a new version of HandoffRail (SDK + Server + Docker).

## Overview

HandoffRail uses **Trusted Publishing (OIDC)** via GitHub Actions — no API tokens needed.
Pushing to `master` triggers CI which:
1. Runs lint + tests (Python 3.11 & 3.12)
2. Builds and pushes Docker image to GHCR
3. Publishes SDK to PyPI (if version changed)

## Version Bump Steps

### 1. Update Version

```bash
# Edit sdk/pyproject.toml
vim sdk/pyproject.toml
# Bump: version = "0.1.0" → "0.2.0"

# If server version also changed:
vim server/pyproject.toml
# Bump server version too
```

### 2. Update Changelog (optional but recommended)

Add an entry to the changelog section in the README or a CHANGELOG.md:

```markdown
## v0.2.0 (2026-MM-DD)
- New feature: ...
- Fixed: ...
- Breaking: ... (if any)
```

### 3. Commit & Push

```bash
git add sdk/pyproject.toml [server/pyproject.toml]
git commit -m "chore: bump version to 0.2.0"
git push origin master
```

### 4. CI Auto-Publishes

The `publish-sdk` job in `.github/workflows/ci.yml` will:
- Build the SDK wheel + sdist
- Publish to PyPI via Trusted Publishing (OIDC)
- `continue-on-error: true` means re-publishing the same version won't fail the build

The `build-and-push-image` job will:
- Build the Docker image
- Push to `ghcr.io/melabuilt-ai/handoffrail:latest`
- Tag with the version if configured

### 5. Verify

```bash
# Check PyPI
pip index versions handoffrail-sdk

# Check Docker
docker pull ghcr.io/melabuilt-ai/handoffrail:latest

# Check CI status
# https://github.com/MelaBuilt-AI/HandoffRail/actions
```

## Trusted Publishing Setup (already configured)

- **PyPI:** Trusted publisher configured for `MelaBuilt-AI/HandoffRail` with workflow `ci.yml`
- **GHCR:** Uses `GITHUB_TOKEN` — no extra config needed
- **No API tokens or secrets to manage**

## Versioning Scheme

We follow **Semantic Versioning**:

- **MAJOR (1.0.0):** Breaking API changes
- **MINOR (0.2.0):** New features, backward compatible
- **PATCH (0.1.1):** Bug fixes only

While on `0.x`, breaking changes may bump MINOR. Once `1.0+`, breaking changes bump MAJOR.

## Pre-Release Checklist

Before bumping a minor or major version:

- [ ] All tests passing (`python3 -m pytest --tb=short -q`)
- [ ] Lint clean (`ruff check server/app/ tests/`)
- [ ] mypy clean (`mypy app/ --ignore-missing-imports`)
- [ ] README/docs updated with new features
- [ ] CHANGELOG entry written
- [ ] No `Waiting on Aaron` blockers in PROJECTS.md

## Rollback

If a release is broken:

1. **PyPI:** Cannot un-publish, but can yank:
   ```bash
   pip install pip-tools
   pip yank handoffrail-sdk==0.2.0  # hides from default search
   ```
2. **Docker:** Re-tag previous version:
   ```bash
   docker pull ghcr.io/melabuilt-ai/handoffrail:0.1.0
   docker tag ghcr.io/melabuilt-ai/handoffrail:0.1.0 ghcr.io/melabuilt-ai/handoffrail:latest
   docker push ghcr.io/melabuilt-ai/handoffrail:latest
   ```
3. **Git:** Revert the version bump commit and push a fix:
   ```bash
   git revert <bump-commit-sha>
   git push origin master
   ```
4. Bump to the next patch version (e.g., `0.2.1`) with the fix.

---

_Maintained by MelaBuilt AI. Last updated: 2026-06-26._