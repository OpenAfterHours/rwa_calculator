"""
Generate P2.36 fixtures: sovereign / institution PD floor first-class config fields.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (contracts/config.py,
    engine/irb/formulas.py)

Scenario design (P2.36 — Basel 3.1 F-IRB sovereign/institution PD floor dispatch):

    Two F-IRB exposures — one sovereign, one institution — with input PDs deliberately
    set below the 0.05% Basel 3.1 floor and below the 0.03% CRR floor so that the
    floor binds and is observable in test assertions.

    The scenario exercises:

    1. PDFloors.basel_3_1().sovereign == Decimal("0.0005") — new explicit field.
    2. PDFloors.basel_3_1().institution == Decimal("0.0005") — new explicit field.
    3. PDFloors.crr().sovereign == Decimal("0.0003") — CRR uniform floor.
    4. PDFloors.crr().institution == Decimal("0.0003") — CRR uniform floor.
    5. PDFloors.get_floor(ExposureClass.CENTRAL_GOVT_CENTRAL_BANK) dispatches to
       the sovereign field (not the corporate fallback).
    6. PDFloors.get_floor(ExposureClass.INSTITUTION) dispatches to the institution
       field (not the corporate fallback).

    The sovereign F-IRB model permission (MODEL_SOV_FIRB) is intentionally present
    even though Basel 3.1 Art. 147A(1)(a) restricts sovereign to SA.  The fixture
    keeps the sovereign on the IRB branch so the floor dispatch path is exercised
    in the engine (documented as "regulatory dead letter for B3.1" in
    firb-calculation.md).

    The institution model permission (MODEL_INST_FIRB) is unrestricted under Basel 3.1
    (F-IRB is the maximum permitted approach — Art. 147A(1)(b)); the floor applies
    normally to institution F-IRB exposures.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Shared parameters (both exposures):
        EAD       = 1,000,000 GBP
        LGD       = 0.40   (Art. 161(1)(aa): senior non-FSE F-IRB LGD, B31)
        PD_floor  = 0.0005 (Art. 160(1): Basel 3.1 floor binds; input PDs < 0.05%)
        M         = 2.5y   (explicit effective_maturity override)

    Basel 3.1 K formula (Art. 153/154, no 1.06 scalar):
        f(PD) = (1 - exp(-50 × 0.0005)) / (1 - exp(-50))  ≈ 0.024690
        R     = 0.12 × f(PD) + 0.24 × (1 - f(PD))        ≈ 0.237037
        G(PD) = Φ⁻¹(0.0005)                               ≈ -3.290527
        G(0.999) = Φ⁻¹(0.999)                             ≈ 3.090232
        inside_N = √(1/(1-R))·G(PD) + √(R/(1-R))·G(0.999) ≈ -2.044703
        cond_PD  = N(inside_N)                             ≈ 0.020442
        K        = LGD × cond_PD − PD × LGD               ≈ 0.007977
        b(PD)    = (0.11852 - 0.05478 × ln(0.0005))²       ≈ 0.286115
        MA       = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
                 = 1 / (1 - 1.5 × 0.286115)               ≈ 1.751844
        RW       = K × 12.5 × MA                           ≈ 0.174677
        Expected: RW ≈ 0.174677, RWA ≈ 174,677

    Override row (institution/sovereign floor = 0.001 via dataclasses.replace):
        PD_floored = 0.001, same M=2.5, LGD=0.40
        f(PD) = (1 - exp(-50 × 0.001)) / (1 - exp(-50))   ≈ 0.048771
        R     = 0.12 × f(PD) + 0.24 × (1 - f(PD))        ≈ 0.234148
        inside_N ≈ -1.822479, cond_PD ≈ 0.034191
        K        ≈ 0.013276, b ≈ 0.246936, MA ≈ 1.588321
        Expected: RW ≈ 0.263591, RWA ≈ 263,591

    CRR (CalculationConfig.crr()):
        Sovereign input PD=0.0001 → floored to 0.0003 (uniform CRR floor)
        Institution input PD=0.0003 → NOT floored (0.0003 == CRR floor, floor does not bind)
        Expected sovereign CRR: pd_floored=0.0003

    EL (expected loss):
        EL = PD × LGD × EAD = 0.0005 × 0.40 × 1,000,000 = 200 GBP

References:
    - PRA PS1/26 Art. 160(1): Basel 3.1 PD floor for sovereign and institution = 0.05%.
    - PRA PS1/26 Art. 147A(1)(a): sovereign restricted to SA under Basel 3.1.
    - PRA PS1/26 Art. 147A(1)(b): institution restricted to F-IRB under Basel 3.1.
    - PRA PS1/26 Art. 161(1)(aa): Basel 3.1 senior non-FSE F-IRB LGD = 40%.
    - CRR Art. 160(1): uniform 0.03% PD floor for all IRB classes.
    - docs/specifications/crr/firb-calculation.md §PD Floor (Basel 3.1 table).

Usage:
    uv run python tests/fixtures/p2_36/p2_36.py
    uv run python tests/fixtures/p2_36/p2_36.py --data-dir /path/to/output
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

# Counterparty references
SOVEREIGN_REF: str = "SOV_P236"
INSTITUTION_REF: str = "INST_P236"

# Loan references
SOVEREIGN_LOAN_REF: str = "EXP_P236_SOV"
INSTITUTION_LOAN_REF: str = "EXP_P236_INST"

# Facility references
SOVEREIGN_FAC_REF: str = "FAC_P236_SOV"
INSTITUTION_FAC_REF: str = "FAC_P236_INST"

# Rating references
RTG_SOV_REF: str = "RTG_P236_SOV"
RTG_INST_REF: str = "RTG_P236_INST"

# Model permission IDs
MODEL_SOV_FIRB: str = "MODEL_SOV_FIRB"
MODEL_INST_FIRB: str = "MODEL_INST_FIRB"

# Dates
VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE: date = date(2028, 7, 1)  # ~2.5y from VALUE_DATE → M ≈ 2.5y
RATING_DATE: date = date(2026, 1, 2)

# Loan economics
DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
EAD: float = DRAWN_AMOUNT  # 1,000,000 GBP (interest=0)

# IRB inputs — PDs deliberately below BOTH CRR (0.03%) and Basel 3.1 (0.05%) floors
# so the floor is always the binding constraint in assertions.
PD_SOVEREIGN: float = 0.0001   # 0.01% — well below both floors
PD_INSTITUTION: float = 0.0003  # 0.03% — below Basel 3.1 0.05% floor; at CRR floor
EFFECTIVE_MATURITY: float = 2.5  # M = 2.5y (explicit override avoids date arithmetic edge cases)

# PD floor values (match PDFloors class expected outputs)
# Basel 3.1: Art. 160(1) — sovereign and institution both 0.05%
EXPECTED_PD_FLOORED_B31: float = 0.0005   # 0.05% for both sovereign and institution

# CRR: Art. 160(1) uniform 0.03% floor
# Sovereign input PD=0.0001 < 0.0003 → floor binds → pd_floored = 0.0003
EXPECTED_PD_FLOORED_SOV_CRR: float = 0.0003
# Institution input PD=0.0003 == 0.0003 → floor is exactly at the boundary, does not lift PD
EXPECTED_PD_FLOORED_INST_CRR: float = 0.0003

# F-IRB supervisory LGD (Art. 161(1)(aa)) for senior non-FSE under Basel 3.1 = 40%
# Under CRR Art. 161(1)(a) = 45%
EXPECTED_LGD_B31: float = 0.40
EXPECTED_LGD_CRR: float = 0.45

# Hand-calc results (Basel 3.1): PD floored to 0.0005, LGD=0.40, M=2.5
# See module docstring for derivation. Sovereign and institution are identical
# at the floored PD (both floor to 0.0005) with same M and LGD.
# Inputs: PD=0.0005, LGD=0.40, M=2.5
#   f=0.024690, R=0.237037, G(PD)=-3.290527, G(0.999)=3.090232
#   inside_N=-2.044703, cond_PD=0.020442, K=0.007977
#   b=0.286115, MA=1.751844
EXPECTED_RW_B31_FLOORED: float = 0.174677    # ≈17.47% risk weight
EXPECTED_RWA_B31_FLOORED: float = 174_677.0  # GBP 174,677
EXPECTED_EL_B31: float = 200.0  # 0.0005 × 0.40 × 1,000,000

# Hand-calc results with override institution/sovereign floor = 0.001 (via dataclasses.replace)
# Inputs: PD=0.001, LGD=0.40, M=2.5
#   f=0.048771, R=0.234148, G(PD)=-3.090232, G(0.999)=3.090232
#   inside_N=-1.822479, cond_PD=0.034191, K=0.013276
#   b=0.246936, MA=1.588321
EXPECTED_RW_B31_SOV_OVERRIDE: float = 0.263591    # ≈26.36% risk weight
EXPECTED_RWA_B31_SOV_OVERRIDE: float = 263_591.0  # GBP 263,591


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.36 counterparty row (sovereign or institution)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_financial_sector_entity: bool

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
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P2.36 parent facility.

    A single committed on-balance-sheet facility per counterparty, matching the
    loan amount exactly. effective_maturity=2.5 prevents date-rounding divergence
    in the IRB K-formula maturity adjustment.
    """

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    effective_maturity: float

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P2.36 loan row.

    seniority="senior": routes to Art. 161(1)(aa) F-IRB supervisory LGD 40% (B31)
    / Art. 161(1)(a) 45% (CRR). Both counterparties are non-FSE so the lower 40%
    Basel 3.1 supervisory LGD applies.

    effective_maturity=2.5: M=2.5 is the load-bearing field for the maturity
    adjustment in the IRB K-formula. Must be consistent with the parent facility.
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
    seniority: str
    effective_maturity: float
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

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
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P2.36 internal rating row.

    The model_id on the rating row links the counterparty's PD to a specific
    model permission row, which the classifier joins to grant the IRB approach.
    PD values are deliberately below the floor so the floor is always binding.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

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
class _ModelPermission:
    """P2.36 model-permission row."""

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


def create_p236_counterparties() -> pl.DataFrame:
    """
    Return both P2.36 counterparties (sovereign + institution) as a DataFrame.

    SOV_P236: entity_type="sovereign" → IRB class central_govt_central_bank.
        PD delivered via rating RTG_P236_SOV = 0.0001 (0.01%), well below both
        CRR (0.03%) and Basel 3.1 (0.05%) floors, so the floor is always binding.
        is_financial_sector_entity=False → non-FSE Art. 161(1)(aa) LGD = 40% (B31).

    INST_P236: entity_type="institution" → IRB class institution.
        PD delivered via rating RTG_P236_INST = 0.0003 (0.03%), which is below
        the Basel 3.1 0.05% floor (floor binds under B31) but equals the CRR floor
        (boundary test — floor does not lift PD under CRR).
        is_financial_sector_entity=False → non-FSE Art. 161(1)(aa) LGD = 40% (B31).
    """
    rows = [
        _Counterparty(
            counterparty_reference=SOVEREIGN_REF,
            counterparty_name="P2.36 Sovereign GB Low-PD",
            entity_type="sovereign",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        _Counterparty(
            counterparty_reference=INSTITUTION_REF,
            counterparty_name="P2.36 Institution GB Low-PD",
            entity_type="institution",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p236_facilities() -> pl.DataFrame:
    """
    Return both P2.36 parent facilities as a DataFrame.

    One committed on-balance-sheet facility per counterparty.
    limit=1,000,000 == drawn_amount: fully drawn → no undrawn portion, no CCF.
    seniority="senior": consistent with the loan row and routes to
    Art. 161(1)(aa) supervisory LGD 40% (B31) / Art. 161(1)(a) 45% (CRR).
    effective_maturity=2.5: M override prevents date-rounding divergence.
    """
    rows = [
        _Facility(
            facility_reference=SOVEREIGN_FAC_REF,
            product_type="TERM_LOAN",
            book_code="SOVEREIGN_BOOK",
            counterparty_reference=SOVEREIGN_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
        ),
        _Facility(
            facility_reference=INSTITUTION_FAC_REF,
            product_type="TERM_LOAN",
            book_code="FI_BOOK",
            counterparty_reference=INSTITUTION_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=DRAWN_AMOUNT,
            committed=True,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p236_loans() -> pl.DataFrame:
    """
    Return both P2.36 loans as a DataFrame.

    EXP_P236_SOV: GBP 1,000,000 senior sovereign term loan. Fully drawn.
    EXP_P236_INST: GBP 1,000,000 senior institution term loan. Fully drawn.

    Both loans share:
        seniority="senior": Art. 161(1)(aa) supervisory LGD 40% (B31) / 45% (CRR).
        effective_maturity=2.5: consistent with parent facility.
        interest=0: EAD = drawn_amount (no accrued interest complication).
    """
    rows = [
        _Loan(
            loan_reference=SOVEREIGN_LOAN_REF,
            product_type="TERM_LOAN",
            book_code="SOVEREIGN_BOOK",
            counterparty_reference=SOVEREIGN_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
        _Loan(
            loan_reference=INSTITUTION_LOAN_REF,
            product_type="TERM_LOAN",
            book_code="FI_BOOK",
            counterparty_reference=INSTITUTION_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p236_ratings() -> pl.DataFrame:
    """
    Return both P2.36 internal ratings as a DataFrame.

    RTG_P236_SOV: PD=0.0001 (0.01%) for SOV_P236, model_id=MODEL_SOV_FIRB.
        PD < CRR floor 0.0003 → floor binds under CRR (pd_floored=0.0003).
        PD < Basel 3.1 floor 0.0005 → floor binds under B31 (pd_floored=0.0005).

    RTG_P236_INST: PD=0.0003 (0.03%) for INST_P236, model_id=MODEL_INST_FIRB.
        PD == CRR floor 0.0003 → boundary case, floor does not lift PD under CRR.
        PD < Basel 3.1 floor 0.0005 → floor binds under B31 (pd_floored=0.0005).
    """
    rows = [
        _Rating(
            rating_reference=RTG_SOV_REF,
            counterparty_reference=SOVEREIGN_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="AAA",  # very low PD rating
            cqs=1,
            pd=PD_SOVEREIGN,   # 0.0001 — below both floors
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_SOV_FIRB,
        ),
        _Rating(
            rating_reference=RTG_INST_REF,
            counterparty_reference=INSTITUTION_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="AAA",  # very low PD rating
            cqs=1,
            pd=PD_INSTITUTION,  # 0.0003 — below B31 floor; at CRR floor boundary
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_INST_FIRB,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p236_model_permissions() -> pl.DataFrame:
    """
    Return both P2.36 model permissions as a DataFrame.

    MODEL_SOV_FIRB: foundation_irb for exposure_class="central_govt_central_bank".
        The exposure_class must match the IRB class derived from entity_type="sovereign"
        (ENTITY_TYPE_TO_IRB_CLASS maps "sovereign" → "central_govt_central_bank").
        Under Basel 3.1 Art. 147A(1)(a), sovereign is restricted to SA; this
        permission is retained to exercise the PD floor dispatch path in the engine
        (the sovereign row will be overridden to SA by the Art. 147A guard, but the
        floor field is still tested via unit assertions on PDFloors config objects).

    MODEL_INST_FIRB: foundation_irb for exposure_class="institution".
        Under Basel 3.1 Art. 147A(1)(b), institution is capped at F-IRB (A-IRB
        unavailable) — foundation_irb is the correct and only IRB approach here.
        The 0.05% PD floor applies normally to institution F-IRB exposures.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_SOV_FIRB,
            exposure_class="central_govt_central_bank",  # matches ENTITY_TYPE_TO_IRB_CLASS["sovereign"]
            approach="foundation_irb",
            country_codes=None,  # all geographies
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_INST_FIRB,
            exposure_class="institution",  # matches ENTITY_TYPE_TO_IRB_CLASS["institution"]
            approach="foundation_irb",
            country_codes=None,  # all geographies
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p236_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.36 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_36/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p236_counterparties()),
        ("facility", create_p236_facilities()),
        ("loan", create_p236_loans()),
        ("rating", create_p236_ratings()),
        ("model_permission", create_p236_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.36 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: sovereign/institution PD floor first-class config fields")
    print(f"  Sovereign:   {SOVEREIGN_REF} (entity_type=sovereign, GB)")
    print(f"               input PD={PD_SOVEREIGN} (below both CRR 0.03% and B31 0.05% floors)")
    print(f"  Institution: {INSTITUTION_REF} (entity_type=institution, GB)")
    print(f"               input PD={PD_INSTITUTION} (at CRR floor; below B31 0.05% floor)")
    print()
    print("  Basel 3.1 (PDFloors.sovereign == PDFloors.institution == 0.0005):")
    print(f"    Both pd_floored = {EXPECTED_PD_FLOORED_B31}")
    print(f"    LGD = {EXPECTED_LGD_B31} (Art. 161(1)(aa): senior non-FSE F-IRB)")
    print(f"    RW  ≈ {EXPECTED_RW_B31_FLOORED}, RWA ≈ {EXPECTED_RWA_B31_FLOORED:,.0f}")
    print(f"    EL  = {EXPECTED_EL_B31:.0f} GBP")
    print()
    print("  Basel 3.1 override (sovereign floor=0.001 via dataclasses.replace):")
    print(f"    pd_floored = 0.001, RW ≈ {EXPECTED_RW_B31_SOV_OVERRIDE}")
    print(f"    RWA ≈ {EXPECTED_RWA_B31_SOV_OVERRIDE:,.0f}")
    print()
    print("  CRR (PDFloors.sovereign == PDFloors.institution == 0.0003):")
    print(f"    Sovereign   pd_floored = {EXPECTED_PD_FLOORED_SOV_CRR}")
    print(f"    Institution pd_floored = {EXPECTED_PD_FLOORED_INST_CRR}")
    print(f"    LGD = {EXPECTED_LGD_CRR} (Art. 161(1)(a): CRR senior non-FSE F-IRB)")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p236_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
