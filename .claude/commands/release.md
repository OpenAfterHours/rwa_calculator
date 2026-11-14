---
description: Release one workspace package (rwa-calc, rwa-filer) or all of them — preview the changelog promotion, confirm, then run scripts/deploy.py, which commits, tags, pushes and creates the GitHub Release (publish.yml uploads to PyPI).
---

You are running a release. The repository is a uv workspace whose packages are
versioned, tagged and published to PyPI **independently**: the root project
`rwa-calc`, plus every member in `scripts/deploy.py::MEMBER_RELEASES` (today
only `rwa-filer`). `scripts/deploy.py` does the work: it checks the remote, runs
the tests, bumps versions, promotes the `[Unreleased]` changelog bullets into a
new version section, builds, commits, tags, pushes the branch and tag to
`origin`, and creates the GitHub Release for the tag. **The GitHub Release is
the publish step**: `.github/workflows/publish.yml` runs on a published release,
picks the package from the tag prefix, and uploads that package to PyPI. This
command wraps the script with a preview and a confirmation so the operator
checks what will be released before any of it happens.

## Usage

```
/release [TARGET] [VERSIONS] [FLAGS]
```

**TARGET** — which package(s):

| TARGET | Releases | Tag | Script call |
|---|---|---|---|
| `rwa-calc` (or omitted) | the root project alone | `v<ver>` | `deploy.py <ver>` |
| `rwa-filer` (any `MEMBER_RELEASES` key) | that member alone | `<name>-v<ver>` | `deploy.py --package <name> <ver>` |
| `all` | every workspace package, dependencies first | one tag per package | `deploy.py --package all --set-version <name>=<ver> ...` |

An omitted TARGET means `rwa-calc`, as it always has. Anything that is not a
package name, `all`, a version, a bump kind or a flag below is a usage error:
stop and say so rather than guessing.

**VERSIONS**:

- For one package: an explicit version (`0.3.35`), a bump kind
  (`patch` / `minor` / `major`), or nothing (= `patch`).
- For `all`: a bump kind applied to every package (default `patch`), and/or
  `NAME=VERSION` pins for individual packages
  (`/release all rwa-filer=0.1.0 rwa-calc=0.3.35`, `/release all minor rwa-filer=0.1.0`).
  A bare version (`/release all 0.4.0`) is a usage error: the packages do not
  share a version.

**FLAGS** (same meaning for every TARGET; pass only when the operator asked):

- `--no-github-release` — push the tag(s) but create no release, so nothing is
  published.
- `--no-push` — commit and tag locally only.
- `--publish` — upload to PyPI from this machine with `uv publish` **instead of**
  via the GitHub Release (which is then skipped, because a release would run
  `publish.yml` onto a version PyPI already has). The CI path is the normal one;
  this is the fallback for when it is unavailable.

Examples:

```
/release rwa-filer 0.1.0                       # rwa-filer alone, at 0.1.0
/release rwa-calc minor                        # rwa-calc alone, minor bump
/release patch                                 # rwa-calc alone (TARGET omitted)
/release all                                   # every package, patch bump each
/release all rwa-filer=0.1.0 rwa-calc=0.3.35   # every package, versions pinned
```

## Why order matters, and what `all` does about it

An installed `rwa-calc` resolves `rwa-filer` from PyPI, so an `rwa-calc` release
that needs a new `rwa-filer` only installs once that `rwa-filer` is published.
`scripts/deploy.py` enforces this in every mode:

- **Single `rwa-calc` release:** refused before the tests unless a published
  `rwa-filer` satisfies the range in the root `pyproject.toml`. If it refuses,
  release `rwa-filer` first (or use `all`) — never reach for
  `--skip-filer-check` on your own.
- **Single member release:** refused before anything changes if another
  workspace package's declared range for it excludes the new version (e.g.
  `rwa-filer 0.2.0` against `rwa-calc`'s `rwa-filer>=0.1,<0.2`). `uv lock`
  would accept it, so nothing else would notice that `rwa-calc` was being
  tested against a version its users never install. Widening the range is a
  code change for the operator to make and review — do not edit it yourself
  to get the release through.
- **`all`:** the script reads every package's declared dependencies and
  releases in dependency order (today: `rwa-filer`, then `rwa-calc`). Before the
  first package changes, it checks every tag's remote state, every range, and
  runs **every** package's test suite, so a failure there publishes nothing.
  Then it releases one package at a time, and after a package that a later one
  depends on, **waits until that exact version is on PyPI** (up to 30 min)
  before starting the next. A new workspace package joins `all` automatically
  once it is in `MEMBER_RELEASES` — `tests/contracts/test_release_coverage.py`
  fails until it is.

Never release several packages by chaining single-package `deploy.py` calls
yourself: `all` exists so the ordering, the up-front checks and the PyPI wait
live in one tested place.

## Step 0 — pre-flight

Releases are cut from `master`. Before previewing anything:

```
git fetch origin
git status -sb
```

- Not on `master`: stop and say so. Switch only if the operator asked for it.
- Behind `origin/master`: `git pull --ff-only`. A fast-forward is the only
  acceptable fix here — never rebase or merge to get there.
- Diverged (ahead AND behind) or dirty: stop and surface it. The script's own
  pre-flight would refuse too, but only after you had shown the operator a
  preview that cannot be released.

## Step 1 — resolve the plan

Parse `$ARGUMENTS` per **Usage**. Then resolve each package being released to a
concrete `current → new` version and tag:

- `rwa-calc`: current version from the root `pyproject.toml`; tag `v<new>`.
- a member: current version from `MemberRelease.pyproject`
  (`packages/rwa-filer/pyproject.toml`); tag `<tag_prefix><new>`.
- `all`: every package, in the order the script will use. Get both the order
  and the versions from the script itself rather than working them out:

  ```
  uv run python scripts/deploy.py --package all [--bump K] [--set-version N=V ...] --dry-run
  ```

  Its first lines list `name: current -> new (tag)` in release order. If it
  refuses (a range excludes a new version, a malformed pin), relay the error
  and stop.

**Never-released current versions.** For each package, check whether its
*current* version was ever released: `git ls-remote --tags origin
refs/tags/<tag-for-current>`. If that tag does not exist and the plan would
bump past it (e.g. `rwa-filer` at `0.1.0`, never released, and a `patch` bump
would publish `0.1.1`), say so and offer the current version instead —
`rwa-filer=0.1.0` for `all`, or `/release rwa-filer 0.1.0`. Do not change the
plan unasked; the operator decides in Step 3.

State the plan in one line per package: `rwa-filer: 0.1.0 → 0.1.0 (rwa-filer-v0.1.0)`.

## Step 2 — preview each [Unreleased] promotion

For each package in the plan, read its changelog — `docs/appendix/changelog.md`
for `rwa-calc`, `MemberRelease.changelog` for a member
(`packages/rwa-filer/CHANGELOG.md`) — and extract the `[Unreleased]` block
(everything between `## [Unreleased]` and the next `---`).

Classify each:

- **Empty / missing** or **placeholder-only** (every bullet is
  `- (Next release changes will go here)`) — warn that the new version section
  will be the stub `Version bump for PyPI release`. Under `all`, say plainly
  that this package would be published with no recorded change, so the
  operator can choose a single-package release instead.
- **Has real bullets** — per package, count the bullets per subsection and list
  each subsection header + count, e.g.:
  ```
  rwa-filer: promoting [Unreleased] into ## [0.1.0] - YYYY-MM-DD
    ### Added   (24 bullets)
  ```
  Then quote the first ~80 chars of each real bullet so the operator can
  sanity-check what is moving. The same section becomes the body of that
  package's GitHub Release, with GitHub's generated PR list appended, so this
  is also the release notes.

## Step 3 — confirm

Print the plan, the flags and the Step 2 summary. Then state plainly what the
run will do once every check has passed, one line per package, in order:

```
This will, in order:
  1. push rwa-filer-v0.1.0 and create GitHub Release rwa-filer-v0.1.0
     -> publish.yml uploads rwa-filer 0.1.0 to PyPI
     -> wait until rwa-filer 0.1.0 is on PyPI
  2. push v0.3.35 and create GitHub Release v0.3.35
     -> publish.yml uploads rwa-calc 0.3.35 to PyPI
PyPI uploads are irreversible.
```

(One numbered entry for a single-package release; adjust for
`--no-github-release`, `--no-push` or `--publish`.) Then **stop and wait** for
the operator to confirm explicitly. Do NOT use `AskUserQuestion` — print the
summary and a `Proceed? (yes/no)` prompt and end the turn. The operator's next
message is the go/no-go, and it covers **every** package in the plan at once.
This is the confirmation the script would otherwise ask for itself; Step 4
passes `--yes` on the strength of it.

If the operator declines, or changes the plan, stop. Do not mutate anything; a
changed plan goes back through Steps 1–3.

## Step 4 — run scripts/deploy.py

On `yes`, run exactly one script invocation. Always pass explicit versions
(not `--bump`) — they were resolved in Step 1 and confirmed in Step 3:

```
uv run python -u scripts/deploy.py <ver> --yes                                  # rwa-calc
uv run python -u scripts/deploy.py --package rwa-filer <ver> --yes              # one member
uv run python -u scripts/deploy.py --package all \
    --set-version rwa-filer=<ver> --set-version rwa-calc=<ver> --yes            # all: pin EVERY package
```

For `all`, pass a `--set-version` for every package in the plan, so the script
cannot resolve a version the operator did not see. Append the operator's flags
(`--no-github-release`, `--no-push`, `--publish`) unchanged. Never pass `--yes`
without a `yes` from the operator in this conversation.

**Run it in the background.** A release runs the full test suite, and `all`
then waits on PyPI between packages — together well past a foreground command's
time limit, and a release killed between its push and its GitHub Release is
the worst place to stop. Start it as a background Bash command
(`run_in_background: true`, timeout 90 minutes) and wait for the completion
notification; do not poll it with `sleep`. `-u` keeps its output flowing to the
log, so you can read progress if the operator asks mid-run.

What the script does, per mode:

- **Single package**: pre-flight (fetches `origin`; refuses on a detached HEAD,
  a branch behind its upstream, a tag already on the remote, or — when a
  GitHub Release will follow — a logged-out `gh`), then its tests, then bump,
  changelog promotion, regenerated docs (`rwa-calc` only), lock, build,
  distribution check, release notes, commit, tag, atomic push of branch + tag,
  and finally `gh release create --verify-tag`, which fires `publish.yml`.
  `rwa-calc` additionally checks a satisfying `rwa-filer` is on PyPI, before
  its tests.
- **`all`**: every tag's pre-flight, then every package's suite, then each
  package through the single-package flow above (tests not repeated), with the
  PyPI wait after any package something later depends on.

If any step fails, stop and surface the exact script output. Do not retry
automatically. In particular:

- A failed push leaves the commit and tag local; the script prints the manual
  push command. Relay it, do not run it, and do not re-run the script (it would
  refuse on the existing tag).
- A failed release creation leaves the tag pushed and nothing published; the
  script prints the manual `gh release create` command. Relay it — running it
  is the publish decision, and that is the operator's.
- Under `all`, the script also prints which packages were already released and
  the single-package commands for the rest, in order. Relay that list as the
  way to finish; finishing it is a new release, which needs its own `yes`.
- A PyPI wait that times out means the dependency's publish run is slow or
  failed. Run `gh run list --workflow=publish.yml --limit 3` once and report
  it. Do not release the dependents until the dependency is on PyPI.

## Step 5 — report

On success, for each package released, one line:

```
rwa-filer 0.1.0: committed, tagged, pushed, GitHub Release rwa-filer-v0.1.0 created.
rwa-calc 0.3.35: committed, tagged, pushed, GitHub Release v0.3.35 created.
```

Then run `gh run list --workflow=publish.yml --limit <number of packages>` once
and report those runs' status lines. Do not poll. Give each PyPI URL
(`https://pypi.org/project/<name>/<ver>/`) as where it lands — under `all`,
every package but the last is already confirmed on PyPI by the script's wait.

- Under `--no-github-release`: say the tags are pushed and nothing is
  published, and print the manual `gh release create` command(s) the script
  emitted.
- Under `--no-push`: print the manual push and release commands instead.
- Under `--publish`: print the PyPI URLs, and say there is no GitHub Release.

## Constraints

- One `scripts/deploy.py` invocation per `/release`. `all` is one invocation;
  never emulate it by chaining single-package calls.
- The GitHub Release is the PyPI publish. It, like `--publish`, requires the
  operator's explicit `yes` in Step 3 every time; a `yes` in an earlier release
  does not carry over.
- Never pass `--skip-tests` automatically. If tests fail, surface the failure;
  do not bypass.
- Never pass `--skip-filer-check` or edit a dependency range to get a release
  through. Both are the operator's call.
- The push and the release are the script's job, not yours. It pushes the
  branch and the single release tag atomically, then creates the release from
  that tag, after every check has passed. Never push ahead of it, never
  `--force`, never `git push --tags`, and never `gh release create` by hand
  unless the operator asks for exactly that after a failure.
- Never `git reset`, `git tag -d` or `gh release delete` to "recover" from a
  failed release. Stop and let the operator decide.
- If an `[Unreleased]` block is missing or placeholder-only, still proceed if
  the operator confirms — the script falls back to the
  `Version bump for PyPI release` stub bullet, and the release notes say the
  same.
