"""
Unit tests for the pre-submission validation gate on ``ResultExporter``.

Covers:
- ``summarise_validation`` — the bundle-level verdict (clean vs broken estate)
- ``ResultExporter.validate_submission`` — the run-level entry point
- ``ResultExporter.export_validation_report`` — the reviewable on-disk artefact

Why: the published validation rules are the supervisor's own checks, run at
submission. An Error-severity break REJECTS the whole return — every template in
the filing, not just the one that broke — so a filer needs "can I submit?"
answered in one field before pressing send, and a break must be an accumulated
outcome rather than an exception.

The bundles here are hand-built rather than pipeline-generated: a break has to be
placed on a *named* rule for the test to assert anything about it, which a real
portfolio cannot be steered into doing.

References:
- src/rwa_calc/reporting/validations/checker.py — the rule evaluator
- COREP Annex II C 07.00; PRA PS1/26 Annex II OF 07.00
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest
from fastapi import HTTPException
from tests.fixtures.recon_ledger import with_reporting_ledger

from rwa_calc.api import rest
from rwa_calc.api.export import ResultExporter, SubmissionValidationResult, summarise_validation
from rwa_calc.api.models import CalculationResponse, SummaryStatistics
from rwa_calc.api.results_cache import ResultsCache
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.validations import (
    COVERAGE_NO_RULE_EXECUTED,
    COVERAGE_TEMPLATE_NOT_COVERED,
    evaluate_all,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# The framework -> rule broken by ``_c07_sheet(total_override=...)``. Both are
# the same identity in the two catalogues: C 07.00 column 0090 ("Exposure value
# after CRM substitution effects, pre conversion factors") is the sum of the
# four CRM outflow/inflow columns 0050-0080.
_IDENTITY_RULE = {"CRR": "v0305_m", "BASEL_3_1": "boe_b0694"}

# Row refs of the C 07.00 rows the identity rule is scoped to. Row 0040 is left
# out on purpose: Annex II reports it only on the immovable-property sheet, and
# emitting it on a corporate sheet breaks a *different* rule (v7477_m), which
# would make the "clean estate" fixture assert nothing.
_ROW_MAGNITUDES = {
    "0010": -100.0,
    "0020": -10.0,
    "0030": -10.0,
    "0050": -5.0,
    "0060": -5.0,
    "0070": -5.0,
    "0080": -5.0,
}

# The exact validation-report schema, in column order. Asserted rather than
# imported: this frame is the artefact a filer (or their filing vendor) reads, so
# a silent column rename or dtype change is a contract break, not a refactor.
_EXPECTED_REPORT_SCHEMA: dict[str, pl.DataType] = {
    "framework": pl.String(),
    "publisher": pl.String(),
    "rule_id": pl.String(),
    "severity": pl.String(),
    "blocking": pl.Boolean(),
    "rule_type": pl.String(),
    "status": pl.String(),
    "reason": pl.String(),
    "detail": pl.String(),
    "tables": pl.String(),
    "template_id": pl.String(),
    "sheet": pl.String(),
    "row_ref": pl.String(),
    "col_ref": pl.String(),
    "lhs": pl.Float64(),
    "rhs": pl.Float64(),
    "evaluated": pl.Int64(),
    "passed": pl.Int64(),
    "failed": pl.Int64(),
    "vacuous": pl.Int64(),
    "skipped": pl.Int64(),
    "failing_coordinates": pl.String(),
    "expression": pl.String(),
    "label": pl.String(),
    "run_is_submittable": pl.Boolean(),
    "run_coverage_shortfall": pl.String(),
    "run_templates_emitted": pl.Int64(),
    "run_templates_covered": pl.Int64(),
    "run_templates_uncovered": pl.String(),
}


# =============================================================================
# Fixtures
# =============================================================================


def _c07_sheet(
    *, total_override: float | None = None, extra_rows: dict[str, float] | None = None
) -> pl.DataFrame:
    """One C 07.00 sheet that satisfies every rule this estate can reach.

    Values are NEGATIVE because Annex II §1.3 reports the CRM columns as
    outflows; a positive figure breaks the sign rule (v2037_s) instead of the
    identity under test. Row 0010 carries the largest magnitude so the
    decomposition rule (v5735_h: r0010 <= r0050 + r0060) holds too.

    ``total_override`` replaces row 0020's column 0090 total, breaking the
    identity rule — and only that rule. ``extra_rows`` adds row refs that the
    clean sheet deliberately omits, to break a rule scoped to them.
    """
    magnitudes = {**_ROW_MAGNITUDES, **(extra_rows or {})}
    refs = sorted(magnitudes)
    components = {column: [magnitudes[ref] for ref in refs] for column in _CRM_COLUMNS}
    totals = [magnitudes[ref] * len(_CRM_COLUMNS) for ref in refs]
    if total_override is not None:
        totals[refs.index("0020")] = total_override
    return pl.DataFrame({"row_ref": refs, **components, "0090": totals})


#: C 07.00 columns 0050-0080 — the CRM substitution in/outflows that sum to 0090.
_CRM_COLUMNS = ("0050", "0060", "0070", "0080")


def _bundle(sheet: pl.DataFrame | None = None) -> COREPTemplateBundle:
    """A COREP bundle carrying just one C 07.00 corporate sheet (or nothing)."""
    return COREPTemplateBundle(
        c07_00={} if sheet is None else {"corporate": sheet},
        c08_01={},
        c08_02={},
    )


@pytest.fixture
def clean_bundle() -> COREPTemplateBundle:
    """An estate on which no enforced rule is broken."""
    return _bundle(_c07_sheet())


@pytest.fixture
def broken_bundle() -> COREPTemplateBundle:
    """An estate whose C 07.00 column 0090 does not sum its components."""
    return _bundle(_c07_sheet(total_override=-39.0))


@pytest.fixture
def uncovered_template_bundle(clean_bundle: COREPTemplateBundle) -> COREPTemplateBundle:
    """A clean estate plus a template no rule can reach.

    The stand-in for the real standing gap: our C 34.x templates are stubs whose
    rows and columns no published rule resolves a reference against, so they are
    emitted — they would be FILED — while nothing is executed on them.
    """
    return COREPTemplateBundle(
        c07_00=clean_bundle.c07_00,
        c08_01={"corporate": pl.DataFrame({"row_ref": ["9999"], "9999": [0.0]})},
        c08_02={},
    )


@pytest.fixture
def warning_only_bundle() -> COREPTemplateBundle:
    """An estate breaking a Warning-severity rule and no Error-severity one.

    Emitting row 0040 on a corporate sheet breaks v7477_m ("only reported in
    exposure class 'Secured by mortgages on immovable property'"), which the EBA
    classifies as a Warning: the return is accepted and the firm explains it.
    """
    sheet = _c07_sheet(extra_rows={"0040": -5.0})
    return _bundle(sheet)


@pytest.fixture
def sample_response(tmp_path: Path) -> CalculationResponse:
    """A minimal completed run, cached to parquet — no pipeline involved."""
    cache = ResultsCache(tmp_path / "cache")
    results_lf = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "retail_other"],
            "ead_final": [1_000_000.0, 500_000.0],
            "risk_weight": [1.0, 0.75],
            "rwa_final": [1_000_000.0, 375_000.0],
        }
    )
    cached = cache.sink_results(results=with_reporting_ledger(results_lf))
    return CalculationResponse(
        success=True,
        framework="CRR",
        reporting_date=date(2025, 12, 31),
        summary=SummaryStatistics(
            total_ead=Decimal("1500000"),
            total_rwa=Decimal("1375000"),
            exposure_count=2,
            average_risk_weight=Decimal("0.9167"),
        ),
        results_path=cached.results_path,
    )


# =============================================================================
# summarise_validation — the verdict
# =============================================================================


class TestCleanEstate:
    """An estate that breaks no enforced rule is submittable."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_is_submittable_with_no_blocking_breaks(
        self, clean_bundle: COREPTemplateBundle, framework: str
    ) -> None:
        # Arrange / Act
        result = summarise_validation(clean_bundle, None, framework)

        # Assert
        assert result.is_submittable is True
        assert result.blocking_count == 0
        assert result.blocking_breaks == ()

    def test_passed_rules_are_counted_separately_from_vacuous_ones(
        self, clean_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(clean_bundle, None, "CRR")

        # Assert: a rule that held only because every operand was null or zero is
        # no evidence of correctness, so it must never inflate the pass count.
        assert result.passed > 0
        assert result.passed + result.failed + result.vacuous + result.not_evaluated == (
            result.rules_enforced
        )

    def test_error_channel_is_empty(self, clean_bundle: COREPTemplateBundle) -> None:
        # Arrange / Act
        result = summarise_validation(clean_bundle, None, "CRR")

        # Assert
        assert result.errors == ()

    def test_every_emitted_template_was_actually_checked(
        self, clean_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(clean_bundle, None, "CRR")

        # Assert: "no break" is only evidence if something ran against the
        # template — this is the limb that stops an unchecked estate reading as
        # a pass.
        assert result.is_coverage_complete is True
        assert result.templates_uncovered == ()
        assert result.rules_executed > 0


class TestBrokenEstate:
    """An Error-severity break blocks the whole submission and is named."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_blocks_the_submission_and_names_the_rule(
        self, broken_bundle: COREPTemplateBundle, framework: str
    ) -> None:
        # Arrange / Act
        result = summarise_validation(broken_bundle, None, framework)

        # Assert
        assert result.is_submittable is False
        assert _IDENTITY_RULE[framework] in result.blocking_rule_ids()

    def test_break_carries_both_figures_and_its_coordinate(
        self, broken_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(broken_bundle, None, "CRR")
        outcome = next(o for o in result.blocking_breaks if o.rule_id == "v0305_m")

        # Assert: -39.0 was reported where the components sum to -40.0.
        assert outcome.failures[0].lhs == pytest.approx(-39.0)
        assert outcome.failures[0].rhs == pytest.approx(-40.0)
        assert outcome.coordinates == ("C 07.00.a[corporate][r0020]",)

    def test_break_reaches_the_error_channel_as_a_blocking_val001(
        self, broken_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(broken_bundle, None, "CRR")
        finding = next(e for e in result.errors if e.field_name == "v0305_m")

        # Assert
        assert finding.code == "VAL001"
        assert finding.severity == "error"

    def test_headline_states_the_verdict_in_one_line(
        self, broken_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        headline = summarise_validation(broken_bundle, None, "CRR").headline()

        # Assert
        assert headline.startswith("BLOCKED: 1 blocking break(s)")

    def test_a_break_is_returned_not_raised(self, broken_bundle: COREPTemplateBundle) -> None:
        # Arrange / Act / Assert: a failing validation is a business outcome, so
        # the accumulate-don't-throw contract must hold even for a blocker.
        assert isinstance(
            summarise_validation(broken_bundle, None, "CRR"), SubmissionValidationResult
        )


class TestWarningsDoNotBlock:
    """A Warning break is explainable; treating it as blocking stops good filings."""

    def test_a_warning_only_estate_is_still_submittable(
        self, warning_only_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(warning_only_bundle, None, "CRR")

        # Assert: the supervisor ACCEPTS this return — blocking on it would stop
        # a submission the supervisor would have taken.
        assert result.warning_count > 0
        assert result.blocking_count == 0
        assert result.is_submittable is True

    def test_the_warning_is_val002_and_not_error_severity(
        self, warning_only_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(warning_only_bundle, None, "CRR")

        # Assert
        assert {error.code for error in result.errors} == {"VAL002"}
        assert all(outcome.severity == "WARNING" for outcome in result.warning_breaks)

    def test_the_verdict_reads_the_rule_severity_not_the_finding_list(
        self, warning_only_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(warning_only_bundle, None, "CRR")

        # Assert: the finding list mixes VAL001 and VAL002, so a verdict derived
        # from "are there findings?" would block here. The split is made on the
        # RULE's severity, upstream of the error channel.
        assert result.errors != ()
        assert result.is_submittable is True
        assert all(outcome.severity == "ERROR" for outcome in result.blocking_breaks)


class TestFailOpenGuard:
    """The gate must never green-light an estate nothing was checked against.

    This is the regression class for the fail-open defect: ``evaluate_all`` over
    an empty bundle reports 741 NOT_EVALUATED rules and therefore ZERO breaks, so
    any verdict derived from "is the finding list empty?" says *submittable*
    precisely when there is least basis for it. Deleting or weakening these
    tests re-opens a control whose failure mode is silently authorising a bad
    regulatory filing.
    """

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_an_empty_estate_is_not_submittable_because_val003_is_raised(
        self, framework: str
    ) -> None:
        # Arrange / Act
        result = summarise_validation(_bundle(), None, framework)

        # Assert: the premise of the trap — no breaks at all …
        assert result.blocking_count == 0
        assert result.warning_count == 0
        assert result.rules_executed == 0
        # … and yet not submittable, because nothing ran to produce them. This
        # is limb 1 — the fail-open hole — and it is the one that blocks.
        assert [error.code for error in result.errors] == ["VAL003"]
        assert result.coverage_shortfall == COVERAGE_NO_RULE_EXECUTED
        assert result.was_checked is False
        assert result.is_submittable is False

    def test_an_unchecked_template_is_reported_but_does_not_block(
        self, uncovered_template_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        result = summarise_validation(uncovered_template_bundle, None, "CRR")

        # Assert: limb 2. The gap is real and named, but blocking on it would
        # reject correct returns — the C 34.x stubs make it a standing condition
        # on every CCR filing, and a control that cries wolf stops being
        # believed. The test ratchet holds this limb, not the API.
        assert result.coverage_shortfall == COVERAGE_TEMPLATE_NOT_COVERED
        assert result.templates_uncovered == ("c08_01",)
        # Coverage is incomplete AND the return is filable — not a contradiction,
        # which is exactly why this property is not named "sufficient".
        assert result.is_coverage_complete is False
        assert result.was_checked is True
        assert result.is_submittable is True

    def test_an_unchecked_template_is_still_told_to_the_filer(
        self, uncovered_template_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange / Act
        headline = summarise_validation(uncovered_template_bundle, None, "CRR").headline()

        # Assert: not blocking is not the same as not telling them.
        assert "1 of 2 template(s) covered" in headline
        assert "UNCHECKED (does not block): c08_01" in headline

    def test_a_break_still_blocks_when_a_template_is_uncovered(
        self, uncovered_template_bundle: COREPTemplateBundle
    ) -> None:
        # Arrange: the same uncovered template, but the C 07.00 identity broken.
        bundle = COREPTemplateBundle(
            c07_00={"corporate": _c07_sheet(total_override=-39.0)},
            c08_01=uncovered_template_bundle.c08_01,
            c08_02={},
        )

        # Act
        result = summarise_validation(bundle, None, "CRR")

        # Assert: limb 2 not blocking must not make limb 1's siblings lenient —
        # a real Error break still rejects the return.
        assert result.coverage_shortfall == COVERAGE_TEMPLATE_NOT_COVERED
        assert "v0305_m" in result.blocking_rule_ids()
        assert result.is_submittable is False

    def test_the_headline_names_the_coverage_shortfall(self) -> None:
        # Arrange / Act
        headline = summarise_validation(_bundle(), None, "CRR").headline()

        # Assert: a filer reading one line must see WHY, not just "BLOCKED".
        assert "NOT CHECKED" in headline
        assert "no rule could be executed" in headline

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_counts_are_always_reported_against_their_denominator(self, framework: str) -> None:
        # Arrange / Act
        result = summarise_validation(_bundle(), None, framework)

        # Assert: "0 problems" is the number that misleads; the headline must
        # carry what was executed and what could not be evaluated.
        headline = result.headline()
        assert f"{result.rules_executed} rule(s) executed" in headline
        assert f"{result.not_evaluated} of {result.rules_enforced}" in headline

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_the_coverage_verdict_is_the_checkers_and_is_not_recomputed_here(
        self, clean_bundle: COREPTemplateBundle, framework: str
    ) -> None:
        # Arrange: an uncheckable estate and a well-covered one.
        for bundle in (_bundle(), clean_bundle):
            report = evaluate_all(bundle, None, framework)

            # Act
            result = summarise_validation(bundle, None, framework)

            # Assert: this layer passes the checker's verdict through rather than
            # holding a floor of its own, so a limb added to the predicate is
            # inherited — not silently missed. A second implementation here is
            # what the module-level guard exists to make unnecessary.
            assert result.coverage_shortfall == report.coverage_shortfall
            assert result.is_coverage_complete is report.is_coverage_sufficient
            assert result.is_coverage_complete is not any(
                error.code == "VAL003" for error in result.errors
            )


class TestDegenerateBundles:
    """A malformed or empty estate produces a verdict, never an exception."""

    def test_empty_bundle_evaluates_no_rule(self) -> None:
        # Arrange / Act
        result = summarise_validation(_bundle(), None, "CRR")

        # Assert: nothing was emitted, so nothing is asserted either way — every
        # rule is NOT_EVALUATED, not a silent pass.
        assert result.not_evaluated == result.rules_enforced
        assert result.passed == 0
        assert result.blocking_breaks == ()

    def test_not_evaluated_rules_carry_a_reason(self) -> None:
        # Arrange / Act
        result = summarise_validation(_bundle(), None, "CRR")

        # Assert
        assert all(outcome.reason for outcome in result.not_evaluated_rules)
        assert sum(result.not_evaluated_reasons().values()) == result.not_evaluated

    def test_an_unknown_framework_is_a_programming_error(self) -> None:
        # Arrange / Act / Assert: the framework selects the rule CATALOGUE, so a
        # silent fallback would validate a return against the wrong supervisor's
        # rules. It raises (via load_rules) rather than degrading — callers must
        # validate at their own boundary, as the REST layer does with a Literal.
        with pytest.raises(ValueError, match="Unknown validation-rule framework"):
            summarise_validation(_bundle(), None, "IFRS9")

    @pytest.mark.parametrize(
        ("label", "frame"),
        [
            ("no row_ref column", pl.DataFrame({"0050": [-1.0], "0090": [-4.0]})),
            ("no rows", pl.DataFrame({"row_ref": []}, schema={"row_ref": pl.String})),
            (
                "all-null cells",
                pl.DataFrame(
                    {"row_ref": ["0010"], "0050": [None], "0090": [None]},
                    schema={"row_ref": pl.String, "0050": pl.Float64, "0090": pl.Float64},
                ),
            ),
            ("non-numeric cells", pl.DataFrame({"row_ref": ["0010"], "0090": ["n/a"]})),
            (
                "non-finite cells",
                pl.DataFrame({"row_ref": ["0010"], "0050": [float("nan")], "0090": [-4.0]}),
            ),
        ],
    )
    def test_malformed_frame_never_raises(self, label: str, frame: pl.DataFrame) -> None:
        # Arrange / Act
        result = summarise_validation(_bundle(frame), None, "CRR")

        # Assert
        assert result.rules_enforced > 0, label


# =============================================================================
# ResultExporter.validate_submission — the run-level entry point
# =============================================================================


class TestValidateSubmission:
    """The exporter method that generates the estate and validates it."""

    def test_returns_a_verdict_for_a_completed_run(
        self, sample_response: CalculationResponse
    ) -> None:
        # Arrange / Act
        result = ResultExporter().validate_submission(sample_response)

        # Assert
        assert result.framework == "CRR"
        assert result.publisher == "EBA"
        assert result.rules_enforced > 0

    def test_does_not_raise_when_the_run_breaks_rules(
        self, sample_response: CalculationResponse
    ) -> None:
        # Arrange / Act
        result = ResultExporter().validate_submission(sample_response)

        # Assert: whatever the verdict, it is data on the result — the caller
        # decides what to do about it.
        assert isinstance(result.is_submittable, bool)
        assert result.blocking_count == len(result.blocking_breaks)


# =============================================================================
# ResultExporter.export_validation_report — the reviewable artefact
# =============================================================================


class TestExportValidationReport:
    """The on-disk rule-outcome feed a filer reviews before filing."""

    def test_parquet_round_trips_with_the_expected_schema(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        export = ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        reloaded = pl.read_parquet(output_path)

        # Assert
        assert export.format == "validation_report_parquet"
        assert export.files == [output_path]
        assert dict(reloaded.schema) == _EXPECTED_REPORT_SCHEMA

    def test_writes_one_row_per_enforced_rule(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        export = ResultExporter().export_validation_report(result, output_path, fmt="parquet")

        # Assert: the review artefact covers every rule that was run, so a reader
        # can see what was NOT evaluated as well as what broke.
        assert export.row_count == result.rules_enforced
        assert pl.read_parquet(output_path).height == result.rules_enforced

    def test_the_break_row_carries_its_coordinate_and_both_figures(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        row = pl.read_parquet(output_path).filter(pl.col("rule_id") == "v0305_m").row(0, named=True)

        # Assert
        assert row["status"] == "FAIL"
        assert row["blocking"] is True
        assert row["template_id"] == "C 07.00.a"
        assert row["sheet"] == "corporate"
        assert row["row_ref"] == "0020"
        assert row["lhs"] == pytest.approx(-39.0)
        assert row["rhs"] == pytest.approx(-40.0)

    def test_blocking_flags_only_the_rules_blocking_this_submission(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        frame = pl.read_parquet(output_path)

        # Assert: a filer filtering `blocking` must get the rules to FIX, not
        # every rule that merely carries Error severity — several hundred of
        # which passed or never ran. That reading stays on `severity`.
        assert frame.filter(pl.col("blocking")).height == result.blocking_count
        assert frame.filter(pl.col("severity") == "ERROR").height > result.blocking_count
        assert frame.filter(pl.col("blocking"))["rule_id"].to_list() == list(
            result.blocking_rule_ids()
        )

    def test_a_rule_that_did_not_break_has_no_coordinate(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        frame = pl.read_parquet(output_path).filter(pl.col("status") != "FAIL")

        # Assert: a coordinate is evidence of a break, so it must never be
        # invented for a rule that passed or was skipped.
        assert frame["template_id"].null_count() == frame.height
        assert frame["lhs"].null_count() == frame.height

    def test_csv_is_written_for_review(
        self, broken_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(broken_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.csv"

        # Act
        export = ResultExporter().export_validation_report(result, output_path)

        # Assert: csv is the default — the reviewable form.
        assert export.format == "validation_report_csv"
        assert "v0305_m" in output_path.read_text(encoding="utf-8")

    def test_the_coverage_finding_is_not_duplicated_as_a_report_row(self, tmp_path: Path) -> None:
        # Arrange: an estate that triggers the checker's VAL003.
        result = summarise_validation(_bundle(), None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        frame = pl.read_parquet(output_path)

        # Assert: VAL003 is a run-level finding, not a rule outcome. It belongs
        # on the error channel once — synthesising a second copy as a report row
        # would double-count the same defect in the artefact a filer reviews.
        coverage_finding = next(error for error in result.errors if error.code == "VAL003")
        assert frame.height == result.rules_enforced
        assert coverage_finding.field_name not in frame["rule_id"].to_list()

    def test_every_row_carries_the_non_blocking_coverage_gap(
        self, uncovered_template_bundle: COREPTemplateBundle, tmp_path: Path
    ) -> None:
        # Arrange
        result = summarise_validation(uncovered_template_bundle, None, "CRR")
        output_path = tmp_path / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        frame = pl.read_parquet(output_path)

        # Assert: the gap does not block, so the report is the only place a
        # reviewer will meet it — and it must survive any sort or filter they
        # apply, hence a run-level constant on every row rather than a footer.
        assert frame["run_coverage_shortfall"].unique().to_list() == [COVERAGE_TEMPLATE_NOT_COVERED]
        assert frame["run_templates_uncovered"].unique().to_list() == ["c08_01"]
        assert frame["run_templates_covered"].unique().to_list() == [1]
        assert frame["run_templates_emitted"].unique().to_list() == [2]
        assert frame["run_is_submittable"].unique().to_list() == [True]

    def test_an_empty_estate_still_writes_a_typed_report(self, tmp_path: Path) -> None:
        # Arrange
        result = summarise_validation(_bundle(), None, "CRR")
        output_path = tmp_path / "nested" / "validation_report.parquet"

        # Act
        ResultExporter().export_validation_report(result, output_path, fmt="parquet")
        reloaded = pl.read_parquet(output_path)

        # Assert: every rule is NOT_EVALUATED, but the columns keep their dtypes.
        assert dict(reloaded.schema) == _EXPECTED_REPORT_SCHEMA
        assert reloaded["status"].unique().to_list() == ["NOT_EVALUATED"]


# =============================================================================
# GET /api/validations
# =============================================================================


@pytest.fixture
def registered_run(sample_response: CalculationResponse) -> Iterator[str]:
    """Register a run in the REST in-process registry and clean it up after."""
    run_id = rest.register_run(sample_response)
    yield run_id
    rest._RUNS.pop(run_id, None)
    rest._TEMPLATE_BUNDLES.pop((run_id, None), None)


class TestSupervisoryValidationsEndpoint:
    """The REST route exposing the verdict for a completed run."""

    def test_answers_whether_the_run_can_be_submitted(self, registered_run: str) -> None:
        # Arrange / Act
        payload = rest.supervisory_validations(registered_run)

        # Assert
        assert isinstance(payload["is_submittable"], bool)
        assert isinstance(payload["is_coverage_complete"], bool)
        assert payload["framework"] == "CRR"
        assert payload["counts"]["blocking"] == len(payload["blocking_breaks"])

    def test_a_blocked_submission_is_a_200_not_an_error_status(self, registered_run: str) -> None:
        # Arrange / Act: broken rules are data about the filing, not a fault in
        # the request, so the route must never turn one into an HTTP error.
        payload = rest.supervisory_validations(registered_run)

        # Assert
        assert "headline" in payload
        assert set(payload["counts"]) >= {"rules_enforced", "passed", "failed", "not_evaluated"}

    def test_unknown_run_id_is_a_404(self) -> None:
        # Arrange / Act / Assert
        with pytest.raises(HTTPException) as excinfo:
            rest.supervisory_validations("no-such-run")
        assert excinfo.value.status_code == 404
