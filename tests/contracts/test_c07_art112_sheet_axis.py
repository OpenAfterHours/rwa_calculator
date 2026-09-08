"""
The C 07.00 / OF 07.00 sheet axis is the Article 112(1) class list — a contract.

Pipeline position:
    reporting portfolios -> PipelineOrchestrator -> COREPGenerator
        -> COREPTemplateBundle.c07_00 (one rendered frame per SHEET KEY)

Why this file exists. ``reporting/kernel/bases.py::sheet_axis`` builds the
z-axis as ``data[class_col].drop_nulls().unique()`` — whatever string the sealed
class carrier happens to hold becomes a sheet, with no membership test anywhere
between the classifier and the submission. The z-axis is not a free vocabulary:
COREP Annex II §3.2.2 indexes it positionally by CRR Art. 112(1)(a)-(q) and
PS1/26 Annex II keeps the same letters, so an engine SUB-class that is not
itself an Art. 112(1) class has to be merged into the letter that carries it
before it can key a sheet. Emitting ``corporate`` and ``corporate_sme`` as two
sheets does not produce a sheet the supervisor can read — it produces two
partial ones and no total for letter (g).

That defect survived because production and its unit tests were written from the
SAME invented vocabulary: ``tests/unit/reporting/corep/test_c07.py`` indexed
sheet keys (``secured_by_re_residential``, ``secured_by_re_commercial``,
``secured_by_re_property``) that are not ``ExposureClass`` members at all. Both
sides agreed and both were wrong (``.claude/LESSONS.md`` B2 / B3).

So every assertion here is anchored on something that CANNOT drift with
``C07_00_SA_SHEET_MAP``:

- ``domain.enums.ExposureClass`` — the vocabulary the aggregator seals;
- ``C02_00_SA_CLASS_MAP`` — the SIBLING template's class map. COREP Annex II
  §1.3.1 makes C 02.00 rows 0070-0211 "See CR SA template", i.e. each row is an
  identity against the C 07.00 sheet for the same Art. 112(1) letter, so the two
  axes are in 1:1 correspondence by construction and a collision on the C 07.00
  side is exactly the defect;
- ``validations/scope.py::SHEET_INDEX_MAPS`` — the published z-axis, read off
  the live EBA/BoE rule sets. A sheet key absent from it is unaddressable, and
  ``resolve_sheet_codes`` then skips every rule scoped to that code as
  ``sheet_not_emitted`` — the supervisory gate FAILS OPEN, so this is a silent
  loss of coverage rather than a visible break.

References:
- CRR Art. 112(1)(a)-(q); COREP Annex II §1.3.1, §3.2.2 (C 07.00 z-axis)
- PRA PS1/26 Annex II (OF 07.00 instructions; class (n) withdrawn)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.fixtures.reporting_crm_substitution_portfolio import (
    build_reporting_crm_substitution_bundle,
)
from tests.fixtures.reporting_portfolio import build_reporting_bundle
from tests.fixtures.reporting_re_split_portfolio import build_reporting_re_split_bundle
from tests.fixtures.reporting_sa_classes_portfolio import build_reporting_sa_classes_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep import templates
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import C02_00_SA_CLASS_MAP, get_sa_row_sections
from rwa_calc.reporting.validations.scope import SHEET_INDEX_MAPS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from rwa_calc.contracts.bundles import RawDataBundle

#: regime key -> (framework string, name of the published sheet-index map).
#: OF 07.00 binds the SAME bundle member as C 07.00 through a different z-axis
#: (``scope.py::_BASEL_TABLES``), so both regimes are covered by running the
#: same portfolios twice, not by reading a second attribute.
_REGIMES: dict[str, tuple[str, str]] = {"crr": ("CRR", "c07"), "b31": ("BASEL_3_1", "of07")}


def _sa_config(framework: str) -> CalculationConfig:
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _irb_config(framework: str) -> CalculationConfig:
    """IRB permission, ``enforce_retail_granularity=False`` on the Basel 3.1 arm.

    Same shape as ``test_reporting_golden``'s config: without the granularity
    election every natural-person row reclassifies to corporate and the retail
    letter (h) disappears from the axis this file is asserting about.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


#: The reporting portfolios whose SA population reaches C 07.00, and how they are
#: configured. Chosen for the LETTERS they open rather than for size: ``rich``
#: carries (g)+(g-SME), (h) and two of the three (i) classes, ``sa-classes``
#: carries (b)-(e) and (l), ``re-split`` is the only estate emitting
#: ``residential_mortgage``, and ``crm-substitution`` is the only one whose
#: guarantor INFLOWS key a sheet (``c07.py::_art112_sheet_key``, the second of the two
#: sites the axis is built from — an inflow into a class with no sheet is the
#: silent-drop path that limb exists to close).
_PORTFOLIOS: dict[str, tuple[Callable[[], RawDataBundle], Callable[[str], CalculationConfig]]] = {
    "rich": (build_reporting_bundle, _irb_config),
    "sa-classes": (build_reporting_sa_classes_bundle, _sa_config),
    "re-split": (build_reporting_re_split_bundle, _sa_config),
    "crm-substitution": (build_reporting_crm_substitution_bundle, _irb_config),
}

_RUNS: list[tuple[str, str]] = [
    (portfolio, regime) for portfolio in _PORTFOLIOS for regime in _REGIMES
]


@lru_cache(maxsize=len(_PORTFOLIOS) * len(_REGIMES))
def _run(portfolio: str, regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """One portfolio through one regime, memoised — every test reads the matrix."""
    framework, _sheet_map_name = _REGIMES[regime_key]
    build, config = _PORTFOLIOS[portfolio]
    result = PipelineOrchestrator().run_with_data(build(), config(framework))
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep


def _declared_sheet_map() -> Mapping[str, str]:
    """The declared engine-class -> Art. 112(1) sheet-key map, or ``{}`` if absent.

    Resolved off the module rather than imported by name deliberately. With no
    map the identity below degrades to exactly the pass-through axis it exists
    to forbid, so the assertions fail on their OWN terms — naming the engine
    classes that share a letter — instead of turning the file into a collection
    error that reads like an unrelated breakage. Absence can never make a test
    here pass.
    """
    return templates.__dict__.get("C07_00_SA_SHEET_MAP", {})


def _art_112_rows(sheet_key: str, sheet_map: Mapping[str, str]) -> set[str]:
    """The C 02.00 SA class row(s) — i.e. Art. 112(1) letters — a sheet key reports.

    A merged key names no engine class of its own, so it is resolved through the
    classes that map INTO it; an unmerged key resolves as itself. An empty result
    means the key is not an Art. 112(1) class at all.
    """
    merged = {cls for cls, key in sheet_map.items() if key == sheet_key} or {sheet_key}
    return {C02_00_SA_CLASS_MAP[cls] for cls in merged if cls in C02_00_SA_CLASS_MAP}


class TestDeclaredVocabulary:
    """The map itself, before any pipeline runs."""

    def test_sheet_map_is_keyed_on_the_exposure_class_enum(self) -> None:
        """LESSONS B2: a class map keyed on invented strings zero-fills silently."""
        sheet_map = _declared_sheet_map()
        assert sheet_map, (
            "reporting/corep/templates.py declares no C07_00_SA_SHEET_MAP, so the "
            "C 07.00 / OF 07.00 z-axis has no declared Art. 112(1) vocabulary and "
            "kernel/bases.py::sheet_axis passes through whatever string the sealed "
            "class carrier holds"
        )

        invented = sorted(set(sheet_map) - {member.value for member in ExposureClass})
        assert not invented, f"C07_00_SA_SHEET_MAP keys are not ExposureClass members: {invented}"

    def test_sheet_map_covers_every_class_the_c02_00_sa_rows_route(self) -> None:
        """Exact set against the sibling map: a class C 02.00 routes into an SA
        class row must have a C 07.00 sheet to be that row's identity against,
        and a class C 02.00 does NOT route has no business keying one."""
        sheet_map = _declared_sheet_map()
        assert sheet_map, "no C07_00_SA_SHEET_MAP declared"

        assert set(sheet_map) == set(C02_00_SA_CLASS_MAP), (
            "C07_00_SA_SHEET_MAP and C02_00_SA_CLASS_MAP disagree on the SA class "
            f"population: only in C 07.00 {sorted(set(sheet_map) - set(C02_00_SA_CLASS_MAP))}, "
            f"only in C 02.00 {sorted(set(C02_00_SA_CLASS_MAP) - set(sheet_map))}"
        )

    def test_every_declared_sheet_key_is_exactly_one_art_112_class(self) -> None:
        """The map is a COARSENING of the class list, never a re-partition: no
        sheet key may gather classes that C 02.00 reports on different rows."""
        sheet_map = _declared_sheet_map()
        assert sheet_map, "no C07_00_SA_SHEET_MAP declared"

        straddling = {
            key: sorted(_art_112_rows(key, sheet_map))
            for key in set(sheet_map.values())
            if len(_art_112_rows(key, sheet_map)) != 1
        }
        assert not straddling, (
            "sheet key(s) do not resolve to exactly one C 02.00 SA class row "
            f"(Art. 112(1) letter): {straddling}"
        )


class TestEmittedAxis:
    """The axis the estate actually publishes, across the reporting portfolios."""

    @pytest.mark.parametrize(("portfolio", "regime_key"), _RUNS)
    def test_sheet_axis_is_one_key_per_art_112_class(self, portfolio: str, regime_key: str) -> None:
        """The defect, stated positively. Two sheets for one Art. 112(1) letter
        means the letter has no total anywhere in the template, and the C 02.00
        row that is meant to be their identity foots against neither."""
        _results, corep = _run(portfolio, regime_key)
        sheet_map = _declared_sheet_map()

        emitted = sorted(corep.c07_00)
        assert emitted, f"{portfolio}/{regime_key}: C 07.00 emitted NO sheet at all"

        by_row: dict[str, list[str]] = {}
        outside: list[str] = []
        for key in emitted:
            rows = _art_112_rows(key, sheet_map)
            if not rows:
                outside.append(key)
                continue
            for row in rows:
                by_row.setdefault(row, []).append(key)

        assert not outside, (
            f"{portfolio}/{regime_key}: sheet key(s) {outside} are not Art. 112(1) "
            "classes — they reached the z-axis through the unvalidated pass-through "
            "in kernel/bases.py::sheet_axis"
        )
        collisions = {row: keys for row, keys in by_row.items() if len(keys) > 1}
        assert not collisions, (
            f"{portfolio}/{regime_key}: more than one C 07.00 sheet per Art. 112(1) "
            f"class (keyed by the C 02.00 SA row they share): {collisions}"
        )

    @pytest.mark.parametrize(("portfolio", "regime_key"), _RUNS)
    def test_every_emitted_sheet_is_addressable_by_the_published_z_axis(
        self, portfolio: str, regime_key: str
    ) -> None:
        """A sheet no ``SheetCode.bundle_keys`` names cannot be reached by any
        published rule: ``resolve_sheet_codes`` returns ``sheet_not_emitted`` and
        every rule scoped to that z-code scores NOT_EVALUATED. The supervisory
        gate fails OPEN, so this is invisible to the break ratchet."""
        _results, corep = _run(portfolio, regime_key)
        _framework, sheet_map_name = _REGIMES[regime_key]

        addressable = {
            key for entry in SHEET_INDEX_MAPS[sheet_map_name].values() for key in entry.bundle_keys
        }
        unaddressable = sorted(set(corep.c07_00) - addressable)
        assert not unaddressable, (
            f"{portfolio}/{regime_key}: sheet key(s) {unaddressable} are emitted but "
            f"named by no SheetCode in SHEET_INDEX_MAPS[{sheet_map_name!r}] — every "
            "published rule scoped to their z-code will silently score NOT_EVALUATED"
        )

    @pytest.mark.parametrize(("portfolio", "regime_key"), _RUNS)
    def test_every_emitted_sheet_carries_a_populated_total_row(
        self, portfolio: str, regime_key: str
    ) -> None:
        """LESSONS B4: absence is this project's dominant escape class, so the
        merge must be shown to have produced a sheet with money on it — a null
        and a legitimate zero are different claims."""
        _results, corep = _run(portfolio, regime_key)

        for key, frame in sorted(corep.c07_00.items()):
            total = frame.filter(pl.col("row_ref") == "0010")
            assert total.height == 1, f"{portfolio}/{regime_key}/{key}: no total row 0010"
            assert total["0010"][0] is not None, (
                f"{portfolio}/{regime_key}/{key}: total row 0010 col 0010 "
                "(original exposure pre-conversion) is NULL"
            )

    def test_the_estate_exercises_the_merge_these_tests_assert(self) -> None:
        """LESSONS C11 — adequacy. If no portfolio in the matrix carries two
        engine classes under one Art. 112(1) letter, the collision assertion
        above is unfalsifiable and this file proves nothing."""
        sheet_map = _declared_sheet_map()

        emitted: set[str] = set()
        classes: set[str] = set()
        for portfolio, regime_key in _RUNS:
            results, corep = _run(portfolio, regime_key)
            emitted |= set(corep.c07_00)
            classes |= {
                value for value in results["reporting_class_origin"].to_list() if value is not None
            }

        feeding: dict[str, set[str]] = {}
        for cls in classes:
            feeding.setdefault(sheet_map.get(cls, cls), set()).add(cls)
        merged = {
            key: sorted(names)
            for key, names in feeding.items()
            if len(names) > 1 and key in emitted
        }
        assert merged, (
            "no emitted C 07.00 sheet is fed by more than one engine exposure class, "
            "so the one-sheet-per-Art. 112(1)-class assertions cannot fail — the "
            f"estate carries classes {sorted(classes)} onto sheets {sorted(emitted)}"
        )


#: A class value the map does not hold. Its ABSENCE from the map is asserted
#: below rather than assumed — a name that quietly became a real key would make
#: every assertion in ``TestUnmappedClassAlarm`` vacuous.
_UNMAPPED_CLASS: str = "brand_new_class"

#: The mapped negative control: a real ``ExposureClass`` member that the map
#: MERGES, so it exercises the mapped limb and the merge at once.
_MERGED_CLASS: str = ExposureClass.CORPORATE_SME.value

_ALARM_TEXT: str = "is not an Art. 112(1) exposure class"


def _sa_frame(classes: dict[str, float]) -> pl.LazyFrame:
    """A minimal SA ledger — one drawn, fully-weighted row per class."""
    names = sorted(classes)
    amounts = [classes[name] for name in names]
    return pl.LazyFrame(
        {
            "exposure_reference": [f"SA_{name.upper()}" for name in names],
            "counterparty_reference": [f"CP_{name.upper()}" for name in names],
            "approach_applied": ["standardised"] * len(names),
            "exposure_class": names,
            "drawn_amount": amounts,
            "undrawn_amount": [0.0] * len(names),
            "ead_final": amounts,
            "rwa_final": amounts,
            "risk_weight": [1.0] * len(names),
            "scra_provision_amount": [0.0] * len(names),
            "gcra_provision_amount": [0.0] * len(names),
            "collateral_adjusted_value": [0.0] * len(names),
            "guaranteed_portion": [0.0] * len(names),
            "sa_cqs": [None] * len(names),
        }
    )


def _alarms(errors: list[str]) -> list[str]:
    """The unmapped-class findings only — other generator errors are not ours."""
    return [error for error in errors if _ALARM_TEXT in error]


class TestUnmappedClassAlarm:
    """A class outside the declared vocabulary is REPORTED, and its money survives.

    ``c07_plans`` keeps an unmapped class rather than folding it into ``other``,
    and records a data-quality finding against it (``corep/c07.py``, the
    ``axis - C07_00_SA_SHEET_KEYS`` limb). Both halves matter and they protect
    different things: the error is what makes a bad class value visible, and the
    pass-through is what stops the exposure disappearing while the C 02.00 total
    still counts it. LESSONS B9 — a hazard the code reports at runtime with
    nothing asserting on it is not a gate; and an alarm only carries information
    if it stays silent on the case where nothing is wrong, which is why the
    mapped control below is part of the same test rather than an afterthought.
    """

    def test_the_fixture_can_express_both_limbs(self) -> None:
        """LESSONS C11 — adequacy, before anything is asserted on the alarm."""
        sheet_map = _declared_sheet_map()

        assert _UNMAPPED_CLASS not in sheet_map, (
            f"{_UNMAPPED_CLASS!r} is now a declared class, so it exercises the "
            "mapped limb and the alarm assertions below prove nothing"
        )
        assert sheet_map.get(_MERGED_CLASS) not in (None, _MERGED_CLASS), (
            f"{_MERGED_CLASS!r} no longer merges, so the negative control no "
            "longer covers the merge"
        )

    def test_an_unmapped_class_raises_exactly_one_named_finding(self) -> None:
        """One finding, naming the offending value — not one per sheet, and not
        one that names the mapped class beside it."""
        frame = _sa_frame({_UNMAPPED_CLASS: 700.0, "corporate": 1_000.0, _MERGED_CLASS: 400.0})

        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame)

        alarms = _alarms(bundle.errors)
        assert len(alarms) == 1, f"expected exactly one unmapped-class finding, got {alarms}"
        assert _UNMAPPED_CLASS in alarms[0], alarms[0]
        assert _MERGED_CLASS not in alarms[0], alarms[0]

    def test_the_unmapped_exposure_is_reported_not_dropped(self) -> None:
        """The half that protects the numbers: a wrong sheet is visible, a
        vanished exposure is not. Asserted as the portfolio total across every
        emitted sheet AND as the offending class's own cell, so a total that
        happened to foot for another reason cannot cover a lost leg."""
        frame = _sa_frame({_UNMAPPED_CLASS: 700.0, "corporate": 1_000.0, _MERGED_CLASS: 400.0})

        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame)

        assert _UNMAPPED_CLASS in bundle.c07_00, (
            f"{_UNMAPPED_CLASS!r} opened no sheet — 700.0 of exposure value left "
            "the template silently, which is worse than the wrong sheet"
        )
        totals = {
            key: sheet.filter(pl.col("row_ref") == "0010")["0200"][0] or 0.0
            for key, sheet in bundle.c07_00.items()
        }
        assert totals[_UNMAPPED_CLASS] == pytest.approx(700.0)
        assert sum(totals.values()) == pytest.approx(2_100.0)

    def test_a_mapped_class_is_silent_and_lands_on_its_merged_sheet(self) -> None:
        """The negative control. Without it the alarm assertion above would hold
        against a generator that reported every class, which is the saturated
        form of the same defect (LESSONS B9)."""
        frame = _sa_frame({"corporate": 1_000.0, _MERGED_CLASS: 400.0})

        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame)

        assert _alarms(bundle.errors) == []
        assert _MERGED_CLASS not in bundle.c07_00
        total = bundle.c07_00["corporate"].filter(pl.col("row_ref") == "0010")["0200"][0]
        assert total == pytest.approx(1_400.0)


# =============================================================================
# The SECOND site the axis is built from: ``c07.py::_art112_sheet_key``
# =============================================================================

#: The MERGED destination class the inflow limb is asserted on. Chosen over the
#: other two fan-ins because letter (h) returns NOTHING on the row axis — the
#: adequacy test below asserts that no C 07.00 (37 rows) or OF 07.00 (72 rows)
#: row names a QRRE split — so a mis-keyed QRRE inflow is reported on no
#: declared cell at all. A mis-keyed ``corporate_sme`` inflow would at least
#: still surface on row 0020 "of which: SME".
_MERGED_INFLOW_CLASS: str = ExposureClass.RETAIL_QRRE.value

#: The self-mapping destination class: the negative control, so these tests
#: cannot pass against a twin that simply sends every inflow to ``retail``.
_SELF_MAPPING_INFLOW_CLASS: str = ExposureClass.INSTITUTION.value

#: The two crossing amounts. Both NON-ZERO and unequal — a zero crossing amount
#: makes both keyings agree and cannot distinguish correct from absent
#: (``.claude/LESSONS.md`` C2), and equal amounts would let one stand in for the
#: other.
_MERGED_INFLOW: float = 500.0
_SELF_MAPPING_INFLOW: float = 300.0

#: The native population on the merged sheet, so the inflow has to be shown
#: ARRIVING on a sheet that already exists rather than merely opening one.
_MERGED_SHEET_NATIVE: float = 200.0


def _sa_frame_with_substitution_inflows() -> pl.LazyFrame:
    """An SA ledger whose guarantees migrate into a MERGED and a self-mapping class.

    ``post_crm_exposure_class_guaranteed`` is the destination-class carrier the
    inflow half of the substitution block keys on
    (``c07.py::_add_sa_origin_inflows`` -> ``_accumulate`` ->
    ``_art112_sheet_key``). Four legs:

    - ``SA_CORP_1`` — unguaranteed, so ``corporate`` has a population of its own.
    - ``SA_CORP_2`` — 500 guaranteed into ``retail_qrre``, which the sheet map
      MERGES into letter (h). The leg that drives the Python twin.
    - ``SA_CORP_3`` — 300 guaranteed into ``institution``, which maps to itself.
    - ``SA_RETAIL_1`` — a native ``retail_other`` loan, so the merged sheet
      carries 200 of its own before any inflow arrives.

    ``is_guarantee_beneficial`` is stated on both guaranteed legs rather than
    left absent: ``_add_sa_origin_inflows`` books an inflow only where Art. 235
    substitution was ACTUALLY applied, and absence says "the CRM sub-step never
    ran" rather than "the guarantee was recognised".
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_CORP_3", "SA_RETAIL_1"],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_E"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "corporate", "retail_other"],
            "exposure_type": ["loan"] * 4,
            "drawn_amount": [1_000.0, 2_000.0, 1_000.0, _MERGED_SHEET_NATIVE],
            "undrawn_amount": [0.0] * 4,
            "ead_final": [1_000.0, 2_000.0, 1_000.0, _MERGED_SHEET_NATIVE],
            "rwa_final": [1_000.0, 2_000.0, 1_000.0, 150.0],
            "risk_weight": [1.0, 1.0, 1.0, 0.75],
            "scra_provision_amount": [0.0] * 4,
            "gcra_provision_amount": [0.0] * 4,
            "guaranteed_portion": [0.0, _MERGED_INFLOW, _SELF_MAPPING_INFLOW, 0.0],
            "protection_type": [None, "guarantee", "guarantee", None],
            "is_guarantee_beneficial": [None, True, True, None],
            "pre_crm_exposure_class": ["corporate", "corporate", "corporate", "retail_other"],
            "post_crm_exposure_class_guaranteed": [
                "corporate",
                _MERGED_INFLOW_CLASS,
                _SELF_MAPPING_INFLOW_CLASS,
                "retail_other",
            ],
        }
    )


def _total_row(sheet: pl.DataFrame) -> pl.DataFrame:
    """The constraint-free TOTAL row 0010 of one rendered C 07.00 sheet."""
    return sheet.filter(pl.col("row_ref") == "0010")


class TestSubstitutionInflowKeysTheMergedSheet:
    """The guarantor-INFLOW half of the axis, i.e. ``c07.py::_art112_sheet_key``.

    ``C07_00_SA_SHEET_MAP`` is applied at TWO sites and the estate covered only
    one. ``_art112_sheet_key_expr`` keys the native population and is exercised
    by every portfolio in the matrix above; the Python twin keys the
    SUBSTITUTION-INFLOW destination classes, and ``c07_plans`` unions
    ``set(inflows.total)`` into the sheet axis. So a wrongly-keyed inflow does
    not raise, does not lose money and does not break a footing identity — it
    MATERIALISES AN EXTRA SHEET, one the published z-axis has no code for, while
    the sheet that should have carried the amount silently reports zero.

    Spying on the twin through the full ``PipelineOrchestrator`` over all five
    reporting portfolios in both regimes, the only classes that ever reached it
    were ``central_govt_central_bank``, ``corporate`` and ``institution`` —
    every one of which the map sends to itself. Replacing the twin with a
    pass-through left the whole C 07.00 estate green. This class is the fixture
    that makes it fail: the destination class is a MERGED one, so the two
    keyings disagree.

    The failure mode is absence-shaped in both directions, so both are asserted
    (``.claude/LESSONS.md`` B4): the merged sheet must be EMITTED and carry a
    NON-NULL col 0100, and the un-merged class must NOT open a sheet of its own.
    """

    def test_the_fixture_exercises_a_merged_and_a_self_mapping_destination(self) -> None:
        """LESSONS C11 — adequacy, asserted before anything reads a cell.

        Every premise these tests rest on, anchored on something that cannot
        drift with ``c07.py``: the enum for the vocabulary, the map itself for
        the merge, and ``SHEET_INDEX_MAPS`` (read off the live EBA/BoE rule
        sets) for the merged key being addressable at all.
        """
        sheet_map = _declared_sheet_map()
        assert sheet_map, "no C07_00_SA_SHEET_MAP declared"

        members = {member.value for member in ExposureClass}
        assert {_MERGED_INFLOW_CLASS, _SELF_MAPPING_INFLOW_CLASS} <= members, (
            "a destination class outside ExposureClass could never be sealed onto "
            "post_crm_exposure_class_guaranteed, so these tests would assert on a "
            "value production cannot produce"
        )

        merged_sheet = sheet_map.get(_MERGED_INFLOW_CLASS)
        assert merged_sheet not in (None, _MERGED_INFLOW_CLASS), (
            f"{_MERGED_INFLOW_CLASS!r} no longer merges, so the twin and the "
            "expression agree on it and a pass-through twin would pass every "
            "assertion below"
        )
        assert sheet_map.get(_SELF_MAPPING_INFLOW_CLASS) == _SELF_MAPPING_INFLOW_CLASS, (
            f"{_SELF_MAPPING_INFLOW_CLASS!r} is no longer a self-mapping class, so "
            "it is no longer a negative control"
        )
        for sheet_map_name in ("c07", "of07"):
            addressable = {
                key
                for entry in SHEET_INDEX_MAPS[sheet_map_name].values()
                for key in entry.bundle_keys
            }
            assert merged_sheet in addressable, (
                f"the merged sheet key {merged_sheet!r} is named by no SheetCode in "
                f"SHEET_INDEX_MAPS[{sheet_map_name!r}], so keying the inflow onto it "
                "would be no better than keying it onto the un-merged class"
            )

        assert _MERGED_INFLOW > 0.0, "a zero crossing amount cannot distinguish the two keyings"
        assert _MERGED_INFLOW != _SELF_MAPPING_INFLOW, (
            "equal crossing amounts let the negative control's inflow stand in for the merged one"
        )

    def test_no_c07_row_compensates_for_the_merged_class(self) -> None:
        """Why THIS merged class. Letter (i) returns on rows 0330-0360 and letter
        (g)'s SME limb on row 0020, but neither regime declares a QRRE row — so a
        QRRE inflow keyed anywhere but letter (h)'s sheet is reported on no
        declared cell of this template at all."""
        for framework in ("CRR", "BASEL_3_1"):
            names = [row.name for section in get_sa_row_sections(framework) for row in section.rows]
            assert names, f"{framework}: C 07.00 declares no rows at all"
            qrre_rows = [
                name for name in names if "qrre" in name.lower() or "revolv" in name.lower()
            ]
            assert not qrre_rows, (
                f"{framework}: C 07.00 now declares QRRE row(s) {qrre_rows}, so letter "
                "(h)'s merge no longer loses the split and the docstring's reason for "
                "choosing this class has drifted"
            )

    def test_a_merged_destination_class_opens_no_sheet_of_its_own(self) -> None:
        """The regression guard proper: the failure mode is a SPURIOUS EXTRA
        sheet, not a missing one, and nothing else in the estate would notice."""
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
            _sa_frame_with_substitution_inflows()
        )
        merged_sheet = _declared_sheet_map()[_MERGED_INFLOW_CLASS]

        assert merged_sheet in bundle.c07_00, (
            f"the merged sheet {merged_sheet!r} was not emitted at all — {sorted(bundle.c07_00)}"
        )
        assert _MERGED_INFLOW_CLASS not in bundle.c07_00, (
            f"the substitution inflow opened a {_MERGED_INFLOW_CLASS!r} sheet: the "
            "Python twin keyed the destination class differently from the expression "
            f"that keys the population, emitting {sorted(bundle.c07_00)}"
        )
        assert _alarms(bundle.errors) == [], (
            "an inflow into a real Art. 112(1) class raised the unmapped-class "
            "finding, so it reached the z-axis through the pass-through limb"
        )

    def test_the_merged_inflow_amount_arrives_on_the_merged_sheet(self) -> None:
        """Keying the sheet right is half of it — the money has to be ON it, in
        the cell Annex II puts it in and inside the col 0110 waterfall. A fix
        that keys the sheet correctly and drops the amount still fails here."""
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
            _sa_frame_with_substitution_inflows()
        )
        merged_sheet = _declared_sheet_map()[_MERGED_INFLOW_CLASS]
        sheet = bundle.c07_00[merged_sheet]
        total = _total_row(sheet)

        assert total["0100"][0] is not None, (
            f"{merged_sheet}: col 0100 is NULL on the total row — a null and a "
            "legitimate zero are different claims (LESSONS B4)"
        )
        assert total["0100"][0] == pytest.approx(_MERGED_INFLOW)
        # The sheet keeps its OWN population: the inflow is added to letter (h),
        # not substituted for it.
        assert total["0010"][0] == pytest.approx(_MERGED_SHEET_NATIVE)
        # ``v0306_m`` / ``boe_b0697``: 0110 = 0040 + 0090 + 0100. Nothing leaves
        # this sheet, so the inflow is the whole difference.
        assert total["0110"][0] == pytest.approx(_MERGED_SHEET_NATIVE + _MERGED_INFLOW)
        # The SPLIT axes key through the same twin by a DIFFERENT call site
        # (``_accumulate_split``, once for the balance-sheet side and once for
        # the risk-weight band), fed by ``ReportingContext.substitution_inflow_*``
        # rather than by ``substitution_inflow``. Every leg here is a drawn loan,
        # so row 0070 ("of which: on-balance sheet", ``c07_bs == "on"``) carries
        # the whole inflow — a split keyed onto a different sheet from its own
        # total would leave this zero while row 0010 above still footed.
        on_bs = sheet.filter(pl.col("row_ref") == "0070")
        assert on_bs.height == 1, f"{merged_sheet}: no on-balance-sheet row 0070"
        assert on_bs["0100"][0] == pytest.approx(_MERGED_INFLOW)

    def test_every_inflow_the_book_generates_is_reported_on_some_sheet(self) -> None:
        """The breakdown foots its parent: col 0100 summed over the emitted
        sheets is the whole covered amount. Keying the merge correctly while
        losing an amount would leave this short — it is deliberately blind to
        WHICH sheet, which is what the two tests above pin."""
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
            _sa_frame_with_substitution_inflows()
        )

        inflows = {key: _total_row(sheet)["0100"][0] for key, sheet in bundle.c07_00.items()}
        assert all(value is not None for value in inflows.values()), (
            f"col 0100 is NULL on the total row of some sheet: {inflows}"
        )
        assert sum(inflows.values()) == pytest.approx(_MERGED_INFLOW + _SELF_MAPPING_INFLOW)

    def test_a_self_mapping_destination_class_still_lands_on_itself(self) -> None:
        """The negative control. Without it every assertion above would hold
        against a twin that sent EVERY inflow to the merged sheet."""
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
            _sa_frame_with_substitution_inflows()
        )

        assert _SELF_MAPPING_INFLOW_CLASS in bundle.c07_00, (
            f"the self-mapping class {_SELF_MAPPING_INFLOW_CLASS!r} lost its "
            f"inflow-only sheet — {sorted(bundle.c07_00)}"
        )
        total = _total_row(bundle.c07_00[_SELF_MAPPING_INFLOW_CLASS])
        assert total["0100"][0] is not None
        assert total["0100"][0] == pytest.approx(_SELF_MAPPING_INFLOW)
