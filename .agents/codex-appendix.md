## Codex sandbox notes

Everything above this line is the shared body, rendered from `CLAUDE.md`. The
notes below are true only of the sandboxed Codex runtime, so they are kept out
of `CLAUDE.md` — that file describes the repository, not one agent's
environment. Each entry is a fallback for a constraint that is not present on a
normal developer machine; if one stops being needed, delete it rather than
leaving it to be tried first.

### Read the lessons file first

**Before starting work, read `.claude/LESSONS.md` in full.** Despite the
`.claude/` path it is repo knowledge, not Claude Code configuration — it is the
working set of traps this project has already paid for, written in
`Trap` / `Why` / `Detect` form so you can detect them rather than rediscover
them. Nothing in your system prompt will tell you this, which is why it is said
here.

### uv

- If the uv cache is read-only, use: `UV_CACHE_DIR=/tmp/claude-1000/uv-cache uv run ...`
- If the network is blocked and uv cannot resolve deps: create the venv with
  `UV_CACHE_DIR=/home/philm/.cache/uv uv sync --offline --extra all --python 3.13`, then run
  directly via `.venv/bin/python -m pytest ...` etc.
- The `all` extra there is load-bearing, not belt-and-braces. `pytest`, `pytest-cov` and `ty`
  live only in `[project.optional-dependencies]`, never in `[dependency-groups]`, so a bare
  `uv sync` uninstalls them and the validation gate then fails on a missing tool rather than on
  a real defect.
- If `uv sync --offline` fails (missing simple indices): manually symlink packages from
  `/home/philm/.cache/uv/archive-v0/` into `.venv/lib/python3.13/site-packages/`. Ensure
  cp313-specific archives are used (not cp314).

### Git

- No global git identity is configured in the sandbox, so commits and tags need one passed per
  invocation: `-c user.name="Phil" -c user.email="123414748+luckyphil122@users.noreply.github.com"`.
  This is a fact about the sandbox only — the developer's own machine has a global identity, so
  do not "fix" the machine config on the strength of this note.
- Pushing to GitHub may fail from the sandbox (CONNECT tunnel 403). That is an egress
  restriction, not a credential problem; hand the branch back rather than retrying variants.
