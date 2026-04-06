#!/bin/bash
# Post-edit hook: auto-format Python files with ruff after Write/Edit.
# Reads hook JSON from stdin, extracts file path, runs ruff if it's a .py file.

FILE=$(python -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [[ "$FILE" == *.py ]] && [[ -f "$FILE" ]]; then
    uv run ruff check --fix "$FILE" 2>/dev/null
    uv run ruff format "$FILE" 2>/dev/null
fi
exit 0
