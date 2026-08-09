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

if [[ $FAILED -ne 0 ]]; then
    python -c "
import json, sys
errors = sys.stdin.read()
print(json.dumps({'continue': False, 'stopReason': 'Pre-commit checks failed. Fix these violations:\n' + errors}))
" <<< "$ERRORS"
else
    echo '{"continue": true}'
fi
