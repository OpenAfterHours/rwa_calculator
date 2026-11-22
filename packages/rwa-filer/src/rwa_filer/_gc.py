"""
Pause the cyclic garbage collector for a bulk build, or run it for a read that makes garbage.

Pipeline position:
    a loader of long-lived reference data (``taxonomy.pack.load_pack``)
        ->  collector_paused()  ->  the build  ->  the collector as the caller had it
    a reader that leaves cyclic garbage (``readers.excel.read_workbook``)
        ->  collector_running()  ->  the read  ->  the collector as the caller had it

Key responsibilities:
- Switch the cyclic collector off while a routine builds a large structure that
  is kept for the life of the process and holds no reference cycles, and put it
  back exactly as it was found.
- The mirror image, for the one-shot command line only: switch the collector
  on while a routine that leaves cyclic garbage behind runs in a command the
  process entry runs with it off, and switch it off again, that garbage gone.

Why pause: the collector runs after every few thousand new container objects
and walks the young ones each time. A loader that builds hundreds of thousands
of objects it then keeps gives it a great deal to walk and nothing to free —
about half the CPU of a cold PRA001 pack load was the collector re-reading the
half-built pack. Reference counting still frees everything a build discards;
only the search for cycles waits, and it resumes when the build ends.

Why run: the command line switches the collector off for a whole command
(``rwa_filer.entry``), because almost everything a command builds lives to its
end. The workbook reader is the exception: openpyxl leaves reference cycles
behind for every worksheet it reads — the archive member it opened and its
decompressor among them, about 70 objects a sheet — which only the collector
can free. With it off for the whole command they were held to the end, and
memory grew with the sheet count: 5,717, 11,861 and 31,061 unreachable objects
at exit after validating workbooks of 59, 155 and 455 sheets, and for the 455
a peak of 326 to 350 MB over ten runs, against 248 to 271 MB with the read
collected. That is an exception to the entry's policy, so
it is made only where the policy holds: everywhere else ``collector_running``
does nothing, and the collector is the host's.

The package already pauses for its Arelle worker (``referee/worker.py``), which
switches the collector off for the whole of a validation. This module is the
same idea for library code, which unlike that worker must hand the interpreter
back the way it found it.

What this module must never do: call ``gc.freeze()``, change the collector's
thresholds, or leave the collector in another state than the one it found.
Those are decisions for the process that owns the interpreter — a command-line
entry point — not for a library function that a dashboard, another package or
a test suite calls.

References:
- Python library reference, ``gc`` — ``gc.disable``, ``gc.enable``, ``gc.isenabled``,
  ``gc.collect``
"""

from __future__ import annotations

import gc
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rwa_filer.entry import collector_switched_off

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


@contextmanager
def collector_running() -> Iterator[None]:
    """Run a block, or a whole function, collected — in a one-shot command that runs without.

    As a context manager (``with collector_running():``) or, called, as a
    decorator (``@collector_running()``). For a routine that leaves cyclic
    garbage behind, read by a command that the process entry runs with the
    collector switched off (``rwa_filer.entry.collector_switched_off``).

    In such a command, when the collector is off, it is switched on for the
    block, and when the block ends, also by raising, it is switched off again
    and one full collection is run. The collections during the block keep its
    garbage from piling up while it runs; the last one frees what they had not
    reached yet (garbage made after the last of them, or moved to an older
    generation before it became garbage), so nothing the block made is held to
    the end of the command. Measured on a command-line ``validate``, which
    reads a workbook before it loads the taxonomy: 60 to 85 ms of collection in
    all for 10 to 155 sheets and 150 ms for 455, of which the last, full
    collection is 20 to 30 ms.

    Everywhere else this does nothing at all, on the way in or on the way out:
    a process the entry did not start (a test session, a host calling
    ``rwa_filer.cli.main``, rwa-calc), one whose command has handed the
    collector back (the dashboard, once it serves), or one run with
    ``RWA_FILER_COLLECTOR=on``. Their collector is theirs, on or off. Not
    keying on ``gc.isenabled()`` alone is deliberate: in a process that
    collects, the collector is also off while another thread is inside
    ``collector_paused``, and a block that took that for the caller's state
    would switch the collector off when it ended, after the pause had switched
    it back on — leaving a server without a collector for the rest of its life.

    It nests to any depth, and with ``collector_paused``: a block that finds
    the collector already on (an outer block switched it on) does nothing.

    Threads. A one-shot command reads its files on one thread. Were two threads
    of one to overlap, the switch being the interpreter's: two blocks at once
    still end with the collector off, and when the second to start ends last,
    what it made after the first ended is held to the end of the command; a
    pause opened in another thread during a block finds the collector on, and
    if it outlasts the block it switches it back on after the block switched
    it off — overruled towards "on", so the rest of the command is collected.
    Neither can leave the collector off for a process that collects, because
    in such a process this does nothing.
    """
    acting = collector_switched_off() and not gc.isenabled()
    if acting:
        gc.enable()
    try:
        yield
    finally:
        if acting:
            gc.disable()
            gc.collect()
