"""
Integration tests: the Art. 113(6) intragroup 0% risk weight — own-funds carve-out
and the derivative (SA-CCR) and SFT (FCCM) exposures it reaches.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> resolve_scope -> ccr_sa_ccr / sft_fccm
    -> classifier -> CRM -> SA calculator (``apply_intragroup_zero_rw``) -> results

Rule text, both regimes (read verbatim 2026-11-24):
- CRR Art. 113(6) (legislation.gov.uk): "With the exception of exposures giving
  rise to Common Equity Tier 1, Additional Tier 1 or Tier 2 items, an institution
  may, subject to the prior approval of the competent authorities, decide not to
  apply the requirements of paragraph 1 of this Article to the exposures of that
  institution to a counterparty which is its parent undertaking, its subsidiary, a
  subsidiary of its parent undertaking or an undertaking linked by a common
  management relationship. ... it may assign a risk weight of 0 %."
- PS1/26 Art. 113(6) (ps126app1.pdf pp. 34-35): "With the exception of exposures
  giving rise to Common Equity Tier 1, Additional Tier 1 or Tier 2 items, an
  institution may with the prior permission of the PRA, assign a risk weight of 0%
  to the exposures of that institution to a counterparty which is its parent
  undertaking, its subsidiary, ..."

Two consequences the engine missed at HEAD (P1.364):
- (D, RWA-increasing) the carve-out: a subordinated intragroup loan — the engine's
  stand-in for "an exposure giving rise to a Tier 2 item" (owner-approved proxy) —
  must keep its normal weight. HEAD gave it 0% in both regimes.
- (A, RWA-reducing, owner sign-off) neither regime excludes counterparty credit
  risk: "exposures of that institution to a counterparty" covers an SA-CCR netting
  set and an SFT to a core-UK-group member (Annex II para 126, both regimes,
  speaks of "intra-group exposures ... that give raise to counterparty credit risk
  but for which the institutions assign a risk weight of zero"). HEAD never tagged
  those rows, so they kept their full weight.

Hand calculation (BANK_A individual run; GRP / BANK_A / BANK_B all core UK group;
BANK_B an externally unrated UK institution with SCRA grade A, CORP_EXT an unrated
corporate; no sovereign rating, so the CRR Art. 121 Table 5 unrated-sovereign
column applies under CRR; under Basel 3.1 BANK_B's senior weight is the SCRA
grade A 40% (PS1/26 Art. 121), so the 150% below can only be Art. 133(5)):

    LOAN_IG_SENIOR  1m senior, intragroup BANK_B        -> 0%   both regimes
    LOAN_IG_SUB     1m subordinated, intragroup BANK_B  -> CRR 100% (Art. 121
                    Table 5, unrated institution, unrated sovereign);
                    B31 150% (PS1/26 Art. 133(5) subordinated debt instrument)
                    HEAD: 0% in both (the 0% override ran last and overwrote it)
    LOAN_EXT        1m senior to CORP_EXT               -> 100% both (control)
    ccr__NS_IG      SA-CCR netting set to BANK_B,
                    intragroup BANK_B                   -> 0%, RWA 0 both regimes
    ccr__NS_EXT     SA-CCR netting set to CORP_EXT      -> 100% both (control)
    ccr__NS_IG_NE__split__*  non-enforceable intragroup set, split per
                    trade by Art. 272(4) — each split set keeps the tag -> 0%
    ccr__SFT_NS_IG  10m cash-lent SFT to BANK_B,
                    intragroup BANK_B (E* = 10m)        -> 0%, RWA 0 both regimes
    ccr__SFT_NS_EXT 10m cash-lent SFT to CORP_EXT       -> 100%, RWA 10m (control)

    Separate run — ccr__SFT_NS_MIX: two 5m cash-lent SFTs to BANK_B netted under
    an eligible MNA (E* = 10m); only the first trade is intragroup-tagged, so the
    set is not wholly intragroup -> CRR 100% / B31 40% (SCRA grade A), RWA
    10m / 4m. A first-trade or any-trade collapse of the carrier would give 0%.

Output-floor control (Basel 3.1, PS1/26 Art. 92(2A)(a)(i): a stand-alone UK
institution on an individual basis is floored): with BANK_B internally rated and
an F-IRB permission, ``ccr__NS_IG`` is IRB-routed, so it keeps its IRB weight and
its non-zero SA-equivalent RWA — the 0% is SA-only, and lowering an IRB row's
S-TREA contribution would lower the floor.

References:
- CRR Art. 113(6); PS1/26 Art. 113(6)-(7); PS1/26 Art. 133(5)
- CRR / PS1/26 Annex II paras 66-68 and 126
- PS1/26 Art. 92(2A)(a)(i)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawSFTBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    BOOK_ENTITY_MAPPING_SCHEMA,
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    NETTING_SET_SCHEMA,
    RATINGS_SCHEMA,
    REPORTING_ENTITY_SCHEMA,
    SFT_TRADE_SCHEMA,
)
from rwa_calc.domain.enums import InstitutionType, PermissionMode, ReportingBasis
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

#: regime -> reporting date (CRR before 2027-01-01, Basel 3.1 after).
_DATES = {"crr": date(2026, 3, 31), "b31": date(2027, 3, 31)}
_MATURITY = date(2031, 3, 31)
_REGIMES = ["crr", "b31"]

_LOAN = 1_000_000.0
_SFT_CASH_LENT = 10_000_000.0

#: The subordinated intragroup loan's weight once the carve-out applies:
#: CRR Art. 121 Table 5 unrated institution (unrated sovereign) / PS1/26 Art. 133(5).
_SUBORDINATED_RW = {"crr": 1.0, "b31": 1.5}

#: BANK_B's senior weight when the intragroup 0% does not apply:
#: CRR Art. 121 Table 5 unrated institution (unrated sovereign) / PS1/26 Art. 121
#: SCRA grade A.
_BANK_B_SENIOR_RW = {"crr": 1.0, "b31": 0.4}

#: Each of the two trades in the netted, partly-tagged SFT set ``SFT_NS_MIX``.
_SFT_MIX_TRADE = 5_000_000.0

_CUG_ENTITIES = ("GRP", "BANK_A", "BANK_B")
_PARENTS = (None, "GRP", "GRP")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module", params=_REGIMES)
def bank_a_solo(request: pytest.FixtureRequest) -> tuple[str, pl.DataFrame]:
    """The BANK_A individual core-UK-group run, SA, one regime per param."""
    regime: str = request.param
    result = PipelineOrchestrator().run_with_data(_bundle(regime), _config(regime))
    return regime, result.results.collect()


# =============================================================================
# (D) The own-funds carve-out — RWA-increasing
# =============================================================================


class TestOwnFundsCarveOut:
    """Exposures giving rise to own-funds items do not take the intragroup 0%."""

    def test_subordinated_intragroup_loan_keeps_its_normal_weight(
        self, bank_a_solo: tuple[str, pl.DataFrame]
    ) -> None:
        """CRR 100% / B31 150% — HEAD zero-weighted it in both regimes."""
        # Arrange
        regime, df = bank_a_solo

        # Act
        row = _row(df, "LOAN_IG_SUB")

        # Assert
        assert row["risk_weight"] == pytest.approx(_SUBORDINATED_RW[regime])
        assert row["rwa_final"] == pytest.approx(_LOAN * _SUBORDINATED_RW[regime])

    def test_senior_intragroup_loan_still_zero_weighted(
        self, bank_a_solo: tuple[str, pl.DataFrame]
    ) -> None:
        """Control: the carve-out leaves an ordinary senior intragroup loan at 0%."""
        # Arrange
        _regime, df = bank_a_solo

        # Act
        row = _row(df, "LOAN_IG_SENIOR")

        # Assert
        assert row["risk_weight"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0)

    def test_external_loan_unaffected(self, bank_a_solo: tuple[str, pl.DataFrame]) -> None:
        """Control: an external unrated corporate loan stays at 100%."""
        _regime, df = bank_a_solo

        row = _row(df, "LOAN_EXT")

        assert row["risk_weight"] == pytest.approx(1.0)
        assert row["rwa_final"] == pytest.approx(_LOAN)


# =============================================================================
# (A) Intragroup CCR and SFT exposures — RWA-reducing (owner sign-off)
# =============================================================================


class TestCounterpartyCreditRiskInScope:
    """An intragroup derivative netting set or SFT to a CUG member takes the 0%."""

    @pytest.mark.parametrize("reference", ["ccr__NS_IG", "ccr__SFT_NS_IG"])
    def test_intragroup_ccr_and_sft_rows_are_zero_weighted(
        self, bank_a_solo: tuple[str, pl.DataFrame], reference: str
    ) -> None:
        # Arrange
        _regime, df = bank_a_solo

        # Act
        row = _row(df, reference)

        # Assert — the row carries real exposure, at a 0% weight
        assert row["ead_final"] > 0.0, "a zero-EAD row cannot show the weight moved"
        assert row["risk_weight"] == pytest.approx(0.0)
        assert row["rwa_final"] == pytest.approx(0.0)

    @pytest.mark.parametrize("reference", ["ccr__NS_EXT", "ccr__SFT_NS_EXT"])
    def test_external_ccr_and_sft_rows_keep_full_weight(
        self, bank_a_solo: tuple[str, pl.DataFrame], reference: str
    ) -> None:
        """Control: the same products to an external unrated corporate stay at 100%."""
        _regime, df = bank_a_solo

        row = _row(df, reference)

        assert row["risk_weight"] == pytest.approx(1.0)
        assert row["rwa_final"] == pytest.approx(row["ead_final"])

    def test_sft_exposure_value_is_the_cash_lent(
        self, bank_a_solo: tuple[str, pl.DataFrame]
    ) -> None:
        """Adequacy: the intragroup SFT's E* is the 10m lent, so a 0% is a 10m move."""
        _regime, df = bank_a_solo

        row = _row(df, "ccr__SFT_NS_IG")

        assert row["ead_final"] == pytest.approx(_SFT_CASH_LENT)

    def test_split_non_enforceable_intragroup_netting_set_keeps_its_tag(
        self, bank_a_solo: tuple[str, pl.DataFrame]
    ) -> None:
        """Art. 272(4): each single-trade set split from an intragroup set takes the 0%."""
        # Arrange
        _regime, df = bank_a_solo

        # Act
        split = df.filter(pl.col("exposure_reference").str.starts_with("ccr__NS_IG_NE__split__"))

        # Assert — both trades priced alone, each with exposure and a 0% weight
        assert split.height == 2, "the non-enforceable set must split into its two trades"
        assert (split["ead_final"] > 0.0).all()
        assert split["risk_weight"].to_list() == pytest.approx([0.0, 0.0])
        assert split["rwa_final"].to_list() == pytest.approx([0.0, 0.0])


@pytest.fixture(scope="module", params=_REGIMES)
def bank_a_solo_mixed_sft(request: pytest.FixtureRequest) -> tuple[str, pl.DataFrame]:
    """BANK_A individual run holding one netted SFT set: one tagged, one untagged trade."""
    regime: str = request.param
    bundle = make_raw_bundle(
        counterparties=_counterparties(),
        reporting_entities=_registry(),
        book_entity_mappings=_book_mapping(),
        sft=_mixed_sft(_DATES[regime]),
    )
    result = PipelineOrchestrator().run_with_data(bundle, _config(regime))
    return regime, result.results.collect()


class TestNettedSftSetNeedsEveryTradeTagged:
    """A netted SFT set takes the 0% only when every trade in it is intragroup-tagged.

    ``SFT_NS_MIX`` nets two 5m cash-lent trades to BANK_B under an eligible MNA
    (Art. 206 / 220(1)), so FCCM prices one E* of 10m. Only the FIRST trade is
    tagged intragroup: the set is not wholly an exposure to a core-UK-group
    member, so it keeps BANK_B's normal institution weight — CRR 100% (Art. 121
    Table 5, unrated institution, unrated sovereign), Basel 3.1 40% (PS1/26
    Art. 121 SCRA grade A). The tagged trade comes first so that a first-trade
    or any-trade collapse of the carrier would zero-weight the set.
    """

    def test_one_netted_row_with_the_summed_exposure(
        self, bank_a_solo_mixed_sft: tuple[str, pl.DataFrame]
    ) -> None:
        """Adequacy: the set nets into one 10m row, so its weight is a 10m question."""
        # Arrange
        _regime, df = bank_a_solo_mixed_sft

        # Act
        row = _row(df, "ccr__SFT_NS_MIX")

        # Assert
        assert row["ead_final"] == pytest.approx(2 * _SFT_MIX_TRADE)

    def test_partly_tagged_set_keeps_the_counterparty_weight(
        self, bank_a_solo_mixed_sft: tuple[str, pl.DataFrame]
    ) -> None:
        # Arrange
        regime, df = bank_a_solo_mixed_sft

        # Act
        row = _row(df, "ccr__SFT_NS_MIX")

        # Assert
        assert row["risk_weight"] == pytest.approx(_BANK_B_SENIOR_RW[regime])
        assert row["rwa_final"] == pytest.approx(row["ead_final"] * _BANK_B_SENIOR_RW[regime])
        assert row["rwa_final"] > 0.0


# =============================================================================
# Output-floor gate — Basel 3.1 only (the floor does not exist under CRR)
# =============================================================================


@pytest.fixture(scope="module")
def b31_irb_floored() -> AggregatedResultBundle:
    """BANK_A individual Basel 3.1 run with BANK_B internally rated and F-IRB permitted."""
    bundle = _bundle("b31", irb_rated_bank_b=True)
    config = CalculationConfig.basel_3_1(
        reporting_date=_DATES["b31"],
        permission_mode=PermissionMode.IRB,
        reporting_entity="BANK_A",
        reporting_basis=ReportingBasis.INDIVIDUAL,
        institution_type=InstitutionType.STANDALONE_UK,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


class TestIrbRoutedIntragroupCcrKeepsSaEquivalent:
    """The 0% is SA-only: an IRB-routed intragroup netting set keeps its S-TREA leg."""

    def test_intragroup_netting_set_is_irb_routed(
        self, b31_irb_floored: AggregatedResultBundle
    ) -> None:
        """Adequacy: without IRB routing this control would test nothing."""
        row = _row(b31_irb_floored.results.collect(), "ccr__NS_IG")

        assert row["approach_applied"] == "foundation_irb"

    def test_irb_routed_intragroup_netting_set_keeps_non_zero_weights(
        self, b31_irb_floored: AggregatedResultBundle
    ) -> None:
        # Arrange
        row = _row(b31_irb_floored.results.collect(), "ccr__NS_IG")

        # Assert — IRB weight and SA-equivalent both untouched by the SA-only 0%
        assert row["ead_final"] > 0.0
        assert row["rwa_final"] > 0.0
        assert row["sa_rwa"] > 0.0, "the S-TREA leg of an IRB row must not take the 0%"

    def test_floor_s_trea_counts_the_irb_routed_intragroup_netting_set(
        self, b31_irb_floored: AggregatedResultBundle
    ) -> None:
        # Arrange
        results = b31_irb_floored.results.collect()
        ns_sa_rwa = _row(results, "ccr__NS_IG")["sa_rwa"]
        summary = b31_irb_floored.output_floor_summary

        # Assert
        assert summary is not None
        assert summary.s_trea >= ns_sa_rwa > 0.0


# =============================================================================
# Bundle builders
# =============================================================================


def _config(regime: str) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(
        reporting_date=_DATES[regime],
        permission_mode=PermissionMode.STANDARDISED,
        reporting_entity="BANK_A",
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


def _bundle(regime: str, *, irb_rated_bank_b: bool = False) -> Any:
    reporting_date = _DATES[regime]
    extra: dict[str, Any] = {}
    if irb_rated_bank_b:
        extra["ratings"] = _bank_b_internal_rating(reporting_date)
        extra["model_permissions"] = _institution_firb_permission()
    return make_raw_bundle(
        loans=_loans(reporting_date),
        counterparties=_counterparties(),
        reporting_entities=_registry(),
        book_entity_mappings=_book_mapping(),
        ccr=_ccr(reporting_date),
        sft=_sft(reporting_date),
        **extra,
    )


def _counterparties() -> pl.DataFrame:
    def _cp(ref: str, entity_type: str) -> dict[str, Any]:
        is_bank = entity_type == "institution"
        return {
            "counterparty_reference": ref,
            "counterparty_name": ref,
            "entity_type": entity_type,
            "country_code": "GB",
            "annual_revenue": None if is_bank else 500_000_000.0,
            "total_assets": None if is_bank else 1_000_000_000.0,
            "default_status": False,
            "is_financial_sector_entity": is_bank,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
            # Basel 3.1 SCRA grade A (40% senior, > 3 months) keeps BANK_B's class
            # weight apart from the Art. 133(5) 150%; CRR does not read it.
            "scra_grade": "A" if is_bank else None,
        }

    return pl.DataFrame(
        [_cp("BANK_B", "institution"), _cp("CORP_EXT", "corporate")],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )


def _loans(reporting_date: date) -> pl.DataFrame:
    def _loan(ref: str, cp: str, seniority: str, intragroup: str | None) -> dict[str, Any]:
        return {
            "loan_reference": ref,
            "product_type": "term_loan",
            "book_code": "BOOK_A1",
            "counterparty_reference": cp,
            "value_date": reporting_date,
            "maturity_date": _MATURITY,
            "currency": "GBP",
            "drawn_amount": _LOAN,
            "interest": 0.0,
            "seniority": seniority,
            "intragroup_entity_reference": intragroup,
        }

    return pl.DataFrame(
        [
            _loan("LOAN_IG_SENIOR", "BANK_B", "senior", "BANK_B"),
            _loan("LOAN_IG_SUB", "BANK_B", "subordinated", "BANK_B"),
            _loan("LOAN_EXT", "CORP_EXT", "senior", None),
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )


def _registry() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "entity_reference": entity,
                "entity_name": entity,
                "lei": f"LEI{entity:0>17}",
                "parent_entity_reference": parent,
                "core_uk_group": True,
            }
            for entity, parent in zip(_CUG_ENTITIES, _PARENTS, strict=True)
        ],
        schema=dtypes_of(REPORTING_ENTITY_SCHEMA),
    )


def _book_mapping() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"book_code": "BOOK_A1", "reporting_entity_reference": "BANK_A"},
            {"book_code": "BOOK_B1", "reporting_entity_reference": "BANK_B"},
        ],
        schema=dtypes_of(BOOK_ENTITY_MAPPING_SCHEMA),
    )


def _ccr(reporting_date: date) -> RawCCRBundle:
    """Unmargined netting sets on BANK_A's book: two intragroup, one external.

    ``NS_IG_NE`` is intragroup but not legally enforceable, so the Art. 272(4)
    gate prices each of its two trades as its own netting set.
    """
    #: (netting set, counterparty, intragroup tag, legally enforceable, trade count)
    sets = [
        ("NS_IG", "BANK_B", "BANK_B", True, 1),
        ("NS_EXT", "CORP_EXT", None, True, 1),
        ("NS_IG_NE", "BANK_B", "BANK_B", False, 2),
    ]
    trades = create_trades(
        [
            make_trade(
                trade_id=f"T_{ns_id}_{n}",
                netting_set_id=ns_id,
                notional=10_000_000.0,
                mtm_value=1_000_000.0,
                start_date=reporting_date,
                maturity_date=_MATURITY,
            )
            for ns_id, _cp, _ig, _enforceable, count in sets
            for n in range(count)
        ]
    )
    netting_sets = pl.DataFrame(
        [
            {
                "netting_set_id": ns_id,
                "counterparty_reference": cp,
                "is_legally_enforceable": enforceable,
                "is_margined": False,
                "book_code": "BOOK_A1",
                "intragroup_entity_reference": intragroup,
            }
            for ns_id, cp, intragroup, enforceable, _count in sets
        ],
        schema=dtypes_of(NETTING_SET_SCHEMA),
    )
    return RawCCRBundle(
        trades=TradeBundle(trades=trades.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
        ),
    )


def _sft(reporting_date: date) -> RawSFTBundle:
    """Two uncollateralised 10m cash-lent SFTs on BANK_A's book: one intragroup."""
    trades = pl.DataFrame(
        [
            {
                "trade_id": f"SFT_{suffix}",
                "netting_set_id": f"SFT_NS_{suffix}",
                "counterparty_reference": cp,
                "notional": _SFT_CASH_LENT,
                "currency": "GBP",
                "maturity_date": date(reporting_date.year, 12, 31),
                "start_date": reporting_date,
                "book_code": "BOOK_A1",
                "intragroup_entity_reference": intragroup,
            }
            for suffix, cp, intragroup in (("IG", "BANK_B", "BANK_B"), ("EXT", "CORP_EXT", None))
        ],
        schema=dtypes_of(SFT_TRADE_SCHEMA),
    )
    sealed, _missing, _lossy = seal_lenient(trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed))


def _mixed_sft(reporting_date: date) -> RawSFTBundle:
    """One netted SFT set to BANK_B: the first trade tagged intragroup, the second not.

    Both trades carry ``under_master_netting_agreement`` and
    ``is_legally_enforceable``, so the netting gate nets them into one E*.
    """
    trades = pl.DataFrame(
        [
            {
                "trade_id": f"SFT_MIX_{n}",
                "netting_set_id": "SFT_NS_MIX",
                "counterparty_reference": "BANK_B",
                "notional": _SFT_MIX_TRADE,
                "currency": "GBP",
                "maturity_date": date(reporting_date.year, 12, 31),
                "start_date": reporting_date,
                "book_code": "BOOK_A1",
                "under_master_netting_agreement": True,
                "is_legally_enforceable": True,
                "intragroup_entity_reference": intragroup,
            }
            for n, intragroup in ((1, "BANK_B"), (2, None))
        ],
        schema=dtypes_of(SFT_TRADE_SCHEMA),
    )
    sealed, _missing, _lossy = seal_lenient(trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed))


def _bank_b_internal_rating(reporting_date: date) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "rating_reference": "RAT_BANK_B",
                "counterparty_reference": "BANK_B",
                "rating_type": "internal",
                "cqs": None,
                "pd": 0.01,
                "rating_date": reporting_date,
                "is_solicited": False,
                "model_id": "MOD_INST_FIRB",
                "is_short_term": False,
            }
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )


def _institution_firb_permission() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "model_id": "MOD_INST_FIRB",
                "exposure_class": "institution",
                "approach": "foundation_irb",
                "country_codes": "GB",
                "excluded_book_codes": None,
            }
        ],
        schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA),
    )


def _row(df: pl.DataFrame, reference: str) -> dict[str, Any]:
    rows = df.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"expected one {reference} row, got {len(rows)}"
    return rows[0]
