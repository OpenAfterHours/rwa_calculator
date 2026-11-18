"""CM-07 / TR-04 / TR-07 / CM-12: the obs_product -> risk_type map is regime-specific.

The map used to live in the common pack, documented as "framework-invariant". It is
not. The two category lists differ for documentary credits and for shipping
guarantees, customs and tax bonds:

CRR Annex I (current UK CRR), verbatim:
    2. Medium risk: "(a) trade finance off-balance sheet items, namely documentary
       credits issued or confirmed (see also 'Medium/low risk'); (b) other
       off-balance sheet items: (i) shipping guarantees, customs and tax bonds; ..."
    3. Medium/low risk: "(a) trade finance off-balance sheet items: (i) documentary
       credits in which underlying shipment acts as collateral and other
       self-liquidating transactions; (ii) warranties (including tender and
       performance bonds and associated advance payment and retention guarantees)
       and guarantees not having the character of credit substitutes; (iii)
       irrevocable standby letters of credit not having the character of credit
       substitutes; ..."
    1. Full risk: "(a) guarantees having the character of credit substitutes ...;
       (c) acceptances; (d) endorsements on bills not bearing the name of another
       institution ...; (e) transactions with recourse (e.g. factoring, invoice
       discount facilities); (f) irrevocable standby letters of credit having the
       character of credit substitutes; ..."

PRA PS1/26 Art. 111 Table A1 (Basel 3.1), verbatim:
    Row 6 (20%): "(a) documentary credits issued or confirmed and other
    self-liquidating transactions; (b) warranties, tender bonds, performance bonds,
    advance payment guarantees, retention guarantees, and guarantees not having the
    character of credit substitutes; (c) irrevocable standby letters of credit not
    having the character of credit substitutes; and (d) shipping guarantees,
    customs and tax bonds."
    Row 1 (100%): "(a) financial guarantees having the character of credit
    substitutes ...; (c) acceptances; (d) endorsements on bills not bearing the name
    of another institution or investment firm; (e) irrevocable standby letters of
    credit having the character of credit substitutes ..."
    Row 2 (100%): "(a) transactions with recourse (including factoring and invoice
    discount facilities)".

So under CRR a plain documentary credit and a shipping / customs / tax bond are 50%
(medium risk); under Basel 3.1 they are 20%. A documentary credit secured by its
shipment (or ``TRADE_LC``, the self-liquidating key) is 20% in both.

CRR F-IRB keeps the Art. 166(8)(b) 20% for "short-term letters of credit arising
from the movement of goods ... for both the issuing and confirming institutions"
whatever their Annex I bucket, so the trade-LC carve-out now also reaches the
medium-risk documentary credit.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INVALID_COLUMN_VALUE
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.data.schemas import OBS_PRODUCT_SYNONYMS, VALID_OBS_PRODUCTS
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.raw_bundle import make_raw_bundle

_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
_NOMINAL = 1_000_000.0

# (product, CRR SA CCF, Basel 3.1 SA CCF) — every canonical key, issued contingent.
_PRODUCT_MATRIX = [
    ("ACCEPTANCE", 1.00, 1.00),
    ("FINANCIAL_GUARANTEE", 1.00, 1.00),
    ("STANDBY_LC_CREDIT_SUBSTITUTE", 1.00, 1.00),
    ("ENDORSEMENT", 1.00, 1.00),
    ("AVAL", 1.00, 1.00),
    ("FACTORING_FACILITY", 1.00, 1.00),
    ("INVOICE_DISCOUNT_FACILITY", 1.00, 1.00),
    ("DOCUMENTARY_CREDIT", 0.50, 0.20),
    ("SHIPPING_GUARANTEE", 0.50, 0.20),
    ("CUSTOMS_BOND", 0.50, 0.20),
    ("TAX_BOND", 0.50, 0.20),
    ("DOCUMENTARY_CREDIT_SHIPMENT_SECURED", 0.20, 0.20),
    ("TRADE_LC", 0.20, 0.20),
    ("PERFORMANCE_BOND", 0.20, 0.20),
    ("WARRANTY", 0.20, 0.20),
    ("TENDER_BOND", 0.20, 0.20),
    ("BID_BOND", 0.20, 0.20),
    ("ADVANCE_PAYMENT_GUARANTEE", 0.20, 0.20),
    ("RETENTION_GUARANTEE", 0.20, 0.20),
    ("STANDBY_LC_NON_CREDIT_SUBSTITUTE", 0.20, 0.20),
]


def _contingent(
    product: str | None,
    *,
    risk_type: str | None = None,
    approach: str = "standardised",
    trade_lc: bool = False,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "exposure_reference": ["C1"],
            "drawn_amount": [0.0],
            "nominal_amount": [_NOMINAL],
            "risk_type": [risk_type],
            "obs_product": [product],
            "approach": [approach],
            "is_obs_commitment": [False],
            "is_short_term_trade_lc": [trade_lc],
        },
        schema_overrides={"risk_type": pl.Utf8, "obs_product": pl.Utf8},
    ).lazy()


def _ccf(frame: pl.LazyFrame, config: CalculationConfig) -> float:
    return CCFCalculator().apply_ccf(frame, config).collect()["ccf"][0]


@pytest.mark.parametrize(("product", "crr_ccf", "b31_ccf"), _PRODUCT_MATRIX)
def test_crr_sa_ccf_follows_annex_i(product: str, crr_ccf: float, b31_ccf: float) -> None:
    """CRR Annex I categories (before the fix DOCUMENTARY_CREDIT was 0.20)."""
    # Arrange / Act / Assert
    assert _ccf(_contingent(product), _CRR) == pytest.approx(crr_ccf)


@pytest.mark.parametrize(("product", "crr_ccf", "b31_ccf"), _PRODUCT_MATRIX)
def test_b31_sa_ccf_follows_table_a1(product: str, crr_ccf: float, b31_ccf: float) -> None:
    """PS1/26 Table A1 rows 1, 2 and 6."""
    # Arrange / Act / Assert
    assert _ccf(_contingent(product), _B31) == pytest.approx(b31_ccf)


def test_the_two_regimes_disagree_on_a_plain_documentary_credit() -> None:
    """The defect in one line: one input, two regimes, two different factors."""
    # Arrange
    frame = _contingent("DOCUMENTARY_CREDIT")

    # Act
    crr, b31 = _ccf(frame, _CRR), _ccf(frame, _B31)

    # Assert — CRR Annex I 2(a) 50% vs PS1/26 Table A1 row 6(a) 20%
    assert (crr, b31) == (pytest.approx(0.50), pytest.approx(0.20))


def test_crr_documentary_credit_ead_is_half_the_nominal() -> None:
    """Hand-calc: 1,000,000 x 50% = 500,000 (before the fix 200,000)."""
    # Arrange
    out = CCFCalculator().apply_ccf(_contingent("DOCUMENTARY_CREDIT"), _CRR).collect()

    # Assert
    assert out["ead_from_ccf"][0] == pytest.approx(500_000.0)


@pytest.mark.parametrize("product", ["DOCUMENTARY_CREDIT", "TRADE_LC"])
def test_crr_firb_short_term_trade_lc_keeps_166_8_b_20_percent(product: str) -> None:
    """Art. 166(8)(b) 20% applies to the short-term trade LC whatever its bucket."""
    # Arrange
    frame = _contingent(product, approach="foundation_irb", trade_lc=True)

    # Act / Assert
    assert _ccf(frame, _CRR) == pytest.approx(0.20)


def test_crr_firb_documentary_credit_without_trade_flag_is_166_10_b_medium_risk() -> None:
    """Outside 166(8)(b) an issued documentary credit is an Art. 166(10)(b) 50% item."""
    # Arrange
    frame = _contingent("DOCUMENTARY_CREDIT", approach="foundation_irb")

    # Act / Assert
    assert _ccf(frame, _CRR) == pytest.approx(0.50)


@pytest.mark.parametrize("config", [_CRR, _B31], ids=["crr", "b31"])
def test_explicit_risk_type_still_wins(config: CalculationConfig) -> None:
    """An explicit LR overrides the product key in both regimes."""
    # Arrange
    frame = _contingent("DOCUMENTARY_CREDIT", risk_type="LR")

    # Act / Assert — CRR LR 0%, B31 LR 10%
    expected = 0.0 if config is _CRR else 0.10
    assert _ccf(frame, config) == pytest.approx(expected)


@pytest.mark.parametrize("spelling", ["shipping_guarantee", "Customs_Bond", "sblc_financial"])
def test_lowercase_and_alias_spellings_resolve(spelling: str) -> None:
    """Synonyms route through OBS_PRODUCT_SYNONYMS before the pack map."""
    # Arrange
    frame = _contingent(spelling)

    # Act
    ccf = _ccf(frame, _B31)

    # Assert — every one of these is a named Table A1 item (never the 50% residual)
    assert ccf in (pytest.approx(0.20), pytest.approx(1.00))


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_every_accepted_product_resolves_in_each_regime(regime: str) -> None:
    """DQ016's absence test assumes every accepted product maps — in BOTH packs."""
    # Arrange
    pack = resolve(regime, date(2026, 1, 1) if regime == "crr" else date(2027, 1, 1))
    mapping = dict(pack.category_map("obs_product_to_risk_type").entries)
    accepted = VALID_OBS_PRODUCTS | set(OBS_PRODUCT_SYNONYMS)

    # Act
    unmapped = sorted(
        p for p in accepted if OBS_PRODUCT_SYNONYMS.get(p.lower(), p.upper()) not in mapping
    )

    # Assert
    assert unmapped == []


def test_the_map_is_not_in_the_common_pack() -> None:
    """The map is cited per regime; a common-pack copy would reassert invariance."""
    # Arrange
    from rwa_calc.rulebook.packs import common

    # Assert
    assert "obs_product_to_risk_type" not in common.ENTRIES


def _bundle_with_product(product: str) -> object:
    contingents = pl.DataFrame(
        {
            "contingent_reference": ["C1"],
            "counterparty_reference": ["CP001"],
            "nominal_amount": [_NOMINAL],
            "obs_product": [product],
        },
    ).lazy()
    return make_raw_bundle(
        contingents=contingents,
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP001"]}),
    )


@pytest.mark.parametrize("spelling", ["bankers_acceptance", "perf_bond", "doc_credit"])
def test_documented_synonym_raises_no_dq006(spelling: str) -> None:
    """CM-12: a documented spelling the engine prices correctly is not invalid input."""
    # Arrange
    bundle = _bundle_with_product(spelling)

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert not [
        e for e in errors if e.code == ERROR_INVALID_COLUMN_VALUE and e.field_name == "obs_product"
    ]


def test_an_unknown_product_still_raises_dq006() -> None:
    """CM-12 control: widening to the synonyms must not accept arbitrary strings."""
    # Arrange
    bundle = _bundle_with_product("NOT_A_PRODUCT")

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert [
        e for e in errors if e.code == ERROR_INVALID_COLUMN_VALUE and e.field_name == "obs_product"
    ]
