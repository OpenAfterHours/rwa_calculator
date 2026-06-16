"""
M3.x acceptance: the generalised labelled two-run comparison (Phase 6 S3).

The dual-framework runner is no longer hard-wired to CRR-vs-Basel-3.1: it compares
any two labelled, rulepack-identified runs. This unlocks reversed-regime,
election-vs-election and regime-vs-amended comparisons (the last via a
``RunSpec.rulepack`` overlay built with ``ResolvedRulepack.with_overrides``) that
the old config-pair gate (``crr_config`` first, ``b31_config`` second) rejected.

These scenarios assert the comparisons the old gate could NOT express now run and
carry their run labels as column suffixes.
"""

from __future__ import annotations

import pytest

from rwa_calc.analysis.comparison import DualFrameworkRunner, RunSpec
from rwa_calc.contracts.bundles import AggregatedResultBundle, ComparisonBundle


class TestLabelledTwoRun:
    """Comparisons the old CRR-vs-B31 framework-pair gate could not express."""

    def test_reversed_regime_pairing(self, raw_data_bundle, crr_sa_config, b31_sa_config):
        """B31-as-baseline / CRR-as-variant now works (the old gate raised)."""
        bundle = DualFrameworkRunner().compare(raw_data_bundle, b31_sa_config, crr_sa_config)

        assert isinstance(bundle, ComparisonBundle)
        assert bundle.baseline_label == "b31"
        assert bundle.variant_label == "crr"
        assert isinstance(bundle.baseline_results, AggregatedResultBundle)

        deltas = bundle.exposure_deltas.collect()
        # Numeric columns carry the run labels as suffixes (b31 = baseline, crr = variant).
        assert "rwa_final_b31" in deltas.columns
        assert "rwa_final_crr" in deltas.columns
        assert deltas.height > 0

    def test_same_regime_distinct_labels(self, raw_data_bundle, b31_sa_config):
        """Two runs of one regime (distinct labels) compare; self-comparison = zero delta."""
        bundle = DualFrameworkRunner().compare(
            raw_data_bundle,
            RunSpec(b31_sa_config, "base"),
            RunSpec(b31_sa_config, "variant"),
        )

        assert bundle.baseline_label == "base"
        assert bundle.variant_label == "variant"

        deltas = bundle.exposure_deltas.collect()
        assert "rwa_final_base" in deltas.columns
        assert "rwa_final_variant" in deltas.columns
        # Identical config on both sides -> every per-exposure delta is zero.
        assert deltas["delta_rwa"].abs().max() < 1e-9

    def test_same_label_rejected(self, raw_data_bundle, b31_sa_config):
        """Two runs that resolve to the same label are rejected (distinct labels required)."""
        with pytest.raises(ValueError, match="labels must differ"):
            DualFrameworkRunner().compare(raw_data_bundle, b31_sa_config, b31_sa_config)
