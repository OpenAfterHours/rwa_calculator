"""
Pause the cyclic garbage collector for the length of a bulk build.

Pipeline position:
    a loader of long-lived reference data (``taxonomy.pack.load_pack``)
        ->  collector_paused()  ->  the build  ->  the collector as the caller had it

Key responsibilities:
- Switch the cyclic collector off while a routine builds a large structure that
  is kept for the life of the process and holds no reference cycles, and put it
  back exactly as it was found.

Why: the collector runs after every few thousand new container objects and
walks the young ones each time. A loader that builds hundreds of thousands of
objects it then keeps gives it a great deal to walk and nothing to free — about
half the CPU of a cold PRA001 pack load was the collector re-reading the
half-built pack. Reference counting still frees everything a build discards;
only the search for cycles waits, and it resumes when the build ends.

The package already does this for its Arelle worker (``referee/worker.py``),
which switches the collector off for the whole of a validation. This module is
the same idea for library code, which unlike that worker must hand the
interpreter back the way it found it.

What this module must never do: call ``gc.freeze()``, change the collector's
thresholds, or leave the collector off. Those are decisions for the process
that owns the interpreter — a command-line entry point — not for a library
function that a dashboard, another package or a test suite calls.

References:
- Python library reference, ``gc`` — ``gc.disable``, ``gc.enable``, ``gc.isenabled``
"""

from __future__ import annotations

import gc
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def collector_paused() -> Iterator[None]:
    """Run a block, or a whole function, with the cyclic collector switched off.

    As a context manager (``with collector_paused():``) or, called, as a
    decorator (``@collector_paused()``).

    The collector is switched back on afterwards only if it was on beforehand,
    and that happens even when the block raises. So:

    - under a caller that has already switched the collector off — a
      command-line entry point, or an outer ``collector_paused`` — this does
      nothing at all, on the way in or on the way out;
    - it nests to any depth: only the outermost pause, the one that found the
      collector on, switches it back on;
    - it cannot leave the collector off. Every pause that switched it off
      switches it on again when it ends.

    Threads. The switch belongs to the interpreter, not to a thread, so while
    one thread is paused every thread runs without cyclic collection, for as
    long as the paused block takes. When two threads pause at once, the first
    to finish switches the collector back on while the other is still
    building. That is the worst case: the collector comes back on early, and
    the second build is collected like any unpaused code — the saving is lost,
    nothing else. The collector is never left off, because the pause that
    found it on always switches it back. The one thing a pause can overrule is
    code that calls ``gc.disable()`` for itself from another thread while a
    pause is open, and it is overruled towards "on".
    """
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
