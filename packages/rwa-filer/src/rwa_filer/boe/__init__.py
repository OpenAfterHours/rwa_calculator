"""
The Bank of England's validation rules, evaluated as the taxonomy evaluates them.

Pipeline position:
    CanonicalReturn + TaxonomyPack + RuleBook  ->  boe.engine.evaluate_rules
        ->  one outcome per enforced rule

Why this is its own package: the Bank publishes each rule twice — as a formula
in the XBRL taxonomy, which its gateway executes, and as a row in a workbook,
which says the same thing in a compact language. This package reads the
workbook and evaluates the rule with the TAXONOMY's semantics: one evaluation
per combination of cells, per-reference defaults for unreported cells, rounding
allowances taken from each fact's stated accuracy, and no evaluation at all for
a template that is not reported. Its verdicts are meant to equal the gateway's,
and the Arelle referee exists to check that they do.

Module map:
- ``grammar``   — the rule language: lexer, parser, syntax tree
- ``importer``  — a rule workbook as a packaged rule book
- ``catalogue`` — the packaged rule books; which rules a module enforces
- ``engine``    — evaluation over a canonical return

References:
- Bank of England Banking Taxonomy v4.1.1 — validation rule workbooks and the
  formula linkbases they are serialised to
"""

from __future__ import annotations
