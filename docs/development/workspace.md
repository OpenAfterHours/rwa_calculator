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

While `rwa-filer` is `0.x`, `rwa-calc` pins its minor version
(`>=0.1,<0.2`). A breaking `rwa-filer` change is a minor bump, so `rwa-calc`
never picks one up unannounced; widening the range is an explicit edit to the
root `pyproject.toml`.

### One-time PyPI set-up for `rwa-filer`

PyPI trusted publishing is configured per PyPI project. Before the first
`rwa-filer` release, add a *pending publisher* for the project name `rwa-filer`
on PyPI, naming this repository, the workflow file `publish.yml` and the
environment `pypi` — the same values the `rwa-calc` project uses.
