"""
Real-estate loan-split template coverage — the split legs, all the way to COREP
C 07.00 and Pillar 3 CR4 / CR5, in both regimes.

Pipeline position:
    build_reporting_re_split_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why this exists. ``tests/integration/test_re_split_pipeline.py`` exercises the
splitter and stops at the results frame, asserting risk weights. Nothing carried
a split leg into a template — measured across the twelve registered golden runs,
the count of rows with a non-null ``split_parent_id`` is **zero** — so the
reporting surface of the split (which sheets it opens, which rows it lands on,
which columns carry it) had no coverage at all. Pillar 3 CR5 rows 9f / 9g exist
solely to report the Basel 3.1 split legs and were ``0.00`` in every one of
those runs.

What this file asserts, and why in that order:

1. **The fixture actually splits.** Row count, the exact ``re_split_role`` set,
   the non-null ``split_parent_id`` count, and every parent's fan-out against
   ``EXPECTED_LEGS_*``. Without this every assertion below could pass on a
   portfolio that had quietly stopped splitting — which is exactly how
   ``reporting_portfolio.py`` came to claim a loan-split it does not produce.
2. **The allocation is the rulepack's.** Each secured leg is checked against
   ``re_split_parameters`` — the same pack entries the engine reads — so the
   expected numbers cannot drift away from ``re_split_{rre,cre}_secured_ltv_cap``
   without this failing.
3. **The templates are EMITTED and the in-scope cells are NON-NULL**
   (``.claude/LESSONS.md`` B4: the dominant escape class here is absence, not
   wrongness), and each sheet / row carries exactly the legs the design table
   puts there.
4. **The regime divergence is pinned on the row that carries it** — the prior
   charge, which PS1/26 Art. 124F(2) deducts from the secured cap and CRR
   Art. 125 does not.

Deliberately NOT asserted here: portfolio-total gross conservation. That
identity is owned by ``tests/properties/test_source_conservation.py`` and
``tests/integration/test_re_split_carrier_conservation.py``; restating it would
add a third place to update and no new information. What this file adds is the
per-sheet and per-row placement those totals cannot see.

References:
- CRR Art. 124(1) / Art. 125 / Art. 126(2)(d): CRR loan-split and its CRE gate
- PRA PS1/26 Art. 124(4) / 124F / 124F(2) / 124H(1)-(3) / 124L
- COREP Annex II, C 07.00: one sheet per SA exposure class
- Pillar 3 CR4 rows 7 / 9 / 17; CR5 rows 9f / 9g (Basel 3.1 only)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.reporting_re_split_portfolio import (
    EXPECTED_LEGS_B31,
    EXPECTED_LEGS_CRR,
    EXPECTED_ROLES_B31,
    EXPECTED_ROLES_CRR,
    LN_CRE_CORP,
    LN_CRE_SME,
    LN_RRE_EXACT,
    LN_RRE_PRIOR,
    PRIOR_CHARGE_LTV,
    SECURED_SUFFIX,
    SPLIT_DESIGN,
    SPLIT_PARENTS_B31,
    SPLIT_PARENTS_CRR,
    TOTAL_DRAWN,
    VALUE_RRE_PRIOR,
    ExpectedLeg,
    build_reporting_re_split_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.stages.re_split.params import re_split_parameters
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle
from rwa_calc.reporting.pillar3.templates import B31_CR5_COLUMNS

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

_EXPECTED_LEGS: dict[str, dict[str, ExpectedLeg]] = {
    "crr": EXPECTED_LEGS_CRR,
    "b31": EXPECTED_LEGS_B31,
}
_EXPECTED_ROLES: dict[str, frozenset[str]] = {
    "crr": EXPECTED_ROLES_CRR,
    "b31": EXPECTED_ROLES_B31,
}
_SPLIT_PARENTS: dict[str, frozenset[str]] = {
    "crr": SPLIT_PARENTS_CRR,
    "b31": SPLIT_PARENTS_B31,
}

#: C 07.00 columns that MUST carry a value on the total row of every sheet this
#: portfolio populates. Chosen as the money spine of the template, not as
#: "whatever happens to be non-null": 0010 original exposure pre-conversion,
#: 0040 net of value adjustments, 0110 exposure after CRM substitution, 0200
#: exposure value, 0220 RWEA. The CCF-bucket columns (0160-0190) are correctly
#: absent — this portfolio is 100% on balance sheet and the conversion-factor
#: axis is ``reporting_offbs_portfolio.py``'s job.
_C07_MONEY_COLS: tuple[str, ...] = ("0010", "0040", "0110", "0200", "0220")

#: Pillar 3 CR4 columns that must carry a value on every populated class row.
#: Col b / col d are the off-balance-sheet pair and are legitimately 0.0 here.
_CR4_MONEY_COLS: tuple[str, ...] = ("a", "c", "e")

#: CR4 rows the portfolio populates. Row 7 is Corporates (the anchor plus every
#: residual leg), row 9 is Art. 112(1)(i) "secured by mortgages on immovable
#: property" (every secured / whole leg), row 17 is the Total.
_CR4_ROW_CORPORATES: str = "7"
_CR4_ROW_SECURED_BY_MORTGAGES: str = "9"
_CR4_ROW_TOTAL: str = "17"

#: The Basel 3.1 CR5 "of which" sub-rows that exist only to report split legs.
_CR5_SECURED_ROW: str = "9f"
_CR5_RESIDUAL_ROW: str = "9g"


def _config(regime_key: str) -> CalculationConfig:
    """SA configuration — loan-splitting is a Standardised Approach mechanism.

    Same reporting dates as the registered golden runs (``_sa_config`` in
    ``test_supervisory_validations.py``) so this portfolio can join ``RUNS``
    without introducing a second reference date into the estate.
    """
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


@lru_cache(maxsize=4)
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle, Pillar3TemplateBundle]:
    """Run the portfolio through one regime and generate both template sets.

    Memoised: template generation costs an order of magnitude more than the
    pipeline run, and every test below reads the same two runs.
    """
    framework = _REGIMES[regime_key]
    result = PipelineOrchestrator().run_with_data(
        build_reporting_re_split_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep, pillar3


def _total_row(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(pl.col("row_ref") == "0010")


def _cr_row(frame: pl.DataFrame, row_ref: str) -> dict[str, object]:
    matched = frame.filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"expected exactly one row {row_ref!r}, got {matched.height}"
    return matched.row(0, named=True)


def _expected_sheet_ead(regime_key: str) -> dict[str, float]:
    """Reporting class -> total ``ead_final`` the design table puts on it."""
    totals: dict[str, float] = {}
    for leg in _EXPECTED_LEGS[regime_key].values():
        totals[leg.reporting_class] = totals.get(leg.reporting_class, 0.0) + leg.ead
    return totals


def _secured_cap(regime_key: str, component: str, prior_charge_ltv: float) -> float:
    """The regime's effective secured-LTV cap, read from the RULEPACK.

    ``re_split_parameters`` resolves ``re_split_{rre,cre}_secured_ltv_cap`` from
    the pack — the same entry the splitter reads — so an expected number here
    cannot drift away from the engine's without one of the two failing. The
    prior-charge subtraction is applied only where the regime's own
    ``uses_prior_charge_reduction`` flag says it applies (PS1/26 Art. 124F(2);
    CRR Art. 125 has no equivalent).
    """
    params = re_split_parameters(is_basel_3_1=regime_key == "b31")[component]
    if not params.uses_prior_charge_reduction:
        return float(params.secured_ltv_cap)
    return max(0.0, float(params.secured_ltv_cap) - prior_charge_ltv)


class TestFixtureActuallySplits:
    """The guard every other assertion in this file rests on.

    A portfolio whose collateral lacks the property attestation columns reaches
    the splitter and is passed straight through, silently — which is what
    ``reporting_portfolio.py`` does today. If that ever happened here, the
    template assertions below would still pass on a smaller, unsplit book, so
    the split has to be proved first and by its own evidence.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_split_lineage_is_present(self, regime_key: str) -> None:
        results, _corep, _p3 = _run(regime_key)

        expected = _EXPECTED_LEGS[regime_key]
        parents = _SPLIT_PARENTS[regime_key]
        expected_lineage = sum(1 for leg in expected.values() if leg.role is not None)

        assert results.height == len(expected)
        assert int(results["split_parent_id"].is_not_null().sum()) == expected_lineage
        assert expected_lineage > 0, "no split lineage at all — the portfolio stopped splitting"
        assert len(parents) > 0

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_expected_role_is_emitted(self, regime_key: str) -> None:
        """Exact set, not a subset: a splitter that stops emitting one of the
        five roles must fail rather than silently narrow the test."""
        results, _corep, _p3 = _run(regime_key)

        roles = {value for value in results["re_split_role"].to_list() if value is not None}
        assert roles == set(_EXPECTED_ROLES[regime_key])

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_leg_matches_the_design_table(self, regime_key: str) -> None:
        """Role, risk-weighting class, reporting class and EAD, per emitted row."""
        results, _corep, _p3 = _run(regime_key)
        expected = _EXPECTED_LEGS[regime_key]

        actual = {
            row["exposure_reference"]: ExpectedLeg(
                row["re_split_role"],
                row["exposure_class"],
                row["reporting_class_origin"],
                float(row["ead_final"] or 0.0),
            )
            for row in results.iter_rows(named=True)
        }
        assert set(actual) == set(expected)
        for reference, want in expected.items():
            got = actual[reference]
            assert got.role == want.role, f"{regime_key}/{reference}: role"
            assert got.exposure_class == want.exposure_class, f"{regime_key}/{reference}: class"
            assert got.reporting_class == want.reporting_class, (
                f"{regime_key}/{reference}: reporting class"
            )
            assert got.ead == pytest.approx(want.ead), f"{regime_key}/{reference}: ead_final"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_each_parent_conserves_its_own_ead(self, regime_key: str) -> None:
        """Per-parent, not portfolio-total: the split allocates ``ead_final``,
        so every parent's children must sum back to its drawn balance. A
        portfolio total would net one parent's over-allocation against
        another's under-allocation."""
        results, _corep, _p3 = _run(regime_key)

        per_parent = (
            results.with_columns(
                pl.coalesce(pl.col("split_parent_id"), pl.col("exposure_reference")).alias("parent")
            )
            .group_by("parent")
            .agg(pl.col("ead_final").fill_null(0.0).sum().alias("child_ead"))
        )
        actual = {
            row["parent"]: float(row["child_ead"]) for row in per_parent.iter_rows(named=True)
        }
        assert set(actual) == set(SPLIT_DESIGN)
        for parent, (drawn, _rre, _cre, _prior) in SPLIT_DESIGN.items():
            assert actual[parent] == pytest.approx(drawn), f"{regime_key}/{parent}"


class TestAllocationComesFromTheRulepack:
    """Every secured leg sits at ``min(parent EAD share, cap x property value)``
    with the cap read from the rulepack, so a changed pack entry moves this test
    and the engine together instead of leaving a stale literal behind."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_no_secured_leg_exceeds_its_regulatory_cap(self, regime_key: str) -> None:
        _results, _corep, _p3 = _run(regime_key)
        expected = _EXPECTED_LEGS[regime_key]

        checked = 0
        for reference, leg in expected.items():
            # ``whole`` is NOT a capped secured leg: PS1/26 Art. 124H(3)
            # reclassifies the entire exposure and lets the SA calculator apply
            # max(floor, min(cp_rw, income-producing RW)) to all of it, so no
            # secured-LTV cap is involved. ``residual`` is the remainder the cap
            # left behind, so it has no cap of its own either.
            if leg.role not in ("secured", "secured_rre", "secured_cre"):
                continue
            parent = reference.rsplit("_", 1)[0]
            _drawn, rre_value, cre_value, prior = SPLIT_DESIGN[parent]
            is_residential = leg.exposure_class == "residential_mortgage"
            component = "residential" if is_residential else "commercial"
            component_value = rre_value if is_residential else cre_value
            cap = _secured_cap(regime_key, component, prior) * component_value
            assert leg.ead <= cap + 1e-6, f"{regime_key}/{reference} exceeds its {component} cap"
            checked += 1
        assert checked >= 4, "too few secured legs checked — the design table shrank"

    def test_prior_charge_binds_the_basel_31_cap_exactly(self) -> None:
        """PS1/26 Art. 124F(2): the secured cap is the ratio LESS prior charges,
        applied to raw property value."""
        cap = _secured_cap("b31", "residential", PRIOR_CHARGE_LTV)
        expected_secured = cap * VALUE_RRE_PRIOR

        leg = EXPECTED_LEGS_B31[LN_RRE_PRIOR + SECURED_SUFFIX]
        assert leg.ead == pytest.approx(expected_secured)


class TestRegimeDivergenceOnThePriorCharge:
    """The load-bearing row. CRR Art. 125 recognises no prior charge, PS1/26
    Art. 124F(2) deducts it — so one exposure splits at two different points and
    the difference is visible end-to-end, not just in the splitter."""

    def test_crr_ignores_the_prior_charge(self) -> None:
        results, _corep, _p3 = _run("crr")

        secured = results.filter(
            pl.col("exposure_reference").is_in(
                [LN_RRE_PRIOR + SECURED_SUFFIX, LN_RRE_EXACT + SECURED_SUFFIX]
            )
        )
        values = set(secured["ead_final"].to_list())
        assert len(values) == 1, (
            "CRR Art. 125 has no prior-charge deduction, so the encumbered and "
            f"unencumbered secured legs must be identical; got {values}"
        )

    def test_basel_31_shrinks_the_secured_leg_by_the_prior_charge(self) -> None:
        results, _corep, _p3 = _run("b31")

        by_ref = dict(
            zip(
                results["exposure_reference"].to_list(),
                results["ead_final"].to_list(),
                strict=True,
            )
        )
        unencumbered = float(by_ref[LN_RRE_EXACT + SECURED_SUFFIX])
        encumbered = float(by_ref[LN_RRE_PRIOR + SECURED_SUFFIX])
        assert encumbered == pytest.approx(unencumbered - PRIOR_CHARGE_LTV * VALUE_RRE_PRIOR)


class TestCorepC0700Surface:
    """C 07.00 is the SA template the split legs land on. One sheet per Art. 112
    class, so a split opens a ``residential_mortgage`` / ``commercial_mortgage``
    sheet the parent exposure never had."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_expected_sheet_is_emitted(self, regime_key: str) -> None:
        """B4(a): the sheet exists. An absent sheet is indistinguishable from a
        zero one on the error channel."""
        _results, corep, _p3 = _run(regime_key)

        assert set(corep.c07_00) >= set(_expected_sheet_ead(regime_key))

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_money_columns_are_non_null_on_every_populated_sheet(self, regime_key: str) -> None:
        """B4(b): the cells in scope carry a value where the portfolio has
        exposure. Asserted per sheet AND per column so a single dead column on
        one sheet cannot hide behind a populated sibling."""
        _results, corep, _p3 = _run(regime_key)

        for sheet in _expected_sheet_ead(regime_key):
            total = _total_row(corep.c07_00[sheet])
            assert total.height == 1, f"{regime_key}/{sheet}: no total row 0010"
            for ref in _C07_MONEY_COLS:
                assert ref in total.columns, f"{regime_key}/{sheet}: col {ref} missing"
                assert total[ref][0] is not None, f"{regime_key}/{sheet}: col {ref} is NULL"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_exposure_value_lands_on_the_sheet_the_split_sends_it_to(self, regime_key: str) -> None:
        """Col 0200 (exposure value) per sheet == the sum of the ``ead_final``
        the design table places on that sheet. This is the placement assertion a
        portfolio total cannot make: a secured leg filed on the corporate sheet
        would leave the total untouched."""
        _results, corep, _p3 = _run(regime_key)

        for sheet, expected in _expected_sheet_ead(regime_key).items():
            total = _total_row(corep.c07_00[sheet])
            assert total["0200"][0] == pytest.approx(expected), f"{regime_key}/{sheet} col 0200"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_rwea_is_non_zero_on_both_split_sides(self, regime_key: str) -> None:
        """A secured leg at a preferential weight and a residual leg at the
        counterparty weight must BOTH produce RWEA — a zero on either side means
        one half of the split stopped being risk-weighted (LESSONS C2)."""
        _results, corep, _p3 = _run(regime_key)

        for sheet in ("residential_mortgage", "corporate"):
            total = _total_row(corep.c07_00[sheet])
            assert float(total["0220"][0] or 0.0) > 0.0, f"{regime_key}/{sheet}: zero RWEA"


class TestPillar3Cr4Surface:
    """CR4 keys its rows on the Art. 112 disclosure classes, so the secured legs
    move from row 7 (Corporates) to row 9 (Secured by mortgages) while the
    residual legs stay on row 7. Both rows, and the Total, must carry them."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_cr4_is_emitted_with_its_money_columns_populated(self, regime_key: str) -> None:
        _results, _corep, pillar3 = _run(regime_key)

        assert pillar3.cr4 is not None, f"{regime_key}: CR4 not emitted"
        for row_ref in (_CR4_ROW_CORPORATES, _CR4_ROW_SECURED_BY_MORTGAGES, _CR4_ROW_TOTAL):
            row = _cr_row(pillar3.cr4, row_ref)
            for column in _CR4_MONEY_COLS:
                assert row[column] is not None, f"{regime_key}: CR4 row {row_ref} col {column}"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_secured_legs_reach_the_immovable_property_row(self, regime_key: str) -> None:
        """Row 9 col c == the post-CRM exposure of every leg the design table
        puts in a real-estate reporting class."""
        _results, _corep, pillar3 = _run(regime_key)

        sheet_ead = _expected_sheet_ead(regime_key)
        expected = sum(
            value
            for cls, value in sheet_ead.items()
            if cls in ("residential_mortgage", "commercial_mortgage", "retail_mortgage")
        )
        assert expected > 0.0, "the design table places nothing in a real-estate class"

        row = _cr_row(pillar3.cr4, _CR4_ROW_SECURED_BY_MORTGAGES)
        assert row["c"] == pytest.approx(expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_residual_legs_stay_on_the_corporate_row(self, regime_key: str) -> None:
        """Art. 124(1) third paragraph / PS1/26 Art. 124L: the uncollateralised
        remainder keeps the counterparty class, so it must NOT follow the
        secured leg onto row 9."""
        _results, _corep, pillar3 = _run(regime_key)

        sheet_ead = _expected_sheet_ead(regime_key)
        expected = sum(
            value for cls, value in sheet_ead.items() if cls in ("corporate", "corporate_sme")
        )
        row = _cr_row(pillar3.cr4, _CR4_ROW_CORPORATES)
        assert row["c"] == pytest.approx(expected)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_cr4_total_row_carries_the_whole_book(self, regime_key: str) -> None:
        """Row 17 col a is the pre-conversion-factor gross. The portfolio is
        100% on balance sheet and fully drawn, so it is the book value — the
        one CR4 cell a per-leg gross-carrier error is visible in."""
        _results, _corep, pillar3 = _run(regime_key)

        row = _cr_row(pillar3.cr4, _CR4_ROW_TOTAL)
        assert row["a"] == pytest.approx(TOTAL_DRAWN)


class TestPillar3Cr5SplitRows:
    """CR5 rows 9f / 9g exist for nothing but the Basel 3.1 split legs, and were
    ``0.00`` in all twelve registered golden runs before this portfolio. They are
    the clearest measure of whether split output reaches a disclosure at all."""

    def test_split_rows_are_absent_under_crr(self) -> None:
        """The sub-rows are a PS1/26 disclosure; the CRR CR5 layout has no such
        row. Asserted so a future layout change that added them under CRR is a
        visible decision rather than a silent one."""
        _results, _corep, pillar3 = _run("crr")

        assert pillar3.cr5 is not None
        refs = set(pillar3.cr5["row_ref"].to_list())
        assert _CR5_SECURED_ROW not in refs
        assert _CR5_RESIDUAL_ROW not in refs

    def test_split_rows_are_emitted_and_non_zero_under_basel_31(self) -> None:
        _results, _corep, pillar3 = _run("b31")

        assert pillar3.cr5 is not None
        total_column = _cr5_total_column()
        for row_ref in (_CR5_SECURED_ROW, _CR5_RESIDUAL_ROW):
            row = _cr_row(pillar3.cr5, row_ref)
            assert row[total_column] is not None, f"CR5 row {row_ref} Total is NULL"
            assert float(row[total_column]) > 0.0, (
                f"CR5 row {row_ref} Total is zero — the row is dead again"
            )

    def test_split_rows_report_the_legs_they_name(self) -> None:
        """Row 9f is "of which: secured up to 55% LTV" and row 9g the residual,
        so each Total must equal the sum of the design table's legs carrying
        that exact ``re_split_role``."""
        _results, _corep, pillar3 = _run("b31")

        total_column = _cr5_total_column()
        for row_ref, role in ((_CR5_SECURED_ROW, "secured"), (_CR5_RESIDUAL_ROW, "residual")):
            expected = sum(leg.ead for leg in EXPECTED_LEGS_B31.values() if leg.role == role)
            row = _cr_row(pillar3.cr5, row_ref)
            assert float(row[total_column]) == pytest.approx(expected), (
                f"CR5 row {row_ref} ({role})"
            )


class TestKnownEngineGaps:
    """Two measured limitations, pinned as strict xfails so the day either is
    fixed this file fails loudly and the expectation is updated deliberately —
    rather than the gap quietly persisting behind a green suite."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "CRR Art. 126(2)(d) is unreachable end-to-end: rental_to_interest_ratio "
            "is on COLLATERAL_SCHEMA but on no edge contract, so HIERARCHY_EXIT_EDGE "
            "strips it before the classifier and flagging.py takes its conservative "
            "pl.lit(False) branch. Engine change required — do not fix here."
        ),
    )
    def test_crr_commercial_collateral_splits_when_rental_coverage_is_attested(self) -> None:
        results, _corep, _p3 = _run("crr")

        legs = results.filter(pl.col("split_parent_id").is_in([LN_CRE_SME, LN_CRE_CORP]))
        assert legs.height > 0

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Pillar 3 CR5 row 9f is defined with re_split_roles=('secured',) only, so "
            "the mixed-collateral secured legs (secured_rre / secured_cre, PS1/26 "
            "Art. 124(4)) are excluded from the 'of which: secured up to 55% LTV' "
            "sub-row even though they ARE secured split legs. Reporting change "
            "required — do not fix here."
        ),
    )
    def test_cr5_secured_row_includes_mixed_collateral_secured_legs(self) -> None:
        _results, _corep, pillar3 = _run("b31")

        expected = sum(
            leg.ead
            for leg in EXPECTED_LEGS_B31.values()
            if leg.role in ("secured", "secured_rre", "secured_cre")
        )
        row = _cr_row(pillar3.cr5, _CR5_SECURED_ROW)
        assert float(row[_cr5_total_column()]) == pytest.approx(expected)


def _cr5_total_column() -> str:
    """The CR5 "Total" column ref, resolved from the template definition.

    Read from ``B31_CR5_COLUMNS`` rather than hardcoded: the CR5 column letters
    are GENERATED from the risk-weight bucket list, so adding one bucket shifts
    every trailing ref. A literal would silently start reading a risk-weight
    bucket (LESSONS B3 — anchor to a source of truth that cannot drift).
    """
    for column in B31_CR5_COLUMNS:
        if column.name == "Total":
            return column.ref
    raise AssertionError("B31_CR5_COLUMNS has no column named 'Total'")
