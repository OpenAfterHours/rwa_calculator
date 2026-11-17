"""
The JSON Schemas of the files rwa-filer writes for other systems to read.

Pipeline position:
    rwa_filer.validate.report.to_record  ->  validation-report-2.schema.json
    rwa_filer.evidence.write_evidence    ->  evidence-1.schema.json (one record per line)
    rwa_filer/boe/data/issues/<release>.json  ->  publisher-issues-1.schema.json

Key responsibilities:
- Ship each output's contract in the wheel, beside the code that writes it, so a
  consumer validates against the schema of the version that wrote the file.
- Ship the contract of the curated publisher-issue register too: it is read by
  ``rwa_filer.boe.issues``, which does not need ``jsonschema`` at run time, and
  held to the schema by the package's tests.
- Version them as the outputs are versioned: the major number is in the file
  name and changes when a field is renamed, removed or changes meaning; within
  a major version a schema only gains fields.

References:
- JSON Schema draft 2020-12
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any, Final

#: The validation report (``rwa-filer validate --report`` / ``--format json``).
VALIDATION_REPORT_SCHEMA: Final = "validation-report-2.schema.json"
#: One record of the evidence export (``rwa-filer validate --evidence``).
EVIDENCE_SCHEMA: Final = "evidence-1.schema.json"
#: A release's publisher-issue register (``boe/data/issues/<release>.json``).
PUBLISHER_ISSUES_SCHEMA: Final = "publisher-issues-1.schema.json"


@cache
def load_schema(name: str) -> dict[str, Any]:
    """The packaged schema ``name`` (one of the ``*_SCHEMA`` constants), parsed.

    Raises:
        FileNotFoundError: no such schema is packaged.
    """
    resource = resources.files(__name__).joinpath(name)
    if not resource.is_file():
        raise FileNotFoundError(f"No packaged schema named {name!r}")
    return json.loads(resource.read_text(encoding="utf-8"))
