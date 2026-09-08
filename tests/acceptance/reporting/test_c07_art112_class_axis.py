"""
C 07.00 / OF 07.00 class merge — the Art. 112(1) totals, on the golden estate.

Pipeline position:
    build_reporting_bundle() -> PipelineOrchestrator -> COREPGenerator
        -> COREPTemplateBundle.c07_00

What this pins, and why the numbers are the point. The template's z-axis is the
CRR Art. 112(1)(a)-(q) class list (COREP Annex II §3.2.2; PS1/26 Annex II keeps
the letters), so the engine's finer classes have to be merged onto it before
they key a sheet:

    corporate + corporate_sme + specialised_lending  -> (g) corporate
    retail_other + retail_qrre                       -> (h) retail
    retail_mortgage + residential_mortgage
        + commercial_mortgage                        -> (i) real_estate

Before that merge the estate published ``corporate`` 8,000,000 and
``corporate_sme`` 500,000 as two separate sheets, and letter (g) had NO total
anywhere in the template. Worse, the SME breakdown row was a casualty of the
same split: with the SME exposures on their own sheet, row 0020 "of which: SME"
on the corporate sheet had nothing to report and published **null** — the
of-which row that exists precisely to make the SME share visible was empty on
every submission. That null is the defect made visible, which is why row 0020
is asserted here as an absolute value rather than as "non-null".

``tests/contracts/test_c07_art112_sheet_axis.py`` owns the VOCABULARY invariant
(one sheet per Art. 112(1) letter, across the reporting portfolios and both
regimes). This file owns the ARITHMETIC on the golden estate: that the merged
sheet carries the sum of its parts, and that every breakdown the merge was
supposed to preserve is still reported — on the ROW axis, where the regulation
puts it (0020 SME, 0330/0340 by ``property_type`` under Basel 3.1, 0310 under
CRR), rather than on the sheet axis, where it never belonged.

Deliberately NOT asserted: column 0150. ``0150 = max(0, 0110 - 0130)`` is the
one non-linear cell on the template, so the merged value is recomputed over the
union frame and is NOT the sum of the two pre-merge sheet values. Asserting it
as a sum would encode an arithmetic that does not hold.

References:
- CRR Art. 112(1)(a)-(q); COREP Annex II §1.3.1, §3.2.2
- PRA PS1/26 Annex II (OF 07.00): rows 0330/0340/0350/0360 real-estate of-whiches
"""

from __future__ import annotations

from functools import lru_cache

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}

#: The Art. 112(1) letters this estate opens, exact. An exact set rather than a
#: subset: re-splitting one of the merged letters back out has to fail here, and
#: a subset assertion cannot see an extra sheet.
_EXPECTED_SHEETS: frozenset[str] = frozenset(
    {
        "central_govt_central_bank",  # (a)
        "institution",  # (f)
        "corporate",  # (g)
        "retail",  # (h)
        "real_estate",  # (i)
        "defaulted",  # (j)
        "other",  # (q)
    }
)

#: Letter (g): ``LN_CORP_RATED`` 5,000,000 + ``LN_CORP_UNRATED`` 3,000,000
#: (both ``corporate``) + ``LN_SME`` 500,000 (``corporate_sme``).
_CORPORATE_TOTAL: float = 8_500_000.0
_CORPORATE_SME: float = 500_000.0

#: Letter (h): ``LN_RETAIL`` 250,000 (``retail_other``).
_RETAIL_TOTAL: float = 250_000.0

#: Letter (i): ``LN_RRE`` 400,000 (``retail_mortgage``, residential) +
#: ``LN_CRE`` 10,000,000 (``commercial_mortgage``, commercial).
_REAL_ESTATE_TOTAL: float = 10_400_000.0
_REAL_ESTATE_RESIDENTIAL: float = 400_000.0
_REAL_ESTATE_COMMERCIAL: float = 10_000_000.0

#: The money spine of the template — the same columns
#: ``test_re_split_template_coverage`` requires, so a merged sheet is held to the
#: standard an unmerged one already met.
_MONEY_COLS: tuple[str, ...] = ("0010", "0040", "0110", "0200", "0220")


@lru_cache(maxsize=len(_REGIMES))
def _run(regime_key: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    """The golden reporting estate under one regime, memoised.

    Uses ``test_reporting_golden``'s own config factories so this file cannot
    drift onto a different estate than the goldens it describes.
    """
    config = _crr_config() if regime_key == "crr" else _b31_config()
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework=_REGIMES[regime_key])
    return result.results.collect(), corep


def _cell(corep: COREPTemplateBundle, sheet: str, row_ref: str, column: str) -> object:
    """One cell, with the sheet's own presence asserted first.

    Indexing the dict directly would raise ``KeyError`` for a sheet that was
    never emitted, and an absent sheet is the failure this file exists to
    describe — so it is an assertion with a message, not a traceback.
    """
    assert sheet in corep.c07_00, (
        f"C 07.00 sheet {sheet!r} not emitted; the axis holds {sorted(corep.c07_00)}"
    )
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected exactly one row {row_ref}, got {matched.height}"
    return matched[column][0]


class TestTheMergeHasSomethingToMerge:
    """LESSONS C11 — the adequacy of the fixture, asserted before the arithmetic.

    Every total below is a SUM over classes. If the estate carried only one
    class behind a letter, the merged total would equal the unmerged one and
    none of these assertions could tell a correct merge from no merge at all.
    """

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_both_corporate_classes_and_both_real_estate_classes_are_present(
        self, regime_key: str
    ) -> None:
        results, _corep = _run(regime_key)

        classes = {
            value for value in results["reporting_class_origin"].to_list() if value is not None
        }
        assert {"corporate", "corporate_sme"} <= classes, (
            "the estate carries only one letter-(g) class, so the corporate total "
            f"below cannot distinguish a merge from a pass-through; got {sorted(classes)}"
        )
        assert {"retail_mortgage", "commercial_mortgage"} <= classes, (
            "the estate carries only one letter-(i) class, so the real-estate total "
            f"below cannot distinguish a merge from a pass-through; got {sorted(classes)}"
        )


class TestSheetAxis:
    """The axis itself — emitted, and collapsed onto the Art. 112(1) letters."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_the_estate_opens_exactly_the_art_112_sheets(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        assert set(corep.c07_00) == set(_EXPECTED_SHEETS)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_every_merged_sheet_has_non_null_money_columns(self, regime_key: str) -> None:
        """LESSONS B4: a merged sheet that emits but publishes nulls is the
        failure mode this whole change is about, so presence is asserted on the
        three merged letters specifically, per column."""
        _results, corep = _run(regime_key)

        for sheet in ("corporate", "retail", "real_estate"):
            assert sheet in corep.c07_00, f"{regime_key}: sheet {sheet!r} not emitted"
            for column in _MONEY_COLS:
                value = _cell(corep, sheet, "0010", column)
                assert value is not None, f"{regime_key}/{sheet}: row 0010 col {column} is NULL"


class TestCorporateLetterG:
    """(g) corporates — ``corporate`` + ``corporate_sme`` on one sheet, with the
    SME share back on row 0020 where Annex II puts it."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_total_is_the_sum_of_both_corporate_classes(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        assert _cell(corep, "corporate", "0010", "0010") == pytest.approx(_CORPORATE_TOTAL)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_of_which_sme_row_reports_the_sme_share(self, regime_key: str) -> None:
        """Row 0020 was NULL before the merge — the SME exposures were on their
        own sheet, so the of-which row on the corporate sheet had nothing to
        describe. A null and a zero are different claims; this asserts neither."""
        value = _cell(_run(regime_key)[1], "corporate", "0020", "0010")

        assert value is not None, f"{regime_key}: row 0020 'of which: SME' is NULL"
        assert value == pytest.approx(_CORPORATE_SME)


class TestRetailLetterH:
    """(h) retail — ``retail_other`` + ``retail_qrre`` on one sheet."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_total_is_reported_under_the_retail_letter(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        assert _cell(corep, "retail", "0010", "0010") == pytest.approx(_RETAIL_TOTAL)


class TestRealEstateLetterI:
    """(i) real estate — the three mortgage classes on one sheet, split back out
    on the row axis by ``property_type``."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_total_is_the_sum_of_all_real_estate_classes(self, regime_key: str) -> None:
        _results, corep = _run(regime_key)

        assert _cell(corep, "real_estate", "0010", "0010") == pytest.approx(_REAL_ESTATE_TOTAL)

    def test_basel_31_splits_the_sheet_back_out_by_property_type(self) -> None:
        """Rows 0330 / 0340 are the of-which pair the sheet-axis split used to
        stand in for. They carry the residential and commercial legs that the
        merged sheet now totals, so no breakdown is lost by the merge."""
        _results, corep = _run("b31")

        residential = _cell(corep, "real_estate", "0330", "0010")
        commercial = _cell(corep, "real_estate", "0340", "0010")
        assert residential is not None, "row 0330 'of which: Regulatory residential RE' is NULL"
        assert commercial is not None, "row 0340 'of which: Regulatory commercial RE' is NULL"
        assert residential == pytest.approx(_REAL_ESTATE_RESIDENTIAL)
        assert commercial == pytest.approx(_REAL_ESTATE_COMMERCIAL)

    def test_basel_31_property_type_breakdown_foots_to_the_sheet_total(self) -> None:
        """The breakdown sums to its parent. A merge that dropped one class off
        the sheet would still look plausible row by row; only the footing shows
        it (``.claude/LESSONS.md`` E2)."""
        _results, corep = _run("b31")

        breakdown = sum(
            float(_cell(corep, "real_estate", row_ref, "0010") or 0.0)  # type: ignore[arg-type]
            for row_ref in ("0330", "0340", "0350", "0360")
        )
        assert breakdown == pytest.approx(_REAL_ESTATE_TOTAL)

    def test_basel_31_reports_no_other_real_estate_and_no_land_adc(self) -> None:
        """Rows 0350 / 0360 are NULL, not zero: this estate holds no
        non-qualifying RE and no land-ADC exposure, and a published zero would
        claim it had looked and found none."""
        _results, corep = _run("b31")

        assert _cell(corep, "real_estate", "0350", "0010") is None
        assert _cell(corep, "real_estate", "0360", "0010") is None

    def test_crr_keeps_both_of_which_rows_on_the_merged_sheet(self) -> None:
        """CRR has no 0330/0340 pair; its split is the memorandum pair 0290
        (commercial) / 0310 (residential), and BOTH must survive the merge onto
        the wider letter-(i) sheet — otherwise the merge would cost CRR the
        residential/commercial distinction the sheet axis used to carry.

        Note the row NOT used here: CRR section-1 row 0040 ("of which: Secured
        by mortgages on immovable property - Residential") is null on this
        sheet. It is declared in the template and wired to no predicate
        (``corep/c07.py`` ``_terms_for_row`` falls through to ``return None``),
        so it was null on the pre-merge ``retail_mortgage`` and
        ``commercial_mortgage`` sheets too — measured, and filed separately.
        """
        _results, corep = _run("crr")

        residential = _cell(corep, "real_estate", "0310", "0010")
        commercial = _cell(corep, "real_estate", "0290", "0010")
        assert residential is not None, "CRR row 0310 residential of-which is NULL"
        assert commercial is not None, "CRR row 0290 commercial of-which is NULL"
        assert residential == pytest.approx(_REAL_ESTATE_RESIDENTIAL)
        assert commercial == pytest.approx(_REAL_ESTATE_COMMERCIAL)
