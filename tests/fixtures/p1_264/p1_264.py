"""
Generate P1.264 fixtures: CRR/PS1-26 Art. 140(1) short-term-override
obligor-class gate.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/hierarchy/enrich.py: ``apply_short_term_rating_override`` —
    class-gate the override to institution/corporate obligors only, per
    Art. 140(1); optionally a new DQ error, e.g. DQ-RT-ST3, for out-of-class
    short-term rating rows)

Key responsibilities:
- Produce five counterparty rows: CP_P264_SOV (sovereign, external CQS 1
  long-term rating -> baseline 0% RW), CP_P264_INST (institution, unrated at
  the counterparty level, correctly-eligible-class control), CP_P264_CORP
  (corporate, unrated at the counterparty level, correctly-eligible-class
  control), CP_P264_SOV2 (sovereign, UNRATED -- no counterparty rating row
  at all -- the P1.225-interaction / observable-leak obligor), CP_P264_NULLTYPE
  (entity_type=NULL -- the reviewer-found null-obligor-class path probe;
  pipeline-verified NOT to hard-fail, see the module docstring's pipeline-run
  notes).
- Produce six GBP 1,000,000 loans:
    LN_P264_S1 / LN_P264_I1 / LN_P264_C1: one per CP_P264_SOV / _INST /
      _CORP, short original maturity (73 days, mirroring p1_216/p1_223/
      p1_225 -- 73/365 ~= 0.1999y <= 0.25y, ST window).
    LN_P264_S2A: CP_P264_SOV2, short original maturity (same 73-day window)
      -- carries the mis-scoped CQS 4 (150%-trigger) rating.
    LN_P264_S2B: CP_P264_SOV2, LONG-term (3y, 2027-01-01 -> 2030-01-01),
      unrated, unsecured -- the sibling exposure that P1.225's obligor-level
      contamination (already landed) should wrongly force to 150% today,
      via S2A's corrupted ``has_short_term_ecai`` / cqs -- see the
      pipeline-run verification notes below.
    LN_P264_N1: CP_P264_NULLTYPE, short original maturity (same 73-day
      window) -- carries a mis-scoped ST-CQS3 rating, same shape as S1's.
- Produce six loan-scoped short-term issue-specific ECAI ratings (mirrors
  p1_216's ``scope_type='loan'`` attachment -- no facility parent needed):
    RTG_P264_S1: scoped to LN_P264_S1 (CP_P264_SOV, sovereign), CQS 3 --
        the MIS-SCOPED rating this fixture targets. Art. 140(1) confines
        short-term ECAI assessments to institution/corporate obligors; a
        sovereign is neither, so this override must be REJECTED.
    RTG_P264_I1: scoped to LN_P264_I1 (CP_P264_INST, institution), CQS 2 --
        correctly-scoped control, proves the gate does not also suppress
        legitimate institution overrides.
    RTG_P264_C1: scoped to LN_P264_C1 (CP_P264_CORP, corporate), CQS 2 --
        correctly-scoped control, proves the gate does not also suppress
        legitimate corporate overrides.
    RTG_P264_S2A: scoped to LN_P264_S2A (CP_P264_SOV2, sovereign, UNRATED
        at the counterparty level), CQS 4 -- the 150%-trigger mis-scope
        this fixture's observable-leak scenario targets.
    RTG_P264_N1: scoped to LN_P264_N1 (CP_P264_NULLTYPE, entity_type=NULL),
        CQS 3 -- pins the null-obligor-class path through the same gate.
- No facilities/facility_mappings, no collateral, no guarantees, no
  provisions -- clean five-obligor SA test.
- Framework: both ``CalculationConfig.crr()`` and ``CalculationConfig.
  basel_3_1()`` against the SAME parquets (SA permission mode) -- Art. 140(1)
  text is identical in both regimes.

Defect under test (pre-fix):
    ``apply_short_term_rating_override`` (engine/stages/hierarchy/enrich.py:
    229-240) overwrites ``cqs`` for ANY scope-matched exposure regardless of
    the underlying counterparty's exposure class. A short-term rating
    mis-scoped onto a sovereign loan (RTG_P264_S1) still replaces that row's
    long-term CQS and sets ``has_short_term_ecai=True`` -- there is no DQ
    validation rejecting out-of-class short-term rating rows. The B31 Table
    4A/6A branches ARE correctly class-gated to institutions/corporates
    (risk_weights.py:641, 711) so they never fire for the sovereign row
    regardless -- the actually-observed post-override effect on
    CP_P264_SOV's risk weight is reported by the pipeline-run verification
    below (not assumed), since the sovereign/CGCB risk-weight lookup is a
    separate code path from the institution/corporate ST branches.

    CP_P264_SOV2 / LN_P264_S2A / LN_P264_S2B probe the P1.225 interaction
    (already landed): ``_apply_obligor_st_contamination_flags``
    (engine/stages/hierarchy/enrich.py:882-926) has no class gate either --
    it reads only ``has_short_term_ecai`` / ``_st_assessment_cqs``, both
    already corrupted by the S2A mis-scope. Unlike CP_P264_SOV (single
    exposure, nothing to spill onto), CP_P264_SOV2 carries a SECOND, unrated,
    unsecured exposure (S2B) that the ``obligor_st_150_contamination`` flag
    (fired by S2A's corrupted CQS 4) can visibly force to 150% -- an
    RWA-visible failing-test baseline, unlike LN_P264_S1's RWA-inert case.
    Pipeline-run-verified, not assumed -- see verification notes below.

Post-fix assertion (primary):
    LN_P264_S1: the mis-scoped override is IGNORED -- cqs and risk_weight
        revert to the CQS-1 long-term sovereign baseline (0% RW), and
        has_short_term_ecai=False. One DQ warning is emitted.
    LN_P264_I1 / LN_P264_C1: UNCHANGED pre- and post-fix -- both are
        correctly-scoped institution/corporate short-term overrides, so the
        class gate must let them through unmodified (RW 50% via Table 7 /
        Table 4A-6A CQS 2, both regimes -- see p1_216/p1_225 precedent).
    LN_P264_S2A: mis-scoped override ignored (mirrors S1) -- reverts to the
        CP_P264_SOV2 unrated-sovereign baseline, has_short_term_ecai=False.
    LN_P264_S2B: with S2A's override rejected, ``obligor_st_150_contamination``
        never sets for CP_P264_SOV2 (no corrupted CQS 4 to trigger it) --
        S2B reverts to the same unrated-sovereign baseline as S2A.

Hand-calculation:
    CP_P264_SOV baseline (pre-override, CQS 1 sovereign, Art. 114 Table 1):
        RW = 0.00 -> RWA = 0 (both regimes)
    LN_P264_S1 (post-fix, override rejected): RW reverts to 0.00 -> RWA = 0
    LN_P264_I1 / LN_P264_C1 (CQS 2, Table 7 / Table 4A-6A):
        RW = 0.50 -> RWA = 1,000,000 x 0.50 = 500,000 (both regimes,
        pre- AND post-fix -- these are the "the gate does not break the
        legitimate case" regression guards)
    CP_P264_SOV2 unrated-sovereign baseline (pipeline-confirmed, isolated by
        dropping RTG_P264_S2A and re-running): RW = 1.00 (100%), both
        regimes -- exactly the CQS-table's UNRATED entry
        (rulebook/packs/crr.py:858, Decimal("1.00"), Art. 114 Table 1).
        NOTE: CP_P264_SOV2 is deliberately non-domestic (country_code="US")
        -- a GB/GBP sovereign hits the Art. 114(4)/(7) domestic-CGCB 0%
        override UNCONDITIONALLY (engine/sa/risk_weights.py:1006-1014),
        which would mask this fallback entirely regardless of rating status.
        RWA = 1,000,000.
    LN_P264_S2A (pre-fix, pipeline-confirmed): RW = 1.00 (100%), both
        regimes -- unchanged from the unrated baseline despite carrying the
        corrupted cqs=4 (CQS 4 happens to ALSO map to 100% on the CGCB
        table, so this observation alone does not distinguish "reads a
        separate cp_sovereign_cqs source" from "reads cqs but CQS4 and
        UNRATED coincide at 100%" -- both are consistent with the value).
    LN_P264_S2B (pre-fix, CONFIRMED RWA-VISIBLE FAILING BASELINE): 1.50
        (150%), both regimes -- the P1.225 obligor-level contamination flag
        (``obligor_st_150_contamination``) fires off S2A's corrupted
        ``has_short_term_ecai`` / cqs=4 with no class gate, forcing this
        genuinely unrated, unsecured, long-term SIBLING exposure to 150%
        even though it carries no rating of its own and its own maturity
        is outside the ST window. RWA = 1,000,000 x 1.50 = 1,500,000 (a
        50pp / GBP 500,000 overstatement vs the correct 100% baseline).
        Post-fix (class gate applied): S2A's override is rejected, the
        contamination flag never sets, S2B reverts to 1.00 (100%),
        RWA = 1,000,000.

References:
    - CRR Art. 140(1) / PS1/26 Art. 140(1) (CRE21.16): short-term credit
      assessments may only be used for short-term asset and off-balance-sheet
      items constituting exposures to institutions and corporates.
    - CRR Art. 114 Table 1 / PS1/26 Art. 114: sovereign CQS-to-RW mapping
      (CQS 1 = 0%), identical under both regimes.
    - CRR Art. 131 Table 7 (landed P1.216) / PS1/26 Art. 120(2B) Table 4A /
      Art. 122(3) Table 6A: CQS 1-6 -> 20/50/100/150/150/150.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:129-133
      (P1.264 finding).
    - tests/fixtures/p1_216/p1_216.py: loan-scoped rating attachment pattern
      (``scope_type='loan'``, no facility parent needed) -- reused here.
    - tests/fixtures/p1_225/p1_225.py: sibling Art. 140(2) obligor-level
      fixture (already landed) -- this fixture reuses the same short
      original-maturity window and checks whether P1.225's obligor-level
      contamination flags (``obligor_st_150_contamination`` /
      ``obligor_st_50_floor``, contracts/edges.py:550-556) spuriously fire on
      CP_P264_SOV's mis-scoped row -- see the pipeline-run verification notes.

Usage:
    uv run python tests/fixtures/p1_264/p1_264.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_SOV_REF = "CP_P264_SOV"  # sovereign, CQS 1 long-term rating, mis-scoped ST target
CP_INST_REF = "CP_P264_INST"  # institution, correctly-scoped ST control
CP_CORP_REF = "CP_P264_CORP"  # corporate, correctly-scoped ST control
CP_SOV2_REF = "CP_P264_SOV2"  # sovereign, UNRATED, P1.225-interaction / observable-leak obligor
CP_NULLTYPE_REF = "CP_P264_NULLTYPE"  # entity_type=NULL, reviewer-found null-class path probe

LOAN_S1_REF = "LN_P264_S1"
LOAN_I1_REF = "LN_P264_I1"
LOAN_C1_REF = "LN_P264_C1"
LOAN_S2A_REF = "LN_P264_S2A"  # CP_SOV2, short-term, mis-scoped ST-CQS4 (150% trigger)
LOAN_S2B_REF = "LN_P264_S2B"  # CP_SOV2, long-term, unrated, unsecured (contamination target)
LOAN_N1_REF = "LN_P264_N1"  # CP_NULLTYPE, short-term, mis-scoped ST-CQS3 (same shape as S1)

RATING_SOV_LONG_TERM_REF = "RTG_P264_SOV_LT"
RATING_S1_MISSCOPED_REF = "RTG_P264_S1"
RATING_I1_REF = "RTG_P264_I1"
RATING_C1_REF = "RTG_P264_C1"
RATING_S2A_MISSCOPED_REF = "RTG_P264_S2A"
RATING_N1_MISSCOPED_REF = "RTG_P264_N1"

# Short-term (ST) window: 73 days = 2027-03-15 - 2027-01-01 -> 73/365 ~= 0.1999y
# (<= 0.25y), mirroring p1_216 / p1_223 / p1_225.
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE_SHORT_TERM = date(2027, 3, 15)
# Long-term sibling window (mirrors p1_225's E2/E5/E6): > 0.25y, outside the ST
# window, so S2B's own maturity cannot itself trigger has_short_term_ecai --
# any 150% it shows must come from obligor-level contamination, not S2B's
# own (non-existent) rating.
MATURITY_DATE_LONG_TERM = date(2030, 1, 1)

DRAWN_AMOUNT = 1_000_000.0  # every loan is GBP 1,000,000 drawn, interest=0

CQS_SOV_LONG_TERM = 1  # sovereign CQS 1 -> 0% RW (Art. 114 Table 1)
CQS_S1_MISSCOPED = 3  # mis-scoped short-term assessment CQS on the sovereign loan
CQS_I1_CORRECT = 2  # institution control -> Table 7 / Table 4A CQS 2 = 50%
CQS_C1_CORRECT = 2  # corporate control -> Table 7 / Table 6A CQS 2 = 50%
CQS_S2A_MISSCOPED = 4  # mis-scoped ST-CQS4 -> Table 7 150%-trigger band (Art. 140(2)(a))
CQS_N1_MISSCOPED = (
    3  # mis-scoped short-term assessment CQS on the null-entity-type loan (mirrors S1)
)

RATING_AGENCY = "S&P"
RATING_DATE = date(2027, 1, 2)

# Table 7 / Table 4A-6A risk weights, numerically identical under CRR
# (landed P1.216) and B31.
EXPECTED_RW_SOV_BASELINE: float = 0.00  # CQS 1, Art. 114 Table 1
EXPECTED_RW_I1: float = 0.50  # CQS 2, both pre- and post-fix
EXPECTED_RW_C1: float = 0.50  # CQS 2, both pre- and post-fix
# CP_P264_SOV2's true unrated baseline (pipeline-confirmed by isolating the
# S2A mis-scope), and the post-fix value both S2A and S2B revert to.
EXPECTED_RW_SOV2_UNRATED_BASELINE: float = 1.00  # CQS-table UNRATED entry
# Expected RWA-visible failing baseline for S2B today (pipeline-confirmed) --
# see the module docstring for the P1.225-interaction hand-calc.
EXPECTED_RW_S2B_PRE_FIX_CONTAMINATED: float = 1.50
# CP_P264_NULLTYPE: entity_type=NULL falls through every ENTITY_TYPE_TO_SA_CLASS
# entry -> exposure_class="other" -> the class-default fallback RW (pipeline-
# confirmed, both regimes -- see module docstring). Unaffected by whether the
# mis-scoped rating override applies (has_short_term_ecai stays False /
# cqs stays null either way -- entity_type "other" is not on the ECRA/SCRA
# short-term Table 7 / Table 4A-6A class list at all), so this is a pure
# class-fallback invariance check, not a movement check like S1/S2A/S2B.
EXPECTED_RW_NULLTYPE_BASELINE: float = 1.00

EXPECTED_RWA_SOV_POST_FIX: float = DRAWN_AMOUNT * EXPECTED_RW_SOV_BASELINE  # 0
EXPECTED_RWA_I1: float = DRAWN_AMOUNT * EXPECTED_RW_I1  # 500,000
EXPECTED_RWA_C1: float = DRAWN_AMOUNT * EXPECTED_RW_C1  # 500,000
EXPECTED_RWA_SOV2_UNRATED_BASELINE: float = (
    DRAWN_AMOUNT * EXPECTED_RW_SOV2_UNRATED_BASELINE
)  # 1,000,000
EXPECTED_RWA_S2B_PRE_FIX_CONTAMINATED: float = (
    DRAWN_AMOUNT * EXPECTED_RW_S2B_PRE_FIX_CONTAMINATED
)  # 1,500,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.264 counterparty row (sovereign target or institution/corporate control)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str | None
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.264 loan: GBP 1,000,000 drawn, senior; ST window by default, or the
    long-term window for S2B (the contamination-target sibling)."""

    loan_reference: str
    counterparty_reference: str
    maturity_date: date = MATURITY_DATE_SHORT_TERM

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": "GBP",
            "value_date": VALUE_DATE,
            "maturity_date": self.maturity_date,
            "drawn_amount": DRAWN_AMOUNT,
            "interest": 0.0,
            "seniority": "senior",
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.264 external rating row.

    Loan-scoped short-term issue-specific ECAI assessment (``scope_type=
    'loan'`` -- mirrors p1_216, no facility parent needed), or the
    sovereign's plain long-term external rating (scope null/null).
    """

    rating_reference: str
    counterparty_reference: str
    rating_agency: str
    rating_value: str
    cqs: int
    rating_date: date
    is_short_term: bool
    scope_type: str | None
    scope_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": "external",
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": None,
            "rating_date": self.rating_date,
            "is_solicited": True,
            "model_id": None,
            "is_short_term": self.is_short_term,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p264_counterparties() -> pl.DataFrame:
    """Return the four P1.264 counterparties as a DataFrame."""
    rows = [
        _Counterparty(
            counterparty_reference=CP_SOV_REF,
            counterparty_name="P1.264 Sovereign Mis-Scope Target",
            entity_type="sovereign",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_INST_REF,
            counterparty_name="P1.264 Institution Correctly-Scoped Control",
            entity_type="bank",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_CORP_REF,
            counterparty_name="P1.264 Corporate Correctly-Scoped Control",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,  # large corporate, matches CORP_UR_001 / P1.225 CP-X
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_SOV2_REF,
            counterparty_name="P1.264 Unrated Sovereign, P1.225 Interaction Probe",
            entity_type="sovereign",
            # NON-domestic (US, not GB/EU) -- load-bearing. A GB/GBP sovereign
            # hits the CRR Art. 114(4)/(7) domestic-CGCB 0% override
            # UNCONDITIONALLY (engine/sa/risk_weights.py:1006-1014,
            # is_uk_domestic), which would mask the genuine unrated-sovereign
            # CQS-table fallback (CQS.UNRATED = 100%, rulebook/packs/crr.py:858)
            # this scenario needs to exercise. US avoids both the UK and EU
            # domestic-currency carve-outs, so the CQS-table lookup actually
            # runs.
            country_code="US",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            # Deliberately UNRATED -- no rating row of any kind (contrast with
            # CP_P264_SOV, which carries a genuine CQS-1 long-term rating).
            # Isolates the unrated-sovereign baseline the pipeline-run
            # verification reports, so S2A/S2B's post-contamination values
            # are compared against an unambiguous, rating-free starting point.
        ),
        _Counterparty(
            counterparty_reference=CP_NULLTYPE_REF,
            counterparty_name="P1.264 Null Entity Type Probe",
            # entity_type=NULL -- pipeline-verified tolerant (no hard failure):
            # falls through every ENTITY_TYPE_TO_SA_CLASS entry to
            # exposure_class="other". Confirms the mis-scoped-rating class
            # gate handles a null obligor class the same way as a genuine
            # ineligible one (sovereign, in S1's case), not a separate crash
            # path.
            entity_type=None,
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p264_loans() -> pl.DataFrame:
    """Return the six P1.264 loans (S1/I1/C1/S2A/S2B/N1) as a DataFrame."""
    rows = [
        _Loan(LOAN_S1_REF, CP_SOV_REF),
        _Loan(LOAN_I1_REF, CP_INST_REF),
        _Loan(LOAN_C1_REF, CP_CORP_REF),
        _Loan(LOAN_S2A_REF, CP_SOV2_REF),
        _Loan(LOAN_S2B_REF, CP_SOV2_REF, maturity_date=MATURITY_DATE_LONG_TERM),
        _Loan(LOAN_N1_REF, CP_NULLTYPE_REF),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p264_ratings() -> pl.DataFrame:
    """
    Return the six P1.264 rating rows as a DataFrame.

    RTG_P264_SOV_LT: sovereign's own long-term external rating, CQS 1,
    is_short_term=False, scope null/null -- the Art. 114 Table 1 baseline
    (0% RW) that the mis-scoped override must NOT be allowed to displace.
    RTG_P264_S1: loan-scoped ST assessment mis-scoped onto the sovereign's
    loan -- CQS 3, is_short_term=True -- the Art. 140(1) violation this
    fixture targets.
    RTG_P264_I1 / RTG_P264_C1: correctly-scoped institution/corporate ST
    assessments, CQS 2 -- regression-guard controls.
    RTG_P264_S2A: loan-scoped ST assessment mis-scoped onto CP_P264_SOV2's
    S2A loan -- CQS 4 (the 150%-trigger band), is_short_term=True -- no
    long-term rating exists for CP_P264_SOV2 at all (genuinely unrated).
    RTG_P264_N1: loan-scoped ST assessment mis-scoped onto CP_P264_NULLTYPE's
    N1 loan -- CQS 3, is_short_term=True (same shape as RTG_P264_S1) --
    CP_P264_NULLTYPE carries entity_type=NULL, not sovereign; this pins the
    null-obligor-class path through the same class gate S1 exercises for a
    genuinely ineligible (but non-null) class.
    """
    rows = [
        _Rating(
            rating_reference=RATING_SOV_LONG_TERM_REF,
            counterparty_reference=CP_SOV_REF,
            rating_agency=RATING_AGENCY,
            rating_value="AAA",
            cqs=CQS_SOV_LONG_TERM,
            rating_date=RATING_DATE,
            is_short_term=False,
            scope_type=None,
            scope_id=None,
        ),
        _Rating(
            rating_reference=RATING_S1_MISSCOPED_REF,
            counterparty_reference=CP_SOV_REF,
            rating_agency=RATING_AGENCY,
            rating_value="BBB",
            cqs=CQS_S1_MISSCOPED,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_S1_REF,
        ),
        _Rating(
            rating_reference=RATING_I1_REF,
            counterparty_reference=CP_INST_REF,
            rating_agency=RATING_AGENCY,
            rating_value="A-2",
            cqs=CQS_I1_CORRECT,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_I1_REF,
        ),
        _Rating(
            rating_reference=RATING_C1_REF,
            counterparty_reference=CP_CORP_REF,
            rating_agency=RATING_AGENCY,
            rating_value="A-2",
            cqs=CQS_C1_CORRECT,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_C1_REF,
        ),
        _Rating(
            rating_reference=RATING_S2A_MISSCOPED_REF,
            counterparty_reference=CP_SOV2_REF,
            rating_agency=RATING_AGENCY,
            rating_value="B",
            cqs=CQS_S2A_MISSCOPED,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_S2A_REF,
        ),
        _Rating(
            rating_reference=RATING_N1_MISSCOPED_REF,
            counterparty_reference=CP_NULLTYPE_REF,
            rating_agency=RATING_AGENCY,
            rating_value="BBB",
            cqs=CQS_N1_MISSCOPED,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_N1_REF,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p264_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.264 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p264_counterparties()),
        ("loan", create_p264_loans()),
        ("rating", create_p264_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.264 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR/PS1-26 Art. 140(1) short-term-override class gate")
    print(
        f"  LN_P264_S1 (CP_SOV, mis-scoped ST-CQS3): baseline sovereign RW="
        f"{EXPECTED_RW_SOV_BASELINE:.0%} (CQS 1); pre-fix effect = REPORT "
        "(pipeline-run observed); post-fix override rejected -> RW reverts to "
        f"{EXPECTED_RW_SOV_BASELINE:.0%}, RWA={EXPECTED_RWA_SOV_POST_FIX:,.0f}"
    )
    print(
        f"  LN_P264_I1 (CP_INST, correctly-scoped ST-CQS2): RW={EXPECTED_RW_I1:.0%} "
        f"RWA={EXPECTED_RWA_I1:,.0f} -- unchanged pre- and post-fix"
    )
    print(
        f"  LN_P264_C1 (CP_CORP, correctly-scoped ST-CQS2): RW={EXPECTED_RW_C1:.0%} "
        f"RWA={EXPECTED_RWA_C1:,.0f} -- unchanged pre- and post-fix"
    )
    print(
        f"  LN_P264_S2A (CP_SOV2 unrated, mis-scoped ST-CQS4): RW="
        f"{EXPECTED_RW_SOV2_UNRATED_BASELINE:.0%} (both regimes, unchanged by its own "
        "corrupted cqs=4) -- pipeline-confirmed"
    )
    print(
        f"  LN_P264_S2B (CP_SOV2, unrated long-term unsecured sibling): pre-fix RW="
        f"{EXPECTED_RW_S2B_PRE_FIX_CONTAMINATED:.0%} RWA={EXPECTED_RWA_S2B_PRE_FIX_CONTAMINATED:,.0f} "
        "(P1.225 contamination leak, pipeline-confirmed both regimes) -> post-fix RW="
        f"{EXPECTED_RW_SOV2_UNRATED_BASELINE:.0%} RWA={EXPECTED_RWA_SOV2_UNRATED_BASELINE:,.0f}"
    )
    print(
        f"  LN_P264_N1 (CP_NULLTYPE, entity_type=NULL, mis-scoped ST-CQS3): RW="
        f"{EXPECTED_RW_NULLTYPE_BASELINE:.0%} (both regimes; exposure_class='other' "
        "class-fallback, unaffected by the mis-scope) -- pipeline-confirmed, null "
        "entity_type tolerated (no hard failure)"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p264_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
