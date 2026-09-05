---
description: Run the release flow — preview the changelog promotion, run scripts/deploy.py, commit, tag, push and create the GitHub Release (which publishes to PyPI via CI).
---

You are running a release. The script `scripts/deploy.py` checks the remote,
runs the tests, bumps versions, promotes `[Unreleased]` changelog bullets into a
new version section, regenerates the generated docs, syncs `uv.lock`, builds,
commits, tags, pushes the branch and the tag to `origin`, and creates the
GitHub Release for the tag. **The GitHub Release is the publish step**:
`.github/workflows/publish.yml` runs on a published release and uploads the
version to PyPI. This command wraps that flow with a preview + confirmation
step so the operator can verify the changelog promotion before any of it
happens.

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
- A trailing `--no-github-release` flag: push the tag but create no release,
  so nothing is published. Only pass it when the operator asked for it.
- A trailing `--no-push` flag: commit and tag locally only. Same rule.
- A trailing `--publish` flag: upload to PyPI from this machine with
  `uv publish` **instead of** via the GitHub Release. The script skips the
  release in that case, because a release would run `publish.yml` onto a
  version PyPI already has. The CI path is the normal one; this is the
  fallback for when it is unavailable.

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
  check what is moving. This same section becomes the body of the GitHub
  Release, with GitHub's generated PR list appended, so what the operator is
  checking here is also the release notes.

## Step 3 — confirm

Print the resolved version, the flags, and the summary from step 2. Then state
plainly what the run will do once every check has passed:

```
This will push v<ver> to origin and create GitHub Release v<ver>, which runs
publish.yml and uploads rwa-calc <ver> to PyPI. PyPI uploads are irreversible.
```

(Adjust for `--no-github-release`, `--no-push` or `--publish`.) Then **stop and
wait** for the operator to confirm explicitly. Do NOT use `AskUserQuestion` —
just print the summary and a `Proceed? (yes/no)` prompt and end the turn. The
operator's next message is the go/no-go. This is the confirmation the script
would otherwise ask for itself; step 4 passes `--yes` on the strength of it.

If the operator declines, stop. Do not mutate anything.

## Step 4 — run scripts/deploy.py

On `yes`, invoke the script via Bash with `--yes`, because the operator has
just confirmed the irreversible steps and the script's own prompt cannot be
answered from here:

```
uv run python scripts/deploy.py <new_version> --yes                      # push + GitHub Release -> PyPI via CI
uv run python scripts/deploy.py <new_version> --yes --no-github-release  # push only, nothing published
uv run python scripts/deploy.py <new_version> --yes --no-push            # commit + tag only
uv run python scripts/deploy.py <new_version> --yes --publish            # push, then uv publish from here
```

Never pass `--yes` without a `yes` from the operator in this conversation.

Always pass the explicit version (not `--bump`) — resolution happened in step 1
and the operator confirmed it.

Stream the output. The script:

1. Pre-flight: fetches `origin` and refuses if HEAD is detached, if the branch
   is behind its upstream, if `v<ver>` already exists on the remote, or (when a
   GitHub Release will follow) if `gh` is not logged in. This runs BEFORE the
   tests so a stale checkout costs seconds, not a suite run.
2. Runs tests (`uv run pytest -x -q`).
3. Updates version strings in pyproject, `__init__.py`, docs.
4. Promotes `[Unreleased]` via `scripts/_deploy_changelog.py`.
5. Regenerates the citation matrix, dependency graph, regulatory tables and
   confidence matrix.
6. `uv sync`, `uv build`, `scripts/check_distribution.py`.
7. Writes `dist/release_notes_v<ver>.md` from the promoted changelog section.
8. Stages release files, commits `chore(release): bump version to <ver>`, tags
   `v<ver>`.
9. Pushes the branch and the tag to `origin` in one atomic push
   (`git push --atomic origin <branch> refs/tags/v<ver>`).
10. Creates GitHub Release `v<ver>` with `gh release create --verify-tag`, the
    notes file as the body and GitHub's generated PR list appended. This fires
    `publish.yml`, which builds and uploads to PyPI.
11. If `--publish`: `uv publish` (and step 10 is skipped).

If any step fails, stop and surface the failure to the operator with the exact
script output. Do not retry automatically. In particular:

- A failed push leaves the commit and tag local; the script prints the manual
  push command. Relay it, do not run it, and do not re-run the script (it would
  refuse on the existing tag).
- A failed release creation leaves the tag pushed and nothing published; the
  script prints the manual `gh release create` command. Relay it — running it
  is the publish decision, and that is the operator's.

## Step 5 — report

On success, print:

```
Release v<ver> committed, tagged, pushed and published as GitHub Release v<ver>.
publish.yml is uploading it to PyPI.
```

Then run `gh run list --workflow=publish.yml --limit 1` once and report that
run's status line. Do not poll. Give the PyPI URL
(`https://pypi.org/project/rwa-calc/<ver>/`) as where it lands.

- Under `--no-github-release`: say the tag is pushed and nothing is published,
  and print the manual `gh release create` command the script emitted.
- Under `--no-push`: print the manual push and release commands instead.
- Under `--publish`: print the PyPI URL, and say there is no GitHub Release.

## Constraints

- One release per invocation. Do not chain.
- The GitHub Release is the PyPI publish. It, like `--publish`, requires the
  operator's explicit `yes` in step 3 every time; a `yes` in an earlier release
  does not carry over.
- Never pass `--skip-tests` automatically. If tests fail, surface the failure;
  do not bypass.
- The push and the release are the script's job, not yours. It pushes the
  branch and the single release tag atomically, then creates the release from
  that tag, after every check has passed. Never push ahead of it, never
  `--force`, never `git push --tags`, and never `gh release create` by hand
  unless the operator asks for exactly that after a failure.
- Never `git reset`, `git tag -d` or `gh release delete` to "recover" from a
  failed release. Stop and let the operator decide.
- If `[Unreleased]` is missing or placeholder-only, still proceed if the operator
  confirms — the script will fall back to the `Version bump for PyPI release`
  stub bullet, and the release notes say the same.
