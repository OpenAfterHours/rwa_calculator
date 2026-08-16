"""P1.267 — the SA CCF residual is regime-divergent, and a null risk_type is signalled.

Two halves, one item.

**The value half.** ``sa_ccf_default`` stated a single 50% MR-equivalent
residual "under both CRR Art. 111 and PRA PS1/26 Table A1". The two texts do
not agree:

- **CRR Annex I** gives all four categories an "other items" residual, but they
  are not equivalent. Item 1(k) is *"other items also carrying full risk"* —
  unconditional — while 2(b)(iv), 3(b)(ii) and 4(c) each read *"other items
  also carrying ... risk and as communicated to [the competent authority]"*.
  Only the full-risk residual is available without notification, and an item
  the engine cannot classify has by definition not been notified. So the CRR
  residual is 100%: the engine understated it by 50pp.
- **PS1/26 Table A1** has three residual limbs and none carries a notification
  condition. Row 3 (*"other issued off-balance sheet items that do not have the
  character of credit substitutes"*) is 50% and Row 5 (*"any other commitment
  not subject to a conversion factor of 10%, 50% or 100%"*) is 40%. So an
  unclassifiable *issued* item at 50% was already RIGHT BY THE TEXT, and an
  unclassifiable *commitment* at 50% OVERSTATED by 10pp — the opposite
  direction, which is why the two arms must not be harmonised.

**The error-channel half.** ``risk_type`` is optional and the DQ006 domain test
filters ``is_not_null()`` before it runs, so a null on a row with a real
off-balance amount is schema-valid, raises nothing, and silently takes whichever
residual applies. That is well-formed input, not malformed input, and it
produced no signal of any kind.

References:
- CRR Art. 111, Annex I items 1(k), 2(b)(iv), 3(b)(ii), 4(c)
- PRA PS1/26 Art. 111, Table A1 Rows 1(f), 3, 5
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INVALID_COLUMN_VALUE, ERROR_UNRESOLVED_OBS_RISK_TYPE
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.engine.ccf import CCFCalculator, sa_ccf_expression
from tests.fixtures.raw_bundle import make_raw_bundle

NOMINAL = 1_000_000.0


@pytest.fixture
def calculator() -> CCFCalculator:
    return CCFCalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))


def _obs_row(
    risk_type: str | None, *, is_commitment: bool, nominal: float = NOMINAL
) -> pl.LazyFrame:
    """One off-balance-sheet row with no drawn balance."""
    return pl.DataFrame(
        {
            "exposure_reference": ["OBS001"],
            "drawn_amount": [0.0],
            "nominal_amount": [nominal],
            "risk_type": [risk_type],
            "is_obs_commitment": [is_commitment],
        }
    ).lazy()


# ---------------------------------------------------------------------------
# CRR — Annex I item 1(k), the only residual with no notification condition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk_type", [None, "XYZ"])
def test_crr_unresolved_risk_type_takes_full_risk(
    calculator: CCFCalculator, crr_config: CalculationConfig, risk_type: str | None
) -> None:
    """CRR: null and unrecognised alike take Annex I 1(k), 100%."""
    # Arrange
    exposures = _obs_row(risk_type, is_commitment=True)

    # Act
    result = calculator.apply_ccf(exposures, crr_config).collect()

    # Assert — was 0.50 / 500,000 before P1.267 (a 50pp understatement)
    assert result["ccf"][0] == pytest.approx(1.00)
    assert result["ead_from_ccf"][0] == pytest.approx(1_000_000.0)


def test_crr_residual_ignores_the_commitment_flag(
    calculator: CCFCalculator, crr_config: CalculationConfig
) -> None:
    """Item 1(k) has no commitment/issued split — both sides land on 100%.

    Guards against copying the Table A1 shape onto CRR, where Annex I simply
    has no such distinction in its unconditional residual.
    """
    # Arrange / Act
    commitment = calculator.apply_ccf(_obs_row(None, is_commitment=True), crr_config).collect()
    issued = calculator.apply_ccf(_obs_row(None, is_commitment=False), crr_config).collect()

    # Assert
    assert commitment["ccf"][0] == pytest.approx(1.00)
    assert issued["ccf"][0] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Basel 3.1 — Table A1 Row 5 (commitment) vs Row 3 (issued)
# ---------------------------------------------------------------------------


def test_b31_unresolved_commitment_takes_row_5(
    calculator: CCFCalculator, b31_config: CalculationConfig
) -> None:
    """B31: an unclassifiable commitment takes Row 5, 40%.

    RWA-REDUCING relative to the old shared 50%, and it feeds the Basel 3.1
    output floor directly.
    """
    # Arrange
    exposures = _obs_row(None, is_commitment=True)

    # Act
    result = calculator.apply_ccf(exposures, b31_config).collect()

    # Assert — was 0.50 / 500,000 (a 10pp overstatement)
    assert result["ccf"][0] == pytest.approx(0.40)
    assert result["ead_from_ccf"][0] == pytest.approx(400_000.0)


def test_b31_unresolved_issued_item_stays_on_row_3(
    calculator: CCFCalculator, b31_config: CalculationConfig
) -> None:
    """B31: an unclassifiable ISSUED item stays at 50% — and must not move.

    The load-bearing survivor. This value passed before P1.267 and passes
    after. Without it, a "fix" that swapped 50% for 100% everywhere would pass
    every moving row above while silently breaking Table A1 Row 3.
    """
    # Arrange
    exposures = _obs_row(None, is_commitment=False)

    # Act
    result = calculator.apply_ccf(exposures, b31_config).collect()

    # Assert
    assert result["ccf"][0] == pytest.approx(0.50)
    assert result["ead_from_ccf"][0] == pytest.approx(500_000.0)


def test_the_two_regimes_disagree_on_the_same_unresolved_commitment(
    calculator: CCFCalculator, crr_config: CalculationConfig, b31_config: CalculationConfig
) -> None:
    """Stated as an identity so the residual cannot silently re-converge.

    A future edit that reinstates one shared residual would satisfy any single
    literal assertion above under some value; it cannot satisfy this.
    """
    # Arrange / Act
    crr = calculator.apply_ccf(_obs_row(None, is_commitment=True), crr_config).collect()
    b31 = calculator.apply_ccf(_obs_row(None, is_commitment=True), b31_config).collect()

    # Assert
    assert crr["ccf"][0] != b31["ccf"][0]


# ---------------------------------------------------------------------------
# Controls — the named ladder and the zero-nominal guard must not move
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("risk_type", "crr_ccf", "b31_ccf"),
    [
        ("FR", 1.00, 1.00),
        ("MR", 0.50, 0.50),
        ("MR_ISSUED", 0.50, 0.50),
        ("OC", 0.50, 0.40),
        ("MLR", 0.20, 0.20),
        ("LR", 0.00, 0.10),
    ],
)
def test_named_ladder_is_untouched(risk_type: str, crr_ccf: float, b31_ccf: float) -> None:
    """Every recognised category keeps its value under both regimes.

    The residual change must not leak into the ladder — including OC and LR,
    where the two regimes already diverged correctly before this item.
    """
    # Arrange
    frame = pl.DataFrame({"risk_type": [risk_type], "is_obs_commitment": [True]})

    # Act
    crr = frame.select(sa_ccf_expression().alias("ccf"))
    b31 = frame.select(sa_ccf_expression(is_basel_3_1=True).alias("ccf"))

    # Assert
    assert crr["ccf"][0] == pytest.approx(crr_ccf)
    assert b31["ccf"][0] == pytest.approx(b31_ccf)


@pytest.mark.parametrize("is_commitment", [True, False])
def test_zero_nominal_is_unaffected_by_the_residual(
    calculator: CCFCalculator, crr_config: CalculationConfig, is_commitment: bool
) -> None:
    """A zero-nominal row yields zero EAD regardless of the residual.

    This is why the item's estate reachability is zero: CCR/SFT rows do reach
    apply_ccf but carry nominal 0, so the CCF term vanishes.
    """
    # Arrange
    exposures = _obs_row(None, is_commitment=is_commitment, nominal=0.0)

    # Act
    result = calculator.apply_ccf(exposures, crr_config).collect()

    # Assert
    assert result["ead_from_ccf"][0] == pytest.approx(0.0)


def test_commitment_col_none_selects_the_issued_limb() -> None:
    """``commitment_col=None`` picks Row 3, the higher B31 residual.

    Used by the provisions weighting basis, whose frame is assembled before the
    CCF stage and is not guaranteed to carry the flag.
    """
    # Arrange
    frame = pl.DataFrame({"risk_type": [None]}, schema={"risk_type": pl.Utf8})

    # Act
    result = frame.select(sa_ccf_expression(is_basel_3_1=True, commitment_col=None).alias("ccf"))

    # Assert — and it must not need the column to be present at all
    assert result["ccf"][0] == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# The error channel — DQ016
# ---------------------------------------------------------------------------


def _bundle_with_facility(risk_type: str | None, obs_product: str | None) -> RawDataBundle:
    """A minimal RawDataBundle holding one facility with a real undrawn limit."""
    facilities = pl.DataFrame(
        {
            "facility_reference": ["FAC001"],
            "counterparty_reference": ["CP001"],
            "limit": [NOMINAL],
            "risk_type": [risk_type],
            "obs_product": [obs_product],
        },
        schema={
            "facility_reference": pl.Utf8,
            "counterparty_reference": pl.Utf8,
            "limit": pl.Float64,
            "risk_type": pl.Utf8,
            "obs_product": pl.Utf8,
        },
    ).lazy()
    return make_raw_bundle(
        facilities=facilities,
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP001"]}),
    )


def test_null_risk_type_with_a_real_limit_raises_exactly_one_dq016() -> None:
    """The gap the item exists to close: today this yields zero errors."""
    # Arrange
    bundle = _bundle_with_facility(None, None)

    # Act
    errors = validate_bundle_values(bundle)

    # Assert — exactly one, and it names the right column
    dq016 = [e for e in errors if e.code == ERROR_UNRESOLVED_OBS_RISK_TYPE]
    assert len(dq016) == 1
    assert dq016[0].field_name == "risk_type"


def test_a_resolvable_obs_product_raises_no_dq016() -> None:
    """``obs_product`` is the second route to a category, so it is not a gap."""
    # Arrange — a guarantee resolves to the full-risk bucket
    bundle = _bundle_with_facility(None, "GUARANTEE")

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert not [e for e in errors if e.code == ERROR_UNRESOLVED_OBS_RISK_TYPE]


def test_a_supplied_risk_type_raises_no_dq016() -> None:
    """The control: a preparer who selected a category gets no warning."""
    # Arrange
    bundle = _bundle_with_facility("MR", None)

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert not [e for e in errors if e.code == ERROR_UNRESOLVED_OBS_RISK_TYPE]


def test_an_unrecognised_risk_type_string_still_raises_dq006_not_dq016() -> None:
    """The two codes partition the space; neither shadows the other.

    DQ006 covers a NON-null string that fails its declared domain; DQ016 covers
    the null that DQ006's ``is_not_null()`` filter steps over.
    """
    # Arrange
    bundle = _bundle_with_facility("XYZ", None)

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert [e for e in errors if e.code == ERROR_INVALID_COLUMN_VALUE]
    assert not [e for e in errors if e.code == ERROR_UNRESOLVED_OBS_RISK_TYPE]


def test_a_zero_limit_raises_no_dq016() -> None:
    """No amount, no capital consequence, no warning."""
    # Arrange
    bundle = make_raw_bundle(
        facilities=_bundle_with_facility(None, None).facilities.with_columns(
            pl.lit(0.0).alias("limit")
        ),
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP001"]}),
    )

    # Act
    errors = validate_bundle_values(bundle)

    # Assert
    assert not [e for e in errors if e.code == ERROR_UNRESOLVED_OBS_RISK_TYPE]


def test_the_zero_amount_tolerance_matches_the_ccf_rule_it_reports_on() -> None:
    """DQ016 and the CCF residual must agree on which rows carry an amount.

    ``contracts/validation.py::_ZERO_AMOUNT_TOLERANCE`` is a hand-copy of the
    threshold in ``engine/ccf.py``'s ``_nominal_is_zero`` predicate, duplicated
    because check 12 bars ``contracts/`` from importing ``engine/``. If the two
    drift, the gate reports rows the rule treats as zero (noise) or stays quiet
    on rows the rule prices on the residual (the gap DQ016 exists to close).
    Read out of the engine source rather than re-typed, so this compares the
    two definitions rather than restating one of them.
    """
    # Arrange
    import inspect
    import re

    from rwa_calc.contracts.validation import _ZERO_AMOUNT_TOLERANCE
    from rwa_calc.engine import ccf

    source = inspect.getsource(ccf)

    # Act — the epsilon in the `_nominal_is_zero` expression
    match = re.search(
        r"\.abs\(\)\s*<\s*([0-9.e-]+)\s*\)\.alias\(\s*\n?\s*\"_nominal_is_zero\"", source
    )

    # Assert
    assert match, "could not locate the _nominal_is_zero threshold in engine/ccf.py"
    assert float(match.group(1)) == _ZERO_AMOUNT_TOLERANCE


def test_every_valid_obs_product_resolves_to_a_risk_category() -> None:
    """Pins the equivalence DQ016's absence-test relies on.

    ``_validate_unresolved_obs_risk_type`` tests whether ``obs_product`` is
    ABSENT rather than whether it maps, because ``contracts/`` may not import
    the rulepack (arch_check check 12). That is only equivalent while every
    member of ``VALID_OBS_PRODUCTS`` maps to a bucket. If a future product is
    added to the domain but not to the CategoryMap, the gap silently reopens —
    so it is pinned here rather than assumed.
    """
    # Arrange
    from rwa_calc.data.schemas import OBS_PRODUCT_SYNONYMS, VALID_OBS_PRODUCTS
    from rwa_calc.rulebook.resolve import resolve

    mapping = dict(
        resolve("crr", date(2026, 1, 1)).category_map("obs_product_to_risk_type").entries
    )

    # Act
    unmapped = sorted(
        product
        for product in VALID_OBS_PRODUCTS
        if OBS_PRODUCT_SYNONYMS.get(product.lower(), product.upper()) not in mapping
    )

    # Assert
    assert unmapped == []
