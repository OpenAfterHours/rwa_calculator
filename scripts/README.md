# Scripts

Utility scripts for the rwa-calc project.

## deploy.py

Automates version updates and PyPI deployment.

### Features

- Updates version in all required files (pyproject.toml, __init__.py, docs)
- Updates changelog with new version section
- Syncs uv.lock
- Runs tests before deployment
- Builds the package
- Optionally publishes to PyPI

### Usage

```bash
# Bump patch version (0.1.3 -> 0.1.4)
python scripts/deploy.py --bump patch

# Bump minor version (0.1.3 -> 0.2.0)
python scripts/deploy.py --bump minor

# Set specific version
python scripts/deploy.py 0.1.4

# Bump and publish to PyPI
python scripts/deploy.py --bump patch --publish

# Dry run (show what would be done)
python scripts/deploy.py --bump patch --dry-run

# Skip tests (not recommended)
python scripts/deploy.py --bump patch --skip-tests
```

### Windows

Use the batch wrapper:

```cmd
scripts\deploy.bat --bump patch
scripts\deploy.bat 0.1.4 --publish
```

### After Deployment

The script reminds you to commit and tag:

```bash
git add -A
git commit -m "chore: release v0.1.4"
git tag v0.1.4
git push origin master --tags
```

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

Downloads regulatory reference documents (PDFs and templates) to `docs/assets/`.

New collaborators should run this after cloning and installing dependencies. Files with
known direct URLs are fetched automatically; remaining files are listed with manual
download instructions.

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
