# Workspace: two packages in one repository

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
that releases two Python packages on their own versions:

| Package | Import name | Where | What it is |
|---------|-------------|-------|------------|
| `rwa-calc` | `rwa_calc` | repository root (`src/rwa_calc`) | The calculator: pipeline, rulepacks, reporting templates, UI |
| `rwa-filer` | `rwa_filer` | `packages/rwa-filer` | The filing package: validates regulatory returns against the published supervisory rules and writes them for submission |

`rwa-filer` is standalone. It can be installed without `rwa-calc` and fed
template-level figures from any system. `rwa-calc` depends on it and reaches it
through one adapter.

## Layout

```
rwa_calculator/                 workspace root AND the rwa-calc project
├── pyproject.toml              [project] rwa-calc + [tool.uv.workspace]
├── uv.lock                     one lockfile for both packages
├── src/rwa_calc/               unchanged
├── tests/                      rwa-calc's tests (unchanged)
├── scripts/                    gates and release tooling for both
└── packages/
    └── rwa-filer/
        ├── pyproject.toml      [project] rwa-filer — depends on polars only
        ├── CHANGELOG.md
        ├── src/rwa_filer/
        └── tests/              rwa-filer's own suite
```

The root stays the `rwa-calc` project and becomes the workspace root; uv allows
one directory to be both. That is deliberate: `src/rwa_calc`, `tests/` and
`scripts/` did not move, so no gate path changed. The alternative — a virtual
root with both packages under `packages/` — would have moved every path the
gates hard-code.

The two additions to the root `pyproject.toml`:

```toml
[project]
dependencies = [
    # ...
    "rwa-filer>=0.1,<0.2",
]

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
rwa-filer = { workspace = true }
```

Inside this repository `rwa-filer` resolves from the workspace (an editable
install of `packages/rwa-filer`). In a built `rwa-calc` wheel the same line is an
ordinary `Requires-Dist: rwa-filer<0.2,>=0.1`, resolved from PyPI.

## What lives where

| Concern | Package | Location |
|---------|---------|----------|
| Published rule extracts, and the importer that builds them | `rwa-filer` | `rwa_filer.rules` |
| Rule engine: parse, expand, evaluate, report | `rwa-filer` | `rwa_filer.validate` |
| Taxonomy packs: the reportable cells and data points of a module | `rwa-filer` | `rwa_filer.taxonomy` |
| The canonical return, its structure checks and its file readers | `rwa-filer` | `rwa_filer.model`, `rwa_filer.validate.structure`, `rwa_filer.readers` |
| The XBRL instance (writer and reader) and the filing package | `rwa-filer` | `rwa_filer.xbrl`, `rwa_filer.filing` |
| Which of our bundle members carries each published table code | `rwa-calc` | `rwa_calc.reporting.filing.bindings` |
| Which of our per-class sheets each published sheet code addresses | `rwa-calc` | `rwa_calc.reporting.filing.sheet_maps` |
| Mapping the engine's findings onto `CalculationError` (`VAL001`–`VAL003`) | `rwa-calc` | `rwa_calc.reporting.filing.checks` |
| Re-addressing our generated cells to the taxonomy's coordinates, and accounting for those with no place | `rwa-calc` | `rwa_calc.reporting.filing.canonical` |
| The filing package for a generated estate; refusing an incomplete one | `rwa-calc` | `rwa_calc.reporting.filing.package` |
| Computing the template figures | `rwa-calc` | `rwa_calc.reporting.corep`, `rwa_calc.reporting.pillar3` |

`rwa_calc.reporting.filing` is the adapter. Everything that knows about the
calculator's bundles, sheet names or exposure classes is on its side of the
boundary; everything that knows how to load, parse and evaluate a published rule
is in `rwa-filer`. The adapter re-exports none of the engine's names — import
those from `rwa_filer` directly.

## The filing-mapping ratchet

`rwa_calc.reporting.filing.canonical.build_canonical_return` turns a generated
Basel 3.1 COREP bundle into a canonical return. Every generated cell is either
placed on a taxonomy data point or returned as unplaced with a reason. None is
dropped.

`scripts/filing_mapping_report.py` runs that over every Basel 3.1 portfolio in
the supervisory register's matrix and ratchets two counts against
`scripts/filing_mapping_baseline.json`:

| Count | Banked | Rule |
|-------|-------:|------|
| `placed_cells` — distinct cells that land on a taxonomy data point | 1,911 | May not fall |
| `unplaced_figures` — distinct cells holding a non-zero figure with no place | 1,025 | May not rise, in total or for any (template, reason) |
| `structure_findings` — placed facts that still cannot be filed | 8 | May not rise, in total or for any (finding, table) |

A zero in a cell the taxonomy lacks loses nothing and is not counted.

The eight structure findings are defects in the generated estate:

| Finding | Table | What is wrong |
|---------|-------|---------------|
| `STR007` | OF 02.00 | Rows 0050 and 0060, column 0010, are one data point in the taxonomy (with OF 07.00 total sheet, column 0220) and hold different values. |
| `STR007` | OF 08.01 | Column 0276 (output-floor RWEA) disagrees with the OF 02.00 column 0020 cell that is the same data point. |
| `STR007` | OF 02.01 | Row 0080, column 0030 (U-TREA) disagrees with OF 02.00 row 0010, column 0010. |
| `STR006` | OF 08.03 | Column 0080 is an integer in the taxonomy and holds a fractional maturity. |

The unplaced figures are the work list. The reasons, largest first:

| Reason | Figures | What it means |
|--------|--------:|---------------|
| `sheet_coarser_than_published_axis` | 816 | Our IRB sheets (OF 08.01–08.05) were per exposure class. The published sheet axis also splits by approach and by SME / non-SME, so a figure on one of our sheets could not be assigned to one published sheet. Cleared 2026-11-13: OF 08.01, 08.02, 08.03 and 08.05 are generated on the published seventeen-sheet axis (see [COREP reporting](../features/corep-reporting.md)). C 08.04 stays keyed by exposure class, and its figures now report as `sheet_has_no_published_code`. |
| `cell_not_reportable` | 102 | The row and column both exist, but the taxonomy greys that cell. |
| `open_rows_not_mapped` | 40 | OF 08.02 has open rows (obligor grades); the adapter does not yet map them. |
| `open_key_not_a_member` | 32 | A sheet key that is not a member of the table's open axis (OF 08.06 specialised-lending types, OF 34.02 netting sets). |
| `column_not_in_taxonomy` | 24 | A column the published table does not have. |
| `row_not_in_taxonomy` | 11 | A row the published table does not have. |

```bash
uv run python scripts/filing_mapping_report.py              # measure and print
uv run python scripts/filing_mapping_report.py --check      # gate against the baseline
uv run python scripts/filing_mapping_report.py --update-baseline
```

The gate is its own CI job, `Filing Mapping Ratchet`. It is not part of
`arch_check`, and its pytest mirror is `slow`-marked, so nothing in the dev loop
runs the measurement. Bank a deliberate move with `--update-baseline` and say
why in the baseline's `_note`.

## The referee differential

Every other check on the filing package is this repository checking its own
work. The referee differential asks someone else. For each Basel 3.1 portfolio
whose generated estate has no structure finding, it writes the XBRL instance,
runs [Arelle](https://arelle.org) on it against the Bank of England's taxonomy
package, and requires two things: Arelle raises no error, and Arelle's verdict
on every rule is the verdict of `rwa-filer`'s own rule engine.

```bash
# The Bank's package at .taxonomy/boe-banking-v411.zip; Arelle in its own environment
RWA_FILER_ARELLE_PYTHON=/path/to/arelle-venv/bin/python \
    uv run python scripts/referee_differential.py --check
```

Five of the thirteen Basel 3.1 portfolios qualify today. The other eight carry
structure findings, which is the filing-mapping ratchet's business, and are not
filed. A portfolio that joins or leaves the five must be re-banked and
explained.

The gate needs Arelle and the Bank's package, neither of which is in the
repository, and takes several minutes and about 3 GB per return. It therefore
runs in its own workflow, `Referee Differential`, and not in `ci.yml`: on a pull
request or push that touches the code it referees, weekly, and on demand. A pull
request that touches none of those paths does not run it. Its baseline logic
and its workflow wiring are pinned by the fast tests in
`tests/contracts/test_referee_differential.py`.

A disagreement is never re-banked as a number. It means the engine or Arelle
has misread a rule, or the taxonomy's formula differs from the workbook text,
and each of those has happened: see
[How the rules are evaluated](../rwa-filer/index.md#how-the-rules-are-evaluated).

## The one rule: the dependency points one way

`rwa-calc` may import `rwa_filer`. **`rwa_filer` may never import `rwa_calc`.**

The shared workspace environment makes `rwa_calc` importable from everywhere, so
an import in the wrong direction passes lint, types and the whole test suite
here — and raises `ModuleNotFoundError` for the first person who installs the
`rwa-filer` wheel without the calculator. Two gates close that, and they catch
different things:

| Gate | What it proves | Where |
|------|----------------|-------|
| `arch_check` check 23 | No module under `packages/rwa-filer/src/rwa_filer` imports `rwa_calc`, as a statement or through `importlib.import_module` / `__import__`. Also holds the member to checks 1, 2 and 14. | `scripts/arch_check.py` — every commit, and CI's lint job |
| `rwa-filer (isolated)` CI job | The member's declared dependencies are complete: its suite passes in an environment built with `uv sync --package rwa-filer`, which contains `rwa-filer`, Polars and pytest and nothing from `rwa-calc`. | `.github/workflows/ci.yml` |

The second gate is the only place a *missing dependency declaration* shows up. A
new runtime dependency for `rwa-filer` goes in `packages/rwa-filer/pyproject.toml`
— adding it to the root project alone would work locally and fail there.

## Day-to-day commands

```bash
# The whole dev environment (both packages, all extras)
uv sync --all-extras

# rwa-calc's tests — does NOT collect packages/
uv run pytest tests/

# rwa-filer's tests, in the shared environment
uv run pytest packages/rwa-filer

# Lint, format and types cover both
uv run ruff check src tests scripts packages
uv run ruff format --check src tests scripts packages
uv run ty check src/rwa_calc/
uv run ty check packages/rwa-filer/src/
```

`rwa-filer` carries its own `[tool.pytest.ini_options]`. pytest takes its
configuration from the closest `pyproject.toml` that has one, so the member's
suite runs without the root project's `addopts` (`-n 8`, the marker filter,
`--benchmark-disable`), which need plugins an `rwa-filer`-only environment does
not install. Its `tests/` directory has no `__init__.py`, so it can never collide
with the root `tests` package.

To reproduce the isolated CI job without disturbing the dev environment, build
the member's environment somewhere else:

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/rwa-filer-venv
uv sync --package rwa-filer
RWA_FILER_ISOLATED=1 uv run --no-sync pytest packages/rwa-filer
unset UV_PROJECT_ENVIRONMENT
```

!!! warning "`uv sync --package rwa-filer` rebuilds the active environment"
    Without `UV_PROJECT_ENVIRONMENT`, that command makes `.venv` hold the member
    alone and removes everything else. Run `uv sync --all-extras` to restore it.

## Releasing

Each package has its own version, changelog, tag and PyPI project.

| | `rwa-calc` | `rwa-filer` |
|---|---|---|
| Version files | `pyproject.toml`, `src/rwa_calc/__init__.py`, `docs/overview.md`, `docs/overrides/main.html` | `packages/rwa-filer/pyproject.toml`, `packages/rwa-filer/src/rwa_filer/__init__.py` |
| Changelog | `docs/appendix/changelog.md` | `packages/rwa-filer/CHANGELOG.md` |
| Tag | `v0.3.35` | `rwa-filer-v0.1.0` |
| Release command | `uv run python scripts/deploy.py 0.3.35` | `uv run python scripts/deploy.py --package rwa-filer 0.1.0` |
| Slash command | `/release rwa-calc 0.3.35` | `/release rwa-filer 0.1.0` |
| Build | `uv build` → `dist/` | `uv build --package rwa-filer -o dist/rwa-filer` |
| PyPI project | `rwa-calc` | `rwa-filer` |

`.github/workflows/publish.yml` runs on every published GitHub Release and
chooses the package from the tag prefix: `v*` publishes `rwa-calc`,
`rwa-filer-v*` publishes `rwa-filer`, and any other tag fails the run without
publishing anything. Each package builds into its own directory so one release
can never check or upload the other's artefacts.

### Release order

**Release `rwa-filer` first.** An installed `rwa-calc` resolves `rwa-filer` from
PyPI, so an `rwa-calc` release that needs a new `rwa-filer` version only installs
once that version is published.

`scripts/deploy.py` enforces this. Before an `rwa-calc` run that publishes, it
reads the `rwa-filer` range from the root `pyproject.toml`, asks PyPI which
versions exist, and refuses the release — before the tests, before anything is
bumped — unless one satisfies the range. "PyPI could not be reached" also
refuses: unknown is not published. Nothing inside the workspace could catch
this, because here `rwa-filer` always resolves from the checkout.
`--skip-filer-check` bypasses it for the case where the version has been
confirmed by hand.

While `rwa-filer` is `0.x`, `rwa-calc` pins its minor version
(`>=0.1,<0.2`). A breaking `rwa-filer` change is a minor bump, so `rwa-calc`
never picks one up unannounced; widening the range is an explicit edit to the
root `pyproject.toml`. `scripts/deploy.py` refuses to release a member at a
version another workspace package's declared range excludes, before anything
changes. Nothing else would catch it: `uv lock` takes a workspace member at
whatever version it is, so every test here would run `rwa-calc` against the new
`rwa-filer` while an installed `rwa-calc` resolved the old one from PyPI.

### Releasing every package at once

```bash
uv run python scripts/deploy.py --package all --set-version rwa-filer=0.1.0 --set-version rwa-calc=0.3.35
```

or `/release all rwa-filer=0.1.0 rwa-calc=0.3.35`. Packages not pinned with
`--set-version` take `--bump` (default `patch`); a single positional version is
refused, since the packages do not share one. The run:

1. Orders the packages so each follows the workspace packages it depends on,
   read from each package's own `pyproject.toml` (today: `rwa-filer`, then
   `rwa-calc`).
2. Checks every range, every tag's remote state and runs every package's test
   suite before the first package changes — a failure here publishes nothing.
3. Releases each package through the same flow a single-package run uses.
4. After a package that a later one depends on, waits (up to 30 minutes) until
   that exact version is on PyPI before starting the next. If it times out, it
   stops and prints the single-package commands that finish the rest.

### Adding a workspace package

A new member under `packages/` joins `--package all` once it has an entry in
`scripts/deploy.py::MEMBER_RELEASES`, a build directory in
`scripts/check_distribution.py::DIST_DIRS`, and a tag-prefix arm plus a
version-check step in `.github/workflows/publish.yml`.
`tests/contracts/test_release_coverage.py` fails until all three exist. The
fourth step — a trusted (pending) publisher for the new PyPI project, as below —
cannot be checked from the repository.

### One-time PyPI set-up for `rwa-filer`

PyPI trusted publishing is configured per PyPI project. Before the first
`rwa-filer` release, add a *pending publisher* for the project name `rwa-filer`
on PyPI, naming this repository, the workflow file `publish.yml` and the
environment `pypi` — the same values the `rwa-calc` project uses.
