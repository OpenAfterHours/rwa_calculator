"""
Shared data for the dashboard tests: two small returns and the header they need.

The returns are the ones the CLI tests use, in real PRA001 cells, so every page
is drawn from the packaged taxonomy and rule book rather than a synthetic one:

- BROKEN: OF 07.00 corporates, original exposure and value adjustments. With
  nothing else reported, the net exposure (column 0040) is zero to the
  regulator, and 995,000 is not zero — boe_b0708 and others break.
- CLEAN: one reported zero. Every rule that reads it runs, and holds.
"""

from __future__ import annotations

from datetime import date

from pack_builders import VALID_LEI
from rwa_filer.readers import HeaderFields

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
