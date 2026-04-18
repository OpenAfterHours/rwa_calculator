#!/bin/bash
# Usage: ./loop.sh [plan] [max_iterations]
# Examples:
#   ./loop.sh              # Build mode, 2 iterations (default)
#   ./loop.sh 20           # Build mode, max 20 iterations
#   ./loop.sh plan         # Plan mode, 2 iterations (default)
#   ./loop.sh plan 5       # Plan mode, max 5 iterations

# Parse arguments
if [[ "$1" = "plan" ]]; then
    # Plan mode
    MODE="plan"
    PROMPT_FILE="PROMPT_plan.md"
    MAX_ITERATIONS=${2:-2}
elif [[ "$1" = "docs_plan" ]]; then
    # Doc Plan mode
    MODE="plan"
    PROMPT_FILE="PROMPT_docs_plan.md"
    MAX_ITERATIONS=${2:-2}
elif [[ "$1" = "docs_build" ]]; then
    # Doc build mode
    MODE="build"
    PROMPT_FILE="PROMPT_docs_build.md"
    MAX_ITERATIONS=${2:-2}
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    # Build mode with max iterations
    MODE="build"
    PROMPT_FILE="PROMPT_build.md"
    MAX_ITERATIONS=$1
else
    # Build mode, default 2 iterations
    MODE="build"
    PROMPT_FILE="PROMPT_build.md"
    MAX_ITERATIONS=2
fi

ITERATION=0
CURRENT_BRANCH=$(git branch --show-current)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Mode:   $MODE"
echo "Prompt: $PROMPT_FILE"
echo "Branch: $CURRENT_BRANCH"
echo "Max:    $MAX_ITERATIONS iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Verify prompt file exists
if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Error: $PROMPT_FILE not found"
    exit 1
fi

mkdir -p logs

while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
    LOGFILE="logs/${MODE}_$(date +%Y%m%d_%H%M%S)_iter${ITERATION}.jsonl"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Iteration $((ITERATION + 1)) / $MAX_ITERATIONS"
    echo "  Log: $LOGFILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Run Ralph iteration with selected prompt
    # -p: Headless mode (non-interactive, reads from stdin)
    # --dangerously-skip-permissions: Auto-approve all tool calls (YOLO mode)
    # --output-format=stream-json: Structured output for logging/monitoring
    # --include-partial-messages: Stream assistant text token-by-token (typing feel)
    # --model opus: Primary agent uses Opus for complex reasoning (task selection, prioritization)
    #               Can use 'sonnet' in build mode for speed if plan is clear and tasks well-defined
    # --verbose: Detailed execution logging
    #
    # Output: full JSON streamed to log file, rendered TUI-like view to terminal
    cat "$PROMPT_FILE" | claude -p \
        --dangerously-skip-permissions \
        --output-format=stream-json \
        --include-partial-messages \
        --model opus \
        --verbose \
        | tee "$LOGFILE" \
        | python3 scripts/render_stream.py

    # Push changes after each iteration
    git push origin "$CURRENT_BRANCH" || {
        echo "Failed to push. Creating remote branch..."
        git push -u origin "$CURRENT_BRANCH"
    }

    ITERATION=$((ITERATION + 1))
    echo -e "\n\n======================== LOOP $ITERATION COMPLETE ========================\n"
done