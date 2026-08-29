"""
Hierarchy resolution domain package.

Pipeline position:
    securitisation_allocator -> hierarchy_resolver -> ccr_sa_ccr

Layout:
- ``resolver``         — ``HierarchyResolver``: the stage recipe + back-compat
  private-method delegators
- ``graph``            — counterparty/facility graph resolution + CP lookup
- ``ratings``          — dual rating-inheritance resolution
- ``facility_undrawn`` — synthetic undrawn rows (MOF / Facility Share)
- ``unify``            — loans/contingents/undrawn -> unified exposure frame
- ``enrich``           — unified-frame decoration (QRRE, ratings, RE, LTV,
  lending group)

The ``run(ctx, rulepack, run_config)`` adapter that wires this domain into the
fold lives at ``engine/stages/hierarchy.py``, not here: ``engine/stages/`` is
the wiring layer and holds nothing else. This package is the only home of the
hierarchy domain; import ``HierarchyResolver`` and
``_FACILITY_QRRE_COUPLED_COLUMNS`` from here.

References:
- CRR Art. 4(1)(39): Group of connected clients (hierarchy resolution)
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
"""

from __future__ import annotations

from rwa_calc.engine.hierarchy.resolver import HierarchyResolver as HierarchyResolver

# QRRE-relevant facility-level columns that must be coupled across two sites:
#   Site A — `facility_undrawn._undrawn_select_expressions` projects these from
#            the facility frame when synthesising `facility_undrawn` exposure
#            rows.
#   Site B — `enrich.propagate_facility_qrre_columns` joins+coalesces these
#            from the facility frame onto the unified exposure frame
#            (loans / contingents).
# The two operations are intentionally different shapes (project vs. join+coalesce)
# and must not be merged — this constant simply pins the column set both sites
# agree on so they cannot drift out of sync.
_FACILITY_QRRE_COUPLED_COLUMNS: tuple[str, ...] = (
    "is_revolving",
    "is_qrre_transactor",
    # PRA PS1/26 Art. 147(5A)(b) / CRR Art. 154(4)(b): facility-level "secured"
    # attestation. Coupled like the other QRRE drivers so BOTH the drawn loan
    # exposures under the facility (Site B) and the synthesised facility_undrawn
    # rows (Site A) inherit it, letting the classifier's unsecured gate demote a
    # secured revolving retail facility in full.
    "is_secured",
    "facility_limit",
    "facility_termination_date",
)
