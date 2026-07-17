"""
Generate P1.227 fixtures: CRR/PS1-26 Art. 201 guarantor-eligibility gate.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/crm/guarantees.py: gate the SA fallback in
    ``_assign_guarantor_approach`` with
    ``guarantor_eligible = ~is_corporate | (guarantor_cqs not null) |
    (beneficiary_is_irb & guarantor_internal_pd not null)``; ineligible ->
    ``guarantor_approach=""`` (no substitution, borrower basis) + a new
    CRM013 warning)

Key responsibilities:
- Produce six counterparty rows:
    CP_P227_B: corporate, external CQS 5 rating -> 150% SA baseline (Art.
        122 Table 5 / Art. 122(2) Table 6, identical at CQS 5 -- both
        regimes). Beneficiary for G1, G2, G4, G5.
    CP_P227_B_IRB: corporate, INTERNAL rating only (pd, model_id=
        "MOD_CORP_P227"), no external rating. Beneficiary for G3 only --
        deliberately a SEPARATE borrower (not CP_P227_B) so the SA and IRB
        beneficiary legs never contend for the same model_permission /
        book_code in one pipeline run (rejected an ``excluded_book_codes``
        single-borrower design as fragile -- see the design sketch
        conversation).
    CP_P227_G1: corporate, genuinely UNRATED (no rating row of any kind) --
        the ineligible-guarantor case Art. 201(1)(g) targets.
    CP_P227_G2: corporate, external CQS 2 -> 50% RW (both regimes) --
        eligible-SA-guarantor control.
    CP_P227_G34: corporate, INTERNAL rating only (pd) -- no external CQS,
        no model_id needed (internal_pd promotion to the rating_inheritance
        frame does not depend on model_id/permission matching --
        hierarchy/ratings.py:88-101). Shared guarantor for G3 (IRB
        beneficiary, Art. 201(2) internal-rating limb) and G4 (SA
        beneficiary, where an internal-only rating is NOT an eligible
        external assessment).
    CP_P227_G5: individual (retail), no ratings of any kind -- the
        review-addendum probe. Art. 201(1) does not list retail persons as
        eligible protection providers; P1.227's engine change will NOT gate
        this (falls through ``_assign_guarantor_approach``'s
        ``.then("sa")`` branch today, out of scope for this item's fix) --
        this fixture only RECORDS today's baseline as evidence for a
        possible separate plan item.
- Produce five GBP 1,000,000 loans, one per guarantee scenario (G1-G5), all
  senior, 3-year maturity, no facilities/facility_mappings.
- Produce four rating rows (RTG_P227_B / _B_IRB / _G2 / _G34) -- CP_P227_G1
  and CP_P227_G5 carry NO rating row at all (genuinely unrated).
- Produce five guarantee rows, one per loan, 100% coverage each.
- Produce one model_permission row: MOD_CORP_P227, exposure_class=
  "corporate", approach="foundation_irb" (F-IRB chosen over A-IRB -- Art.
  201(2)'s IRB limb is satisfied by ANY IRB-approach beneficiary; F-IRB is
  the well-trodden path elsewhere in this fixture estate and avoids dragging
  modelled-LGD inputs into an item that is not about them). Grants IRB for
  CP_P227_B_IRB's exposure only.
- No collateral, no provisions -- clean five-guarantee, six-obligor SA/IRB
  mixed test.
- Framework: both ``CalculationConfig.crr()`` and ``CalculationConfig.
  basel_3_1()`` against the SAME parquets -- Art. 201 text is identical in
  both regimes.

Scenario rows:

    | ref | guarantor       | guarantor rating        | beneficiary    | role |
    |-----|------------------|--------------------------|----------------|------|
    | G1  | CP_P227_G1       | UNRATED corporate        | CP_P227_B (SA) | ineligible -- must be dropped |
    | G2  | CP_P227_G2       | external CQS 2 corporate | CP_P227_B (SA) | eligible SA control |
    | G3  | CP_P227_G34      | internal-only corporate  | CP_P227_B_IRB (F-IRB) | Art. 201(2) IRB limb -- eligible |
    | G4  | CP_P227_G34      | internal-only corporate  | CP_P227_B (SA) | internal-only invisible to SA ECAI lookup -- ineligible |
    | G5  | CP_P227_G5       | UNRATED individual       | CP_P227_B (SA) | retail-class probe -- evidence only, NOT gated by this item |

Defect under test (pre-fix):
    ``_assign_guarantor_approach`` (engine/crm/guarantees.py:396-449) routes
    ANY corporate-class guarantor with a resolved ``guarantor_exposure_class``
    to ``"sa"`` approach unconditionally (the final
    ``.when(pl.col("guarantor_exposure_class") != "").then(pl.lit("sa"))``
    branch), regardless of whether that guarantor carries any rating at all.
    G1 (genuinely unrated) and G4 (internal-only, invisible to the SA ECAI
    lookup which only reads ``guarantor_cqs``) both substitute in today at
    the unrated-corporate class-default RW (100%) -- a capital
    understatement vs. the correct borrower-basis RW their beneficiaries
    would otherwise carry (150%, CP_P227_B's own CQS-5 SA fallback). Art.
    201(1)(g) requires a corporate guarantor to have an established credit
    assessment by a nominated ECAI (external CQS) OR -- per Art. 201(2) --
    to be recognised via the institution's own internal rating WHEN the
    beneficiary exposure is itself IRB-approach. G3 satisfies the IRB limb
    (its beneficiary, CP_P227_B_IRB, is F-IRB) so it is genuinely eligible
    and should NOT move pre/post-fix. G4's beneficiary (CP_P227_B) is SA, so
    the SAME internal-only guarantor is ineligible there -- the crux of the
    G3-vs-G4 split this fixture isolates.

Post-fix assertion (primary):
    G1: guarantor_approach reverts to "" (no substitution) -> RW = borrower
        basis (CP_P227_B's own 150% CQS-5 SA fallback) + CRM013 warning.
    G2: UNCHANGED -- eligible external-CQS control, RW = 50% both pre/post.
    G3: UNCHANGED -- Art. 201(2) IRB limb is satisfied, F-IRB substitution
        values are pipeline-reported below (not assumed) and must not move.
    G4: guarantor_approach reverts to "" -> RW = borrower basis (150%) +
        CRM013 warning -- same shape as G1, different root cause (internal-
        only rating insufficient for an SA beneficiary).
    G5: OUT OF SCOPE for this item's fix -- pipeline-run baseline recorded
        as evidence only; test-writer may pin today's behaviour with an
        explanatory comment rather than an inversion.

Hand-calculation:
    CP_P227_B baseline (unguaranteed, CQS 5, Art. 122 Table 5 / Table 6,
    identical at CQS 5 both regimes -- verified via rulebook/packs/crr.py:
    999-1013 and packs/b31.py:889-903, both Decimal("1.50")):
        RW = 1.50 -> RWA = 1,000,000 x 1.50 = 1,500,000

    G1 (pre-fix, bug): guarantor RW substituted in at the unrated-corporate
        class default -> RW = 1.00 -> RWA = 1,000,000 (a 50pp understatement
        vs the correct 150% borrower-basis RWA of 1,500,000).
    G1 (post-fix): guarantee dropped -> RW = 1.50 -> RWA = 1,500,000.

    G2: guarantor RW substituted at CQS 2 -> RW = 0.50 -> RWA = 500,000,
        both pre- and post-fix (eligible control, Art. 122 Table 5/6 CQS 2
        identical both regimes -- rulebook/packs/crr.py:999-1013,
        packs/b31.py:889-903, both Decimal("0.50")).

    G3: F-IRB parameter-substitution values -- PIPELINE-REPORTED below, not
        assumed. Expected UNCHANGED pre- vs post-fix (Art. 201(2) admits
        this guarantor for an IRB beneficiary).

    G4 (pre-fix, bug): same shape as G1 -- guarantor RW substituted in at
        the unrated-corporate class default (the SA lookup never reads
        ``guarantor_internal_pd``) -> RW = 1.00 -> RWA = 1,000,000.
    G4 (post-fix): guarantee dropped (internal-only rating insufficient for
        an SA beneficiary) -> RW = 1.50 -> RWA = 1,500,000.

    G5: PIPELINE-REPORTED below (evidence only, not asserted against an
        expected post-fix value by this item).

References:
    - CRR Art. 201(1)(g) / PS1/26 Art. 201(1)(g): corporate guarantors must
      have an established credit assessment by a nominated ECAI, or (Art.
      201(2)) be internally rated by an IRB institution WHERE the
      institution has IRB permission and the beneficiary exposure is IRB.
    - CRR Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6: CQS 5 -> 150%, CQS 2
      -> 50%, identical both regimes (verified in the design sketch pass).
    - docs/plans/compliance-audit-crr-111-241-rectification.md (P1.227
      finding).
    - src/rwa_calc/engine/crm/guarantees.py:356-393 (_join_guarantor_ratings
      -- guarantor_cqs / guarantor_internal_pd provenance), :396-449
      (_assign_guarantor_approach -- the SA-fallback branch this item gates).
    - src/rwa_calc/engine/stages/hierarchy/ratings.py:88-101 (internal_pd
      promotion -- no model_id/permission dependency).
    - tests/fixtures/p1_183/p1_183.py: model_permission builder pattern
      reused for MOD_CORP_P227.
    - tests/fixtures/p1_10/p1_10.py: guarantor-pattern precedent reused
      throughout this fixture.

Usage:
    uv run python tests/fixtures/p1_227/p1_227.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_B_REF = "CP_P227_B"  # corporate, external CQS 5, 150% SA baseline; beneficiary for G1/G2/G4/G5
CP_B_IRB_REF = "CP_P227_B_IRB"  # corporate, internal-only, F-IRB; beneficiary for G3
CP_G1_REF = "CP_P227_G1"  # corporate, UNRATED -- ineligible guarantor case
CP_G2_REF = "CP_P227_G2"  # corporate, external CQS 2 -- eligible SA control
CP_G34_REF = "CP_P227_G34"  # corporate, internal-only -- shared guarantor for G3/G4
CP_G5_REF = "CP_P227_G5"  # individual (retail), UNRATED -- review-addendum probe

LOAN_G1_REF = "LN_P227_G1"
LOAN_G2_REF = "LN_P227_G2"
LOAN_G3_REF = "LN_P227_G3"
LOAN_G4_REF = "LN_P227_G4"
LOAN_G5_REF = "LN_P227_G5"

RATING_B_REF = "RTG_P227_B"
RATING_B_IRB_REF = "RTG_P227_B_IRB"
RATING_G2_REF = "RTG_P227_G2"
RATING_G34_REF = "RTG_P227_G34"

GUARANTEE_G1_REF = "GUAR_P227_G1"
GUARANTEE_G2_REF = "GUAR_P227_G2"
GUARANTEE_G3_REF = "GUAR_P227_G3"
GUARANTEE_G4_REF = "GUAR_P227_G4"
GUARANTEE_G5_REF = "GUAR_P227_G5"

MODEL_ID = "MOD_CORP_P227"

VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2030, 1, 1)  # 3y -- plain unsecured term loan, no ST/maturity nuance needed

DRAWN_AMOUNT = 1_000_000.0  # every loan is GBP 1,000,000 drawn, interest=0

CQS_B = 5  # CP_P227_B's own external rating -> Table 5/6 150% (identical both regimes)
CQS_G2 = 2  # CP_P227_G2's own external rating -> Table 5/6 50% (identical both regimes)

BORROWER_IRB_PD = 0.0150  # CP_P227_B_IRB's own internal PD (1.50%)
GUARANTOR_G34_PD = 0.0100  # CP_P227_G34's internal PD (1.00%)

RATING_AGENCY = "S&P"
RATING_DATE = date(2027, 1, 2)

# Table 5/6 risk weights, numerically identical under CRR and B31 at CQS 5/2.
EXPECTED_RW_B_BASELINE: float = 1.50  # CQS 5, unguaranteed / post-fix G1 & G4 borrower basis
EXPECTED_RW_G2: float = 0.50  # CQS 2, both pre- and post-fix
# Pre-fix (bug) shared shape for G1/G4: unrated-corporate class-default RW
# substituted in regardless of guarantor eligibility.
EXPECTED_RW_G1_G4_PRE_FIX: float = 1.00

# G3: pipeline-confirmed F-IRB parameter-substitution risk weights (full K /
# correlation / maturity-adjustment formula, not a flat CQS-table lookup --
# differs slightly by regime due to differing scaling factors / PD
# treatment). Expected unchanged pre- vs post-fix (Art. 201(2) IRB limb).
EXPECTED_RW_G3_CRR: float = 1.034401
EXPECTED_RW_G3_B31: float = 0.867422

# G5: pipeline-confirmed -- the retail-guarantor substitution resolves to a
# NULL guarantor_rw (RETAIL_OTHER is not a key in the CQS-driven SA
# risk-weight lookup table at all -- grepped risk_weights.py, zero hits for
# "RETAIL_OTHER"). engine/sa/rw_adjustments.py:230-237's
# ``is_guarantee_beneficial`` check requires guarantor_rw to be non-null, so
# a null guarantor_rw is correctly treated as non-beneficial and the
# substitution is skipped -- the exposure reverts to the borrower's own
# pre-CRM risk weight. NOT a capital understatement today: this is
# EVIDENCE that the existing null-guard already neutralises a retail-class
# guarantor, independent of any Art. 201-specific eligibility gate.
EXPECTED_RW_G5_TODAY: float = 1.50  # == EXPECTED_RW_B_BASELINE, both regimes

EXPECTED_RWA_B_BASELINE: float = DRAWN_AMOUNT * EXPECTED_RW_B_BASELINE  # 1,500,000
EXPECTED_RWA_G2: float = DRAWN_AMOUNT * EXPECTED_RW_G2  # 500,000
EXPECTED_RWA_G1_G4_PRE_FIX: float = DRAWN_AMOUNT * EXPECTED_RW_G1_G4_PRE_FIX  # 1,000,000
EXPECTED_RWA_G1_G4_POST_FIX: float = EXPECTED_RWA_B_BASELINE  # 1,500,000, borrower basis
EXPECTED_RWA_G3_CRR: float = DRAWN_AMOUNT * EXPECTED_RW_G3_CRR
EXPECTED_RWA_G3_B31: float = DRAWN_AMOUNT * EXPECTED_RW_G3_B31
EXPECTED_RWA_G5_TODAY: float = DRAWN_AMOUNT * EXPECTED_RW_G5_TODAY  # 1,500,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.227 counterparty row (borrower, IRB borrower, or one of five guarantor types)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
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
    """P1.227 loan: GBP 1,000,000 drawn, senior, 3-year maturity."""

    loan_reference: str
    counterparty_reference: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": "GBP",
            "value_date": VALUE_DATE,
            "maturity_date": MATURITY_DATE,
            "drawn_amount": DRAWN_AMOUNT,
            "interest": 0.0,
            "seniority": "senior",
        }


@dataclass(frozen=True)
class _Rating:
    """P1.227 rating row: external (CQS-based) or internal (PD-based)."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str | None
    rating_value: str | None
    cqs: int | None
    pd: float | None
    rating_date: date
    is_solicited: bool
    model_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


@dataclass(frozen=True)
class _Guarantee:
    """P1.227 guarantee row: 100% coverage, maturity matches the loan (no Art. 233 mismatch)."""

    guarantee_reference: str
    guarantor: str
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": "corporate_guarantee",
            "guarantor": self.guarantor,
            "currency": "GBP",
            "maturity_date": MATURITY_DATE,
            "amount_covered": DRAWN_AMOUNT,
            "percentage_covered": 1.0,
            "beneficiary_type": "loan",
            "beneficiary_reference": self.beneficiary_reference,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """P1.227 model permission: F-IRB for corporate, no geo or book restrictions."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p227_counterparties() -> pl.DataFrame:
    """Return the six P1.227 counterparties as a DataFrame."""
    rows = [
        _Counterparty(
            counterparty_reference=CP_B_REF,
            counterparty_name="P1.227 SA Borrower, External CQS5",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,  # large corporate, matches CORP_UR_001 / P1.225 CP-X
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_B_IRB_REF,
            counterparty_name="P1.227 F-IRB Borrower, Internal Rating Only",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_G1_REF,
            counterparty_name="P1.227 Unrated Corporate Guarantor (Ineligible)",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            # Deliberately UNRATED -- no rating row of any kind.
        ),
        _Counterparty(
            counterparty_reference=CP_G2_REF,
            counterparty_name="P1.227 ECAI-CQS2 Corporate Guarantor (Eligible Control)",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_G34_REF,
            counterparty_name="P1.227 Internal-Only Corporate Guarantor (Shared G3/G4)",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_G5_REF,
            counterparty_name="P1.227 Retail Individual Guarantor (Review-Addendum Probe)",
            entity_type="individual",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            # Deliberately UNRATED -- no rating row of any kind. Art. 201(1)
            # does not list retail persons as eligible protection providers;
            # this row is evidence-gathering only, not gated by P1.227.
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p227_loans() -> pl.DataFrame:
    """Return the five P1.227 loans (G1-G5) as a DataFrame."""
    rows = [
        _Loan(LOAN_G1_REF, CP_B_REF),
        _Loan(LOAN_G2_REF, CP_B_REF),
        _Loan(LOAN_G3_REF, CP_B_IRB_REF),
        _Loan(LOAN_G4_REF, CP_B_REF),
        _Loan(LOAN_G5_REF, CP_B_REF),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p227_ratings() -> pl.DataFrame:
    """
    Return the four P1.227 rating rows as a DataFrame.

    RTG_P227_B: CP_P227_B's own external rating, CQS 5 -> 150% SA baseline.
    RTG_P227_B_IRB: CP_P227_B_IRB's own internal rating, pd=1.50%,
    model_id=MOD_CORP_P227 -- links to the model_permission granting F-IRB.
    RTG_P227_G2: CP_P227_G2's own external rating, CQS 2 -> 50% eligible RW.
    RTG_P227_G34: CP_P227_G34's own internal rating, pd=1.00% -- no
    model_id needed (internal_pd promotion does not depend on a matching
    model_permission).
    CP_P227_G1 and CP_P227_G5 carry NO rating row (genuinely unrated).
    """
    rows = [
        _Rating(
            rating_reference=RATING_B_REF,
            counterparty_reference=CP_B_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="B",
            cqs=CQS_B,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
        _Rating(
            rating_reference=RATING_B_IRB_REF,
            counterparty_reference=CP_B_IRB_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="4B",
            cqs=None,
            pd=BORROWER_IRB_PD,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RATING_G2_REF,
            counterparty_reference=CP_G2_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="A",
            cqs=CQS_G2,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
        _Rating(
            rating_reference=RATING_G34_REF,
            counterparty_reference=CP_G34_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",
            cqs=None,
            pd=GUARANTOR_G34_PD,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p227_guarantees() -> pl.DataFrame:
    """Return the five P1.227 guarantee rows (G1-G5), one per loan, 100% coverage each."""
    rows = [
        _Guarantee(GUARANTEE_G1_REF, CP_G1_REF, LOAN_G1_REF),
        _Guarantee(GUARANTEE_G2_REF, CP_G2_REF, LOAN_G2_REF),
        _Guarantee(GUARANTEE_G3_REF, CP_G34_REF, LOAN_G3_REF),
        _Guarantee(GUARANTEE_G4_REF, CP_G34_REF, LOAN_G4_REF),
        _Guarantee(GUARANTEE_G5_REF, CP_G5_REF, LOAN_G5_REF),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p227_model_permission() -> pl.DataFrame:
    """Return the single P1.227 model permission: F-IRB for corporate, MOD_CORP_P227."""
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p227_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.227 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p227_counterparties()),
        ("loan", create_p227_loans()),
        ("rating", create_p227_ratings()),
        ("guarantee", create_p227_guarantees()),
        ("model_permission", create_p227_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.227 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR/PS1-26 Art. 201 guarantor-eligibility gate")
    print(
        f"  CP_P227_B baseline (unguaranteed, CQS 5): RW={EXPECTED_RW_B_BASELINE:.0%} "
        f"RWA={EXPECTED_RWA_B_BASELINE:,.0f} (both regimes)"
    )
    print(
        f"  G1 (unrated corporate): pre-fix RW={EXPECTED_RW_G1_G4_PRE_FIX:.0%} "
        f"RWA={EXPECTED_RWA_G1_G4_PRE_FIX:,.0f} -> post-fix RW={EXPECTED_RW_B_BASELINE:.0%} "
        f"RWA={EXPECTED_RWA_G1_G4_POST_FIX:,.0f} (dropped, borrower basis)"
    )
    print(
        f"  G2 (ECAI CQS2 corporate): RW={EXPECTED_RW_G2:.0%} RWA={EXPECTED_RWA_G2:,.0f} "
        "-- unchanged pre- and post-fix"
    )
    print(
        f"  G3 (internal-only, F-IRB beneficiary): RW={EXPECTED_RW_G3_CRR:.4f} (CRR) / "
        f"{EXPECTED_RW_G3_B31:.4f} (B31) -- F-IRB parameter-substitution values, "
        "pipeline-confirmed, expected unchanged pre- and post-fix"
    )
    print(
        f"  G4 (internal-only, SA beneficiary): pre-fix RW={EXPECTED_RW_G1_G4_PRE_FIX:.0%} "
        f"RWA={EXPECTED_RWA_G1_G4_PRE_FIX:,.0f} -> post-fix RW={EXPECTED_RW_B_BASELINE:.0%} "
        f"RWA={EXPECTED_RWA_G1_G4_POST_FIX:,.0f} (dropped, borrower basis)"
    )
    print(
        f"  G5 (retail individual, review-addendum probe): RW={EXPECTED_RW_G5_TODAY:.0%} "
        f"RWA={EXPECTED_RWA_G5_TODAY:,.0f}, both regimes -- guarantor_rw resolves NULL "
        "(RETAIL_OTHER not in the CQS-driven SA lookup) -> is_guarantee_beneficial=False "
        "-> substitution skipped, reverts to borrower basis -- NOT gated by this item, "
        "recorded as evidence only"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p227_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
