"""
Generate P1.183 fixtures: CRR Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD floor.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (aggregator helper
    beside engine/aggregator/_el_summary.py, called from aggregate() after
    compute_el_portfolio_summary; rulebook/packs/crr.py Feature
    crr_retail_re_portfolio_lgd_floor)

Key responsibilities:
- Produce six counterparty rows: five individual retail-mortgage borrowers
  (BREACH book E1/E2, COMPLIANT book E3/E4, exclusion-prover E5) plus one
  sovereign central-government guarantor (CP_GOV_P183, CQS 1 -> 0% RW).
- Produce five A-IRB retail-mortgage loan rows, one per borrower, each with a
  dedicated own-estimate LGD chosen to land the EW-avg (exposure-at-default
  weighted average LGD) of each book on a specific side of the 10% Art. 164(4)
  residential-RE portfolio floor:
    Breach book    (E1, E2):     EW-avg = 7.25%  < 10% -> ONE IRB007 warning
    Compliant book (E3, E4):     EW-avg = 11.00% >= 10% -> no warning
    Exclusion prover (E5, added to the compliant book): a very low own-LGD
    (2%) central-government-guaranteed row that, if wrongly INCLUDED in the
    portfolio average, drags it below 10% — proving the Art. 164(4)
    central-government-guarantee exclusion holds by the ABSENCE of a warning
    when E5 is correctly excluded.
- Produce five internal ratings (one per borrower, model_id=MODEL_ID) and one
  external rating (guarantor, CQS 1) so the guarantor's RW is unambiguously 0%.
- Produce one model_permission row granting AIRB for exposure_class
  "retail_mortgage" under MODEL_ID (dedicated model_id — no collision with
  other fixtures' AIRB permissions).
- Produce one guarantee row: E5's loan, 100% covered by CP_GOV_P183, maturity
  >= loan maturity (no Art. 233 mismatch scaling to disentangle).

No new schema columns are needed for this fixture — property_type, lgd, and
the guarantee chain (is_guaranteed / guarantor_exposure_class, both existing
production columns derived by engine/crm/guarantees.py:apply_guarantees) all
already exist. The new LGD-floor WARNING check itself does not exist yet
(engine-implementer's job); these fixtures exercise only the population the
future helper must select — is_airb & exposure_class == "retail_mortgage" &
NOT central-government-guaranteed — which flows the pipeline TODAY unchanged.

Hand-calculation (CalculationConfig.crr(permission_mode=PermissionMode.IRB) —
CRR A-IRB has no per-exposure LGD floor at all (engine/irb/formulas.py
_lgd_floor_expression: ``if not resolved_pack.feature("airb_lgd_floor"): return
pl.lit(0.0)``, and ``airb_lgd_floor`` is a Basel-3.1-only Feature), so every
own-LGD value below is expected to reach the aggregator UNCLIPPED):

    Breach book:
        E1: ead_final = 1,000,000  lgd = 0.05  -> lgd x ead = 50,000
        E2: ead_final = 3,000,000  lgd = 0.08  -> lgd x ead = 240,000
        EW-avg = (50,000 + 240,000) / (1,000,000 + 3,000,000)
               = 290,000 / 4,000,000 = 0.0725 = 7.25%  < 10% -> WARNING

    Compliant book:
        E3: ead_final = 2,000,000  lgd = 0.12  -> lgd x ead = 240,000
        E4: ead_final = 2,000,000  lgd = 0.10  -> lgd x ead = 200,000
        EW-avg = (240,000 + 200,000) / (2,000,000 + 2,000,000)
               = 440,000 / 4,000,000 = 0.11 = 11.00% >= 10% -> no warning

    Exclusion prover (E5, own lgd = 0.02, ead_final = 2,000,000):
        If WRONGLY included in the compliant book:
            (440,000 + 2,000,000 x 0.02) / (4,000,000 + 2,000,000)
                = 480,000 / 6,000,000 = 0.08 = 8.00% < 10% -> would (wrongly) WARN
        Correctly EXCLUDED (Art. 164(4) central-government-guarantee carve-out):
            compliant book stays at 11.00% -> no warning (the proof is the
            absence of a warning, not a numeric assertion on E5 itself).

References:
    - CRR Art. 164(4): portfolio-level minimum EW-avg LGD for A-IRB retail
      exposures secured by residential (10%) / commercial (15%) real estate.
    - CRR Art. 164(4): the residential/commercial-RE floor does not apply to
      exposures guaranteed by central governments (or their regional
      governments/local authorities/PSEs on an Art. 115(1)/116(4) equivalence
      basis) — the Art. 164(4) exclusion this fixture's E5 row proves.
    - CRR Art. 112 Table A2 / rulebook/packs/common.py "entity_type_to_sa_class":
      entity_type="sovereign" -> ExposureClass.CENTRAL_GOVT_CENTRAL_BANK
      ("central_govt_central_bank") — the guarantor_exposure_class this
      fixture's guarantee row must produce.
    - engine/crm/guarantees.py:apply_guarantees: is_guaranteed / guarantor_exposure_class
      derivation (existing production columns, no schema change needed).
    - engine/irb/formulas.py:_lgd_floor_expression: confirms CRR A-IRB has no
      existing per-exposure LGD floor (returns 0.0 when the Basel-3.1-only
      ``airb_lgd_floor`` Feature is off) — CRR is the live gap this new
      portfolio-level check closes; Basel 3.1 already floors retail_mortgage
      A-IRB LGD at 5% per-exposure (Art. 164(4)(a)), making the new
      portfolio-level check largely inert there.
    - tests/fixtures/p1_98/p1_98.py: identical self-contained A-IRB fixture
      pattern (own counterparty/loan/rating/model_permission parquet, no
      dependence on the acceptance-harness-only global model_id enrichment).
    - docs/plans/compliance-audit-crr-111-241-rectification.md (P1.183,
      art164-4-5-portfolio-lgd-floor finding).

Usage:
    uv run python tests/fixtures/p1_183/p1_183.py
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

MODEL_ID = "RETAIL_MTG_AIRB_P183"

# Borrower counterparty / loan / rating references, keyed by scenario row.
CP_E1_REF = "CP_E1_P183"
CP_E2_REF = "CP_E2_P183"
CP_E3_REF = "CP_E3_P183"
CP_E4_REF = "CP_E4_P183"
CP_E5_REF = "CP_E5_P183"
CP_GOV_REF = "CP_GOV_P183"  # central government guarantor

LOAN_E1_REF = "LN_E1_P183"
LOAN_E2_REF = "LN_E2_P183"
LOAN_E3_REF = "LN_E3_P183"
LOAN_E4_REF = "LN_E4_P183"
LOAN_E5_REF = "LN_E5_P183"

GUARANTEE_E5_REF = "GUAR_E5_P183"

VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2051, 1, 1)  # 25y — matches the shared RTL_MTG residential pattern
RATING_DATE = date(2026, 1, 2)

BORROWER_PD = 0.0100  # 1.00% — comfortably above the CRR single 0.03% PD floor

# Own-estimate LGDs (see module docstring hand-calc)
LGD_E1 = 0.05
LGD_E2 = 0.08
LGD_E3 = 0.12
LGD_E4 = 0.10
LGD_E5 = 0.02  # very low — would drag the portfolio below 10% if wrongly included

EAD_E1 = 1_000_000.0
EAD_E2 = 3_000_000.0
EAD_E3 = 2_000_000.0
EAD_E4 = 2_000_000.0
EAD_E5 = 2_000_000.0

GOVERNOR_CQS = 1  # central government, CQS 1 -> 0% RW (Art. 114 Table 1)

# Expected outputs (see module docstring hand-calc)
EXPECTED_BREACH_EW_AVG_LGD = 0.0725  # 7.25% < 10% floor -> WARNING
EXPECTED_COMPLIANT_EW_AVG_LGD = 0.11  # 11.00% >= 10% floor -> no warning
EXPECTED_WRONGLY_INCLUDED_EW_AVG_LGD = 0.08  # 8.00% — proves the exclusion matters


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.183 counterparty row (retail-mortgage borrower or sovereign guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool

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
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.183 A-IRB retail-mortgage loan.

    product_type="RESIDENTIAL_MORTGAGE" sets is_mortgage=True in the classifier
    (engine/stages/classify/attributes.py:_build_is_mortgage_expr — matches on
    "MORTGAGE" in the uppercased product_type), and combined with the borrower's
    entity_type="individual" this routes unconditionally to
    exposure_class="retail_mortgage" (engine/stages/classify/subtypes.py —
    "Retail mortgage — stays RETAIL_MORTGAGE regardless of threshold").
    property_type="residential" is set explicitly even though it is not read by
    the classifier today, since the future portfolio-LGD-floor helper splits its
    population by property_type (residential 10% / commercial 15% band).
    """

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    lgd: float
    beel: float
    seniority: str
    property_type: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
            "property_type": self.property_type,
        }


@dataclass(frozen=True)
class _Rating:
    """P1.183 rating row: internal (borrower, model_id=MODEL_ID) or external (guarantor)."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
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
    """P1.183 guarantee row: E5's loan, 100% covered by the central-government guarantor."""

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": self.guarantee_type,
            "guarantor": self.guarantor,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """P1.183 model permission: AIRB for retail_mortgage, no geo or book restrictions."""

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


def create_p183_counterparties() -> pl.DataFrame:
    """Return the six P1.183 counterparties (five borrowers + one guarantor)."""
    borrowers = [
        _Counterparty(
            counterparty_reference=ref,
            counterparty_name=name,
            entity_type="individual",
            country_code="GB",
            annual_revenue=annual_revenue,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=True,
        )
        for ref, name, annual_revenue in (
            (CP_E1_REF, "P1.183 Breach Borrower E1", 60_000.0),
            (CP_E2_REF, "P1.183 Breach Borrower E2", 90_000.0),
            (CP_E3_REF, "P1.183 Compliant Borrower E3", 75_000.0),
            (CP_E4_REF, "P1.183 Compliant Borrower E4", 80_000.0),
            (CP_E5_REF, "P1.183 Exclusion-Prover Borrower E5", 65_000.0),
        )
    ]
    guarantor = _Counterparty(
        counterparty_reference=CP_GOV_REF,
        counterparty_name="P1.183 Central Government Guarantor",
        entity_type="sovereign",
        country_code="GB",
        annual_revenue=None,
        total_assets=None,
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
        is_natural_person=False,
    )
    rows = [*borrowers, guarantor]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p183_loans() -> pl.DataFrame:
    """Return the five P1.183 A-IRB retail-mortgage loans, one per borrower."""
    rows = [
        _Loan(
            loan_reference=loan_ref,
            product_type="RESIDENTIAL_MORTGAGE",
            book_code="RETAIL_MORTGAGES_P183",
            counterparty_reference=cp_ref,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=drawn_amount,
            interest=0.0,
            lgd=lgd,
            beel=0.0,
            seniority="senior",
            property_type="residential",
        )
        for loan_ref, cp_ref, drawn_amount, lgd in (
            (LOAN_E1_REF, CP_E1_REF, EAD_E1, LGD_E1),
            (LOAN_E2_REF, CP_E2_REF, EAD_E2, LGD_E2),
            (LOAN_E3_REF, CP_E3_REF, EAD_E3, LGD_E3),
            (LOAN_E4_REF, CP_E4_REF, EAD_E4, LGD_E4),
            (LOAN_E5_REF, CP_E5_REF, EAD_E5, LGD_E5),
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p183_ratings() -> pl.DataFrame:
    """
    Return the six P1.183 ratings: five internal borrower ratings (model_id=MODEL_ID)
    plus one external guarantor rating (CQS 1 -> 0% RW, Art. 114 Table 1).
    """
    borrower_rows = [
        _Rating(
            rating_reference=f"RTG-{cp_ref}",
            counterparty_reference=cp_ref,
            rating_type="internal",
            rating_agency="internal",
            rating_value="1A",
            cqs=1,
            pd=BORROWER_PD,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        )
        for cp_ref in (CP_E1_REF, CP_E2_REF, CP_E3_REF, CP_E4_REF, CP_E5_REF)
    ]
    guarantor_row = _Rating(
        rating_reference=f"RTG-{CP_GOV_REF}",
        counterparty_reference=CP_GOV_REF,
        rating_type="external",
        rating_agency="S&P",
        rating_value="AAA",
        cqs=GOVERNOR_CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
    )
    rows = [*borrower_rows, guarantor_row]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p183_guarantee() -> pl.DataFrame:
    """
    Return the single P1.183 guarantee: E5's loan, 100% covered by CP_GOV_P183.

    Maturity == loan maturity (both 2051-01-01) — no Art. 233 mismatch scaling.
    A 0%-RW CQS-1 central-government guarantor is unambiguously beneficial, so
    the guarantee survives any non-beneficial-substitution filtering and
    ``is_guaranteed`` / ``guarantor_exposure_class`` land as expected.
    """
    rows = [
        _Guarantee(
            guarantee_reference=GUARANTEE_E5_REF,
            guarantee_type="sovereign_guarantee",
            guarantor=CP_GOV_REF,
            currency="GBP",
            maturity_date=MATURITY_DATE,
            amount_covered=EAD_E5,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_E5_REF,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p183_model_permission() -> pl.DataFrame:
    """Return the single P1.183 model permission: AIRB for retail_mortgage."""
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="retail_mortgage",
            approach="advanced_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p183_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.183 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p183_counterparties()),
        ("loan", create_p183_loans()),
        ("rating", create_p183_ratings()),
        ("guarantee", create_p183_guarantee()),
        ("model_permission", create_p183_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.183 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD floor")
    print(
        f"  Breach book:    {LOAN_E1_REF} (lgd={LGD_E1:.0%}, ead={EAD_E1:,.0f}), "
        f"{LOAN_E2_REF} (lgd={LGD_E2:.0%}, ead={EAD_E2:,.0f})"
    )
    print(f"                  EW-avg = {EXPECTED_BREACH_EW_AVG_LGD:.2%} < 10% -> WARNING")
    print(
        f"  Compliant book: {LOAN_E3_REF} (lgd={LGD_E3:.0%}, ead={EAD_E3:,.0f}), "
        f"{LOAN_E4_REF} (lgd={LGD_E4:.0%}, ead={EAD_E4:,.0f})"
    )
    print(f"                  EW-avg = {EXPECTED_COMPLIANT_EW_AVG_LGD:.2%} >= 10% -> no warning")
    print(
        f"  Exclusion prover: {LOAN_E5_REF} (lgd={LGD_E5:.0%}, ead={EAD_E5:,.0f}), "
        f"100% guaranteed by {CP_GOV_REF} (CQS {GOVERNOR_CQS} -> 0% RW)"
    )
    print(
        "                  if wrongly included: "
        f"{EXPECTED_WRONGLY_INCLUDED_EW_AVG_LGD:.2%} < 10% -> would (wrongly) warn"
    )
    print()
    print("  No new schema columns needed — property_type, lgd, guarantee chain all exist.")
    print("  The portfolio-level LGD-floor WARNING check itself is not yet implemented.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p183_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
