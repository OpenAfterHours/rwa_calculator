#!/usr/bin/env python3
"""
Render Claude Code stream-json events as a TUI-like terminal view.

Consumes newline-delimited JSON events from stdin (produced by
`claude -p --output-format=stream-json --verbose`) and prints a readable
summary for each event: assistant text, tool invocations with their inputs,
tool results, and final cost/duration banner.

Intended to be piped after `tee` in loop.sh so the raw JSONL log is preserved
while the terminal gets a richer view.
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

# Reconfigure stdout to UTF-8 so bullet/arrow glyphs render on Windows consoles
# (default cp1252 can't encode ●, ↳, etc.). Fall back silently on older Python.
with contextlib.suppress(AttributeError, OSError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Glyphs — fall back to ASCII if the stream cannot encode the preferred ones.
_enc = (getattr(sys.stdout, "encoding", "") or "").lower()
_UNICODE_OK = "utf" in _enc
BULLET = "●" if _UNICODE_OK else "*"
ARROW = "↳" if _UNICODE_OK else "->"
CROSS = "✗" if _UNICODE_OK else "x"
DOT = "·" if _UNICODE_OK else "."
ELLIPSIS = "…" if _UNICODE_OK else "..."


def _tty() -> bool:
    return sys.stdout.isatty()


class C:
    """ANSI colour codes, blanked out when stdout is not a TTY."""

    _on = _tty()
    RESET = "\033[0m" if _on else ""
    DIM = "\033[2m" if _on else ""
    BOLD = "\033[1m" if _on else ""
    CYAN = "\033[36m" if _on else ""
    GREEN = "\033[32m" if _on else ""
    RED = "\033[31m" if _on else ""
    YELLOW = "\033[33m" if _on else ""
    MAGENTA = "\033[35m" if _on else ""
    GREY = "\033[90m" if _on else ""


MAX_LINE = 120


def _truncate(text: str, limit: int = MAX_LINE) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + ELLIPSIS


def _emit(line: str) -> None:
    print(line, flush=True)


def _render_system(event: dict[str, Any]) -> None:
    if event.get("subtype") != "init":
        return
    model = event.get("model", "?")
    cwd = event.get("cwd", "?")
    session = event.get("session_id", "?")
    _emit(f"{C.DIM}model={model}  session={session[:8]}  cwd={cwd}{C.RESET}")


def _render_tool_use(block: dict[str, Any]) -> None:
    name = block.get("name", "unknown")
    inp = block.get("input", {}) or {}
    header = f"{C.CYAN}{BULLET}{C.RESET} {C.BOLD}{name}{C.RESET}"

    renderer = _TOOL_RENDERERS.get(name)
    if renderer is not None:
        renderer(header, inp)
        return

    _render_tool_default(header, inp)


def _render_tool_read(header: str, inp: dict[str, Any]) -> None:
    path = inp.get("file_path", "?")
    suffix = ""
    if inp.get("offset") is not None or inp.get("limit") is not None:
        off = inp.get("offset", 0)
        lim = inp.get("limit")
        end = f"{off + lim}" if lim else "?"
        suffix = f"  {C.DIM}(lines {off}-{end}){C.RESET}"
    _emit(f"{header}  {path}{suffix}")


def _render_tool_edit(header: str, inp: dict[str, Any]) -> None:
    path = inp.get("file_path", "?")
    old = _truncate(inp.get("old_string", ""), 80)
    new = _truncate(inp.get("new_string", ""), 80)
    replace_all = inp.get("replace_all")
    flag = f"  {C.DIM}(replace_all){C.RESET}" if replace_all else ""
    _emit(f"{header}  {path}{flag}")
    if old:
        _emit(f"  {C.RED}- {old}{C.RESET}")
    if new:
        _emit(f"  {C.GREEN}+ {new}{C.RESET}")


def _render_tool_write(header: str, inp: dict[str, Any]) -> None:
    path = inp.get("file_path", "?")
    content = inp.get("content", "") or ""
    n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    _emit(f"{header}  {path}  {C.DIM}({n_lines} lines){C.RESET}")


def _render_tool_bash(header: str, inp: dict[str, Any]) -> None:
    cmd = _truncate(inp.get("command", ""), 100)
    desc = inp.get("description")
    desc_s = f"  {C.DIM}# {desc}{C.RESET}" if desc else ""
    _emit(f"{header}  {C.YELLOW}${C.RESET} {cmd}{desc_s}")


def _render_tool_grep(header: str, inp: dict[str, Any]) -> None:
    pattern = _truncate(inp.get("pattern", ""), 60)
    path = inp.get("path") or inp.get("glob") or "."
    mode = inp.get("output_mode", "files_with_matches")
    _emit(f'{header}  "{pattern}"  {C.DIM}in {path}  [{mode}]{C.RESET}')


def _render_tool_glob(header: str, inp: dict[str, Any]) -> None:
    pattern = inp.get("pattern", "?")
    path = inp.get("path") or "."
    _emit(f"{header}  {pattern}  {C.DIM}in {path}{C.RESET}")


def _render_tool_todo(header: str, inp: dict[str, Any]) -> None:
    todos = inp.get("todos", [])
    _emit(header)
    for t in todos:
        status = t.get("status", "pending")
        subject = t.get("subject") or t.get("content", "")
        mark = {
            "completed": f"{C.GREEN}[x]{C.RESET}",
            "in_progress": f"{C.YELLOW}[~]{C.RESET}",
            "pending": f"{C.DIM}[ ]{C.RESET}",
        }.get(status, "[ ]")
        _emit(f"  {mark} {subject}")


def _render_tool_agent(header: str, inp: dict[str, Any]) -> None:
    desc = inp.get("description", "")
    subtype = inp.get("subagent_type", "general-purpose")
    _emit(f"{header}  {desc}  {C.DIM}[{subtype}]{C.RESET}")


def _render_tool_web(header: str, inp: dict[str, Any]) -> None:
    url = inp.get("url") or inp.get("query", "")
    _emit(f"{header}  {_truncate(url, 100)}")


def _render_tool_default(header: str, inp: dict[str, Any]) -> None:
    # default: dump first couple of interesting args
    if inp:
        preview = ", ".join(f"{k}={_truncate(str(v), 40)}" for k, v in list(inp.items())[:3])
        _emit(f"{header}  {C.DIM}{preview}{C.RESET}")
    else:
        _emit(header)


# Dispatch table: tool name -> renderer taking (header, input dict).
_TOOL_RENDERERS: dict[str, Any] = {
    "Read": _render_tool_read,
    "Edit": _render_tool_edit,
    "Write": _render_tool_write,
    "Bash": _render_tool_bash,
    "Grep": _render_tool_grep,
    "Glob": _render_tool_glob,
    "TodoWrite": _render_tool_todo,
    "Agent": _render_tool_agent,
    "Task": _render_tool_agent,
    "WebFetch": _render_tool_web,
    "WebSearch": _render_tool_web,
}


def _render_thinking_block(block: dict[str, Any]) -> None:
    text = block.get("thinking", "") or ""
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first:
        _emit(f"{C.GREY}{DOT} thinking: {_truncate(first, 100)}{C.RESET}")


def _render_assistant(event: dict[str, Any]) -> None:
    content = event.get("message", {}).get("content", []) or []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text:
                _emit(text)
        elif btype == "thinking":
            _render_thinking_block(block)
        elif btype == "tool_use":
            _render_tool_use(block)


def _tool_result_text(block: dict[str, Any]) -> str:
    """Extract the displayable text from a tool_result content payload.

    content can be a string or a list of {type:text,text:...} dicts.
    """
    raw = block.get("content", "")
    if isinstance(raw, list):
        parts = [b.get("text", "") for b in raw if isinstance(b, dict)]
        return "\n".join(p for p in parts if p)
    return str(raw or "")


def _render_user(event: dict[str, Any]) -> None:
    # user events carry tool_result blocks back from tool execution
    content = event.get("message", {}).get("content", []) or []
    for block in content:
        if block.get("type") != "tool_result":
            continue
        text = _tool_result_text(block)
        if not text:
            continue
        if block.get("is_error", False):
            _emit(f"  {C.RED}{CROSS} {_truncate(text, 200)}{C.RESET}")
        else:
            # one-line summary — show first non-empty line
            first = next((ln for ln in text.splitlines() if ln.strip()), "")
            if first:
                _emit(f"  {C.DIM}{ARROW} {_truncate(first, 140)}{C.RESET}")


def _render_stream_event(event: dict[str, Any]) -> None:
    """Partial-message deltas from --include-partial-messages.

    We stream text deltas inline without a trailing newline so output feels
    typed. Message-stop flushes a newline.
    """
    ev = event.get("event", {}) or {}
    etype = ev.get("type")
    if etype == "content_block_delta":
        delta = ev.get("delta", {}) or {}
        if delta.get("type") == "text_delta":
            sys.stdout.write(delta.get("text", ""))
            sys.stdout.flush()
    elif etype == "message_stop":
        sys.stdout.write("\n")
        sys.stdout.flush()


def _render_result(event: dict[str, Any]) -> None:
    cost = event.get("total_cost_usd", event.get("cost_usd", "?"))
    dur = event.get("duration_ms", "?")
    turns = event.get("num_turns", "?")
    _emit(f"\n{C.MAGENTA}--- Result (cost=${cost} duration={dur}ms turns={turns}) ---{C.RESET}")
    result_text = event.get("result")
    if result_text:
        _emit(str(result_text))


def _render_assistant_after_partials(event: dict[str, Any]) -> None:
    """Render an assistant event whose text was already streamed via deltas.

    Text deltas are emitted by ``_render_stream_event``; here we only render the
    non-text blocks (tool_use, thinking) that do not arrive as ``text_delta``.
    """
    for block in event.get("message", {}).get("content", []) or []:
        btype = block.get("type")
        if btype == "tool_use":
            _render_tool_use(block)
        elif btype == "thinking":
            _render_thinking_block(block)


def _parse_event(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def main() -> None:
    # If partial-messages streaming is active, a full assistant message
    # event will arrive after the deltas and duplicate the text. Track
    # whether we've been streaming partials this turn so we can skip the
    # full-message text block on arrival.
    streaming_partials = False

    for raw in sys.stdin:
        event = _parse_event(raw)
        if event is None:
            continue

        etype = event.get("type")
        if etype == "system":
            _render_system(event)
        elif etype == "stream_event":
            streaming_partials = True
            _render_stream_event(event)
        elif etype == "assistant":
            if streaming_partials:
                _render_assistant_after_partials(event)
                streaming_partials = False
            else:
                _render_assistant(event)
        elif etype == "user":
            _render_user(event)
        elif etype == "result":
            _render_result(event)


if __name__ == "__main__":
    main()
