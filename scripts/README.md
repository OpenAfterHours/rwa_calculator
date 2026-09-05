# Scripts

Utility scripts for the rwa-calc project.

## deploy.py

Automates version updates, the release commit, tag and push, and the GitHub
Release that publishes to PyPI.

> **Recommended path:** invoke `/release` in a Claude Code session instead of
> calling `deploy.py` directly. The slash command previews which `[Unreleased]`
> bullets will be promoted into the new version section before running the
> script, so you can verify the changelog promotion before it is committed and
> pushed.

The `[Unreleased]` -> new-version promotion logic lives in
`scripts/_deploy_changelog.py` (pure string transforms, unit-tested at
`tests/unit/test_deploy_changelog.py`).

### Features

- Fails fast, before the tests, if the branch is behind `origin`, the tag
  already exists there, HEAD is detached, or `gh` is not logged in
- Runs tests before deployment
- Updates version in all required files (pyproject.toml, __init__.py, docs)
- Updates changelog with new version section
- Regenerates the version-stamped generated docs pages
- Syncs uv.lock
- Builds the package and checks the distribution metadata
- Commits and tags the release
- Pushes the branch and the release tag to `origin` in one atomic push
- Creates the GitHub Release from the promoted changelog section, which runs
  `publish.yml` and uploads to PyPI
- Names those irreversible steps up front and asks for confirmation (`--yes`
  skips the prompt for non-interactive callers such as `/release`)
- Or uploads from this machine with `--publish` instead of via the release

### Usage

```bash
# Bump patch version (0.1.3 -> 0.1.4)
python scripts/deploy.py --bump patch

# Bump minor version (0.1.3 -> 0.2.0)
python scripts/deploy.py --bump minor

# Set specific version
python scripts/deploy.py 0.1.4

# Same, without the confirmation prompt (what /release passes)
python scripts/deploy.py 0.1.4 --yes

# Push the tag but create no GitHub Release, so nothing is published
python scripts/deploy.py 0.1.4 --no-github-release

# Upload from this machine instead of via the GitHub Release
python scripts/deploy.py --bump patch --publish

# Dry run (show what would be done)
python scripts/deploy.py --bump patch --dry-run

# Skip tests (not recommended)
python scripts/deploy.py --bump patch --skip-tests

# Commit and tag locally without pushing
python scripts/deploy.py 0.1.4 --no-push
```

### Windows

Use the batch wrapper:

```cmd
scripts\deploy.bat --bump patch
scripts\deploy.bat 0.1.4 --publish
```

### After Deployment

Nothing. The script has committed `chore(release): bump version to X.Y.Z`,
tagged `vX.Y.Z`, pushed both to `origin` in one atomic push (either both are on
the remote or neither is; only the release tag travels, stray local tags stay
local), and created GitHub Release `vX.Y.Z` from the promoted changelog section
with GitHub's generated PR list appended. That release is what publishes:
`.github/workflows/publish.yml` runs on a published release, builds, and
uploads to PyPI. Watch it with:

```bash
gh run list --workflow=publish.yml --limit 1
```

The script refuses up front, before the test run, if the local branch is behind
its upstream, if the tag already exists on the remote, if HEAD is detached, or
if `gh` is not logged in, so a stale checkout is caught in seconds.

`--no-github-release` pushes without creating the release, so nothing is
published; `--no-push` (or `--no-git`, which implies it) commits and tags
locally only. In both cases the script prints the exact commands to finish by
hand:

```bash
git push --atomic origin master refs/tags/vX.Y.Z
gh release create vX.Y.Z --verify-tag --title vX.Y.Z --notes-file dist/release_notes_vX.Y.Z.md --generate-notes
```

`--publish` uploads from this machine with `uv publish` instead of via the
GitHub Release, which is then skipped: a release created after a local upload
would run `publish.yml` onto a version PyPI already has. Use it only when CI
publishing is unavailable.

### PyPI Token

For publishing, ensure you have a PyPI token configured. UV looks for credentials in:

1. `UV_PUBLISH_TOKEN` environment variable
2. `~/.pypirc` file
3. Keyring

Set up with:

```bash
# Option 1: Environment variable
export UV_PUBLISH_TOKEN=pypi-xxxxx

# Option 2: .pypirc file
cat > ~/.pypirc << EOF
[pypi]
username = __token__
password = pypi-xxxxx
EOF
```

## download_docs.py

Downloads regulatory reference documents (PDFs, reporting templates and the two
supervisory validation-rule workbooks) to `docs/assets/`.

New collaborators should run this after cloning and installing dependencies. Files with
known direct URLs are fetched automatically; remaining files are listed with manual
download instructions. Everything it fetches is gitignored, so this script — not the
repository — is how `docs/assets/` gets populated and repopulated.

### Usage

```bash
# Download all available documents
uv run python scripts/download_docs.py

# Force re-download (overwrite existing files)
uv run python scripts/download_docs.py --force

# List all documents in the manifest
uv run python scripts/download_docs.py --list

# Dry run (show what would be done)
uv run python scripts/download_docs.py --dry-run
```

### Archive extraction

A manifest entry may set `extract_member` / `extract_as` to pull one member out of a
downloaded archive. The BoE validation-rules zip uses this to extract
`boe-validation-rules-banking-reporting-v4.0.0.xlsx` alongside itself; such entries
add a second line to the run summary under a new `extracted` status.

Extraction honours the flags above: skipped when the target already exists, redone under
`--force`, reported as `would extract` under `--dry-run`. It runs independently of the
download outcome, so a deleted member is re-extracted from an already-present archive
without re-downloading it. A missing member is reported as a failure and sets a non-zero
exit code rather than raising.

See [Scripts & Automation](../docs/development/scripts.md) for the narrative version.

## extract_validation_rules.py

Extracts the credit-risk supervisory validation rules from the two workbooks fetched by
`download_docs.py` into committed JSON under `docs/reference/validation-rules/`:

- `crr-eba-v3.0-credit-risk.json` — EBA rules for COREP C 02.00 / C 07.00 / C 08.0x /
  C 09.0x / C 34.xx (CRR)
- `basel31-boe-v4.0.0-credit-risk.json` — BoE rules for OF02 / OF07 / OF08 / OF09 /
  C08.04 / C09.04 / C34.xx (Basel 3.1)

The source workbooks are gitignored; the JSON extracts are the committed artefact, so
downstream consumers and CI never need the raw xlsx. Re-run this only when the workbooks
are refreshed, and commit the regenerated JSON with it.

### Usage

```bash
# Re-extract and write the JSON
uv run python scripts/extract_validation_rules.py

# Fail non-zero if the committed JSON is stale (CI gate)
uv run python scripts/extract_validation_rules.py --check

# Print N parsed rules per source for inspection
uv run python scripts/extract_validation_rules.py --sample 3
```

If either workbook is missing, the script exits non-zero and points back at
`download_docs.py` rather than failing obscurely.

## worktree.py

Manages developer git worktrees for running multiple Claude Code instances in
parallel. Each worktree gets its own branch `wt/<name>` and sits at
`../rwa_calculator-<name>` next to the main repo.

This is distinct from `/next-items`, which manages its own `batch/*` worktrees
internally — `worktree.py` is the manual equivalent for human-driven parallel
work.

### Usage

```bash
# Create a new worktree off current HEAD
uv run python scripts/worktree.py create feature-x

# Create off a specific base
uv run python scripts/worktree.py create spike-y --from master

# List all wt/* worktrees with dirty/ahead/behind status
uv run python scripts/worktree.py list

# Remove a worktree, keep the branch
uv run python scripts/worktree.py remove feature-x

# Remove a worktree AND delete the branch
uv run python scripts/worktree.py remove feature-x --delete-branch

# Force-remove (skips dirty-state check, force-removes existing path)
uv run python scripts/worktree.py remove feature-x --force
```

After `create`, the script prints the exact `UV_PROJECT_ENVIRONMENT` export
command for both PowerShell and bash so the new worktree reuses the main
repo's `.venv` (saves disk and `uv sync` time per worktree).
