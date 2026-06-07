"""Unit tests for the parallel-run ReconciliationRunner.

Covers per-component bucketing (exact / within-tolerance / break), categorical
normalisation + value_map, unmatched rows (missing_left/right), the summary and
tie-out frames, the break worklist, composite keys, and the non-fatal data-quality
warnings (REC001 missing column, REC002 duplicate legacy key, REC003 missing key).
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.config import ComponentMapping, LegacyColumnMapping
from rwa_calc.contracts.errors import (
    ERROR_RECON_DUPLICATE_LEGACY_KEY,
    ERROR_RECON_KEY_COLUMN_MISSING,
    ERROR_RECON_LEGACY_COLUMN_MISSING,
)
from rwa_calc.contracts.protocols import ReconciliationRunnerProtocol
from rwa_calc.engine.reconciliation import (
    BUCKET_BREAK,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
    BUCKET_WITHIN,
    ReconciliationRunner,
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


class TestDataQualityWarnings:
    def test_duplicate_legacy_key_warns_and_no_fanout(self) -> None:
        # Arrange: L1 appears twice in the legacy file.
        legacy = pl.LazyFrame(
            {"loan_id": ["L1", "L1", "L2", "L3"], "legacy_rwa": [50.0, 51.0, 150.0, 250.0]}
        )

        # Act
        bundle = _recon(_ours(), legacy, _mapping())
        df = bundle.component_reconciliation.collect()

        # Assert: REC002 raised; join stays 1:1 (no row multiplication).
        assert any(e.code == ERROR_RECON_DUPLICATE_LEGACY_KEY for e in bundle.errors)
        assert df.height == 3

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
        # Arrange: map pd, but our frame has no irb_pd_floored/irb_pd column.
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
