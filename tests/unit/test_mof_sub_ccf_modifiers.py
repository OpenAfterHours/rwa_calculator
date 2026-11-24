"""Unit tests: a Multiple Option Facility sub-limit row is priced as its OWN item (P1.452).

The MOF waterfall (``engine/hierarchy/facility_undrawn.py``) emits one undrawn
row per sub-limit. Each row already took the sub's ``risk_type``, counterparty,
limit and ``committed`` flag; every other column was the ROOT umbrella's, so
the sub's own conversion-factor modifiers never reached the CCF stage (review
findings CM-06 / SF-08).

Rule text relied on (quoted verbatim):

- PS1/26 Art. 111(1)(b): "an off-balance sheet item listed in Column A of Table
  A1 shall be the product of: (i) its nominal value ... and (ii) the applicable
  conversion factor (the percentage specified in the corresponding row of
  Column B)".
- PS1/26 Art. 111(1)(c): "a commitment to issue an off-balance sheet item listed
  in Table A1 shall be calculated in accordance with point (b) of paragraph 1,
  but using the lower of: (i) the percentage specified in Column B that is
  applicable to the off-balance sheet item on which the commitment is made; and
  (ii) the percentage specified in Column B that is applicable to the type of
  commitment".
- PS1/26 Table A1 row (4)(b): "UK residential mortgage commitments that are not
  subject to a conversion factor of 10% or 100%" - 50%; row (5): "Any other
  commitment that is not subject to a conversion factor of 10%, 50% or 100%" -
  40%; row (6)(a) documentary credits - 20%.
- CRR Art. 166(8)(b): "for short-term letters of credit arising from the
  movement of goods, a conversion factor of 20 % shall apply for both the
  issuing and confirming institutions"; (8)(d): "for other credit lines, note
  issuance facilities (NIFs), and revolving underwriting facilities (RUFs), a
  conversion factor of 75 % shall apply".
- PS1/26 Art. 166A(5): "An institution shall, for undrawn purchase commitments
  for revolving purchased receivables, calculate the exposure value using a
  conversion factor of 40%".

So each sub-limit is priced on its own Table A1 / Annex I row. What the sub row
now takes from the sub, outright (no fall-back to the umbrella, because a null
there carries meaning): ``underlying_risk_type`` (null = not a commitment to
issue), ``is_purchased_receivable_commitment``, ``is_short_term_trade_lc`` and
``obs_product`` - and a sub described only by ``obs_product`` gets a row.
``is_uk_residential_mortgage_commitment`` (tri-state, null = derive) is the
sub's own when it states one; a sub stating nothing takes the umbrella's True
(never its False, which would suppress the derivation), so a silent sub-line of
a flagged mortgage umbrella is not moved off Row 4(b)'s 50%.

Every moved column moves the CCF in BOTH directions, depending on which of the
sub and the umbrella carries the attribute; each direction is pinned below
(reducing legs say so). The money, the Basel 3.1 output floor and the
trade-LC knock-on legs (SA short-term windows, Art. 121(6), Art. 162(3) M) are
pinned end to end in ``tests/acceptance/test_mof_sub_ccf_modifiers_pipeline.py``
and ``tests/acceptance/test_mof_sub_knock_on_legs_pipeline.py``.

**Held for the owner's decision, pinned here as guards (green before and after
the fix):** the umbrella's dates, ``is_obs_commitment`` and ``ccf_modelled``
stay on the row. Under a committed, limited umbrella the headroom a sub takes is
still the umbrella's commitment (the SF-02 precedent), so a shorter or
issued-item sub-line must not lower the CCF until that is decided.

Values are the rulepack's (``resolve(regime, date)``): ``sa_ccf`` CRR OC 50% /
MLR 20% / MR_ISSUED 50%, Basel 3.1 OC 40% / MLR 20% / MR 50%;
``firb_credit_line_ccf`` 75%; ``firb_trade_lc_ccf`` 20%;
``oc_short_maturity_ccf`` 20%; ``irb_purchased_receivable_commitment_ccf`` 40%.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import seal_raw_table

_VALUE = date(2025, 1, 1)
_MATURITY = date(2031, 6, 30)
#: A sub-line's own short original maturity (182 days) - the held CRR leg.
_SUB_VALUE = date(2025, 1, 1)
_SUB_MATURITY = date(2025, 7, 2)

_CONFIGS = {
    "CRR": CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "B31": CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)),
}
_REGIMES = tuple(_CONFIGS)


def _facility(ref: str, limit: float, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "facility_reference": ref,
        "product_type": "RCF",
        "book_code": "CORP",
        "counterparty_reference": "CP1",
        "value_date": _VALUE,
        "maturity_date": _MATURITY,
        "currency": "GBP",
        "limit": limit,
        "committed": True,
        "seniority": "senior",
        "risk_type": "OC",
    }
    row.update(overrides)
    return row


def _map(parent: str, child: str) -> dict[str, str]:
    return {"parent_facility_reference": parent, "child_reference": child, "child_type": "facility"}


def _mof(parent: dict[str, Any], *subs: dict[str, Any]) -> tuple[list, list]:
    """An umbrella ``parent`` with ``subs`` mapped directly under it."""
    return [parent, *subs], [
        _map(parent["facility_reference"], s["facility_reference"]) for s in subs
    ]


def _undrawn(facilities: list[dict[str, Any]], mappings: list[dict[str, str]], regime: str):
    """Run ``calculate_facility_undrawn`` on loader-sealed frames and collect it."""
    resolver = HierarchyResolver()
    fac = seal_raw_table(pl.DataFrame(facilities).lazy(), "facilities")
    loans = seal_raw_table(
        pl.LazyFrame(schema={"loan_reference": pl.String, "drawn_amount": pl.Float64}), "loans"
    )
    maps = seal_raw_table(pl.DataFrame(mappings).lazy(), "facility_mappings")
    root_lookup = resolver._build_facility_root_lookup(maps)
    return (
        resolver._calculate_facility_undrawn(
            fac, loans, None, maps, root_lookup, config=_CONFIGS[regime]
        )
        .collect()
        .sort("exposure_reference")
    )


def _row(frame: pl.DataFrame, reference: str) -> dict[str, Any]:
    rows = frame.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, (
        f"expected exactly one {reference} row, got {rows.height}: "
        f"{sorted(frame['exposure_reference'].to_list())}"
    )
    return rows.row(0, named=True)


def _priced_ccf(frame: pl.DataFrame, regime: str, reference: str, approach: ApproachType) -> float:
    """The CCF the CCF stage gives one emitted row, routed to ``approach``."""
    priced = (
        CCFCalculator()
        .apply_ccf(frame.lazy().with_columns(approach=pl.lit(approach.value)), _CONFIGS[regime])
        .collect()
    )
    return float(_row(priced, reference)["ccf"])


# =============================================================================
# The sub row carries the sub's OWN item nature
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
class TestSubRowTakesTheSubsItemNature:
    """Each column is taken from the sub outright - never coalesced to the umbrella."""

    def test_sub_row_carries_the_subs_underlying_risk_type(self, regime: str) -> None:
        # Arrange - a commitment to issue a documentary credit under a plain umbrella.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_LC", 4_000_000.0, underlying_risk_type="MLR"),
        )

        # Act
        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_LC")

        # Assert
        assert row["underlying_risk_type"] == "MLR"

    def test_sub_row_does_not_inherit_the_umbrellas_underlying_risk_type(self, regime: str) -> None:
        # Arrange - the umbrella is tagged as an LC commitment; the cash sub is not.
        # A coalesce(sub, parent) would hand the cash line the umbrella's cap.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, underlying_risk_type="MLR"),
            _facility("SUB_CASH", 4_000_000.0),
        )

        # Act
        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_CASH")

        # Assert
        assert row["underlying_risk_type"] is None

    def test_sub_row_carries_the_subs_residential_mortgage_flag(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_RESI", 4_000_000.0, is_uk_residential_mortgage_commitment=True),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_RESI")

        assert row["is_uk_residential_mortgage_commitment"] is True

    def test_an_unstated_sub_residential_flag_stays_unstated(self, regime: str) -> None:
        # Arrange - the umbrella says False; the sub states nothing, so the CCF
        # stage must be left free to derive Row 4(b) from the sub row's evidence.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=False),
            _facility("SUB_RESI", 4_000_000.0),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_RESI")

        assert row["is_uk_residential_mortgage_commitment"] is None

    def test_a_silent_sub_takes_the_umbrellas_true_residential_flag(self, regime: str) -> None:
        # Guard - the umbrella is a flagged UK residential mortgage commitment; a
        # sub-line stating nothing of itself stays on Row 4(b) rather than being
        # moved to its own bucket (the one fall-back to the umbrella).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=True),
            _facility("SUB_SILENT", 4_000_000.0),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_SILENT")

        assert row["is_uk_residential_mortgage_commitment"] is True

    def test_a_sub_stating_false_keeps_it_under_a_flagged_umbrella(self, regime: str) -> None:
        # Arrange - the sub says of itself that it is not a mortgage commitment.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=True),
            _facility("SUB_NOT", 4_000_000.0, is_uk_residential_mortgage_commitment=False),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_NOT")

        assert row["is_uk_residential_mortgage_commitment"] is False

    def test_sub_row_carries_the_subs_purchased_receivable_flag(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_PR", 4_000_000.0, is_purchased_receivable_commitment=True),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_PR")

        assert row["is_purchased_receivable_commitment"] is True

    def test_sub_row_carries_the_subs_trade_lc_flag(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_TLC", 4_000_000.0, risk_type="MLR", is_short_term_trade_lc=True),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_TLC")

        assert row["is_short_term_trade_lc"] is True

    def test_the_residual_row_keeps_the_umbrellas_values(self, regime: str) -> None:
        # Arrange - the residual is the umbrella's own headroom, not a sub's.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility(
                "SUB_TLC",
                4_000_000.0,
                risk_type="MLR",
                underlying_risk_type="MLR",
                is_short_term_trade_lc=True,
            ),
        )

        # Act
        residual = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_RESIDUAL")

        # Assert
        assert residual["undrawn_amount"] == pytest.approx(6_000_000.0)
        assert residual["underlying_risk_type"] is None
        assert residual["is_short_term_trade_lc"] is False


#: The regime's ``obs_product_to_risk_type`` bucket for a plain documentary
#: credit: CRR Annex I 2(a) medium risk (issued) vs PS1/26 Table A1 row (6)(a).
_DOCUMENTARY_CREDIT_BUCKET = {"CRR": "MR_ISSUED", "B31": "MLR"}


@pytest.mark.parametrize("regime", _REGIMES)
def test_a_sub_described_only_by_its_product_gets_its_own_row(regime: str) -> None:
    # Arrange - the documented obs_product input route, with no risk_type.
    facilities, mappings = _mof(
        _facility("P", 10_000_000.0),
        _facility("SUB_DC", 4_000_000.0, risk_type=None, obs_product="DOCUMENTARY_CREDIT"),
    )

    # Act
    undrawn = _undrawn(facilities, mappings, regime)

    # Assert - its own slice, on its own product's bucket, not folded into the residual.
    row = _row(undrawn, "P_UNDRAWN_SUB_DC")
    assert row["undrawn_amount"] == pytest.approx(4_000_000.0)
    assert row["risk_type"] == _DOCUMENTARY_CREDIT_BUCKET[regime]
    assert row["obs_product"] == "DOCUMENTARY_CREDIT"
    assert _row(undrawn, "P_UNDRAWN_RESIDUAL")["undrawn_amount"] == pytest.approx(6_000_000.0)


# =============================================================================
# Held legs - the umbrella's terms stay on the row until the owner decides
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
class TestHeldLegsKeepTheUmbrellasTerms:
    """Guards, green on both sides of the fix: these columns are NOT moved yet."""

    def test_sub_row_keeps_the_umbrellas_dates(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_SHORT", 4_000_000.0, value_date=_SUB_VALUE, maturity_date=_SUB_MATURITY),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_SHORT")

        assert (row["value_date"], row["maturity_date"]) == (_VALUE, _MATURITY)

    def test_sub_row_keeps_the_umbrellas_commitment_flag(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_ISS", 4_000_000.0, risk_type="MR_ISSUED", is_obs_commitment=False),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_ISS")

        assert row["is_obs_commitment"] is True

    def test_sub_row_keeps_the_umbrellas_modelled_ccf(self, regime: str) -> None:
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, ccf_modelled=0.9),
            _facility("SUB_OWN", 4_000_000.0, ccf_modelled=0.3),
        )

        row = _row(_undrawn(facilities, mappings, regime), "P_UNDRAWN_SUB_OWN")

        assert row["ccf_modelled"] == pytest.approx(0.9)


# =============================================================================
# The waterfall ranks each sub on the SA CCF its row is priced at
# =============================================================================


def _allocated(undrawn: pl.DataFrame) -> dict[str, float]:
    subs = undrawn.filter(pl.col("mof_risk_type_source").is_not_null())
    return dict(zip(subs["mof_risk_type_source"], subs["undrawn_amount"], strict=True))


class TestWaterfallRanksOnThePricedCcf:
    """The umbrella headroom (5m) covers one of two 5m subs: the dearer one takes it.

    The references are chosen so that the pre-fix tie-break (risk type, then
    reference) picks the OTHER sub, so each test fails if the ranking ignores
    the modifier.
    """

    def test_b31_an_underlying_capped_lc_commitment_ranks_below_a_plain_commitment(
        self,
    ) -> None:
        # Arrange - SUB_A: OC capped at the MLR underlying (20%); SUB_B: OC (40%).
        facilities, mappings = _mof(
            _facility("P", 5_000_000.0),
            _facility("SUB_A", 5_000_000.0, underlying_risk_type="MLR"),
            _facility("SUB_B", 5_000_000.0),
        )

        # Act
        allocated = _allocated(_undrawn(facilities, mappings, "B31"))

        # Assert
        assert allocated == {"SUB_B": pytest.approx(5_000_000.0)}

    def test_b31_a_flagged_residential_commitment_ranks_above_a_plain_commitment(
        self,
    ) -> None:
        # Arrange - SUB_A: OC (40%); SUB_B: OC flagged Row 4(b) (50%).
        facilities, mappings = _mof(
            _facility("P", 5_000_000.0),
            _facility("SUB_A", 5_000_000.0),
            _facility("SUB_B", 5_000_000.0, is_uk_residential_mortgage_commitment=True),
        )

        allocated = _allocated(_undrawn(facilities, mappings, "B31"))

        assert allocated == {"SUB_B": pytest.approx(5_000_000.0)}

    def test_b31_a_silent_sub_of_a_flagged_mortgage_umbrella_ranks_at_row_4b(self) -> None:
        # Arrange - SUB_A states it is not a mortgage commitment (row 5, 40%);
        # SUB_B states nothing and takes the umbrella's flag (row 4(b), 50%).
        facilities, mappings = _mof(
            _facility("P", 5_000_000.0, is_uk_residential_mortgage_commitment=True),
            _facility("SUB_A", 5_000_000.0, is_uk_residential_mortgage_commitment=False),
            _facility("SUB_B", 5_000_000.0),
        )

        allocated = _allocated(_undrawn(facilities, mappings, "B31"))

        assert allocated == {"SUB_B": pytest.approx(5_000_000.0)}

    def test_crr_an_oc_sub_under_a_short_umbrella_ranks_at_the_short_maturity_ccf(
        self,
    ) -> None:
        # Arrange - a 273-day umbrella: its OC sub is priced at the Annex I 3(b)
        # 20%, level with the MLR sub, so the risk-type tie-break (MLR < OC)
        # decides - not the 50% OC bucket the sub was ranked at before.
        facilities, mappings = _mof(
            _facility(
                "P", 5_000_000.0, value_date=date(2026, 1, 1), maturity_date=date(2026, 10, 1)
            ),
            _facility("SUB_A", 5_000_000.0),
            _facility("SUB_B", 5_000_000.0, risk_type="MLR"),
        )

        allocated = _allocated(_undrawn(facilities, mappings, "CRR"))

        assert allocated == {"SUB_B": pytest.approx(5_000_000.0)}


# =============================================================================
# The CCF the emitted rows are priced at
# =============================================================================


class TestSubRowConversionFactor:
    """CCFCalculator on the emitted rows - each assertion red on its own pre-fix."""

    def test_b31_sa_commitment_to_issue_an_lc_takes_the_lower_of(self) -> None:
        # Art. 111(1)(c): min(row 5 40%, row 6 20%) = 20% (40% pre-fix).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_LC", 4_000_000.0, underlying_risk_type="MLR"),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_LC", ApproachType.SA)

        assert ccf == pytest.approx(0.20)

    def test_b31_sa_residential_mortgage_commitment_takes_row_4b(self) -> None:
        # Table A1 row (4)(b): 50% (row 5 40% pre-fix).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_RESI", 4_000_000.0, is_uk_residential_mortgage_commitment=True),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_RESI", ApproachType.SA)

        assert ccf == pytest.approx(0.50)

    def test_b31_sa_cash_sub_under_an_lc_tagged_umbrella_is_not_capped(self) -> None:
        # Row 5 40% - the umbrella's MLR underlying capped it to 20% pre-fix.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, underlying_risk_type="MLR"),
            _facility("SUB_CASH", 4_000_000.0),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_CASH", ApproachType.SA)

        assert ccf == pytest.approx(0.40)

    @pytest.mark.parametrize("approach", [ApproachType.SA, ApproachType.FIRB])
    def test_b31_silent_sub_of_a_flagged_mortgage_umbrella_stays_on_row_4b(
        self, approach: ApproachType
    ) -> None:
        # Guard: Row (4)(b) 50% on both carriers, as before the fix - the sub
        # states nothing, so the umbrella's True covers it (no 50% -> 40% move).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=True),
            _facility("SUB_SILENT", 4_000_000.0),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_SILENT", approach)

        assert ccf == pytest.approx(0.50)

    @pytest.mark.parametrize("approach", [ApproachType.SA, ApproachType.FIRB])
    def test_b31_sub_stating_false_under_a_flagged_umbrella_takes_row_5(
        self, approach: ApproachType
    ) -> None:
        # RWA-REDUCING leg (signed off with output-floor evidence in the pipeline
        # sibling): the sub's own explicit False - row (5) 40%, not the
        # umbrella's row (4)(b) 50% it took before.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=True),
            _facility("SUB_NOT", 4_000_000.0, is_uk_residential_mortgage_commitment=False),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_NOT", approach)

        assert ccf == pytest.approx(0.40)

    @pytest.mark.parametrize(
        ("umbrella_flag", "sub_flag", "expected"),
        [
            # RWA-increasing: the umbrella's False no longer suppresses the
            # derivation on a sub that states nothing - row (4)(b) 50% (40% pre-fix).
            (False, None, 0.50),
            # RWA-REDUCING: the sub's own False wins over a derivation the
            # umbrella's null left open - row (5) 40% (50% pre-fix).
            (None, False, 0.40),
        ],
    )
    def test_b31_sa_row_4b_derivation_reads_the_subs_own_statement(
        self, umbrella_flag: bool | None, sub_flag: bool | None, expected: float
    ) -> None:
        # Arrange - a sub row the CCF stage's Row 4(b) derivation evidences: a
        # GBP retail-mortgage commitment of a GB obligor, secured on residential
        # property (the classifier / CRM columns are set on the emitted row).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_uk_residential_mortgage_commitment=umbrella_flag),
            _facility("SUB_RESI", 4_000_000.0, is_uk_residential_mortgage_commitment=sub_flag),
        )
        undrawn = _undrawn(facilities, mappings, "B31").with_columns(
            exposure_class=pl.lit("retail_mortgage"),
            property_type=pl.lit("residential"),
            residential_collateral_value=pl.lit(0.0),
            cp_country_code=pl.lit("GB"),
        )

        # Act
        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_RESI", ApproachType.SA)

        # Assert
        assert ccf == pytest.approx(expected)

    def test_b31_firb_revolving_purchased_receivables_sub_takes_166a5(self) -> None:
        # Art. 166A(5): 40% on the IRB carrier for an MR (50%) sub-line of a
        # revolving umbrella (50% pre-fix).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_revolving=True),
            _facility(
                "SUB_PR", 4_000_000.0, risk_type="MR", is_purchased_receivable_commitment=True
            ),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_PR", ApproachType.FIRB)

        assert ccf == pytest.approx(0.40)

    def test_b31_firb_flagged_mlr_sub_takes_166a5(self) -> None:
        # Art. 166A(5) 40% on the IRB carrier for a flagged documentary-credit
        # sub-line of a revolving umbrella - up from its row (6)(a) 20%, which it
        # took from the unflagged umbrella pre-fix (RWA-increasing).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_revolving=True),
            _facility(
                "SUB_PR", 4_000_000.0, risk_type="MLR", is_purchased_receivable_commitment=True
            ),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_PR", ApproachType.FIRB)

        assert ccf == pytest.approx(0.40)

    def test_b31_firb_unflagged_mlr_sub_of_a_flagged_umbrella_leaves_166a5(self) -> None:
        # RWA-REDUCING leg: the umbrella is a revolving purchased-receivables
        # commitment, the documentary-credit sub-line is not - row (6)(a) 20%,
        # not the umbrella's Art. 166A(5) 40% it took pre-fix.
        facilities, mappings = _mof(
            _facility(
                "P", 10_000_000.0, is_revolving=True, is_purchased_receivable_commitment=True
            ),
            _facility("SUB_DC", 4_000_000.0, risk_type="MLR"),
        )
        undrawn = _undrawn(facilities, mappings, "B31")

        ccf = _priced_ccf(undrawn, "B31", "P_UNDRAWN_SUB_DC", ApproachType.FIRB)

        assert ccf == pytest.approx(0.20)

    def test_crr_firb_purchased_receivable_flag_is_inert(self) -> None:
        # Guard: Art. 166A(5) is a PS1/26 rule with no CRR equivalent - the
        # flagged MR sub-line stays on CRR Art. 166(8)(d) 75%.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, is_revolving=True),
            _facility(
                "SUB_PR", 4_000_000.0, risk_type="MR", is_purchased_receivable_commitment=True
            ),
        )
        undrawn = _undrawn(facilities, mappings, "CRR")

        ccf = _priced_ccf(undrawn, "CRR", "P_UNDRAWN_SUB_PR", ApproachType.FIRB)

        assert ccf == pytest.approx(0.75)

    def test_crr_firb_unflagged_lc_sub_of_a_trade_lc_umbrella_takes_166_8_d(self) -> None:
        # RWA-increasing leg: the umbrella is flagged a short-term trade LC, the
        # MLR sub-line is not - Art. 166(8)(d) 75%, not the 166(8)(b) 20% it
        # took from the umbrella pre-fix.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0, risk_type="MLR", is_short_term_trade_lc=True),
            _facility("SUB_MLR", 4_000_000.0, risk_type="MLR"),
        )
        undrawn = _undrawn(facilities, mappings, "CRR")

        ccf = _priced_ccf(undrawn, "CRR", "P_UNDRAWN_SUB_MLR", ApproachType.FIRB)

        assert ccf == pytest.approx(0.75)

    def test_crr_firb_short_term_trade_lc_sub_takes_166_8_b(self) -> None:
        # Art. 166(8)(b): 20% (the umbrella's 166(8)(d) credit-line 75% pre-fix).
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_TLC", 4_000_000.0, risk_type="MLR", is_short_term_trade_lc=True),
        )
        undrawn = _undrawn(facilities, mappings, "CRR")

        ccf = _priced_ccf(undrawn, "CRR", "P_UNDRAWN_SUB_TLC", ApproachType.FIRB)

        assert ccf == pytest.approx(0.20)

    def test_crr_sa_short_sub_under_a_long_committed_umbrella_stays_at_50(self) -> None:
        # Guard (held decision): the headroom is the 5-year umbrella's commitment,
        # so the sub's own 182-day term does not reach Annex I 3(b) 20%.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_SHORT", 4_000_000.0, value_date=_SUB_VALUE, maturity_date=_SUB_MATURITY),
        )
        undrawn = _undrawn(facilities, mappings, "CRR")

        ccf = _priced_ccf(undrawn, "CRR", "P_UNDRAWN_SUB_SHORT", ApproachType.SA)

        assert ccf == pytest.approx(0.50)

    def test_crr_firb_issued_item_sub_under_a_committed_umbrella_stays_at_75(self) -> None:
        # Guard (held decision): the umbrella's commitment flag stays on the row.
        facilities, mappings = _mof(
            _facility("P", 10_000_000.0),
            _facility("SUB_ISS", 4_000_000.0, risk_type="MR_ISSUED", is_obs_commitment=False),
        )
        undrawn = _undrawn(facilities, mappings, "CRR")

        ccf = _priced_ccf(undrawn, "CRR", "P_UNDRAWN_SUB_ISS", ApproachType.FIRB)

        assert ccf == pytest.approx(0.75)
