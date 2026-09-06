#!/bin/bash
# Pre-commit gate for Claude Code hooks.
# Blocks git commit if architectural checks or ruff lint fail.
#
# Called by PreToolUse hook on Bash(git:*) commands.
# Reads hook JSON from stdin, checks if the command is a git commit,
# then runs arch_check.py and ruff. Outputs JSON to block if violations found.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only gate git commit commands
echo "$COMMAND" | grep -qE '\bgit\b.*\bcommit\b' || exit 0

ERRORS=""
FAILED=0

# Both gate steps run with --no-build --no-sync: the hook fires on every commit,
# so it executes in the environment the developer already has rather than
# resolving one. --no-sync keeps uv out of the dependency solver entirely, and
# --no-build refuses to run a source distribution's setup scripts if it ever did
# reach the solver. The two are a pair — --no-build ALONE fails outright, because
# the editable local project (rwa-calc) has no binary distribution to install
# from. Re-sync explicitly with `uv sync --all-groups` after changing deps.

# Architectural linter
ARCH_OUT=$(uv run --no-build --no-sync python scripts/arch_check.py 2>&1)
if [[ $? -ne 0 ]]; then
    FAILED=1
    ERRORS="${ARCH_OUT}"$'\n'
fi

# Ruff lint check
RUFF_OUT=$(uv run --no-build --no-sync ruff check src/ 2>&1)
if [[ $? -ne 0 ]]; then
    FAILED=1
    ERRORS="${ERRORS}${RUFF_OUT}"$'\n'
fi

# Distinguishes an UNPROVISIONED environment from real violations. Runs only
# once something has already failed, so the happy path costs nothing.
#
# A fresh git worktree has no `.venv` — it is gitignored, so `git worktree add`
# materialises tracked files and nothing else — and `uv run --no-sync` CREATES
# an empty one rather than refusing to run. arch_check then executes on bare
# stdlib and reports its two watchfire checks as "VIOLATIONS FOUND", while ruff
# is absent outright ("Failed to spawn: `ruff`"). Both are environment faults
# wearing the costume of code faults: the commit is blocked and every word of
# the message points at the wrong thing.
#
# The probe deliberately tests only THIRD-PARTY tools. Importing `rwa_calc`
# would be a stronger statement about the environment and a much worse probe: a
# syntax error just introduced in `src/` would fail it, and a real code fault
# would then be reported as a missing virtualenv — the same class of misdirection
# this function exists to remove, pointing the other way.
tools_missing() {
    ! uv run --no-build --no-sync python -c "import watchfire" >/dev/null 2>&1 \
        || ! uv run --no-build --no-sync ruff --version >/dev/null 2>&1
}

if [[ $FAILED -ne 0 ]]; then
    if tools_missing; then
        ERRORS="The gate could not run: this working copy has no dev tools installed.
Nothing below is a finding about your code.

Fix, from $(pwd) (about 30s with a warm uv cache):

    uv sync --all-extras --frozen

then re-run the commit. A fresh git worktree starts without a .venv, and
'uv run --no-sync' creates an empty one instead of refusing to run — so
arch_check ran on bare stdlib and ruff was missing entirely.

--- original gate output, for reference ---
${ERRORS}"
    fi
    python -c "
import json, sys
errors = sys.stdin.read()
print(json.dumps({'continue': False, 'stopReason': 'Pre-commit checks failed. Fix these violations:\n' + errors}))
" <<< "$ERRORS"
else
    echo '{"continue": true}'
fi
