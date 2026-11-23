"""Tests for validate_aggregated_bundle — P2.34.

Validates the output-bounds checker on AggregatedResultBundle.results.

The function raises four categories of bound violations:
- OUT001: risk_weight > 12.5  (CRR Art. 92(3); CRE31.5)
- OUT002: risk_weight < 0     (CRR Art. 153; CRE31)
- OUT003: rwa_final < -1e-9   (CRR Art. 92(3))
- OUT004: ead_final is null   (data quality)
- OUT005: rwa_final is null   (data quality; P1.345)

It also pins IRB009 (P1.351), which ``validate_branch_reasons`` raises at the
same exit for a retail IRB row priced on an Art. 161(1) corporate supervisory
LGD (CRR Art. 151(7) / 164(1); PS1/26 Art. 164(1)).

References:
- CRR Art. 92(3): minimum capital requirement
- CRR Art. 153: IRB risk weight function
- CRE31: Basel risk weight floors
"""

from __future__ import annotations

import polars as pl
import pytest

import rwa_calc.contracts.validation as _validation_module
from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.errors import ErrorCategory, ErrorSeverity
from rwa_calc.contracts.validation import validate_branch_reasons
from rwa_calc.domain.branch_reasons import (
    IRB_LGD_BRANCH_REASON,
    UNKNOWN_FALLBACK,
    IrbLgdReason,
    reason_dtype,
)
from rwa_calc.domain.enums import ExposureClass

# Defer resolution of validate_aggregated_bundle so collection succeeds even
# before the engine-implementer adds the function.  Each test that calls it
# will get an AttributeError turned into a plain assertion failure, which
# satisfies the "assertion-style for C3.4" requirement.
_validate_aggregated_bundle = getattr(_validation_module, "validate_aggregated_bundle", None)


def validate_aggregated_bundle(*args, **kwargs):  # type: ignore[return]
    """Thin shim that defers the ImportError to assertion time."""
    assert _validate_aggregated_bundle is not None, (
        "validate_aggregated_bundle is not yet defined in rwa_calc.contracts.validation"
    )
    return _validate_aggregated_bundle(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _unregister_results_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deregister the aggregator_exit brand for this module (Phase 3).

    These tests pin ``validate_aggregated_bundle`` bounds-checking on
    column-exact minimal frames — including the missing-column ramp, which a
    lenient seal would mask by injecting typed nulls. Deregistering
    ``AggregatedResultBundle.results`` pins the unregistered strangler ramp,
    mirroring tests/contracts/test_edge_contracts.py::TestBundleBrandValidation.
    """
    from rwa_calc.contracts import bundles as bundles_module

    monkeypatch.delitem(bundles_module.SEALED_FRAME_FIELDS, "AggregatedResultBundle.results")


def _make_results_lf(
    exposure_references: list[str],
    risk_weights: list[float | None],
    rwa_finals: list[float | None],
    ead_finals: list[float | None],
) -> pl.LazyFrame:
    """Build a minimal per-exposure results LazyFrame."""
    n = len(exposure_references)
    return pl.LazyFrame(
        {
            "exposure_reference": exposure_references,
            "approach_applied": ["sa"] * n,
            "exposure_class": ["corporate"] * n,
            "ead_final": pl.Series(ead_finals, dtype=pl.Float64),
            "risk_weight": pl.Series(risk_weights, dtype=pl.Float64),
            "rwa_final": pl.Series(rwa_finals, dtype=pl.Float64),
        }
    )


def _make_bundle(results: pl.LazyFrame) -> AggregatedResultBundle:
    """Wrap a results LazyFrame in a minimal AggregatedResultBundle."""
    return AggregatedResultBundle(results=results)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOut005NullRwaFinal:
    """OUT005 — the twin of OUT004 on the capital carrier (P1.345 / P1.317).

    P1.317 published a row with a POPULATED ``ead_final``, a ``risk_weight`` of
    2.5 and a NULL ``rwa_final``. Every existing bound passed it: OUT001-003 all
    guard on ``is_not_null()`` first, and OUT004 watches the wrong column. The
    bounds gate was one spec short, and the guard that shipped with P1.317 is
    equity-scoped, so any other exposure class could repeat it silently.

    These tests pin the gap itself, not the equity instance.
    """

    def test_out005_fires_on_the_p1_317_shape(self):
        """Populated ead_final + null rwa_final is caught, and by OUT005 alone."""
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E001"],
                "risk_weight": [2.5],
                "rwa_final": [None],
                "ead_final": [10_000_000.0],
            },
            schema_overrides={"rwa_final": pl.Float64},
        )

        errors = validate_aggregated_bundle(_make_bundle(results))

        codes = sorted({e.code for e in errors})
        assert codes == ["OUT005"], (
            f"expected OUT005 alone on the P1.317 shape, got {codes}. "
            "OUT004 firing here would mean it is watching the wrong column; "
            "nothing firing means the bounds gate is still one spec short."
        )
        assert errors[0].exposure_reference == "E001"

    def test_out005_is_silent_on_a_populated_rwa(self):
        """The control: a clean row must not trip the new bound."""
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E001"],
                "risk_weight": [0.75],
                "rwa_final": [7_500_000.0],
                "ead_final": [10_000_000.0],
            }
        )

        errors = validate_aggregated_bundle(_make_bundle(results))

        assert [e.code for e in errors] == []

    def test_out005_and_out004_are_independent(self):
        """Both nulls on one row raise both codes — neither masks the other."""
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E001"],
                "risk_weight": [0.75],
                "rwa_final": [None],
                "ead_final": [None],
            },
            schema_overrides={"rwa_final": pl.Float64, "ead_final": pl.Float64},
        )

        errors = validate_aggregated_bundle(_make_bundle(results))

        assert sorted({e.code for e in errors}) == ["OUT004", "OUT005"]


class TestValidateAggregatedBundle:
    """Contract tests for validate_aggregated_bundle."""

    def test_validate_aggregated_bundle_returns_four_errors_for_known_failure_modes(self):
        """Four distinct bound violations across four rows produce exactly four errors.

        Fixture (from scenario proposal):
          E001 — clean row: rw=0.20, rwa=200_000, ead=1_000_000
          E002 — OUT001: rw=13.0  (> 12.5)
          E003 — OUT002 + OUT003: rw=-0.5 (< 0), rwa=-500_000 (< -1e-9)
          E004 — OUT004: ead_final=None
        """
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — exactly four errors
        assert len(errors) == 4, f"Expected 4 errors but got {len(errors)}: " + ", ".join(
            f"[{e.code}] {e.exposure_reference}" for e in errors
        )

        codes = [e.code for e in errors]
        assert codes.count("OUT001") == 1, f"Expected 1× OUT001, got {codes.count('OUT001')}"
        assert codes.count("OUT002") == 1, f"Expected 1× OUT002, got {codes.count('OUT002')}"
        assert codes.count("OUT003") == 1, f"Expected 1× OUT003, got {codes.count('OUT003')}"
        assert codes.count("OUT004") == 1, f"Expected 1× OUT004, got {codes.count('OUT004')}"

    def test_validate_aggregated_bundle_out001_error_references_correct_exposure(self):
        """OUT001 error must identify the violating exposure (E002)."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — OUT001 points to E002
        out001 = [e for e in errors if e.code == "OUT001"]
        assert len(out001) == 1
        assert out001[0].exposure_reference == "E002"

    def test_validate_aggregated_bundle_out002_and_out003_share_same_exposure(self):
        """E003 produces both OUT002 (rw < 0) and OUT003 (rwa < -1e-9)."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["E001", "E002", "E003", "E004"],
            risk_weights=[0.20, 13.0, -0.5, 1.00],
            rwa_finals=[200_000.0, 1_300_000.0, -500_000.0, 1_000_000.0],
            ead_finals=[1_000_000.0, 100_000.0, 1_000_000.0, None],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — both OUT002 and OUT003 reference E003
        e003_codes = {e.code for e in errors if e.exposure_reference == "E003"}
        assert "OUT002" in e003_codes
        assert "OUT003" in e003_codes

    def test_validate_aggregated_bundle_clean_bundle_returns_empty_list(self):
        """All-clean results produce no errors."""
        # Arrange — four rows identical to E001 shape (all within bounds, no nulls)
        results = _make_results_lf(
            exposure_references=["C001", "C002", "C003", "C004"],
            risk_weights=[0.20, 0.75, 1.50, 0.35],
            rwa_finals=[200_000.0, 750_000.0, 1_500_000.0, 350_000.0],
            ead_finals=[1_000_000.0, 1_000_000.0, 1_000_000.0, 1_000_000.0],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        assert errors == []

    def test_validate_aggregated_bundle_empty_results_returns_empty_list(self):
        """An empty results LazyFrame (zero rows) must return an empty list."""
        # Arrange — empty frame with the correct schema
        results = pl.LazyFrame(
            {
                "exposure_reference": pl.Series([], dtype=pl.String),
                "approach_applied": pl.Series([], dtype=pl.String),
                "exposure_class": pl.Series([], dtype=pl.String),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa_final": pl.Series([], dtype=pl.Float64),
            }
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        assert errors == []

    def test_validate_aggregated_bundle_sample_cap_limits_row_errors(self):
        """When more than sample_cap rows violate a bound, extra rows are summarised.

        Build 7 rows that all exceed risk_weight > 12.5 (OUT001).
        With sample_cap=5, expect exactly 5 per-row OUT001 errors plus 1 summary
        error for the 2 rows beyond the cap — total 6.
        """
        # Arrange
        n = 7
        results = _make_results_lf(
            exposure_references=[f"X{i:03d}" for i in range(n)],
            risk_weights=[14.0] * n,
            rwa_finals=[1_000_000.0] * n,
            ead_finals=[1_000_000.0] * n,
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle, sample_cap=5)

        # Assert — 5 per-row errors + 1 summary = 6 total; all coded OUT001
        out001_errors = [e for e in errors if e.code == "OUT001"]
        assert len(out001_errors) == 6, (
            f"Expected 6 OUT001 errors (5 row + 1 summary) but got {len(out001_errors)}"
        )

    def test_validate_aggregated_bundle_missing_column_silently_skipped(self):
        """If risk_weight is absent from results schema the bound is silently skipped."""
        # Arrange — omit risk_weight column entirely
        results = pl.LazyFrame(
            {
                "exposure_reference": ["M001", "M002"],
                "approach_applied": ["sa", "sa"],
                "exposure_class": ["corporate", "corporate"],
                "ead_final": pl.Series([500_000.0, 750_000.0], dtype=pl.Float64),
                "rwa_final": pl.Series([50_000.0, 75_000.0], dtype=pl.Float64),
                # risk_weight deliberately absent
            }
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert — no OUT001/OUT002 errors (bounds rely on risk_weight)
        rw_error_codes = {e.code for e in errors if e.code in ("OUT001", "OUT002")}
        assert rw_error_codes == set()

    @pytest.mark.parametrize(
        "rw,expected_violation",
        [
            (12.5, False),  # exact boundary — not above cap, no error
            (12.500001, True),  # infinitesimally above — error
            (0.0, False),  # exact zero — not negative, no error
            (-1e-10, True),  # tiny negative — error
        ],
    )
    def test_validate_aggregated_bundle_boundary_values(self, rw: float, expected_violation: bool):
        """Boundary values for risk_weight are handled with strict inequality."""
        # Arrange
        results = _make_results_lf(
            exposure_references=["B001"],
            risk_weights=[rw],
            rwa_finals=[100_000.0],
            ead_finals=[1_000_000.0],
        )
        bundle = _make_bundle(results)

        # Act
        errors = validate_aggregated_bundle(bundle)

        # Assert
        rw_codes = {e.code for e in errors if e.code in ("OUT001", "OUT002")}
        if expected_violation:
            assert len(rw_codes) == 1, f"Expected 1 RW violation error for rw={rw}, got {rw_codes}"
        else:
            assert rw_codes == set(), f"Expected no RW violation for rw={rw}, got {rw_codes}"


# ---------------------------------------------------------------------------
# IRB009 — retail IRB row priced on a corporate supervisory LGD (P1.351)
# ---------------------------------------------------------------------------

#: The code, written out so the test is anchored to the published value.
_IRB009 = "IRB009"

#: CRR / PS1/26 Art. 147(2)(d): the IRB retail classes, as enum members. The
#: tripwire test below fails if the enum gains a retail member this set lacks.
_RETAIL_IRB_CLASSES = frozenset(
    {ExposureClass.RETAIL_MORTGAGE, ExposureClass.RETAIL_QRRE, ExposureClass.RETAIL_OTHER}
)


def _irb_results(
    rows: list[tuple[str, str | None, str | None, str | None]],
    *,
    with_subtype: bool = True,
) -> AggregatedResultBundle:
    """Build a results bundle from ``(ref, exposure_class_irb, reason, subtype)`` rows.

    The reason column carries the sealed ``irb_lgd_branch_reason`` dtype (an
    Enum over ``IrbLgdReason``), so the validator meets the exit's real shape.
    ``with_subtype=False`` builds a frame that genuinely OMITS
    ``purchased_receivables_subtype`` rather than holding it as a typed null
    (LESSONS B1: absent and null are different code paths).
    """
    columns: dict[str, pl.Series] = {
        "exposure_reference": pl.Series([r[0] for r in rows], dtype=pl.String),
        "exposure_class_irb": pl.Series([r[1] for r in rows], dtype=pl.String),
        IRB_LGD_BRANCH_REASON: pl.Series([r[2] for r in rows], dtype=reason_dtype(IrbLgdReason)),
    }
    if with_subtype:
        columns["purchased_receivables_subtype"] = pl.Series([r[3] for r in rows], dtype=pl.String)
    return _make_bundle(pl.LazyFrame(columns))


def _irb009(bundle: AggregatedResultBundle, sample_cap: int = 5) -> list:
    """The IRB009 errors ``validate_branch_reasons`` raises on a bundle."""
    return [e for e in validate_branch_reasons(bundle, sample_cap=sample_cap) if e.code == _IRB009]


class TestIrb009RetailCorporateSupervisoryLgd:
    """``validate_branch_reasons`` names retail rows priced on Art. 161(1) (P1.351).

    CRR Art. 151(7) / Art. 164(1) and PS1/26 Art. 164(1)(a) require own LGD
    estimates for retail IRB; Art. 161(1) is a corporates / institutions
    article. The only supervisory retail LGD is for dilution risk of purchased
    receivables (Art. 164(1)). The end-to-end pin, in both regimes, is
    ``tests/acceptance/crr/test_p1_351_retail_supervisory_subtype.py``; these
    tests pin the predicate's edges on the sealed exit's column shape.
    """

    def test_retail_class_set_covers_every_retail_enum_member(self) -> None:
        """Tripwire: a new retail ExposureClass member must join the guard (LESSONS B2)."""
        retail_members = {m for m in ExposureClass if m.value.startswith("retail")}

        assert retail_members == _RETAIL_IRB_CLASSES

    @pytest.mark.parametrize("exposure_class", list(ExposureClass), ids=lambda m: m.value)
    def test_supervisory_firb_fires_on_retail_classes_only(
        self, exposure_class: ExposureClass
    ) -> None:
        """Art. 161(1)(a)/(b) on a retail row fires; on any other class it does not."""
        bundle = _irb_results([("E1", exposure_class.value, "supervisory_firb", None)])

        named = [e.exposure_reference for e in _irb009(bundle)]

        expected = ["E1"] if exposure_class in _RETAIL_IRB_CLASSES else []
        assert named == expected

    @pytest.mark.parametrize(
        ("subtype", "fires"),
        [
            ("senior", True),
            ("subordinated", True),
            ("dilution_risk", False),
            # Case variants pass the input gate (DQ006 lower-cases both sides) but
            # miss the engine's exact-match dispatch, which prices them on the
            # Art. 161(1)(a)/(b) seniority fallback - a corporate rate.
            ("Senior", True),
            ("Subordinated", True),
            ("SUBORDINATED", True),
            ("Dilution_Risk", True),
            ("DILUTION_RISK", True),
            # Out of vocabulary: DQ006 names the spelling, and the dispatch still
            # prices the row on the seniority fallback.
            ("junior", True),
        ],
    )
    def test_supervisory_subtype_fires_unless_priced_on_the_dilution_rate(
        self, subtype: str, fires: bool
    ) -> None:
        """Only the exact ``dilution_risk`` spelling reaches Art. 164(1)'s retail rate.

        The engine dispatch (``engine/irb/transforms.py::apply_firb_lgd``) matches
        the subtype exactly; every other spelling on this branch is priced on an
        Art. 161(1) corporate rate, (e)/(f) or the (a)/(b) seniority fallback.
        """
        bundle = _irb_results([("E1", "retail_other", "supervisory_subtype", subtype)])

        named = [e.exposure_reference for e in _irb009(bundle)]

        assert named == (["E1"] if fires else [])

    def test_null_subtype_on_the_subtype_branch_fires(self) -> None:
        """Mirrors the dispatch: a null subtype is not the dilution rate.

        The engine never writes ``supervisory_subtype`` beside a null subtype, but
        if a frame did, its ``when(subtype == "dilution_risk")`` would not match
        and the row would take the seniority fallback - a corporate rate.
        """
        bundle = _irb_results([("E1", "retail_other", "supervisory_subtype", None)])

        assert [e.exposure_reference for e in _irb009(bundle)] == ["E1"]

    @pytest.mark.parametrize(
        "subtype",
        ["senior", "subordinated", "dilution_risk", "Senior", "Dilution_Risk", "junior"],
    )
    def test_corporate_supervisory_subtype_is_authorised(self, subtype: str) -> None:
        """Art. 161(1) is the corporate population's own article: never IRB009, any spelling."""
        bundle = _irb_results([("E1", "corporate", "supervisory_subtype", subtype)])

        assert _irb009(bundle) == []

    @pytest.mark.parametrize("reason", ["own_estimate", "ccr_modelled", UNKNOWN_FALLBACK, None])
    def test_retail_rows_not_on_a_supervisory_rate_are_silent(self, reason: str | None) -> None:
        """Own estimates are what Art. 164(1) requires; UNKNOWN_FALLBACK is BR001's."""
        bundle = _irb_results([("E1", "retail_other", reason, "senior")])

        assert _irb009(bundle) == []

    def test_null_irb_class_is_silent(self) -> None:
        """A row with no IRB class is not shown to be retail, so it is not named."""
        bundle = _irb_results([("E1", None, "supervisory_firb", None)])

        assert _irb009(bundle) == []

    def test_absent_subtype_column_still_names_supervisory_firb_rows(self) -> None:
        """Without the subtype column the (a)/(b) limb still fires; nothing raises."""
        bundle = _irb_results(
            [
                ("E1", "retail_qrre", "supervisory_firb", None),
                ("E2", "retail_other", "own_estimate", None),
            ],
            with_subtype=False,
        )

        assert [e.exposure_reference for e in _irb009(bundle)] == ["E1"]

    def test_warning_shape(self) -> None:
        """WARNING / DATA_QUALITY, row-named, on the branch-reason column."""
        bundle = _irb_results([("E1", "retail_mortgage", "supervisory_subtype", "subordinated")])

        (error,) = _irb009(bundle)

        assert error.severity == ErrorSeverity.WARNING
        assert error.category == ErrorCategory.DATA_QUALITY
        assert error.exposure_reference == "E1"
        assert error.field_name == IRB_LGD_BRANCH_REASON
        assert error.actual_value == "supervisory_subtype"
        assert "Art. 164(1)" in (error.regulatory_reference or "")

    def test_sample_cap_then_one_summary(self) -> None:
        """Up to ``sample_cap`` row-named errors, then one summary with the omitted count.

        ``tests/robustness/harness.py`` clause (c) depends on this shape.
        """
        rows = [(f"E{i}", "retail_other", "supervisory_firb", None) for i in range(7)]

        errors = _irb009(_irb_results(rows), sample_cap=5)

        assert [e.exposure_reference for e in errors] == ["E0", "E1", "E2", "E3", "E4", None]
        assert "2 additional row(s) omitted" in errors[-1].message

    def test_br001_is_unaffected_by_the_retail_scan(self) -> None:
        """The two codes share one scan of the reason column; neither swallows the other."""
        bundle = _irb_results(
            [
                ("E1", "retail_other", "supervisory_firb", None),
                ("E2", "corporate", UNKNOWN_FALLBACK, None),
            ]
        )

        codes = sorted(
            (e.code, e.exposure_reference) for e in validate_branch_reasons(bundle, sample_cap=5)
        )

        assert codes == [("BR001", "E2"), (_IRB009, "E1")]
