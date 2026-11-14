"""
XBRL — the submission file: writing a canonical return as one, and reading one back.

Pipeline position:
    CanonicalReturn  ->  writer.write_instance  ->  <name>.xbrl
    <name>.xbrl      ->  reader.read_instance   ->  CanonicalReturn

Module map:
- ``writer`` — a structurally clean return as an XBRL 2.1 instance that follows
  the Bank of England XBRL Filing Manual
- ``reader`` — an instance, from this package or any other system, back into
  the canonical return, so the same checks run on it

References:
- BoE XBRL Filing Manual v1.0.1
- XBRL 2.1; XBRL Dimensions 1.0
"""

from __future__ import annotations

from rwa_filer.xbrl.writer import (
    Instance,
    InstanceOptions,
    UnwritableReturnError,
    write_instance,
)

__all__ = ["Instance", "InstanceOptions", "UnwritableReturnError", "write_instance"]
