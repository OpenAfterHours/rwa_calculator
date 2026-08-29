"""
Rendering an untrusted value safe to put in a log record.

Pipeline position:
    Cross-cutting — called at a log site by any layer that logs a value it did
    not itself produce (an HTTP query parameter, a path segment, a column name
    read out of an operator's file).

Key responsibilities:
- ``loggable`` — neutralise the characters that let a caller-supplied value
  forge a log record, and bound its length.

Why this exists as a call-site helper rather than a formatter. Log injection
(CWE-117) is the forging of log *records*: a value carrying a newline writes
what reads as a second, authored line, and one carrying an ANSI escape can
rewrite what a terminal already displayed. A reader — or an incident responder —
then believes a record the system never emitted. Sanitising inside a
``logging.Formatter`` would catch every site at once and is tempting for that
reason, but it disarms the caller's own reasoning: the log site is where the
author knows whether a value is theirs or a stranger's, and a formatter that
silently rewrites every message makes an untrusted value indistinguishable from
a trusted one at the point where the distinction is still visible.

**Prefer provenance over sanitising.** Where the value is being matched against
a collection this process produced — the sheets a template emitted, the
templates a run generated — return the element FROM that collection instead of
the caller's string. The two compare equal, so behaviour is unchanged, but only
one of them has an origin a reader can trust, and no sanitising is then needed.
Reach for ``loggable`` when there is no such collection to match against: a run
id, an operator-supplied filename.

References:
- CWE-117: Improper Output Neutralization for Logs
- docs/specifications/observability.md
"""

from __future__ import annotations

#: A log line is a diagnostic, not a transcript. Bounded so an oversized value
#: cannot bury the records around it.
_MAX_LENGTH = 120

_REPLACEMENT = "?"
_TRUNCATED = "..."


def loggable(value: object, *, max_length: int = _MAX_LENGTH) -> str:
    """Render ``value`` safe to interpolate into a log record.

    Every character that could break or rewrite a line becomes ``?``, and the
    result is truncated to ``max_length``. A non-string is rendered with ``str``
    first, so a caller need not special-case ``None`` or an int.

    The result is for HUMANS reading a log. It is not reversible and must never
    be parsed back into a value or compared against one — neutralising is a
    one-way narrowing, and two distinct inputs can render identically.

    Args:
        value: The untrusted value to render.
        max_length: Maximum characters to keep. Longer values are truncated and
            marked, so a reader can tell a cut from a short value.

    Returns:
        A bounded string carrying no character that can forge a record.
    """
    if max_length <= 0:
        msg = f"max_length must be positive, got {max_length}"
        raise ValueError(msg)
    text = "".join(_REPLACEMENT if _forgeable(char) else char for char in str(value))
    if len(text) <= max_length:
        return text
    return text[:max_length] + _TRUNCATED


def _forgeable(char: str) -> bool:
    """True for a character that can break or rewrite a log line.

    ``str.isprintable`` is False for exactly the categories that matter — Cc,
    Cf, Cs, Co, Cn, Zl (U+2028), Zp (U+2029), and every Zs except a plain space
    — so it is both the precise test and the one that lets a legitimate
    diagnostic through unharmed.

    A narrower ASCII allowlist was written first and rejected by its own test:
    it mangled the values this project actually logs (``c08_03/corporate/0010
    (ours)``, the em dash in a template title). A control that degrades the
    diagnostic it protects buys nothing — a reader who cannot trust the text
    stops reading it. Printability is the axis the threat lives on; punctuation
    and non-ASCII letters are not.
    """
    return not char.isprintable()
