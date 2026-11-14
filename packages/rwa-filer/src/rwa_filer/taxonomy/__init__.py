"""
Taxonomy packs — the supervisor's data-point model, compiled to package data.

Pipeline position:
    BoE DPM workbooks + taxonomy package  ->  compiler.compile_pack  (offline)
        ->  taxonomy/data/<module>-<version>/  (package data)
        ->  pack.resolve_pack(module, reference_date)  ->  TaxonomyPack

Key responsibilities:
- Hold, for every reportable cell of every table in a reporting module, the
  XBRL data point it maps to: the metric and its dimension members.
- Resolve the pack that applies to a reference date, so a return is always read
  against the taxonomy version in force on that date.

The runtime never parses an XBRL taxonomy. A pack is compiled once, offline,
from the publisher's own files, and committed as versioned data — the same
pattern as the rule extracts in ``rwa_filer.rules``.

Module map:
- ``compiler`` — build a pack from the publisher's DPM workbooks and taxonomy
- ``pack``     — the pack's on-disk format, loader and resolver

References:
- Bank of England Banking Taxonomy (DPM dictionary, annotated templates,
  XBRL taxonomy package)
"""

from __future__ import annotations
