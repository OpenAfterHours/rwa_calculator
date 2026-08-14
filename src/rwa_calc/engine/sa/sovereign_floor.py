"""
Art. 121(6) sovereign risk-weight floor for FX unrated institution exposures.

Pipeline position:
    ``engine/sa/risk_weights.py::apply_risk_weights`` -> here, after the
    framework override chain and the Art. 140(2) short-term contamination
    override, before the Art. 127 defaulted blend.

Key responsibilities:
- Floor an unrated institution's risk weight at its jurisdiction's sovereign
  risk weight when the exposure is NOT in the institution's domestic currency.
- Emit ``sa_risk_weight_branch_reason`` beside the value, naming which limb of
  the rule decided the row — and, where the domesticity test is itself
  indeterminate, saying so instead of silently leaving the row unfloored.

Why this rule has its own module
--------------------------------
It was extracted from ``risk_weights.py`` when Phase 3 instrumented it: that
file sits on the ``max_engine_module_loc`` ratchet with single-digit headroom,
so the instrument had nowhere to go (`.claude/LESSONS.md` G — extract as you
go). The rule is a self-contained article with one entry point, so the seam is
natural rather than forced.

References:
- PRA PS1/26 Art. 121(6) — the floor (UK CRR Art. 121 has four paragraphs and
  no (5) or (6); the engine applies the provision under both regimes, which
  IMPLEMENTATION_PLAN.md P1.334 records as owed work, not as this module's)
- PRA PS1/26 Art. 114(1)-(2) — the floor's value source
- CRE20.22 + footnote 13 — Basel 3.1 SCRA sovereign floor and its trade carve-out
- docs/plans/test-space-correctness-proposal.md — Phase 3
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.domain.branch_reasons import SA_RISK_WEIGHT_BRANCH_REASON, SovereignFloorReason
from rwa_calc.domain.enums import CQS, RiskType
from rwa_calc.engine.branch_reason import BranchCase, decide
from rwa_calc.engine.sa.crr_risk_weight_tables import CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS
from rwa_calc.engine.sa.sovereign_derived import cqs_table_lookup_expr

logger = logging.getLogger(__name__)


@cites("CRR Art. 121")
@cites("PS1/26, paragraph 121")
def apply_sovereign_floor_for_institutions(
    exposures: pl.LazyFrame,
    is_domestic_currency_expr: pl.Expr,
) -> pl.LazyFrame:
    """Apply sovereign RW floor for FX unrated institution exposures.

    Art. 121(6) (CRR) / CRE20.22 (Basel 3.1): The risk weight for an
    unrated institution exposure not denominated in the institution's
    domestic currency cannot be lower than the sovereign risk weight of
    the institution's jurisdiction.

    Exception: Self-liquidating trade-related contingent items arising
    from the movement of goods with original maturity ≤ 1 year are not
    subject to this floor (CRE20.22 footnote 13).

    Exception: QCCP **trade** exposures, which CRR Art. 306 pins at 2%
    (clearing member's own) / 4% (client-cleared) as lex specialis. CRR
    Art. 107(2) sends only trade exposures and default fund contributions
    to Chapter 6 Section 9; "all other types of exposures to a qualifying
    CCP" are treated as exposures to an institution and stay inside this
    floor, so the carve-out is gated on the CCR trade ``risk_type`` and not
    on the counterparty being a QCCP alone (P1.342).

    The floor is defined by reference to Art. 114(1) **and** (2), so an
    unrated sovereign does not escape it: Art. 114(2) Table 1 prices the
    rated ladder and Art. 114(1) supplies the 100% residual for a central
    government with no ECAI assessment. A null ``cp_sovereign_cqs``
    therefore floors at 100%, not at nothing (P1.254). Art. 121(6) cites
    only paragraphs (1) and (2) of Art. 114, so the ECB 0% relief and the
    UK-sterling 0% relief sit deliberately outside the cross-reference and
    are not consulted here — the floor exists precisely for exposures that
    are NOT in the local currency.

    Asymmetry, recorded rather than papered over: a frame that never
    carries ``cp_sovereign_cqs`` **at all** is still left unfloored, as
    ``test_missing_columns_backward_compat`` pins. That shape only arises
    in synthetic unit frames — production rows always carry the column
    (nullable) off the sealed ``crm_exit`` edge — so no capital number
    depends on it. Do not "fix" it by asserting the contract null-fill
    covers the case; it demonstrably does not. See P1.312.
    ``cp_local_currency`` enables accurate FX detection; when absent,
    falls back to the UK/EU domestic currency expression.

    References:
    - CRR Art. 121(6)
    - PRA PS1/26 Art. 121(6)
    - PRA PS1/26 Art. 114(1)-(2) — the floor's value source
    - CRE20.22 (Basel 3.1 SCRA sovereign floor)
    - CRR Art. 306(1)(a)/(c), Art. 307 — the QCCP trade-exposure weights the
      carve-out protects. No ``@cites`` decorator: watchfire's bundled CRR
      index does not cover Arts. 300-311 (omitted from the onshored
      consolidation by SI 2021/1078), so the attribution is a docstring one.
    - CRR Art. 107(2) — only trade exposures and default fund contributions
      reach the Chapter 6 Section 9 regime
    """
    _uc = pl.col("_upper_class")

    # Art. 114(1) residual for a central government with no ECAI assessment —
    # the value the floor falls back to so an unrated sovereign does not escape
    # it (P1.254). Read inside the function, from the same pack-bound table the
    # direct CGCB ladder uses, so this module declares no regulatory literal at
    # module scope (arch_check check 5) and none of its own anywhere.
    cgcb_unrated_rw = float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED])

    # Sovereign CQS → risk weight mapping (Art. 114(2) Table 1 —
    # CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS), falling back to the
    # Art. 114(1) unrated-sovereign residual so the floor still binds when
    # the jurisdiction's central government carries no ECAI assessment.
    _sovereign_rw = cqs_table_lookup_expr(
        "cp_sovereign_cqs",
        CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
        cgcb_unrated_rw,
    )

    # Compute sovereign RW as a temporary column
    exposures = exposures.with_columns(_sovereign_rw.alias("_sovereign_rw"))

    # FX detection: exposure currency != institution's domestic currency.
    # Use cp_local_currency if available; fall back to UK/EU domestic check.
    _is_fx = (
        pl.when(pl.col("cp_local_currency").is_not_null())
        .then(pl.col("currency").fill_null("") != pl.col("cp_local_currency"))
        .otherwise(~is_domestic_currency_expr)
    )

    # Exception: self-liquidating trade items ≤ 1yr original maturity
    # (Art. 121(6) CRR / CRE20.22 footnote 13 — both key on ORIGINAL maturity).
    _is_trade_exempt = pl.col("is_short_term_trade_lc").fill_null(False) & (
        pl.col("original_maturity_years").fill_null(5.0) <= 1.0
    )

    # Exception: QCCP TRADE exposures (CRR Art. 306 / CRE54.14-15), which the
    # risk-weight chain pins at 2% (proprietary) / 4% (client-cleared). Art. 306
    # is lex specialis and admits no Art. 121(6) floor; flooring a 2% pin to the
    # Art. 114(1) unrated-sovereign residual overstates the leg 50x.
    #
    # The predicate carries a TRADE-EXPOSURE term as well as the QCCP one, and
    # that is the whole of its difference from the pin's own predicate in
    # ``risk_weights.py``. CRR Art. 107(2) sends only trade exposures and default
    # fund contributions to Chapter 6 Section 9; "all other types of exposures to
    # a qualifying CCP" are treated "as exposures to an institution", so an
    # ordinary loan to a QCCP stays squarely inside Art. 121(6). Copying the pin's
    # predicate would exempt that loan too.
    #
    # Null-safe on every term WITHOUT a ``fill_null``: this case sits FIRST in the
    # chain below, and ``decide`` names a row UNKNOWN_FALLBACK the moment a
    # predicate ahead of it is indeterminate — so a null here would relabel the
    # whole estate. ``eq_missing`` is total by construction, and
    # ``is_null() | col`` is total by Kleene (the right operand can only be read
    # when the left is False, i.e. when the column is known). That keeps the
    # defensive surface off the ``engine_fill_null_sites`` ratchet.
    #
    # An absent ``cp_is_qccp`` is read as qualifying, matching the pin in
    # ``risk_weights.py`` that set the weight this limb protects.
    _is_ccr_trade_exposure = pl.col("risk_type").eq_missing(RiskType.CCR_DERIVATIVE.value) | pl.col(
        "risk_type"
    ).eq_missing(RiskType.CCR_SFT.value)
    _is_qccp = pl.col("cp_entity_type").eq_missing("ccp") & (
        pl.col("cp_is_qccp").is_null() | pl.col("cp_is_qccp")
    )
    _is_qccp_trade_exposure = _is_ccr_trade_exposure & _is_qccp

    # Floor applies to every unrated institution exposure in FX, excluding
    # trade-exempt items. No sovereign-CQS gate: ``_sovereign_rw`` is total
    # over the Art. 114(1)+(2) domain, so an unrated sovereign floors at 100%.
    _is_unrated = pl.col("cqs").is_null() | (pl.col("cqs") <= 0)
    _is_institution = _uc.str.contains("INSTITUTION", literal=True)

    _floor_applies = _is_institution & _is_unrated & _is_fx & ~_is_trade_exempt

    # Instrumented (Phase 3): the reason is emitted beside the value from the
    # SAME predicates, so the two cannot drift.
    #
    # VALUE EQUIVALENCE, discharged rather than assumed. Every case below but
    # FLOOR_BOUND yields the incumbent ``risk_weight``, as does ``otherwise``,
    # so the only case that can move a number is FLOOR_BOUND — and its
    # predicate is the ORIGINAL ``_floor_applies`` conjunction, merely ANDed
    # with the condition under which ``max_horizontal`` would have picked the
    # sovereign leg. Hence: floor applies and binds -> sovereign RW (as
    # before); floor applies and does not bind -> ``risk_weight`` (as before,
    # since ``max`` would have returned it); floor does not apply, or is
    # indeterminate -> ``risk_weight`` (as before, since ``pl.when`` sends both
    # False and null to ``otherwise``). Splitting the conjunction into ordered
    # cases WITHOUT this discipline would arm the floor on rows where a null
    # term currently disarms it — a live RWA change wearing an instrument's
    # clothes. See ``engine/branch_reason.py``.
    #
    # The DOMESTIC_CURRENCY case is where P1.333 surfaces: for a counterparty
    # outside the UK/EU domestic-currency map with no ``cp_local_currency``,
    # ``is_domestic_currency_expr`` is null, so ``~_is_fx`` is null and the row
    # is named UNKNOWN_FALLBACK instead of silently keeping an unfloored RW.
    #
    # The Art. 306 carve-out sits FIRST: it is lex specialis, so a QCCP trade
    # exposure is out of the floor's scope whatever the later limbs say about
    # its rating or its domesticity. Its value leg is the untouched incumbent
    # ``risk_weight``, so it moves no number that was not already going to be
    # left alone — the equivalence argument above is unchanged by it, and the
    # rows it newly NAMES are exactly the rows leg 2 newly takes off
    # UNKNOWN_FALLBACK.
    _rw = pl.col("risk_weight")
    floor_value, floor_reason = decide(
        (
            BranchCase(SovereignFloorReason.QCCP_TRADE_EXPOSURE, _is_qccp_trade_exposure, _rw),
            BranchCase(SovereignFloorReason.NOT_INSTITUTION, ~_is_institution, _rw),
            BranchCase(SovereignFloorReason.RATED, ~_is_unrated, _rw),
            BranchCase(SovereignFloorReason.TRADE_EXEMPT, _is_trade_exempt, _rw),
            BranchCase(SovereignFloorReason.DOMESTIC_CURRENCY, ~_is_fx, _rw),
            BranchCase(
                SovereignFloorReason.FLOOR_BOUND,
                _floor_applies & (pl.col("_sovereign_rw") > _rw),
                pl.max_horizontal(_rw, pl.col("_sovereign_rw")),
            ),
        ),
        otherwise=_rw,
        otherwise_reason=SovereignFloorReason.FLOOR_NOT_BINDING,
        vocabulary=SovereignFloorReason,
    )

    return exposures.with_columns(
        floor_value.alias("risk_weight"),
        floor_reason.alias(SA_RISK_WEIGHT_BRANCH_REASON),
    )
