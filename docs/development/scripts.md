# Scripts & Automation

The project includes several scripts for setup, deployment, test data generation, and development automation. This page is a quick reference — each section links to detailed documentation where it exists.

## Quick Reference

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `scripts/download_docs.py` | Download regulatory PDFs, templates and validation-rule workbooks | After cloning the repo |
| `scripts/extract_validation_rules.py` | Re-extract the committed validation-rule JSON from those workbooks | After refreshing the workbooks |
| `scripts/deploy.py` | Version bump + PyPI publish | Cutting a release |
| `scripts/generate_dependency_graph.py` | Regenerate the module dependency graph docs page | After structural refactors |
| `scripts/arch_check.py` | The numbered architectural invariants — the project's main structural gate | Every commit (pre-commit hook) and in CI |
| `scripts/validator_reachability.py` | Census of which contracts-layer guards production can actually reach | When draining an `arch_check` check 20 failure |
| `scripts/check_parked_registers.py` | Shrink-only ratchet over the declared registers of parked findings | Runs in-suite on every pytest run; by hand when adding or draining a known disagreement |
| `tests/fixtures/generate_all.py` | Regenerate test fixture parquet files | After modifying fixture definitions |
| `workbooks/crr_expected_outputs/generate_outputs.py` | Generate CRR acceptance test golden files | After adding/changing CRR scenarios |
| `loop.sh` | Iterative Claude agent development loop | Hands-off agent-driven development |

---

## Setup Scripts

### `scripts/download_docs.py` — Download regulatory documents

Downloads the regulatory reference material to `docs/assets/`: the PRA PS1/26 and CRR PDFs, the reporting templates, and the two supervisory **validation-rule** sources. New collaborators should run this after cloning and installing dependencies. Files with known direct URLs are fetched automatically; remaining files are listed with manual download instructions.

Everything it fetches is gitignored (`docs/assets/*.pdf`, `*.PDF`, `*.zip` and the repo-wide `*.xlsx`), so this script — not the repository — is how `docs/assets/` gets populated and repopulated.

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

#### Validation-rule sources

Two manifest entries carry the published supervisory validation rules — the checks the regulators run against submitted COREP/OF returns:

| File | Framework | Contents |
|------|-----------|----------|
| `eba-validation-rules.xlsx` | CRR | EBA validation rules for COREP/FINREP, all framework versions. Sheet `v3.0(3.0.1)` is the current CRR one. |
| `boe-banking-taxonomy-validations-v4.0.0.zip` | Basel 3.1 | BoE banking XBRL taxonomy validation rules v4.0.0. The Banking reporting module holds the OF credit-risk tables. |

These are the raw inputs to [`scripts/extract_validation_rules.py`](#scriptsextract_validation_rulespy-extract-the-committed-validation-rule-json) below.

#### Archive entries and extraction

A manifest entry may name a member to pull out of a downloaded archive, via two optional `DocEntry` fields:

- `extract_member` — the member path inside the zip. Setting it marks the entry as an archive.
- `extract_as` — the filename to write it as, defaulting to the member's own basename.

The BoE zip uses both: it extracts the Banking reporting workbook to `docs/assets/boe-validation-rules-banking-reporting-v4.0.0.xlsx`. Archive entries therefore produce two lines in the run summary — one for the archive, one for the extracted member — and a successful extraction reports the status `extracted`:

```text
  skip     boe-banking-taxonomy-validations-v4.0.0.zip (already exists, 1.5 MB)
  extract  boe-validation-rules-banking-reporting-v4.0.0.xlsx ... done (375.6 KB)

Download Summary
==================================================
  Extracted:   1 files (375.6 KB)
  Skipped:     14 files (already present)
```

Extraction is idempotent and independent of the download outcome, which matters in practice: if the zip is already on disk but the workbook has been deleted, the script re-extracts it **without** re-downloading the archive. `--force` redoes both; `--dry-run` reports `would extract` and writes nothing. A missing archive member is reported as a failure in the summary and sets a non-zero exit code, rather than raising.

!!! info "See also"
    This script is referenced in the [Installation Guide](../getting-started/installation.md) setup steps. Full flag reference in [`scripts/README.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/scripts/README.md).

### `scripts/extract_validation_rules.py` — Extract the committed validation-rule JSON

Reads the two validation-rule workbooks fetched above and emits a filtered, machine-readable JSON extract to [Reporting Validation Rules](../reference/validation-rules/index.md), covering only the templates this project produces:

| Output | Framework | Scope |
|--------|-----------|-------|
| `crr-eba-v3.0-credit-risk.json` | CRR | COREP C 02.00 / C 07.00 / C 08.0x / C 09.0x / C 34.xx |
| `basel31-boe-v4.0.0-credit-risk.json` | Basel 3.1 | OF02 / OF07 / OF08 / OF09 / C08.04 / C09.04 / C34.xx |

The source workbooks are gitignored; **the JSON extracts are the committed artefact**, so downstream consumers and CI never need the raw xlsx. Re-run this only when the workbooks are refreshed — and commit the regenerated JSON with it.

```bash
# Re-extract and write the JSON
uv run python scripts/extract_validation_rules.py

# Fail non-zero if the committed JSON is stale (CI gate)
uv run python scripts/extract_validation_rules.py --check

# Print 3 parsed rules per source for inspection
uv run python scripts/extract_validation_rules.py --sample 3
```

If the workbooks are missing it exits non-zero and points you back at `download_docs.py` rather than failing obscurely.

### `scripts/deploy.py` — Version bumping and PyPI publication

Automates the release process end to end: checks that the local branch is current with `origin` and the tag is free (before the tests, so a stale checkout fails in seconds), runs tests, updates version strings across all files (`pyproject.toml`, `__init__.py`, docs, changelog), regenerates the version-stamped docs pages, syncs `uv.lock`, builds the package, commits and tags the release, pushes the branch and tag to `origin` in one atomic push, and optionally publishes to PyPI. Intended for maintainers.

```bash
# Bump patch version (e.g. 0.1.3 -> 0.1.4), commit, tag and push
uv run python scripts/deploy.py --bump patch

# Set specific version and publish
uv run python scripts/deploy.py 0.1.4 --publish

# Commit and tag locally without pushing
uv run python scripts/deploy.py 0.1.4 --no-push

# Dry run
uv run python scripts/deploy.py --bump patch --dry-run
```

Pushing the tag does not publish: `.github/workflows/publish.yml` runs on a published GitHub Release, so without `--publish` the follow-up is `gh release create vX.Y.Z --generate-notes`.

!!! info "See also"
    Full details (Windows batch wrapper, PyPI token setup, post-deployment git workflow) in [`scripts/README.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/master/scripts/README.md).

### `scripts/generate_dependency_graph.py` — Regenerate the module dependency graph

Builds the live import graph of `src/rwa_calc` with the [`curfew`](https://github.com/OpenAfterHours) dev tool and writes the [Module Dependencies](module-dependencies.md) page — a package-level overview plus the full module-level graph. Re-run by `scripts/deploy.py` on every release, so it normally only needs running by hand after a structural refactor.

```bash
# Regenerate the docs page
uv run python scripts/generate_dependency_graph.py

# Inspect the graph directly without writing docs
uv run curfew show --mermaid                       # full module graph to stdout
uv run curfew report rwa_calc.engine.classify  # one module's deps + dependents
```

---

## Architecture & Correctness Gates

### `scripts/arch_check.py` — The numbered architectural invariants

The project's structural gate. It runs on every commit through the pre-commit hook and again in CI, and each numbered check is a lesson that graduated out of `.claude/LESSONS.md` into something that fails automatically.

```bash
# Run every check against src/rwa_calc/ (the default target)
uv run python scripts/arch_check.py

# Scope to a subpath; whole-package checks skip themselves
uv run python scripts/arch_check.py src/rwa_calc/engine

# Bank an improvement in the architecture-debt ratchet (check 11)
uv run python scripts/arch_check.py --update-baseline
```

**The canonical list of checks is the module docstring in `scripts/arch_check.py` itself**, and it is deliberately not restated here — a numbered list copied into prose drifts from the code, which is the failure this project graduated the skill-value generator to stop. Read the docstring; each check names its own allowlist constant and the justification an entry there must carry.

Exit codes are `0` (all checks pass) and `1` (violations found). Soft warnings — currently the watchfire `unresolved` bucket and pack citations outside the bundled index — print under `[WARN]` and do not fail the run.

### `scripts/validator_reachability.py` — Contracts guard reachability census

The human-readable face of **check 20**. Check 20 fails the build when a guard in the `contracts/` layer is unreachable from production code; this script prints the same measurement as a census, so a developer draining the list sees the shape of the problem instead of a pass/fail.

```bash
uv run python scripts/validator_reachability.py
```

For each module under `contracts/` it reports the production entry points, the reachable guards, and the unreachable ones with their line counts. There are exactly two correct responses to a name in the unreachable list: wire it into a production path, or delete it. A validator that no production path invokes is not a guard — it is documentation with a green test attached, and the estate has shipped 402 lines of exactly that (see [the escape log](escape-log.md)).

The analysis has one implementation, in `arch_check.py`; this script reads it from there. The dependency points diagnostic → gate and never the other way, so the gate keeps working if this script is renamed or deleted. `tests/contracts/test_guard_reachability_gate.py` asserts both halves.

### `scripts/check_parked_registers.py` — The parked-findings ratchet

A *parked finding* is one a gate made and the estate then agreed to tolerate: a strict xfail against the oracle, a recorded classification disagreement, a published supervisory rule we knowingly break. `docs/development/escape-log.md`'s `caught-and-parked` escape class exists for what they share — a gate fires, the finding is recorded, and the wrong number ships anyway.

This script gates the two registers whose membership is **declared**:

- `tests/oracle/test_oracle.py::KNOWN_DISAGREEMENTS`
- `tests/conformance/classification_table.toml`'s `[[known_disagreement]]`

```bash
# Census — every entry and the plan bullet that owns it
uv run python scripts/check_parked_registers.py

# The gate (exit 1 on a failure)
uv run python scripts/check_parked_registers.py --check

# Prune ids that have left the register and refresh owners. Will NOT add.
uv run python scripts/check_parked_registers.py --update-baseline
```

Two conditions fail it. **An entry outside `scripts/parked_registers_baseline.json`** — the id set may only shrink, and `--update-baseline` deliberately refuses to bank an addition, so parking a new known-wrong number means hand-editing the baseline where a reviewer sees it. **An entry naming no owning plan bullet** — every reason string must carry an `OWNER: P<tier>.<n>` token pointing at the `IMPLEMENTATION_PLAN.md` item responsible for the fix (`.claude/LESSONS.md` B7). Removing an entry is free: that is the outcome the register exists to provoke, and `xfail(strict=True)` already fails the suite when a parked disagreement starts agreeing.

The set arithmetic and the owner grammar live in `scripts/tolerated_findings.py`, shared with the **measured** register in `tests/acceptance/reporting/test_supervisory_validations.py` — that one keeps its own runner, because its membership is a union over sixteen pipeline runs, but both use the same `diff`. `tests/contracts/test_parked_register_ratchet.py` runs this gate on every pytest run, so it cannot rot unwired.

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

Runs Claude Code in headless mode, reading a prompt file from `prompts/` (`prompts/build.md` or `prompts/plan.md`), executing the instructions, pushing changes, and repeating for a configurable number of iterations. Useful for hands-off agent-driven development sessions.

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
