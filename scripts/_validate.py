"""
CLI-input validators shared across the developer scripts.

Several scripts (deploy.py, worktree.py, profile_memory.py) interpolate
operator-supplied CLI arguments into ``subprocess`` argv lists (git tags, git
refs, a reporting date passed to a worker process). Every such call already uses
the argv-list form (never ``shell=True``), so there is no shell to inject into —
but a malformed or hostile argument can still be mis-parsed by the invoked tool
(e.g. a leading ``-`` read as an option, or a non-semver string that silently
fails an in-file version rewrite).

These validators run at the argparse boundary, closest to the untrusted source,
and reject bad input *before* any command is built. They follow the
``worktree.py:_validate_name`` convention: raise ``SystemExit`` with an
``error: ...`` message (fast-fail, non-zero exit, no traceback) and return the
validated value so the dataflow from source to subprocess sink passes visibly
through the sanitizer.
"""

from __future__ import annotations

import re
from datetime import date

# Strict release semver (N.N.N). Pre-release / build suffixes are intentionally
# rejected: deploy.bump_version only ever emits N.N.N and every VERSION_FILES
# pattern matches \d+\.\d+\.\d+, so a suffixed version would silently fail the
# in-file rewrite anyway.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Safe git commitish allowlist: a leading alphanumeric, then alphanumerics plus
# the ref punctuation git permits (. _ / -). Excludes a leading '-' (option
# injection), whitespace, and the ref metacharacters '~^:?*[]' and backslash.
# Accepts HEAD, master, origin/main, v0.3.1, and full/short SHAs.
GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_semver(value: str) -> str:
    """Return ``value`` if it is a strict N.N.N version, else exit with an error."""
    if not SEMVER_RE.match(value):
        raise SystemExit(f"error: invalid version {value!r}. Expected N.N.N (e.g. 0.3.2).")
    return value


def validate_git_ref(value: str) -> str:
    """Return ``value`` if it is a safe git ref, else exit with an error."""
    if (
        not GIT_REF_RE.match(value)
        or ".." in value
        or "@{" in value
        or value.endswith((".lock", "/"))
    ):
        raise SystemExit(
            f"error: invalid git ref {value!r}. "
            f"Use letters, digits, and . _ / - (e.g. HEAD, master, origin/main)."
        )
    return value


def validate_iso_date(value: str) -> str:
    """Return ``value`` if it is an ISO-8601 date (YYYY-MM-DD), else exit with an error."""
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(
            f"error: invalid reporting date {value!r}. Expected ISO YYYY-MM-DD (e.g. 2026-01-01)."
        ) from exc
    return value
