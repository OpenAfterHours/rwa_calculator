"""Unit tests for the legacy reporting-ledger projection retained on reconcile().

``CreditRiskCalc.reconcile()`` already loads the firm's extract and hands it to
the reconciliation runner; the runner consumes it into a join and nothing keeps
it, so there is no way to generate the firm's side of a return afterwards. The
seam under test projects that extract ONCE into the sealed reporting-ledger
vocabulary (``analysis.legacy_ledger.project_legacy_ledger``) and carries the
result on the response. It must:

- carry a ``LegacyLedgerSource`` on our run's framework, plus its
  ``LedgerCoverage``, whenever the mapping reaches at least one scoped template;
- keep succeeding on a thin mapping, with the coverage naming what is
  unreachable and the reconciliation itself untouched;
- degrade to ``None`` + a non-blocking warning when the projection raises or the
  mapping reaches no template at all — a firm whose extract cannot produce
  templates still gets its exposure-grain reconciliation;
- stay lazy: generating a template is the caller's job, later, so nothing
  collects the projection on the request thread.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import polars as pl
import pytest
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

from rwa_calc.analysis.legacy_ledger import LEDGER_TEMPLATE_IDS, LEDGER_VOCABULARY
from rwa_calc.analysis.recon_registry import ComponentMapping, LegacyColumnMapping
from rwa_calc.api.models import CalculationResponse, ReconciliationResponse
from rwa_calc.api.reconciliation import ReconciliationSettings
from rwa_calc.api.service import ERROR_RECON_LEDGER_UNAVAILABLE, CreditRiskCalc
from rwa_calc.contracts.bundles import create_empty_reconciliation_bundle

if TYPE_CHECKING:
    from collections.abc import Iterable

# The projection target, patched by name so the service's call-time import
# resolves to the patched object.
_PROJECT = "rwa_calc.analysis.legacy_ledger.project_legacy_ledger"

# Enough to reach every scoped template: the three sheet/population/money
# columns each plan builder resolves, plus the PD that C 08.03 bands on.
_RICH: dict[str, ComponentMapping] = {
    "exposure_class": ComponentMapping("CLASS"),
    "approach": ComponentMapping("METHOD"),
    "ead": ComponentMapping("EAD"),
    "rwa": ComponentMapping("RWA"),
    "pd": ComponentMapping("PD", unit="decimal"),
}

# The same, minus the PD: C 07.00 and C 08.01 stay reachable, C 08.03 does not.
_THIN: dict[str, ComponentMapping] = {name: cm for name, cm in _RICH.items() if name != "pd"}

# One amount and nothing to key a sheet on — no scoped template is reachable.
_UNREACHABLE: dict[str, ComponentMapping] = {"rwa": ComponentMapping("RWA")}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def our_calc(tmp_path: Path) -> CreditRiskCalc:
    """A CreditRiskCalc over the mandatory-minimum single-loan data set."""
    data_dir = write_mandatory_minimum(tmp_path)
    return CreditRiskCalc(
        data_path=data_dir,
        framework="CRR",
        reporting_date=date(2025, 1, 1),
        permission_mode="standardised",
    )


@pytest.fixture
def prior(our_calc: CreditRiskCalc) -> CalculationResponse:
    """One completed our-side run, reused so no test re-runs the pipeline."""
    response = our_calc.calculate()
    assert response.success
    return response


@pytest.fixture
def legacy_file(prior: CalculationResponse, tmp_path: Path) -> Path:
    """A legacy extract holding our one loan, matching us on every component."""
    results = prior.collect_results()
    legacy = tmp_path / "legacy.csv"
    pl.DataFrame(
        {
            "loan_id": [results["exposure_reference"][0]],
            "CLASS": ["corporate"],
            "METHOD": ["standardised"],
            "EAD": [float(results["ead_final"][0])],
            "RWA": [float(results["rwa_final"][0])],
            "PD": [0.01],
        }
    ).write_csv(legacy)
    return legacy


def _settings(legacy: Path, components: dict[str, ComponentMapping]) -> ReconciliationSettings:
    return ReconciliationSettings(
        legacy_file=legacy.resolve(),
        legacy_format="csv",
        mapping=LegacyColumnMapping(
            legacy_keys=("loan_id",),
            our_keys=("exposure_reference",),
            components=components,
        ),
    )


def _without_projection(
    calc: CreditRiskCalc, settings: ReconciliationSettings, prior: CalculationResponse
) -> ReconciliationResponse:
    """The same reconciliation with the projection disabled — the baseline."""
    with patch(_PROJECT, side_effect=RuntimeError("projection disabled for baseline")):
        return calc.reconcile(settings, calculation=prior)


# =============================================================================
# Tests
# =============================================================================


class TestProjectionIsRetained:
    def test_rich_mapping_carries_the_projected_legacy_source(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange
        settings = _settings(legacy_file, _RICH)

        # Act
        response = our_calc.reconcile(settings, calculation=prior)

        # Assert: a source on OUR framework, speaking sealed ledger column names.
        assert response.success
        source = response.legacy_ledger
        assert source is not None
        assert source.framework == our_calc.framework
        assert set(source.scan_results().collect_schema().names()) == {
            "exposure_reference",
            "reporting_class_origin",
            "reporting_approach_origin",
            "ead_final",
            "rwa_final",
            "pd_floored",
            "pd",
        }

    def test_rich_mapping_reaches_every_scoped_template(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange / Act
        response = our_calc.reconcile(_settings(legacy_file, _RICH), calculation=prior)

        # Assert
        coverage = response.legacy_ledger_coverage
        assert coverage is not None
        assert coverage.reachable_templates == set(LEDGER_TEMPLATE_IDS)
        assert not [e for e in response.errors if e.code == ERROR_RECON_LEDGER_UNAVAILABLE]

    def test_response_defaults_leave_both_fields_none(self) -> None:
        # Arrange / Act: every pre-existing construction site passes neither field.
        response = ReconciliationResponse(
            success=True,
            bundle=create_empty_reconciliation_bundle(),
            legacy_file=Path("legacy.csv"),
        )

        # Assert
        assert response.legacy_ledger is None
        assert response.legacy_ledger_coverage is None


class TestThinMappingDegradesHonestly:
    def test_thin_mapping_still_succeeds_and_names_what_is_unreachable(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange: no PD, so C 08.03 cannot band its rows.
        settings = _settings(legacy_file, _THIN)

        # Act
        response = our_calc.reconcile(settings, calculation=prior)

        # Assert
        assert response.success
        coverage = response.legacy_ledger_coverage
        assert coverage is not None
        assert coverage.reachable_templates == {"c07_00", "c08_01"}
        assert "pd_floored" in coverage.missing
        assert coverage.unavailable_refs("c08_03")

    def test_thin_mapping_leaves_the_reconciliation_untouched(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange
        settings = _settings(legacy_file, _THIN)

        # Act
        with_projection = our_calc.reconcile(settings, calculation=prior)
        baseline = _without_projection(our_calc, settings, prior)

        # Assert: the bundle the analyst already had is unchanged.
        assert with_projection.success == baseline.success
        assert (
            with_projection.collect_summary_by_bucket().to_dicts()
            == baseline.collect_summary_by_bucket().to_dicts()
        )
        assert (
            with_projection.collect_summary_by_component().to_dicts()
            == baseline.collect_summary_by_component().to_dicts()
        )

    def test_mapping_reaching_no_template_warns_and_carries_nothing(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange: an RWA and no sheet key — no scoped template can be produced.
        settings = _settings(legacy_file, _UNREACHABLE)

        # Act
        response = our_calc.reconcile(settings, calculation=prior)

        # Assert
        assert response.success
        assert response.legacy_ledger is None
        assert response.legacy_ledger_coverage is None
        warnings = [e for e in response.errors if e.code == ERROR_RECON_LEDGER_UNAVAILABLE]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"
        # The warning names the columns that would unlock a template.
        assert "reporting_class_origin" in warnings[0].message


class TestProjectionFailureDoesNotBreakReconciliation:
    def test_failure_keeps_success_and_records_a_warning(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange
        settings = _settings(legacy_file, _RICH)
        healthy = our_calc.reconcile(settings, calculation=prior)

        # Act
        with patch(_PROJECT, side_effect=RuntimeError("projection exploded")):
            response = our_calc.reconcile(settings, calculation=prior)

        # Assert: same reconciliation, no source, one non-blocking warning.
        assert response.success == healthy.success is True
        assert response.legacy_ledger is None
        assert response.legacy_ledger_coverage is None
        assert (
            response.collect_summary_by_bucket().to_dicts()
            == healthy.collect_summary_by_bucket().to_dicts()
        )
        warnings = [e for e in response.errors if e.code == ERROR_RECON_LEDGER_UNAVAILABLE]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"
        assert "projection exploded" in warnings[0].message

    def test_failure_adds_no_other_errors(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange
        settings = _settings(legacy_file, _RICH)
        healthy = our_calc.reconcile(settings, calculation=prior)

        # Act
        with patch(_PROJECT, side_effect=RuntimeError("projection exploded")):
            response = our_calc.reconcile(settings, calculation=prior)

        # Assert: the runner's own error channel is unchanged.
        assert [e.code for e in response.errors if e.code != ERROR_RECON_LEDGER_UNAVAILABLE] == [
            e.code for e in healthy.errors
        ]


class TestProjectionStaysLazy:
    def test_the_projected_ledger_is_never_collected(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        # Arrange: retain every collected frame (identity, not id(), so a freed
        # object's address cannot be reused and produce a false positive).
        collected: list[pl.LazyFrame] = []
        real_collect = pl.LazyFrame.collect

        def spy(self: pl.LazyFrame, *args: object, **kwargs: object) -> pl.DataFrame:
            collected.append(self)
            return real_collect(self, *args, **kwargs)  # type: ignore[arg-type]

        # Act
        with patch.object(pl.LazyFrame, "collect", spy):
            response = our_calc.reconcile(_settings(legacy_file, _RICH), calculation=prior)

        # Assert
        source = response.legacy_ledger
        assert source is not None
        assert isinstance(source.scan_results(), pl.LazyFrame)
        assert all(frame is not source.ledger for frame in collected)

    def test_the_projection_adds_exactly_one_bounded_label_measurement_pass(
        self, our_calc: CreditRiskCalc, legacy_file: Path, prior: CalculationResponse
    ) -> None:
        """The projection materialises ONE bounded pass, and only that one.

        This test used to be named "adds no collects at all" and asserted an
        inequality over ``pl.LazyFrame.collect`` alone. Both were wrong once the
        projection began measuring label vocabularies: the measurement uses
        ``pl.collect_all``, which that spy cannot see, so the test stayed green
        while asserting the opposite of the truth. A guard blind to the mechanism
        in use is worse than no guard, because the next reader trusts it.

        WHAT THE PASS IS, AND WHY IT IS UNAVOIDABLE. ``project_legacy_ledger``
        reports the legacy labels that match no engine vocabulary — an unmapped
        exposure class produces bogus sheets, an unmapped approach empties every
        template — and reachability accounts for them. Whether a value matches a
        vocabulary is a question about DATA; no amount of column-name reasoning
        answers it. So the projection runs one ``pl.collect_all`` over one
        ``group_by`` per vocabulary column the mapping SUPPLIES — never over the
        ones it does not, which is why this fixture's two-label mapping measures
        two plans and not the four ``LEDGER_VOCABULARY`` knows about.

        WHAT IT IS NOT. The firm's extract is NOT materialised. Each plan selects
        a single String column, so projection pushdown reads four columns and no
        others, and the projected ledger itself stays a ``LazyFrame`` — asserted
        by ``test_the_projected_ledger_is_never_collected`` above.

        The bound is two-sided and exact, so this reddens if a future change adds
        a second materialisation AND if one removes the label measurement. The
        plan count is anchored to ``len(LEDGER_VOCABULARY)`` rather than a
        literal, so adding a fifth vocabulary column is not a spurious failure.
        """
        # Arrange: the same settings run with and without the projection, spying
        # BOTH materialisation entry points — the eager one and the batched one.
        settings = _settings(legacy_file, _RICH)
        eager: list[int] = []
        batched: list[int] = []
        real_collect = pl.LazyFrame.collect
        real_collect_all = pl.collect_all

        def spy_collect(self: pl.LazyFrame, *args: object, **kwargs: object) -> pl.DataFrame:
            eager.append(1)
            return real_collect(self, *args, **kwargs)  # type: ignore[arg-type]

        def spy_collect_all(frames: object, *args: object, **kwargs: object) -> list[pl.DataFrame]:
            plans = list(cast("Iterable[pl.LazyFrame]", frames))
            batched.append(len(plans))
            return real_collect_all(plans, *args, **kwargs)  # type: ignore[arg-type]

        # Act
        with (
            patch.object(pl.LazyFrame, "collect", spy_collect),
            patch.object(pl, "collect_all", spy_collect_all),
        ):
            response = our_calc.reconcile(settings, calculation=prior)
            with_eager, with_batched = len(eager), sorted(batched)
            eager.clear()
            batched.clear()
            _without_projection(our_calc, settings, prior)
            without_eager, without_batched = len(eager), sorted(batched)

        # Assert: no eager collect added at all...
        assert with_eager == without_eager
        # ...and exactly one batched pass, of one plan per SUPPLIED vocabulary
        # column. Derived from the projected schema rather than written as a
        # literal, so it stays true if the mapping or the vocabulary grows, while
        # still pinning which columns this fixture actually reaches.
        source = response.legacy_ledger
        assert source is not None
        projected = set(source.scan_results().collect_schema().names())
        measured = sorted(column for column in LEDGER_VOCABULARY if column in projected)
        assert measured == ["reporting_approach_origin", "reporting_class_origin"]
        assert with_batched == sorted([*without_batched, len(measured)])
