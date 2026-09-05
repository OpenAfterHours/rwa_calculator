---
description: Run the release flow — preview the changelog promotion, run scripts/deploy.py, commit, tag and push. Optionally publish to PyPI.
---

You are running a release. The script `scripts/deploy.py` checks the remote,
runs the tests, bumps versions, promotes `[Unreleased]` changelog bullets into a
new version section, regenerates the generated docs, syncs `uv.lock`, builds,
commits, tags, and pushes the branch and the tag to `origin`. This command wraps
that flow with a preview + confirmation step so the operator can verify the
changelog promotion before it is committed and pushed.

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

## Step 1 — parse args

`$ARGUMENTS` may be:

- An explicit version: `0.2.15`
- A bump kind: `patch` / `minor` / `major`
- Empty: default to `patch` bump
- A trailing `--publish` flag (in any position): publish to PyPI after the push
- A trailing `--no-push` flag: commit and tag locally without pushing. Only pass
  it when the operator asked for it.

Resolve to a concrete `new_version` by reading the current version from
`pyproject.toml` (line containing `version = "..."`) and applying the bump if
needed. Confirm to the operator in one line: `Current: X.Y.Z → New: A.B.C`.

## Step 2 — preview the [Unreleased] promotion

Read `docs/appendix/changelog.md`. Extract the `[Unreleased]` block (everything
between `## [Unreleased]` and the next `---`).

Classify:

- **Empty / missing** — say so; warn that the new version section will be the
  hardcoded `Version bump for PyPI release` stub.
- **Placeholder-only** — every bullet is `- (Next release changes will go here)`;
  same warning as above.
- **Has real bullets** — count the bullets per subsection and list each
  subsection header + count, e.g.:
  ```
  Promoting from [Unreleased] into ## [0.2.15] - YYYY-MM-DD:
    ### Changed (1 bullet)
    ### Added   (5 bullets)
  ```
  Then quote the first ~80 chars of each real bullet so the operator can sanity-
  check what is moving.

## Step 3 — confirm

Print the resolved version, the publish flag, and the summary from step 2, then
**stop and wait** for the operator to confirm explicitly. Do NOT use
`AskUserQuestion` — just print the summary and a `Proceed? (yes/no)` prompt and
end the turn. The operator's next message is the go/no-go.

Say in the summary that the script will push the release to `origin` once
every check has passed — the operator is confirming the push, not only the
commit.

If the operator declines, stop. Do not mutate anything.

## Step 4 — run scripts/deploy.py

On `yes`, invoke the script via Bash:

```
uv run python scripts/deploy.py <new_version>           # push, no PyPI
uv run python scripts/deploy.py <new_version> --publish # push, then uv publish
uv run python scripts/deploy.py <new_version> --no-push # commit + tag only
```

Always pass the explicit version (not `--bump`) — resolution happened in step 1
and the operator confirmed it.

Stream the output. The script:

1. Pre-flight: fetches `origin` and refuses if HEAD is detached, if the branch
   is behind its upstream, or if `v<ver>` already exists on the remote. This
   runs BEFORE the tests so a stale checkout costs seconds, not a suite run.
2. Runs tests (`uv run pytest -x -q`).
3. Updates version strings in pyproject, `__init__.py`, docs.
4. Promotes `[Unreleased]` via `scripts/_deploy_changelog.py`.
5. Regenerates the citation matrix, dependency graph, regulatory tables and
   confidence matrix.
6. `uv sync`, `uv build`, `scripts/check_distribution.py`.
7. Stages release files, commits `chore(release): bump version to <ver>`, tags
   `v<ver>`.
8. Pushes the branch and the tag to `origin` in one atomic push
   (`git push --atomic origin <branch> refs/tags/v<ver>`). Skipped under
   `--no-push`.
9. If `--publish`: `uv publish`.

If any step fails, stop and surface the failure to the operator with the exact
script output. Do not retry automatically. A failed push in particular leaves
the commit and tag local; the script prints the manual push command — relay
it, do not run it, and do not re-run the script (it would refuse on the
existing tag).

## Step 5 — report

On success, print:

```
Release v<ver> committed, tagged and pushed to origin (<branch>, v<ver>).
```

Then say how PyPI stands. Pushing the tag does NOT publish:
`.github/workflows/publish.yml` runs on a *published GitHub Release*, not on a
tag push. So:

- Without `--publish`:
  ```
  Not published to PyPI. To publish via CI:
    gh release create v<ver> --generate-notes
  ```
- With `--publish`: print the PyPI URL
  (`https://pypi.org/project/rwa-calc/<ver>/`).

Under `--no-push`, print the manual push command the script emitted instead of
the first line.

## Constraints

- One release per invocation. Do not chain.
- `--publish` requires explicit operator confirmation in step 3 even if it was on
  the slash-command args. PyPI uploads are irreversible.
- Never pass `--skip-tests` automatically. If tests fail, surface the failure;
  do not bypass.
- The push is the script's job, not yours. It pushes the branch and the single
  release tag atomically, after every check has passed. Never push ahead of it,
  never `--force`, and never `git push --tags` — that sweeps every stray local
  tag onto the remote.
- Never `git reset` or `git tag -d` to "recover" from a failed release. Stop and
  let the operator decide.
- If `[Unreleased]` is missing or placeholder-only, still proceed if the operator
  confirms — the script will fall back to the `Version bump for PyPI release`
  stub bullet.
