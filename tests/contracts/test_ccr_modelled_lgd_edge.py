"""
Contract tests for the ``ccr_modelled_lgd`` carrier column (P1.215: A-IRB
routing for synthetic CCR rows).

Sibling to tests/contracts/test_ccr_effective_maturity_edge.py — same
placement-trap pattern, different carrier. Pins the schema + edge-contract
surface the engine-implementer wires next:
- ``ccr_modelled_lgd`` (Float64, optional) is declared on ``SFT_TRADE_SCHEMA``
  and the SA-CCR derivative ``TRADE_SCHEMA``, so a synthetic CCR row can carry
  an own-estimate LGD from either an FCCM SFT or an SA-CCR derivative input.
- It is declared on the CCR-flavoured exit edges (``CCR_EXIT_EDGE``,
  ``CLASSIFIER_EXIT_CCR_EDGE``, ``CRM_EXIT_CCR_EDGE``,
  ``RE_SPLIT_EXIT_CCR_EDGE``) so it survives through to the classifier's
  ``has_modelled_lgd`` AIRB gate (engine/stages/classify/permissions.py:340).
- It is ABSENT from ``HIERARCHY_EXIT_EDGE`` — a hierarchy-base column would be
  silently filtered out of the CCR-flavoured exits by the
  ``c not in HIERARCHY_EXIT_EDGE.columns`` comprehension (the placement trap
  ``ccr_effective_maturity`` already guards against).

References:
- CRR Art. 143 / Art. 169-171: own-estimate LGD under A-IRB.
- engine/stages/classify/permissions.py:340 — the AIRB gate this carrier feeds.
- tests/fixtures/ccr/golden_ccr_sft_irb_maturity.py — the fixture that
  already carries ``ccr_modelled_lgd`` on the SFT trade row (currently
  dropped at the loader-boundary seal, since neither schema declares it yet).
- tests/contracts/test_ccr_effective_maturity_edge.py — the template this
  file mirrors.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CCRConfig
from rwa_calc.contracts.edges import (
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_CCR_EDGE,
    HIERARCHY_EXIT_EDGE,
    RE_SPLIT_EXIT_CCR_EDGE,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA, SFT_TRADE_SCHEMA, TRADE_SCHEMA
from rwa_calc.engine.ccr.pipeline_adapter import ccr_rows_to_exposures

CARRIER = "ccr_modelled_lgd"

CCR_FLAVOURED_EDGES = [
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_CCR_EDGE,
    RE_SPLIT_EXIT_CCR_EDGE,
]


class TestCcrModelledLgdCarrier:
    """The ``ccr_modelled_lgd`` carrier lives on the CCR-flavoured edges."""

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_present_on_ccr_edge(self, edge):
        # Arrange / Act / Assert
        assert CARRIER in edge.columns, (
            f"'{CARRIER}' must be declared on edge '{edge.name}' "
            "(CCR-only spread should propagate it)"
        )

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_is_float64(self, edge):
        # Arrange
        assert CARRIER in edge.columns
        # Act / Assert
        assert edge.columns[CARRIER].dtype == pl.Float64, (
            f"'{CARRIER}' must be pl.Float64 on edge '{edge.name}', "
            f"got {edge.columns[CARRIER].dtype}"
        )

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_is_optional(self, edge):
        # Arrange
        assert CARRIER in edge.columns
        # Act / Assert
        assert edge.columns[CARRIER].required is False, (
            f"'{CARRIER}' must be required=False on edge '{edge.name}' "
            "(absent on lending rows; conform injects a typed null)"
        )

    def test_carrier_absent_from_hierarchy_exit_edge(self):
        # The placement-trap guard: a hierarchy-base column is filtered out of
        # the CCR exits by 'c not in HIERARCHY_EXIT_EDGE.columns'.
        assert CARRIER not in HIERARCHY_EXIT_EDGE.columns, (
            f"'{CARRIER}' must NOT be on HIERARCHY_EXIT_EDGE — placing it there "
            "would silently strip it from the CCR classifier/crm exits"
        )


class TestCcrModelledLgdInputSchemas:
    """``ccr_modelled_lgd`` exists on SFT_TRADE_SCHEMA and the SA-CCR TRADE_SCHEMA."""

    def test_carrier_present_on_sft_trade_schema(self):
        assert CARRIER in SFT_TRADE_SCHEMA, f"SFT_TRADE_SCHEMA must declare '{CARRIER}'"

    def test_carrier_is_float64_on_sft_trade_schema(self):
        assert CARRIER in SFT_TRADE_SCHEMA
        assert SFT_TRADE_SCHEMA[CARRIER].dtype == pl.Float64, (
            f"SFT_TRADE_SCHEMA['{CARRIER}'] must be pl.Float64, "
            f"got {SFT_TRADE_SCHEMA[CARRIER].dtype}"
        )

    def test_carrier_optional_on_sft_trade_schema(self):
        assert CARRIER in SFT_TRADE_SCHEMA
        assert SFT_TRADE_SCHEMA[CARRIER].required is False, (
            f"SFT_TRADE_SCHEMA['{CARRIER}'] must be required=False"
        )

    def test_carrier_present_on_trade_schema(self):
        assert CARRIER in TRADE_SCHEMA, f"TRADE_SCHEMA must declare '{CARRIER}'"

    def test_carrier_is_float64_on_trade_schema(self):
        assert CARRIER in TRADE_SCHEMA
        assert TRADE_SCHEMA[CARRIER].dtype == pl.Float64, (
            f"TRADE_SCHEMA['{CARRIER}'] must be pl.Float64, got {TRADE_SCHEMA[CARRIER].dtype}"
        )

    def test_carrier_optional_on_trade_schema(self):
        assert CARRIER in TRADE_SCHEMA
        assert TRADE_SCHEMA[CARRIER].required is False, (
            f"TRADE_SCHEMA['{CARRIER}'] must be required=False"
        )


def _two_trade_ns_raw_ccr(lgd_a: float, lgd_b: float) -> RawCCRBundle:
    """Return a RawCCRBundle: one netting set, two IR-swap trades, distinct LGDs.

    Both trades sit in the same legally-enforceable, unmargined netting set
    (NS_001 / CP_001) and carry the golden CCR-A1 10y GBP IR-swap economics —
    only ``ccr_modelled_lgd`` differs (``lgd_a`` on the first trade, ``lgd_b``
    on the second). Margin-agreement and collateral frames are empty-schema.
    """
    trades_df = create_trades(
        [
            make_trade(trade_id="T_LGD_A", netting_set_id="NS_001"),
            make_trade(trade_id="T_LGD_B", netting_set_id="NS_001"),
        ]
    ).with_columns(pl.Series(CARRIER, [lgd_a, lgd_b], dtype=pl.Float64))

    return RawCCRBundle(
        trades=TradeBundle(trades=trades_df.lazy()),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets(
                [make_netting_set(netting_set_id="NS_001", counterparty_reference="CP_001")]
            ).lazy()
        ),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()
        ),
    )


class TestCcrModelledLgdCollapse:
    """The NS-grain collapse of ``ccr_modelled_lgd`` is deterministic + conservative.

    A netting set has no stable trade order, so collapsing heterogeneous
    modelled LGDs via ``.first()`` would pick an order-nondeterministic value.
    ``ccr_rows_to_exposures`` collapses via ``.max()`` — order-independent and
    conservative (the highest LGD is the largest capital input; a higher LGD
    drives a larger K / RWA). This pins the max is selected for a two-trade NS.
    """

    @pytest.mark.parametrize(
        ("lgd_a", "lgd_b", "expected_max"),
        [
            (0.30, 0.55, 0.55),  # max is the second trade
            (0.55, 0.30, 0.55),  # max is the first trade — order-independent
        ],
    )
    def test_multi_trade_ns_collapses_to_max_modelled_lgd(
        self, lgd_a: float, lgd_b: float, expected_max: float
    ) -> None:
        # Arrange
        raw_ccr = _two_trade_ns_raw_ccr(lgd_a, lgd_b)

        # Act — one synthetic exposure row per netting set.
        rows = ccr_rows_to_exposures(raw_ccr, CCRConfig(), date(2026, 6, 30)).collect()

        # Assert — exactly one NS row, carrying the MAX modelled LGD.
        ns_rows = rows.filter(pl.col("source_netting_set_id") == "NS_001")
        assert ns_rows.height == 1, (
            f"expected exactly 1 synthetic row for NS_001, got {ns_rows.height}"
        )
        actual = ns_rows.row(0, named=True)[CARRIER]
        assert actual == pytest.approx(expected_max, abs=1e-9), (
            f"multi-trade NS with modelled LGDs {{{lgd_a}, {lgd_b}}} must collapse to "
            f"the max ({expected_max}) — deterministic + conservative, got {actual}"
        )
