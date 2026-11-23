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
- Say whether the policy holds right now (``collector_switched_off``), for the
  one exception made to it: reading a workbook, which runs collected
  (``rwa_filer._gc.collector_running``).
- Touch nothing but the process it starts. ``rwa_filer.cli.main(argv)`` is the
  in-process API — the test suite and any host call it — and it sets no
  collector policy: only ``run`` does, and ``keep_collecting`` undoes only what
  ``run`` did. (The library pauses the collector while it builds a taxonomy pack
  or reads an XBRL instance, for the whole interpreter, and restores what it
  found: ``rwa_filer._gc.collector_paused``.)
- Let the policy be switched off without a release: with
  ``RWA_FILER_COLLECTOR=on`` in the environment, ``run`` leaves the collector
  as the interpreter started it (on) and does not freeze the heap, so the
  command runs as ``main`` called in-process would. Exactly ``on``: any other
  value, or none, is the policy described here.

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
objects a sheet, whatever the sheet holds. So the workbook reader runs with the
collector on (``rwa_filer._gc.collector_running``) and switches it off again
when it is done, after one full collection: what it left is freed then, not at
exit. Without that, validating workbooks of 59, 155 and 455 sheets ended with
5,717, 11,861 and 31,061 unreachable objects, and the 455 peaked at 326 to
350 MB over ten runs; with it, 849 at every size from 10 to 455 sheets, a
peak of 248 to 271 MB, and 60 to 155 ms of collection for the read.

Writing a workbook (``rwa-filer template``) is not covered: openpyxl's
in-memory workbook is cyclic too, and a 323-sheet blank template ends with
about 287,000 unreachable objects. Its peak memory measured the same as with
the collector on (243 MB): the workbook is kept until it is saved either way,
and the command ends when it is.

References:
- rwa_filer.referee.worker — the same policy, for the Arelle worker
- Python ``gc``: ``disable``, ``freeze`` (the permanent generation)
- docs/plans/rwa-filer-performance-review-2026-11-22.md — the measurements
"""

from __future__ import annotations

import gc
import os
import sys
from typing import Final, NoReturn

#: The environment variable that switches the policy off for one run, and the
#: one value that does: ``RWA_FILER_COLLECTOR=on`` keeps the collector on.
_SWITCH: Final = "RWA_FILER_COLLECTOR"
_KEEP_COLLECTING: Final = "on"

#: Whether the collector is off by this policy now: ``run`` switched it off for
#: this process's command, and ``keep_collecting`` has not handed it back. Only
#: then does ``keep_collecting`` switch it on, so a caller of ``cli.main`` keeps
#: its own policy; and only then does the workbook reader run collected
#: (``rwa_filer._gc.collector_running``).
_collector_switched_off = False


def run() -> NoReturn:
    """Run the ``rwa-filer`` command this process was started for, then exit with its code.

    The console script and ``python -m rwa_filer.cli`` call this; nothing else
    should. It changes the garbage collector for the whole process (see the
    module docstring), which is right only for a process that exists to run one
    command. In-process callers use ``rwa_filer.cli.main``.

    With ``RWA_FILER_COLLECTOR=on`` in the environment it changes nothing: the
    collector stays as the interpreter started it and the heap is not frozen.
    """
    global _collector_switched_off
    one_shot = os.environ.get(_SWITCH) != _KEEP_COLLECTING
    if one_shot:
        gc.disable()
        _collector_switched_off = True
    try:
        # Imported here, after the collector is off: importing the command line
        # loads some 430 modules, and their objects all live to the end too.
        from rwa_filer.cli import main

        code = main()
    finally:
        # Also when the command raised or argparse exited: every way out of the
        # process goes through the interpreter's shutdown. Not under the switch:
        # a frozen heap is the other half of the policy it turns off.
        if one_shot:
            gc.freeze()
    sys.exit(code)


def keep_collecting() -> None:
    """Switch the collector back on, if ``run`` switched it off for this process.

    Called by a command that does not end with its work — the dashboard —
    before it starts serving: what it did until then (opening and validating
    the file it was given) is one-shot work and ran with the collector off; a
    server that runs for hours creates garbage for hours.

    Does nothing when the process did not come in through ``run``: an
    in-process caller's collector is its own, on or off. From here on the
    process is no longer under the one-shot policy (``collector_switched_off``).
    """
    global _collector_switched_off
    if _collector_switched_off:
        gc.enable()
        _collector_switched_off = False


def collector_switched_off() -> bool:
    """Whether the collector is off because this process is running a one-shot command.

    True from the moment ``run`` switches it off until ``keep_collecting``
    hands it back; never in a process that did not come in through ``run``
    (an in-process caller of ``cli.main``, a test session, a host), nor under
    ``RWA_FILER_COLLECTOR=on``. ``rwa_filer._gc.collector_running`` reads it: it
    makes an exception to this policy, so it acts only while the policy holds.
    """
    return _collector_switched_off
