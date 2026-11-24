"""Unit tests for the P1.355 umbrella-cap inputs the hierarchy stage attaches.

Pipeline position:
    Loader -> HierarchyResolver (``enrich.propagate_facility_qrre_columns``)
    -> ExposureClassifier (``subtypes.qrre_obligor_aggregate_limit_expr``)

CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the aggregate nominal exposure
to a single individual. The classifier caps an individual's figure under a
multi-option umbrella at the root facility's limit only where that limit bounds
what the individual has drawn under it. Two columns carry the inputs, and both
are joined onto every leg from the facilities table on
``root_facility_reference``:

- ``root_facility_limit`` — the root's ``limit``;
- ``root_facility_utilisation`` — what the leg draws against that limit, IN THE
  ROOT FACILITY'S CURRENCY: a loan's drawn balance and a contingent's amount
  (on- or off-balance-sheet), floored at zero; zero on a headroom row; null
  where the run holds no rate to convert it.

Three properties are pinned here, each the subject of a review objection to the
first P1.355 attempt:

1. **The join multiplies no row.** The facilities table can repeat a reference
   (DQ004, and the pipeline continues by design). A plain join on a repeated
   root doubled every leg under it — and with it EAD — so the join reads one
   row per reference, choosing the value that caps LEAST where the copies
   disagree: null if any copy's limit is null or the copies disagree on
   currency, else the largest limit.
2. **A contingent's drawing is read wherever the unified frame puts it**: an
   on-balance-sheet contingent's amount is in ``drawn_amount`` (its
   ``nominal_amount`` is 0), an off-balance-sheet one's in ``nominal_amount``.
3. **Drawings are compared in the root facility's currency**, as headroom
   netting compares them (``facility_undrawn.facility_utilisation_rows``):
   the root's limit is never FX-converted, while ``drawn_amount`` is converted
   to the reporting currency before classification.

References:
- CRR Art. 154(4)(c) / PRA PS1/26 Art. 147(5A)(c).
- ``src/rwa_calc/engine/hierarchy/enrich.py::propagate_facility_qrre_columns``.
- ``src/rwa_calc/engine/hierarchy/facility_fx.py``: the facility-currency factor.
- ``tests/fixtures/p1_355/p1_355.py``: ``build_p1_355_duplicate_bundle``.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.hierarchy import enrich as enrich_module
from rwa_calc.engine.hierarchy.enrich import propagate_facility_qrre_columns
from rwa_calc.engine.hierarchy.facility_fx import build_facility_fx
from tests.fixtures.p1_355.p1_355 import (
    DUP_DRAWN,
    DUP_ROOT_LIMIT,
    DUPS_LIMIT,
    EUR_GBP_RATE,
    FAC_DUP_ROOT,
    FAC_DUPS,
    LN_DUP_A,
    LN_DUP_B,
    LN_DUPS,
    build_p1_355_duplicate_bundle,
)

_REPORTING_DATE = date(2027, 1, 4)


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, enforce_retail_granularity=False
    )


def _neutral_root_join(
    exposures: pl.LazyFrame, facilities: pl.LazyFrame | None, fx: object
) -> pl.LazyFrame:
    """The hierarchy as it was before the root join existed: typed nulls, no join."""
    return exposures.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("root_facility_limit"),
        pl.lit(None, dtype=pl.Float64).alias("root_facility_utilisation"),
    )


def _resolve(regime: str) -> pl.DataFrame:
    resolved = HierarchyResolver().resolve(build_p1_355_duplicate_bundle(), _config(regime))
    return resolved.exposures.collect()


# =============================================================================
# 1. A duplicated facility reference multiplies no leg. FAILS on a plain join.
# =============================================================================


@pytest.mark.parametrize("regime", ["crr", "b31"])
class TestDuplicatedFacilityReferenceAddsNoRow:
    """The facilities table lists the DUP root and the single-level DUPS
    facility twice each (DQ004). The root join must not copy any leg."""

    def test_each_loan_under_a_duplicated_root_is_one_row(self, regime: str) -> None:
        """Absolute: the subs are listed once, so nothing else copies these legs."""
        counts = Counter(_resolve(regime)["exposure_reference"])
        assert (counts[LN_DUP_A], counts[LN_DUP_B]) == (1, 1)

    def test_the_root_join_adds_no_row_and_moves_no_amount(
        self, regime: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every exposure appears as often, with the same amounts, as when the
        root join is replaced by typed nulls — the hierarchy's output before the
        join existed. Covers the duplicated single-level facility, whose loan
        and headroom rows the IMMEDIATE-parent join already copies (a
        pre-existing DQ004 consequence this item does not change)."""
        live = _resolve(regime)
        monkeypatch.setattr(enrich_module, "_join_root_facility_limit", _neutral_root_join)
        neutral = _resolve(regime)
        assert Counter(live["exposure_reference"]) == Counter(neutral["exposure_reference"])
        amounts = ["drawn_amount", "nominal_amount", "undrawn_amount"]
        assert live.select(amounts).sum().row(0) == neutral.select(amounts).sum().row(0)

    def test_the_duplicated_single_level_facilitys_loan_is_still_present(self, regime: str) -> None:
        """Adequacy: DUPS exercises the single-level path (its own root)."""
        rows = _resolve(regime).filter(pl.col("exposure_reference") == LN_DUPS)
        assert set(rows["root_facility_reference"]) == {FAC_DUPS}
        assert set(rows["root_facility_limit"]) == {DUPS_LIMIT}

    def test_a_duplicated_roots_limit_is_carried_once(self, regime: str) -> None:
        rows = _resolve(regime).filter(pl.col("exposure_reference").is_in([LN_DUP_A, LN_DUP_B]))
        assert set(rows["root_facility_reference"]) == {FAC_DUP_ROOT}
        assert rows["root_facility_limit"].to_list() == [DUP_ROOT_LIMIT, DUP_ROOT_LIMIT]
        assert rows["root_facility_utilisation"].to_list() == [DUP_DRAWN, DUP_DRAWN]


# =============================================================================
# 1b. Disagreeing duplicates resolve to the value that caps LEAST.
# =============================================================================

_SUB = "SUB"


def _exposure_rows(**overrides: list[object]) -> pl.LazyFrame:
    """Unified-frame rows as ``unify`` hands them to the step (pre-FX).

    Every row sits under one non-duplicated sub-facility, so only the ROOT join
    could copy it. ``netting_agreement_reference`` is on the frame as it is on
    the production unified frame, so a step that read it would see it.
    """
    n = len(next(iter(overrides.values())))
    base: dict[str, list[object]] = {
        "exposure_reference": [f"E{i}" for i in range(n)],
        "exposure_type": ["loan"] * n,
        "counterparty_reference": ["CP"] * n,
        "parent_facility_reference": [_SUB] * n,
        "currency": ["GBP"] * n,
        "drawn_amount": [10_000.0] * n,
        "nominal_amount": [0.0] * n,
        "netting_agreement_reference": [None] * n,
    }
    base.update(overrides)
    return pl.LazyFrame(
        base,
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "counterparty_reference": pl.String,
            "parent_facility_reference": pl.String,
            "root_facility_reference": pl.String,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "netting_agreement_reference": pl.String,
        },
    )


def _facility_rows(rows: list[tuple[str, float | None, str]]) -> pl.LazyFrame:
    """``(facility_reference, limit, currency)`` rows plus the shared sub."""
    refs, limits, currencies = (list(col) for col in zip(*rows, strict=True))
    n = len(rows) + 1
    return pl.LazyFrame(
        {
            "facility_reference": [*refs, _SUB],
            "limit": [*limits, 60_000.0],
            "currency": [*currencies, "GBP"],
            "is_revolving": [True] * n,
            "is_qrre_transactor": [False] * n,
            "is_secured": [False] * n,
            "facility_termination_date": [None] * n,
            "is_short_term_trade_lc": [False] * n,
        },
        schema={
            "facility_reference": pl.String,
            "limit": pl.Float64,
            "currency": pl.String,
            "is_revolving": pl.Boolean,
            "is_qrre_transactor": pl.Boolean,
            "is_secured": pl.Boolean,
            "facility_termination_date": pl.Date,
            "is_short_term_trade_lc": pl.Boolean,
        },
    )


class TestDisagreeingDuplicatesCapLeast:
    """Where a repeated root's copies disagree, the joined limit is the one that
    caps least, and the frame keeps its height."""

    @pytest.fixture(scope="class")
    def joined(self) -> pl.DataFrame:
        facilities = _facility_rows(
            [
                ("R_SAME", 80_000.0, "GBP"),
                ("R_SAME", 80_000.0, "GBP"),
                ("R_ONE_NULL", 80_000.0, "GBP"),
                ("R_ONE_NULL", None, "GBP"),
                ("R_TWO_LIMITS", 80_000.0, "GBP"),
                ("R_TWO_LIMITS", 100_000.0, "GBP"),
                ("R_TWO_CCYS", 80_000.0, "GBP"),
                ("R_TWO_CCYS", 80_000.0, "EUR"),
            ]
        )
        exposures = _exposure_rows(
            root_facility_reference=["R_SAME", "R_ONE_NULL", "R_TWO_LIMITS", "R_TWO_CCYS"]
        )
        return propagate_facility_qrre_columns(exposures, facilities).collect()

    def test_no_row_is_added(self, joined: pl.DataFrame) -> None:
        assert joined["exposure_reference"].to_list() == ["E0", "E1", "E2", "E3"]

    def test_identical_copies_give_their_limit(self, joined: pl.DataFrame) -> None:
        assert joined["root_facility_limit"][0] == 80_000.0

    def test_a_null_copy_gives_no_cap(self, joined: pl.DataFrame) -> None:
        assert joined["root_facility_limit"][1] is None

    def test_disagreeing_limits_give_the_largest(self, joined: pl.DataFrame) -> None:
        assert joined["root_facility_limit"][2] == 100_000.0

    def test_disagreeing_currencies_give_no_cap(self, joined: pl.DataFrame) -> None:
        assert joined["root_facility_limit"][3] is None


# =============================================================================
# 2 / 3. What each leg draws against its root, in the root's currency.
# =============================================================================


class TestRootFacilityUtilisation:
    """Under one EUR root (EUR -> GBP at ``EUR_GBP_RATE``; no USD rate): each
    row's drawing in EUR. FAILS where the drawing is read from the wrong
    column or left in its own currency."""

    @pytest.fixture(scope="class")
    def utilisation(self) -> dict[str, float | None]:
        facilities = _facility_rows([("ROOT_EUR", 80_000.0, "EUR")])
        exposures = _exposure_rows(
            exposure_reference=[
                "LOAN_EUR",
                "LOAN_GBP",
                "CONT_ONB",
                "CONT_OFB",
                "HEADROOM",
                "LOAN_USD",
                "LOAN_CREDIT",
                "LOAN_CREDIT_NETTED",
            ],
            exposure_type=[
                "loan",
                "loan",
                "contingent",
                "contingent",
                "facility_undrawn",
                "loan",
                "loan",
                "loan",
            ],
            root_facility_reference=["ROOT_EUR"] * 8,
            currency=["EUR", "GBP", "EUR", "EUR", "EUR", "USD", "EUR", "EUR"],
            drawn_amount=[42_000.0, 36_000.0, 30_000.0, 0.0, 0.0, 40_000.0, -5_000.0, -5_000.0],
            nominal_amount=[0.0, 0.0, 0.0, 30_000.0, 40_000.0, 0.0, 0.0, 0.0],
            netting_agreement_reference=[None] * 7 + ["NET-1"],
        )
        fx_rates = pl.LazyFrame(
            {"currency_from": ["EUR"], "currency_to": ["GBP"], "rate": [EUR_GBP_RATE]}
        )
        fx = build_facility_fx(fx_rates, _config("crr"))
        out = propagate_facility_qrre_columns(exposures, facilities, fx=fx).collect()
        return dict(out.select("exposure_reference", "root_facility_utilisation").iter_rows())

    def test_a_loan_in_the_roots_currency_counts_as_drawn(
        self, utilisation: dict[str, float | None]
    ) -> None:
        assert utilisation["LOAN_EUR"] == pytest.approx(42_000.0, rel=1e-12)

    def test_a_loan_in_another_currency_is_put_in_the_roots(
        self, utilisation: dict[str, float | None]
    ) -> None:
        """GBP 36,000 under a EUR root is EUR 36,000 / 0.8732 — not 36,000, and
        not 36,000 x 0.8732 (the factor applied the wrong way)."""
        assert utilisation["LOAN_GBP"] == pytest.approx(36_000.0 / EUR_GBP_RATE, rel=1e-12)

    def test_an_on_balance_sheet_contingent_counts_its_drawn_amount(
        self, utilisation: dict[str, float | None]
    ) -> None:
        assert utilisation["CONT_ONB"] == pytest.approx(30_000.0, rel=1e-12)

    def test_an_off_balance_sheet_contingent_counts_its_nominal(
        self, utilisation: dict[str, float | None]
    ) -> None:
        assert utilisation["CONT_OFB"] == pytest.approx(30_000.0, rel=1e-12)

    def test_a_headroom_row_draws_nothing(self, utilisation: dict[str, float | None]) -> None:
        assert utilisation["HEADROOM"] == 0.0

    def test_a_drawing_the_run_cannot_convert_is_null(
        self, utilisation: dict[str, float | None]
    ) -> None:
        """Unmeasurable, never silently zero: the classifier then declines to cap."""
        assert utilisation["LOAN_USD"] is None

    def test_a_credit_balance_never_reduces_the_drawings(
        self, utilisation: dict[str, float | None]
    ) -> None:
        assert utilisation["LOAN_CREDIT"] == 0.0

    def test_a_netted_credit_balance_never_reduces_the_drawings_either(
        self, utilisation: dict[str, float | None]
    ) -> None:
        """Where the guard deliberately differs from its sibling. Headroom netting
        (``facility_undrawn.facility_utilisation_rows``) counts a negative loan
        balance under a ``netting_agreement_reference`` (Art. 195 / 219), which
        frees headroom; the overdrawn guard floors it at zero all the same — a
        deposit netted elsewhere must not make an umbrella look less drawn than
        its debit balances, which would let the cap through (RWA-reducing). A
        copy of the sibling's amount gives -5,000 here."""
        assert utilisation["LOAN_CREDIT_NETTED"] == 0.0
