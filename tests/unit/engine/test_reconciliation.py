"""Unit tests for the parallel-run ReconciliationRunner.

Covers per-component bucketing (exact / within-tolerance / break), categorical
normalisation + value_map, unmatched rows (missing_left/right), the summary and
tie-out frames, the break worklist, composite keys, and the non-fatal data-quality
warnings (REC001 missing column, REC002 duplicate legacy key, REC003 missing key).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.analysis.reconciliation import (
    BUCKET_BREAK,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
    BUCKET_WITHIN,
    ReconciliationRunner,
    ReconciliationRunnerProtocol,
)
from rwa_calc.contracts.errors import (
    ERROR_RECON_DUPLICATE_LEGACY_KEY,
    ERROR_RECON_GRAIN_HETEROGENEOUS,
    ERROR_RECON_KEY_COLUMN_MISSING,
    ERROR_RECON_LEGACY_COLUMN_MISSING,
    ERROR_RECON_NO_KEY_OVERLAP,
    ERROR_RECON_NON_FINITE_VALUE,
)


def _ours() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2", "L3"],
            "exposure_class": ["corporate", "retail", "corporate"],
            "approach_applied": ["SA", "SA", "SA"],
            "ead_final": [100.0, 200.0, 500.0],
            "rwa_final": [50.0, 150.0, 250.0],
            "risk_weight": [0.50, 0.75, 0.50],
        }
    )


def _ours_irb() -> pl.LazyFrame:
    """IRB-shaped results carrying the engine's REAL per-exposure output column
    names (pd_floored / lgd_floored / guaranteed_portion), as written to the
    parquet that ``scan_results()`` scans — not the fictional irb_-prefixed
    CALCULATION_OUTPUT_SCHEMA names."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2"],
            "exposure_class": ["corporate", "corporate"],
            "approach_applied": ["AIRB", "AIRB"],
            "ead_final": [100.0, 200.0],
            "rwa_final": [80.0, 160.0],
            "pd_floored": [0.012, 0.030],
            "lgd_floored": [0.45, 0.45],
            "guaranteed_portion": [25.0, 0.0],
        }
    )


def _legacy() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "loan_id": ["L1", "L2", "L3"],
            "legacy_rwa": [50.0, 150.3, 300.0],  # L1 exact, L2 +0.2% within, L3 +20% break
        }
    )


def _mapping(**overrides: ComponentMapping) -> LegacyColumnMapping:
    components: dict[str, ComponentMapping] = {"rwa": ComponentMapping("legacy_rwa")}
    components.update(overrides)
    return LegacyColumnMapping(
        legacy_keys=("loan_id",),
        our_keys=("exposure_reference",),
        components=components,
    )


def _recon(ours: pl.LazyFrame, legacy: pl.LazyFrame, mapping: LegacyColumnMapping):
    return ReconciliationRunner().reconcile(ours, legacy, mapping)


def _bucket_for(recon_df: pl.DataFrame, key: str, col: str = "row_bucket") -> str:
    return recon_df.filter(pl.col("_recon_key") == key).row(0, named=True)[col]


class TestProtocol:
    def test_runner_satisfies_protocol(self) -> None:
        assert isinstance(ReconciliationRunner(), ReconciliationRunnerProtocol)


class TestNumericBucketing:
    def test_exact_within_break_buckets(self) -> None:
        # Arrange / Act
        bundle = _recon(_ours(), _legacy(), _mapping())
        df = bundle.component_reconciliation.collect()

        # Assert: 1% relative tolerance on rwa.
        assert _bucket_for(df, "L1", "rwa_bucket") == BUCKET_EXACT
        assert _bucket_for(df, "L2", "rwa_bucket") == BUCKET_WITHIN
        assert _bucket_for(df, "L3", "rwa_bucket") == BUCKET_BREAK

    def test_tolerance_override_tightens_match(self) -> None:
        # Arrange: override rwa tolerance to a tiny absolute value.
        mapping = LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components={"rwa": ComponentMapping("legacy_rwa", tol_kind="abs", tol=0.001)},
        )

        # Act
        df = _recon(_ours(), _legacy(), mapping).component_reconciliation.collect()

        # Assert: L2 (+0.3 abs) now breaks under the tight absolute tolerance.
        assert _bucket_for(df, "L2", "rwa_bucket") == BUCKET_BREAK

    def test_abs_delta_and_rel_delta_computed(self) -> None:
        df = _recon(_ours(), _legacy(), _mapping()).component_reconciliation.collect()
        l3 = df.filter(pl.col("_recon_key") == "L3").row(0, named=True)
        assert l3["abs_delta_rwa"] == pytest.approx(250.0 - 300.0)
        assert l3["rel_delta_rwa"] == pytest.approx((250.0 - 300.0) / 300.0)


class TestCategoricalBucketing:
    def test_value_map_and_normalisation(self) -> None:
        # Arrange: legacy uses upper-case synonyms; ours is canonical lower-case.
        legacy = pl.LazyFrame(
            {
                "loan_id": ["L1", "L2", "L3"],
                "legacy_rwa": [50.0, 150.0, 250.0],
                "legacy_exposure_class": ["CORP", " Retail ", "RETAIL"],
            }
        )
        mapping = _mapping(
            exposure_class=ComponentMapping(
                "legacy_exposure_class", value_map={"CORP": "corporate", "RETAIL": "retail"}
            )
        )

        # Act
        df = _recon(_ours(), legacy, mapping).component_reconciliation.collect()

        # Assert: L1 CORP->corporate matches; L2 " Retail " normalises to retail;
        # L3 legacy retail vs ours corporate -> break.
        assert _bucket_for(df, "L1", "exposure_class_bucket") == BUCKET_EXACT
        assert _bucket_for(df, "L2", "exposure_class_bucket") == BUCKET_EXACT
        assert _bucket_for(df, "L3", "exposure_class_bucket") == BUCKET_BREAK


class TestUnmatched:
    def test_missing_left_and_right(self) -> None:
        # Arrange: L3 only in ours, L9 only in legacy.
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L3"],
                "exposure_class": ["corporate", "corporate"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [100.0, 500.0],
                "rwa_final": [50.0, 250.0],
                "risk_weight": [0.50, 0.50],
            }
        )
        legacy = pl.LazyFrame({"loan_id": ["L1", "L9"], "legacy_rwa": [50.0, 99.0]})

        # Act
        df = _recon(ours, legacy, _mapping()).component_reconciliation.collect()

        # Assert
        assert _bucket_for(df, "L3") == BUCKET_MISSING_RIGHT
        assert _bucket_for(df, "L9") == BUCKET_MISSING_LEFT

    def test_summary_by_bucket_counts(self) -> None:
        bundle = _recon(_ours(), _legacy(), _mapping())
        counts = {
            r["row_bucket"]: r["count"] for r in bundle.summary_by_bucket.collect().to_dicts()
        }
        # L1 exact, L2 within, L3 break.
        assert counts.get(BUCKET_EXACT) == 1
        assert counts.get(BUCKET_WITHIN) == 1
        assert counts.get(BUCKET_BREAK) == 1


class TestSummaries:
    def test_summary_by_component_break_rate(self) -> None:
        df = _recon(_ours(), _legacy(), _mapping()).summary_by_component.collect()
        rwa = df.filter(pl.col("component") == "rwa").row(0, named=True)
        assert rwa["n_exact_match"] == 1
        assert rwa["n_within_tolerance"] == 1
        assert rwa["n_break"] == 1
        assert rwa["break_rate"] == pytest.approx(1 / 3)
        assert rwa["sum_abs_delta"] == pytest.approx(0.3 + 50.0)

    def test_totals_tie_out(self) -> None:
        df = _recon(_ours(), _legacy(), _mapping()).totals_tie_out.collect()
        rwa = df.filter(pl.col("component") == "rwa").row(0, named=True)
        assert rwa["our_total"] == pytest.approx(450.0)
        assert rwa["legacy_total"] == pytest.approx(500.3)
        assert rwa["delta"] == pytest.approx(-50.3)

    def test_breaks_detail_sorted_by_materiality(self) -> None:
        df = _recon(_ours(), _legacy(), _mapping()).breaks_detail.collect()
        # Only L3 rwa breaks; it is the single, largest break.
        assert df.height == 1
        top = df.row(0, named=True)
        assert top["component"] == "rwa"
        assert top["_recon_key"] == "L3"
        assert top["abs_delta"] == pytest.approx(-50.0)

    def test_summary_by_exposure_class(self) -> None:
        df = _recon(_ours(), _legacy(), _mapping()).summary_by_exposure_class.collect()
        corp = df.filter(pl.col("our_exposure_class") == "corporate").row(0, named=True)
        # corporate = L1 (exact) + L3 (break)
        assert corp["n_total"] == 2
        assert corp["n_break"] == 1


class TestClassAllocation:
    def _legacy_with_class(self) -> pl.LazyFrame:
        # Legacy reports a class + EAD/RWA per line; CORP/RETAIL synonyms. Columns
        # already carry the loader's canonical ``legacy_<component>`` names.
        return pl.LazyFrame(
            {
                "loan_id": ["L1", "L2", "L3"],
                "legacy_ead": [100.0, 200.0, 480.0],
                "legacy_rwa": [50.0, 150.0, 240.0],
                "legacy_exposure_class": ["CORP", "RETAIL", "CORP"],
            }
        )

    def _alloc_mapping(self) -> LegacyColumnMapping:
        return LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components={
                "ead": ComponentMapping("legacy_ead"),
                "rwa": ComponentMapping("legacy_rwa"),
                "exposure_class": ComponentMapping(
                    "legacy_exposure_class", value_map={"CORP": "corporate", "RETAIL": "retail"}
                ),
            },
        )

    def test_class_allocation_sums_per_class_with_value_map(self) -> None:
        # Act
        alloc = _recon(_ours(), self._legacy_with_class(), self._alloc_mapping()).class_allocation
        df = alloc.collect()

        # Assert: corporate = L1 + L3 on each side; value_map applied to legacy.
        corp = df.filter(pl.col("exposure_class") == "corporate").row(0, named=True)
        assert corp["our_ead"] == pytest.approx(600.0)  # 100 + 500
        assert corp["our_rwa"] == pytest.approx(300.0)  # 50 + 250
        assert corp["legacy_ead"] == pytest.approx(580.0)  # 100 + 480
        assert corp["legacy_rwa"] == pytest.approx(290.0)  # 50 + 240
        assert corp["delta_ead"] == pytest.approx(20.0)
        assert corp["delta_rwa"] == pytest.approx(10.0)

    def test_class_allocation_flags_class_present_one_side_only(self) -> None:
        # Arrange: ours classifies L3 as residential_mortgage; legacy still corporate.
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2", "L3"],
                "exposure_class": ["corporate", "retail", "residential_mortgage"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [100.0, 200.0, 500.0],
                "rwa_final": [50.0, 150.0, 175.0],
                "risk_weight": [0.50, 0.75, 0.35],
            }
        )

        # Act
        df = _recon(
            ours, self._legacy_with_class(), self._alloc_mapping()
        ).class_allocation.collect()

        # Assert: residential_mortgage is ours-only -> legacy side 0, full delta.
        rre = df.filter(pl.col("exposure_class") == "residential_mortgage").row(0, named=True)
        assert rre["our_ead"] == pytest.approx(500.0)
        assert rre["legacy_ead"] == pytest.approx(0.0)
        assert rre["delta_ead"] == pytest.approx(500.0)

    def test_class_allocation_empty_when_class_unmapped(self) -> None:
        # No exposure_class component mapped -> stable empty allocation frame.
        df = _recon(_ours(), _legacy(), _mapping()).class_allocation.collect()
        assert df.height == 0
        assert "exposure_class" in df.columns
        assert "delta_rwa" in df.columns


class TestCompositeKey:
    def test_reconciles_on_composite_key(self) -> None:
        # Arrange: join on counterparty + book.
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2"],
                "counterparty_reference": ["C1", "C2"],
                "book_code": ["B1", "B1"],
                "exposure_class": ["corporate", "retail"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [100.0, 200.0],
                "rwa_final": [50.0, 150.0],
                "risk_weight": [0.50, 0.75],
            }
        )
        legacy = pl.LazyFrame(
            {
                "cpty": ["C1", "C2"],
                "book": ["B1", "B1"],
                "legacy_rwa": [50.0, 150.0],
            }
        )
        mapping = LegacyColumnMapping(
            legacy_keys=("cpty", "book"),
            our_keys=("counterparty_reference", "book_code"),
            components={"rwa": ComponentMapping("legacy_rwa")},
        )

        # Act
        df = _recon(ours, legacy, mapping).component_reconciliation.collect()

        # Assert: both rows match exactly on the composite key.
        assert df.height == 2
        assert set(df["row_bucket"]) == {BUCKET_EXACT}


class TestExposureClassGrain:
    """Per-(exposure x class) reconciliation: a value-mapped class join key so a
    split exposure matches line-for-line and a moved class shows as missing."""

    def _mapping(self) -> LegacyColumnMapping:
        return LegacyColumnMapping(
            legacy_keys=("obligor_id", "legacy_exposure_class"),
            our_keys=("exposure_reference", "exposure_class"),
            components={
                "ead": ComponentMapping("legacy_ead"),
                "rwa": ComponentMapping("legacy_rwa"),
                "exposure_class": ComponentMapping(
                    "legacy_exposure_class",
                    value_map={"RRE": "residential_mortgage", "CORP": "corporate"},
                ),
            },
        )

    def test_reconciles_split_exposure_per_class(self) -> None:
        # Arrange: L1 is split across two classes (collateralised RRE + residual
        # corporate); both sides agree line-for-line (legacy uses RRE/CORP synonyms).
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L1", "L2"],
                "exposure_class": ["residential_mortgage", "corporate", "corporate"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [300.0, 700.0, 200.0],
                "rwa_final": [105.0, 560.0, 150.0],
                "risk_weight": [0.35, 0.80, 0.75],
            }
        )
        legacy = pl.LazyFrame(
            {
                "obligor_id": ["L1", "L1", "L2"],
                "legacy_exposure_class": ["RRE", "CORP", "CORP"],
                "legacy_ead": [300.0, 700.0, 200.0],
                "legacy_rwa": [105.0, 560.0, 150.0],
            }
        )

        # Act
        df = _recon(ours, legacy, self._mapping()).component_reconciliation.collect()

        # Assert: each (exposure, class) line matches via the value-mapped class key.
        assert df.height == 3
        assert set(df["row_bucket"]) == {BUCKET_EXACT}

    def test_moved_class_shows_as_missing_on_each_side(self) -> None:
        # Arrange: ours keeps L1 entirely corporate; legacy moved it to RRE.
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1000.0],
                "rwa_final": [800.0],
                "risk_weight": [0.80],
            }
        )
        legacy = pl.LazyFrame(
            {
                "obligor_id": ["L1"],
                "legacy_exposure_class": ["RRE"],
                "legacy_ead": [1000.0],
                "legacy_rwa": [350.0],
            }
        )

        # Act
        df = _recon(ours, legacy, self._mapping()).component_reconciliation.collect()

        # Assert: L1||corporate is ours-only; L1||residential_mortgage is legacy-only.
        assert df.height == 2
        assert set(df["row_bucket"]) == {BUCKET_MISSING_LEFT, BUCKET_MISSING_RIGHT}


class TestDataQualityWarnings:
    def test_duplicate_legacy_key_aggregates_not_drops(self) -> None:
        # Arrange: L1 appears twice in the legacy file (e.g. one exposure split
        # across two lines — a collateralised portion and the residual).
        legacy = pl.LazyFrame(
            {"loan_id": ["L1", "L1", "L2", "L3"], "legacy_rwa": [50.0, 51.0, 150.0, 250.0]}
        )

        # Act
        bundle = _recon(_ours(), legacy, _mapping())
        df = bundle.component_reconciliation.collect()

        # Assert: REC002 raised (informational); the duplicate legacy rows are
        # SUMMED to the key grain, not dropped — symmetric with our side.
        assert any(e.code == ERROR_RECON_DUPLICATE_LEGACY_KEY for e in bundle.errors)
        assert df.height == 3  # one row per key (L1 aggregated, L2, L3)
        l1 = df.filter(pl.col("_recon_key") == "L1").row(0, named=True)
        assert l1["legacy_rwa"] == pytest.approx(101.0)  # 50 + 51, not first-row 50

    def test_duplicate_legacy_key_ties_out_on_summed_total(self) -> None:
        # Arrange: L1 split across two lines summing to 101.
        legacy = pl.LazyFrame(
            {"loan_id": ["L1", "L1", "L2", "L3"], "legacy_rwa": [50.0, 51.0, 150.0, 250.0]}
        )

        # Act
        tie = _recon(_ours(), legacy, _mapping()).totals_tie_out.collect()

        # Assert: legacy total includes both L1 lines (101 + 150 + 250 = 501).
        rwa = tie.filter(pl.col("component") == "rwa").row(0, named=True)
        assert rwa["legacy_total"] == pytest.approx(501.0)

    def test_duplicate_legacy_rows_disagree_on_class_warns_rec004(self) -> None:
        # Arrange: L1 is split across two risk classes in the legacy file — the
        # collateralised portion landed in a different class to the residual.
        legacy = pl.LazyFrame(
            {
                "loan_id": ["L1", "L1", "L2", "L3"],
                "legacy_rwa": [20.0, 30.0, 150.0, 250.0],
                "legacy_exposure_class": [
                    "corporate",
                    "residential_mortgage",
                    "retail",
                    "corporate",
                ],
            }
        )
        mapping = _mapping(exposure_class=ComponentMapping("legacy_exposure_class"))

        # Act
        bundle = _recon(_ours(), legacy, mapping)

        # Assert: REC004 surfaces that a legacy key aggregated mixed classes.
        assert any(e.code == ERROR_RECON_GRAIN_HETEROGENEOUS for e in bundle.errors)

    def test_missing_legacy_column_skips_component(self) -> None:
        # Arrange: map ead but the legacy frame has no legacy_ead column.
        mapping = _mapping(ead=ComponentMapping("legacy_ead"))

        # Act
        bundle = _recon(_ours(), _legacy(), mapping)

        # Assert: REC001 warning; ead skipped, rwa still reconciled.
        assert any(e.code == ERROR_RECON_LEGACY_COLUMN_MISSING for e in bundle.errors)
        components = set(bundle.summary_by_component.collect()["component"])
        assert "ead" not in components
        assert "rwa" in components

    def test_missing_our_column_skips_component(self) -> None:
        # Arrange: map pd, but the SA-shaped _ours() frame carries no pd column
        # under any name (neither the floored pd_floored nor the raw pd).
        legacy = pl.LazyFrame(
            {
                "loan_id": ["L1", "L2", "L3"],
                "legacy_rwa": [50.0, 150.0, 250.0],
                "legacy_pd": [0.01, 0.02, 0.03],
            }
        )
        mapping = _mapping(pd=ComponentMapping("legacy_pd"))

        # Act
        bundle = _recon(_ours(), legacy, mapping)

        # Assert
        assert any(e.code == ERROR_RECON_LEGACY_COLUMN_MISSING for e in bundle.errors)
        assert "pd" not in set(bundle.summary_by_component.collect()["component"])

    def test_irb_pd_lgd_guarantee_resolve_against_real_output_names(self) -> None:
        # Regression guard for the REC001 "no column for component 'lgd'" bug: the
        # registry must resolve pd/lgd/guarantee against the engine's REAL output
        # names (pd_floored / lgd_floored / guaranteed_portion), NOT the fictional
        # irb_-prefixed CALCULATION_OUTPUT_SCHEMA names the engine never emits.
        legacy = pl.LazyFrame(
            {
                "loan_id": ["L1", "L2"],
                "legacy_rwa": [80.0, 160.0],
                "legacy_pd": [0.012, 0.030],
                "legacy_lgd": [0.45, 0.45],
                "legacy_guarantee": [25.0, 0.0],
            }
        )
        mapping = LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components={
                "rwa": ComponentMapping("legacy_rwa"),
                "pd": ComponentMapping("legacy_pd"),
                "lgd": ComponentMapping("legacy_lgd"),
                "guarantee": ComponentMapping("legacy_guarantee"),
            },
        )

        # Act
        bundle = _recon(_ours_irb(), legacy, mapping)

        # Assert: none are skipped (no REC001) and each reconciles exactly.
        assert not any(e.code == ERROR_RECON_LEGACY_COLUMN_MISSING for e in bundle.errors)
        components = set(bundle.summary_by_component.collect()["component"])
        assert {"pd", "lgd", "guarantee"} <= components
        df = bundle.component_reconciliation.collect()
        assert _bucket_for(df, "L1", "pd_bucket") == BUCKET_EXACT
        assert _bucket_for(df, "L1", "lgd_bucket") == BUCKET_EXACT
        assert _bucket_for(df, "L1", "guarantee_bucket") == BUCKET_EXACT

    def test_missing_composite_key_returns_empty_bundle(self) -> None:
        # Arrange: our_keys references a column not on our frame.
        mapping = LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("nonexistent",),
            components={"rwa": ComponentMapping("legacy_rwa")},
        )

        # Act
        bundle = _recon(_ours(), _legacy(), mapping)

        # Assert: REC003 + empty reconciliation.
        assert any(e.code == ERROR_RECON_KEY_COLUMN_MISSING for e in bundle.errors)
        assert bundle.component_reconciliation.collect().height == 0

    def test_zero_key_overlap_warns_rec005(self) -> None:
        # Arrange: legacy ids share NO values with our exposure_reference (the
        # classic "legacy feeds through, ours blank" key-mapping mistake).
        legacy = pl.LazyFrame({"loan_id": ["X1", "X2", "X3"], "legacy_rwa": [50.0, 150.0, 250.0]})

        # Act
        bundle = _recon(_ours(), legacy, _mapping())

        # Assert: REC005 surfaces that nothing joined, instead of a silent
        # all-one-sided report with an empty errors list.
        assert any(e.code == ERROR_RECON_NO_KEY_OVERLAP for e in bundle.errors)

    def test_matching_keys_do_not_warn_rec005(self) -> None:
        # Arrange / Act: keys align (L1..L3 on both sides).
        bundle = _recon(_ours(), _legacy(), _mapping())

        # Assert: no spurious zero-overlap warning on the happy path.
        assert not any(e.code == ERROR_RECON_NO_KEY_OVERLAP for e in bundle.errors)

    def test_non_finite_our_value_warns_rec006(self) -> None:
        # Arrange: one matched exposure carries a NaN rwa_final (e.g. an IRB
        # maturity-adjustment blow-up upstream). A single NaN poisons the total.
        ours = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2", "L3"],
                "exposure_class": ["corporate", "retail", "corporate"],
                "approach_applied": ["AIRB", "AIRB", "AIRB"],
                "ead_final": [100.0, 200.0, 500.0],
                "rwa_final": [50.0, float("nan"), 250.0],
                "risk_weight": [0.50, 0.75, 0.50],
            }
        )

        # Act
        bundle = _recon(ours, _legacy(), _mapping())

        # Assert: REC006 names the affected component so the analyst looks
        # upstream rather than at the mapping.
        nf = [e for e in bundle.errors if e.code == ERROR_RECON_NON_FINITE_VALUE]
        assert nf
        assert "rwa" in (nf[0].actual_value or "")

    def test_finite_our_values_do_not_warn_rec006(self) -> None:
        # Arrange / Act: all our values finite.
        bundle = _recon(_ours(), _legacy(), _mapping())

        # Assert: no spurious non-finite warning.
        assert not any(e.code == ERROR_RECON_NON_FINITE_VALUE for e in bundle.errors)
