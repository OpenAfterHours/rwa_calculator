"""
The process entry of the ``rwa-filer`` command: one command, then the process ends.

Pipeline position:
    shell  ->  the ``rwa-filer`` console script  ->  rwa_filer.entry.run
        ->  rwa_filer.cli.main  ->  the process's exit code

Key responsibilities:
- Run a one-shot command with the cyclic garbage collector switched off, and
  freeze the heap before the interpreter shuts down, so that neither the
  command nor the exit walks data that lives to the end of the process anyway.
- Hand the collector back to a command that goes on running
  (``keep_collecting``): the dashboard serves until it is interrupted, and a
  process that never ends must not run without a collector.
- Touch nothing but the process it starts. ``rwa_filer.cli.main(argv)`` is the
  in-process API — the test suite and any host call it — and it never changes
  the collector; only ``run`` does, and ``keep_collecting`` undoes only what
  ``run`` did.

Why the collector is off
------------------------
A command builds its reference data once and keeps it to the end: the taxonomy
pack, the rule book and the return are about 740,000 container objects on a
small PRA001 ``validate``. They are not garbage, and the collector cannot know
that, so every time enough new objects are allocated it walks the survivors
again. Measured on that ``validate`` (2,227 facts): 358 young, 32 middle and 2
full collections, which between them reclaimed about 830 objects, most of them
the argument parser's own. Switched off, the same command runs no collection
at all and takes 1.12 s of CPU instead of 1.48 s; the same return as an XBRL
instance, whose reader builds more, 1.39 s instead of 2.18 s.

Interpreter shutdown is the same walk once more: its final collections
traverse the whole heap to free memory the operating system is about to
reclaim anyway — 130 to 160 ms after that ``validate``. ``gc.freeze()`` moves
every tracked object to the permanent generation, which those collections
skip, and shutdown takes under 20 ms. The two belong together: with the
collector off and no freeze, shutdown has more to walk and took 230 ms.

Not ``os._exit``: it would save a few milliseconds more and skip the exit
hooks and the flush of standard output. After ``gc.freeze()`` the interpreter
still shuts down normally, so every stream is flushed and every exit hook runs.

Why this is safe
----------------
The collector decides when unreachable cycles are freed, never what a command
computes; it can change an output only through code that runs when an object
is freed. Checked in this package (``grep`` over ``src/rwa_filer``, 2026-11-22):

- no class defines ``__del__``, and nothing registers a weak-reference
  callback or an ``atexit`` hook, so no result is produced by a finaliser;
- every file the package writes is closed before the function that wrote it
  returns — a ``with`` block (the zip in ``filing``, the ledger in
  ``workflow.ledger``, the rule-book, extract and deny-list importers, the
  release builder), an explicit ``close`` in a ``finally`` (the gzip stream in
  ``evidence``), ``Path.write_text`` / ``write_bytes`` (the instance, the
  manifest, the report), or a library call that closes what it opens (Polars'
  ``write_ipc`` for a pack, openpyxl's ``save`` for a workbook). Nothing is
  left for a finaliser to flush.

What the policy would break is a file that a ``__del__`` completes: its owner,
caught in a reference cycle, is never freed here, so the file's last buffered
bytes never reach the disk. (A file merely left open in a cycle is a different
matter and no worse off: measured on CPython 3.13.18, its unflushed tail is
lost at exit with the collector on, with it off and with the heap frozen
alike.) ``tests/test_process_entry.py`` compares the files a command writes
through this entry, byte for byte, with those of a process that collects.

The package already runs its Arelle worker this way
(``rwa_filer.referee.worker``: collector off for the session, and no teardown
at all), for the same reason.

The known cost
--------------
Cyclic garbage a command does create is held until the process ends. For a
fact table or an XBRL instance that is about 1,700 objects, the argument
parser's among them and nothing of the return's: 1,679 for fact tables of
2,770 to 44,320 facts, 1,701 for instances of 2,227 to 25,987 facts, and as
few for ``build``, ``compare``, ``diff`` and an evidence export. Peak memory
was all but unchanged on a fact table (323 MB to 326 MB) and higher on an XBRL
instance: 394 MB every time, against 345 to 368 MB over five runs with the
collector on. Those 1,700 objects do not account for that difference; it is
measured here, not explained.

A workbook is different: the library that reads it leaves cycles behind for
every sheet — the archive members it opened and their decompressors, about 70
objects a sheet, whatever the sheet holds. Validating a blank 323-sheet PRA001
template ends with about 22,600 unreachable objects, and peaked at 386 MB
instead of 328 MB. It is bounded by the workbook, and the process ends with
the command.

References:
- rwa_filer.referee.worker — the same policy, for the Arelle worker
- Python ``gc``: ``disable``, ``freeze`` (the permanent generation)
- docs/plans/rwa-filer-performance-review-2026-11-22.md — the measurements
"""

from __future__ import annotations

import gc
import sys
from typing import NoReturn

#: Whether ``run`` switched the collector off for this process. ``keep_collecting``
#: switches it back on only then, so a caller of ``cli.main`` keeps its own policy.
_collector_switched_off = False


def run() -> NoReturn:
    """Run the ``rwa-filer`` command this process was started for, then exit with its code.

    The console script and ``python -m rwa_filer.cli`` call this; nothing else
    should. It changes the garbage collector for the whole process (see the
    module docstring), which is right only for a process that exists to run one
    command. In-process callers use ``rwa_filer.cli.main``.
    """
    global _collector_switched_off
    gc.disable()
    _collector_switched_off = True
    try:
        # Imported here, after the collector is off: importing the command line
        # loads some 430 modules, and their objects all live to the end too.
        from rwa_filer.cli import main

        code = main()
    finally:
        # Also when the command raised or argparse exited: every way out of the
        # process goes through the interpreter's shutdown.
        gc.freeze()
    sys.exit(code)


def keep_collecting() -> None:
    """Switch the collector back on, if ``run`` switched it off for this process.

    Called by a command that does not end with its work — the dashboard —
    before it starts serving: what it did until then (opening and validating
    the file it was given) is one-shot work and ran with the collector off; a
    server that runs for hours creates garbage for hours.

    Does nothing when the process did not come in through ``run``: an
    in-process caller's collector is its own, on or off.
    """
    if _collector_switched_off:
        gc.enable()
