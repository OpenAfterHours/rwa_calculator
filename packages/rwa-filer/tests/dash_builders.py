"""
Shared data for the dashboard tests: two small returns and the header they need.

The returns are the ones the CLI tests use, in real PRA001 cells, so every page
is drawn from the packaged taxonomy and rule book rather than a synthetic one:

- BROKEN: OF 07.00 corporates, original exposure and value adjustments. With
  nothing else reported, the net exposure (column 0040) is zero to the
  regulator, and 995,000 is not zero — boe_b0708 and others break.
- CLEAN: one reported zero. Every rule that reads it runs, and holds.

And the two overrides that make BROKEN fileable, drafted through the template
grid's cell panel as a person drafts them: zero the exposure, take the
adjustment out.

And two helpers for the tests of what happens when two requests meet
(``parked_inside`` and ``wait_until``): they line threads up at a known point by
looking at where each thread is, so no such test sleeps and hopes.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import date
from typing import TYPE_CHECKING

from pack_builders import VALID_LEI
from rwa_filer.readers import HeaderFields

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn

BROKEN_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)
CLEAN_CSV = "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n"
REFERENCE_DATE = "2027-03-31"
#: The form fields a fact table needs.
HEADER_FORM = {"entity": VALID_LEI, "reference_date": REFERENCE_DATE, "module": "PRA001"}
HEADER = HeaderFields(entity=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001")
#: A loopback address: the app answers loopback host names only.
BASE_URL = "http://127.0.0.1:8765"
#: The same header as command-line options.
HEADER_ARGS_CLI = [
    "--entity",
    VALID_LEI,
    "--reference-date",
    REFERENCE_DATE,
    "--module",
    "PRA001",
]

#: Seconds a test waits for threads to reach a point before it is a failure, not a hang.
PATIENCE = 60.0

#: The row of BROKEN the override tests draft against: OF 07.00, sheet 0008, row 0010.
CELL = {"table": "OF07.00.01.01", "sheet": "0008", "key": "", "row": "0010"}
#: The grid page that row is drawn on, as the cell panel's form returns to it.
GRID = "/templates?table=OF07.00.01.01&sheet=0008&row=0010&col=0010"


def draft(client: TestClient, opened: OpenedReturn, column: str, **fields: str) -> str:
    """Post the cell panel's override form for one column of ``CELL``; the page it lands on."""
    base = f"/returns/{opened.return_id}"
    data = {**CELL, "col": column, "data_type": "monetary", "next": base + GRID, **fields}
    return client.post(f"{base}/adjustments", data=data).text


def make_fileable(client: TestClient, opened: OpenedReturn) -> None:
    """Draft the two overrides that leave BROKEN with nothing blocking it."""
    draft(client, opened, "0010", value="0", reason="Booked to the wrong class")
    draft(client, opened, "0030", remove="yes", reason="Follows the exposure")


def parked_inside(function: Callable[..., object]) -> int:
    """How many threads are inside a call of ``function`` and blocked in a ``threading`` wait.

    A thread waiting on an ``Event`` or a ``Condition`` has ``Condition.wait``
    as its innermost Python frame; the frames below it say whose call it is
    waiting in. That tells a test a request has got as far as it can — held on a
    gate the test set, or waiting for another request's work — without the test
    having to know which of the two, and without a sleep.
    """
    code = function.__code__
    parked = 0
    for innermost in sys._current_frames().values():
        waiting = (
            innermost.f_code.co_filename == threading.__file__
            and innermost.f_code.co_name == "wait"
        )
        frame = innermost.f_back if waiting else None
        while frame is not None and frame.f_code is not code:
            frame = frame.f_back
        parked += frame is not None
    return parked


def wait_until(condition: Callable[[], bool], *, patience: float = PATIENCE) -> None:
    """Return once ``condition`` holds; fail the test if it has not within ``patience`` seconds."""
    deadline = time.monotonic() + patience
    while not condition():
        assert time.monotonic() < deadline, "the threads never reached the point the test set up"
        time.sleep(0.001)
