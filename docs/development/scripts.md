# Scripts & Automation

The project includes several scripts for setup, deployment, test data generation, and development automation. This page is a quick reference — each section links to detailed documentation where it exists.

## Quick Reference

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `scripts/download_docs.py` | Download regulatory PDFs | After cloning the repo |
| `scripts/deploy.py` | Version bump + PyPI publish | Cutting a release |
| `tests/fixtures/generate_all.py` | Regenerate test fixture parquet files | After modifying fixture definitions |
| `workbooks/crr_expected_outputs/generate_outputs.py` | Generate CRR acceptance test golden files | After adding/changing CRR scenarios |
| `loop.sh` | Iterative Claude agent development loop | Hands-off agent-driven development |

---

## Setup Scripts

### `scripts/download_docs.py` — Download regulatory documents

Downloads regulatory reference PDFs and templates to `docs/assets/`. New collaborators should run this after cloning and installing dependencies. Files with known direct URLs are fetched automatically; remaining files are listed with manual download instructions.

```bash
# Download all available documents
uv run python scripts/download_docs.py

# Force re-download existing files
uv run python scripts/download_docs.py --force

# List all documents in the manifest
uv run python scripts/download_docs.py --list

# Dry run
uv run python scripts/download_docs.py --dry-run
```

!!! info "See also"
    This script is referenced in the [Installation Guide](../getting-started/installation.md) setup steps. Full flag reference in [`scripts/README.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/scripts/README.md).

### `scripts/deploy.py` — Version bumping and PyPI publication

Automates the release process: updates version strings across all files (`pyproject.toml`, `__init__.py`, docs, changelog), syncs `uv.lock`, runs tests, builds the package, and optionally publishes to PyPI. Intended for maintainers.

```bash
# Bump patch version (e.g. 0.1.3 -> 0.1.4)
uv run python scripts/deploy.py --bump patch

# Set specific version and publish
uv run python scripts/deploy.py 0.1.4 --publish

# Dry run
uv run python scripts/deploy.py --bump patch --dry-run
```

!!! info "See also"
    Full details (Windows batch wrapper, PyPI token setup, post-deployment git workflow) in [`scripts/README.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/scripts/README.md).

---

## Test Data Scripts

### `tests/fixtures/generate_all.py` — Regenerate test fixture parquet files

Master script that runs all fixture generators in dependency order, producing the parquet files used by the test suite. Run this after modifying any fixture definition in `tests/fixtures/`.

```bash
uv run python tests/fixtures/generate_all.py
```

!!! info "See also"
    [Testing Guide — Generating Fixture Data](testing.md#generating-fixture-data) for the full fixture authoring workflow.

### `workbooks/crr_expected_outputs/generate_outputs.py` — Generate CRR golden files

Generates the expected RWA output files in `tests/expected_outputs/crr/` used by CRR acceptance tests. Run this after adding or changing CRR test scenarios.

```bash
uv run python workbooks/crr_expected_outputs/generate_outputs.py
```

Basel 3.1 expected outputs are generated via the Marimo workbook orchestrator at `workbooks/basel31_expected_outputs/main.py`.

!!! info "See also"
    [Workbooks & UI — Expected Output Workbooks](workbooks.md#expected-output-workbooks) for the full scenario authoring workflow.

---

## Development Automation

### `loop.sh` — Iterative Claude agent development loop

Runs Claude Code in headless mode, reading a prompt file (`PROMPT_build.md` or `PROMPT_plan.md`), executing the instructions, pushing changes, and repeating for a configurable number of iterations. Useful for hands-off agent-driven development sessions.

```bash
# Build mode, 2 iterations (default)
./loop.sh

# Build mode, 20 iterations
./loop.sh 20

# Plan mode, 2 iterations
./loop.sh plan

# Plan mode, 5 iterations
./loop.sh plan 5
```

!!! tip
    Requires Claude CLI installed and git push access to the current branch. Output is logged as structured JSON to `logs/`.
