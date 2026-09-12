"""COREP template-definition constants (structural, no generation).

Split from tests/unit/test_corep.py (Phase 7 Sn) — bodies verbatim.

The SA class assertions were repointed off ``SA_EXPOSURE_CLASS_ROWS`` (P1.372).
That map was a SECOND, stale sheet vocabulary living beside the live one: PR #497
re-keyed the C 07.00 / OF 07.00 exposure-class dimension onto Art. 112(1)
(``C07_00_SA_SHEET_MAP``) and moved the display names to ``sheet_labels.py``,
after which nothing in ``src/`` read it. Its membership half is asserted here
against ``ExposureClass`` and its label half against ``get_c07_sheet_labels``.
The defect #497 fixed was production and its tests sharing an INVENTED
vocabulary; a stale one kept alive by a test is the same trap in slower motion
(``.claude/LESSONS.md`` B2 / B3).

The ROW REFS both maps carried are deliberately NOT repointed, because neither
set addressed the template it was read as describing. An exposure class on these
axes gets a SHEET, not a row, so there was no row for a ref to be. ``0071`` ("Of
which: SME corporates") and ``0091`` ("Of which: Qualifying revolving") are rows
of nothing at all — neither C 07.00 nor OF 07.00 declares a QRRE row in either
regime — and the refs that DO exist elsewhere address a different cell entirely:
``B31_C09_01_ROWS`` row 0071 is a real-estate sub-row, and on the IRB side
``corporate``'s "0030" is C 08.01's "Off balance sheet items subject to credit
risk". ``generator.py`` reads the IRB map for the NAME alone and throws the ref
away. So ``test_row_refs_are_unique`` asserted uniqueness over an axis no
submission carries; the live form of that claim — two workbook tabs may not
print the same name — is asserted on the labels instead.
"""

from __future__ import annotations

import math

import pytest

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.corep.sheet_labels import get_c07_sheet_labels
from rwa_calc.reporting.corep.templates import (
    B31_C07_COLUMNS,
    B31_C08_COLUMNS,
    B31_IRB_ROW_SECTIONS,
    B31_SA_RISK_WEIGHT_BANDS,
    B31_SA_ROW_SECTIONS,
    C07_00_SA_SHEET_KEYS,
    C07_00_SA_SHEET_MAP,
    C07_COLUMNS,
    C08_01_COLUMNS,
    CRR_C07_COLUMNS,
    CRR_C08_COLUMNS,
    CRR_IRB_ROW_SECTIONS,
    CRR_SA_ROW_SECTIONS,
    IRB_EXPOSURE_CLASS_LABELS,
    PD_BANDS,
    SA_RISK_WEIGHT_BANDS,
    get_c07_columns,
    get_c08_columns,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from rwa_calc.reporting.validations.scope import SHEET_INDEX_MAPS

#: The frameworks ``get_c07_sheet_labels`` resolves. PS1/26 renames four of the
#: fourteen Art. 112(1) classes, so a one-regime assertion covers half the estate.
_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")


def _duplicated(labels: dict[str, str]) -> list[str]:
    """Labels carried by more than one key — a workbook tab a reader cannot index."""
    names = sorted(labels.values())
    return sorted({name for name in names if names.count(name) > 1})


class TestTemplateDefinitions:
    """Tests for COREP template structure definitions."""

    def test_sa_sheet_map_covers_every_exposure_class(self) -> None:
        """Every engine SA class has an Art. 112(1) sheet to be submitted on.

        Anchored on ``ExposureClass`` itself (LESSONS B2 / B3). The map this
        replaced named seven classes by hand, so it could only ever check the
        classes its author had already thought of, and it agreed with nothing.
        A class the map omits does not surface as a missing row:
        ``reporting/kernel/bases.py::sheet_axis`` passes the raw class string
        through and opens a sheet no published z-code addresses, whereupon every
        rule scoped to that code scores NOT_EVALUATED and the gate fails OPEN.
        """
        classes = {member.value for member in ExposureClass}

        assert set(C07_00_SA_SHEET_MAP) == classes, (
            "C07_00_SA_SHEET_MAP is not total over ExposureClass: unmapped "
            f"{sorted(classes - set(C07_00_SA_SHEET_MAP))}, non-members "
            f"{sorted(set(C07_00_SA_SHEET_MAP) - classes)}"
        )

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_every_sa_sheet_key_is_named_for_the_reader(self, framework: str) -> None:
        """Each Art. 112(1) sheet the map can open carries a display name.

        The display-name half of the ``(row_ref, name)`` map this replaced, which
        nothing else asserts. Anchored on ``C07_00_SA_SHEET_KEYS`` — built from
        ``C07_00_SA_SHEET_MAP``'s own values — so it cannot be satisfied by a list
        copied out of ``sheet_labels.py``. An unlabelled key is not cosmetic: the
        Excel tab and the UI sheet picker fall back to the raw key, which is how a
        sheet holding commercial mortgages came to be shown as ``retail_mortgage``.
        """
        labels = get_c07_sheet_labels(framework)

        assert set(labels) == set(C07_00_SA_SHEET_KEYS), (
            f"{framework}: the C 07.00 label vocabulary and the sheet keys "
            "C07_00_SA_SHEET_MAP produces disagree — unlabelled "
            f"{sorted(set(C07_00_SA_SHEET_KEYS) - set(labels))}, labelled but "
            f"unreachable {sorted(set(labels) - set(C07_00_SA_SHEET_KEYS))}"
        )
        blank = sorted(key for key, name in labels.items() if not name.strip())
        assert not blank, f"{framework}: sheet key(s) {blank} carry an empty label"

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_sa_sheet_labels_are_distinct(self, framework: str) -> None:
        """Two Art. 112(1) sheets may not print the same name.

        The live form of the row-ref uniqueness this replaced: the label is what
        a reader indexes a workbook tab by, where the refs the old map carried
        indexed no template at all (see the module docstring).
        """
        duplicated = _duplicated(get_c07_sheet_labels(framework))

        assert not duplicated, (
            f"{framework}: C 07.00 label(s) carried by more than one sheet key, "
            f"so the workbook holds two tabs a reader cannot tell apart: {duplicated}"
        )

    @pytest.mark.parametrize("sheet_map_name", ["c08", "of08"])
    def test_every_published_irb_sheet_is_named_for_the_reader(self, sheet_map_name: str) -> None:
        """Every IRB sheet the published z-axis can address carries a name.

        Anchored on ``validations/scope.py::SHEET_INDEX_MAPS`` — the Art. 147(2)
        z-axis read off the live EBA/BoE rule sets, which cannot drift with
        ``templates.py``. Containment, not equality: ``of08`` names no
        ``central_govt_central_bank`` sheet because PS1/26 withdraws the IRB
        sovereign class, and a label for a class only CRR emits is correct.
        """
        published = {
            key for entry in SHEET_INDEX_MAPS[sheet_map_name].values() for key in entry.bundle_keys
        }
        assert published, f"{sheet_map_name}: no SheetCode names a bundle key at all"

        unlabelled = sorted(published - set(IRB_EXPOSURE_CLASS_LABELS))
        assert not unlabelled, (
            f"{sheet_map_name}: IRB sheet key(s) {unlabelled} are addressed by a "
            "published z-code but carry no label, so generator.py names their "
            "C 08.0x tab by the raw class key"
        )

    def test_irb_sheet_labels_are_distinct(self) -> None:
        """Two IRB sheets may not print the same name — the live form of the
        row-ref uniqueness this replaced, for the same reason as the SA side."""
        assert IRB_EXPOSURE_CLASS_LABELS, "no IRB class label map declared"

        duplicated = _duplicated(IRB_EXPOSURE_CLASS_LABELS)
        assert not duplicated, (
            "IRB label(s) carried by more than one class, so the workbook holds "
            f"two C 08.0x tabs a reader cannot tell apart: {duplicated}"
        )

    def test_sa_risk_weight_bands_in_ascending_order(self) -> None:
        """Risk weight bands must be in ascending order."""
        rw_values = [rw for rw, _ in SA_RISK_WEIGHT_BANDS]
        assert rw_values == sorted(rw_values)

    def test_pd_bands_cover_full_range(self) -> None:
        """PD bands must cover 0% to 100%+ without gaps."""
        assert PD_BANDS[0][0] == pytest.approx(0.0, abs=1e-10)
        assert math.isinf(PD_BANDS[-1][1])

        for i in range(len(PD_BANDS) - 1):
            assert PD_BANDS[i][1] == PD_BANDS[i + 1][0], f"Gap between bands {i} and {i + 1}"

    def test_c07_columns_have_refs(self) -> None:
        """C 07.00 column definitions have reference numbers."""
        for col in C07_COLUMNS:
            assert col.ref.isdigit(), f"Column ref must be numeric: {col.ref}"
            assert len(col.name) > 0

    def test_c08_01_columns_have_refs(self) -> None:
        """C 08.01 column definitions have reference numbers."""
        for col in C08_01_COLUMNS:
            assert col.ref.isdigit()
            assert len(col.name) > 0


class TestCRRC07ColumnDefinitions:
    """Tests for CRR C 07.00 column definitions (correct 4-digit refs)."""

    def test_crr_c07_has_24_data_columns(self) -> None:
        """CRR C 07.00 has 28 columns covering full SA waterfall."""
        assert len(CRR_C07_COLUMNS) == 28

    def test_crr_c07_uses_4_digit_refs(self) -> None:
        """All CRR C 07.00 column refs are 4 digits."""
        for col in CRR_C07_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"
            assert col.ref.isdigit(), f"Ref {col.ref} is not numeric"

    def test_crr_c07_refs_unique(self) -> None:
        """Column refs are unique."""
        refs = [col.ref for col in CRR_C07_COLUMNS]
        assert len(refs) == len(set(refs))

    def test_crr_c07_starts_with_original_exposure(self) -> None:
        """First column is original exposure (0010)."""
        assert CRR_C07_COLUMNS[0].ref == "0010"
        assert "Original exposure" in CRR_C07_COLUMNS[0].name

    def test_crr_c07_ends_with_ecai_derived(self) -> None:
        """Last column is ECAI credit assessment derived from central govt (0240)."""
        assert CRR_C07_COLUMNS[-1].ref == "0240"

    def test_crr_c07_has_supporting_factor_columns(self) -> None:
        """CRR includes supporting factor columns (0215-0217)."""
        refs = {col.ref for col in CRR_C07_COLUMNS}
        assert "0215" in refs
        assert "0216" in refs
        assert "0217" in refs

    def test_crr_c07_ccf_buckets(self) -> None:
        """CRR CCF buckets are 0%, 20%, 50%, 100%."""
        ccf_cols = [col for col in CRR_C07_COLUMNS if col.group == "CCF Breakdown"]
        assert len(ccf_cols) == 4
        assert ccf_cols[0].name == "Off-BS by CCF: 0%"
        assert ccf_cols[1].name == "Off-BS by CCF: 20%"
        assert ccf_cols[2].name == "Off-BS by CCF: 50%"
        assert ccf_cols[3].name == "Off-BS by CCF: 100%"

    def test_crr_c07_all_columns_have_groups(self) -> None:
        """Every CRR C 07.00 column has a logical group assigned."""
        for col in CRR_C07_COLUMNS:
            assert col.group, f"Column {col.ref} has no group"


class TestB31C07ColumnDefinitions:
    """Tests for Basel 3.1 OF 07.00 column definitions."""

    def test_b31_c07_has_correct_column_count(self) -> None:
        """B3.1 OF 07.00 has 28 columns (adds 4, removes 3 vs CRR)."""
        assert len(B31_C07_COLUMNS) == 28

    def test_b31_c07_uses_4_digit_refs(self) -> None:
        """All B3.1 OF 07.00 column refs are 4 digits."""
        for col in B31_C07_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"

    def test_b31_c07_has_on_bs_netting(self) -> None:
        """B3.1 adds on-balance sheet netting column (0035)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0035" in refs

    def test_b31_c07_has_40pct_ccf(self) -> None:
        """B3.1 adds 40% CCF bucket (0171)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0171" in refs

    def test_b31_c07_has_unrated_ecai(self) -> None:
        """B3.1 adds unrated ECAI column (0235)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0235" in refs

    def test_b31_c07_no_supporting_factors(self) -> None:
        """B3.1 removes supporting factor columns (0215-0217)."""
        refs = {col.ref for col in B31_C07_COLUMNS}
        assert "0215" not in refs
        assert "0216" not in refs
        assert "0217" not in refs

    def test_b31_c07_ccf_10pct_replaces_0pct(self) -> None:
        """B3.1 changes 0% CCF to 10%."""
        col_0160 = next(c for c in B31_C07_COLUMNS if c.ref == "0160")
        assert "10%" in col_0160.name

    def test_b31_c07_ccf_buckets(self) -> None:
        """B3.1 CCF buckets are 10%, 20%, 40%, 50%, 100%."""
        ccf_cols = [col for col in B31_C07_COLUMNS if col.group == "CCF Breakdown"]
        assert len(ccf_cols) == 5
        assert "10%" in ccf_cols[0].name
        assert "20%" in ccf_cols[1].name
        assert "40%" in ccf_cols[2].name
        assert "50%" in ccf_cols[3].name
        assert "100%" in ccf_cols[4].name


class TestSARowSections:
    """Tests for SA row section definitions (C 07.00 / OF 07.00)."""

    def test_crr_sa_has_5_sections(self) -> None:
        assert len(CRR_SA_ROW_SECTIONS) == 5

    def test_crr_sa_section_names(self) -> None:
        names = [s.name for s in CRR_SA_ROW_SECTIONS]
        assert "Total Exposures" in names
        assert "Breakdown by Exposure Types" in names
        assert "Breakdown by Risk Weights" in names
        assert "Breakdown by CIU Approach" in names
        assert "Memorandum Items" in names

    def test_crr_sa_total_section_starts_with_0010(self) -> None:
        total_section = CRR_SA_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"
        assert "TOTAL" in total_section.rows[0].name

    def test_crr_sa_total_section_has_of_which_rows(self) -> None:
        total_section = CRR_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs
        assert "0020" in refs
        assert "0030" in refs
        assert "0035" in refs

    def test_crr_sa_rw_section_has_15_rows(self) -> None:
        rw_section = CRR_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 15

    def test_crr_sa_rw_section_row_refs_ascending(self) -> None:
        rw_section = CRR_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert refs == sorted(refs)

    def test_crr_sa_memorandum_has_4_rows(self) -> None:
        memo_section = CRR_SA_ROW_SECTIONS[4]
        assert memo_section.name == "Memorandum Items"
        assert len(memo_section.rows) == 4

    def test_crr_sa_all_row_refs_unique(self) -> None:
        all_refs = [r.ref for s in CRR_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_sa_has_5_sections(self) -> None:
        assert len(B31_SA_ROW_SECTIONS) == 5

    def test_b31_sa_rw_section_has_28_rows(self) -> None:
        rw_section = B31_SA_ROW_SECTIONS[2]
        assert rw_section.name == "Breakdown by Risk Weights"
        assert len(rw_section.rows) == 28

    def test_b31_sa_has_specialised_lending_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0021" in refs
        assert "0022" in refs
        assert "0023" in refs
        assert "0024" in refs
        assert "0025" in refs
        assert "0026" in refs

    def test_b31_sa_has_re_detail_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0330" in refs
        assert "0340" in refs
        assert "0360" in refs

    def test_b31_sa_no_supporting_factor_rows(self) -> None:
        total_section = B31_SA_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0030" not in refs
        assert "0035" not in refs

    def test_b31_sa_has_400pct_rw(self) -> None:
        rw_section = B31_SA_ROW_SECTIONS[2]
        refs = [r.ref for r in rw_section.rows]
        assert "0261" in refs
        assert "0260" not in refs

    def test_b31_sa_memorandum_has_equity_transitional(self) -> None:
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0371" in refs
        assert "0372" in refs
        assert "0373" in refs
        assert "0374" in refs

    def test_b31_sa_memorandum_has_currency_mismatch(self) -> None:
        memo_section = B31_SA_ROW_SECTIONS[4]
        refs = [r.ref for r in memo_section.rows]
        assert "0380" in refs

    def test_b31_sa_all_row_refs_unique(self) -> None:
        all_refs = [r.ref for s in B31_SA_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestCRRC08ColumnDefinitions:
    """Tests for CRR C 08.01 column definitions."""

    def test_crr_c08_has_correct_column_count(self) -> None:
        assert len(CRR_C08_COLUMNS) == 37

    def test_crr_c08_uses_4_digit_refs(self) -> None:
        for col in CRR_C08_COLUMNS:
            assert len(col.ref) == 4, f"Ref {col.ref} is not 4 digits"

    def test_crr_c08_starts_with_pd(self) -> None:
        assert CRR_C08_COLUMNS[0].ref == "0010"
        assert "PD" in CRR_C08_COLUMNS[0].name

    def test_crr_c08_has_double_default(self) -> None:
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0220" in refs

    def test_crr_c08_has_supporting_factors(self) -> None:
        refs = {col.ref for col in CRR_C08_COLUMNS}
        assert "0255" in refs
        assert "0256" in refs
        assert "0257" in refs

    def test_crr_c08_maturity_in_days(self) -> None:
        col_0250 = next(c for c in CRR_C08_COLUMNS if c.ref == "0250")
        assert "days" in col_0250.name.lower()

    def test_crr_c08_refs_unique(self) -> None:
        refs = [col.ref for col in CRR_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestB31C08ColumnDefinitions:
    """Tests for Basel 3.1 OF 08.01 column definitions."""

    def test_b31_c08_no_pd_column(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0010" not in refs

    def test_b31_c08_no_double_default(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0220" not in refs

    def test_b31_c08_no_supporting_factors(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0255" not in refs
        assert "0256" not in refs
        assert "0257" not in refs

    def test_b31_c08_has_on_bs_netting(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0035" in refs

    def test_b31_c08_has_slotting_fccm(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0101" in refs
        assert "0102" in refs
        assert "0103" in refs
        assert "0104" in refs

    def test_b31_c08_has_defaulted_breakdowns(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0125" in refs
        assert "0265" in refs

    def test_b31_c08_has_post_model_adjustments(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0251" in refs
        assert "0252" in refs
        assert "0253" in refs
        assert "0254" in refs

    def test_b31_c08_has_output_floor(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0275" in refs
        assert "0276" in refs

    def test_b31_c08_has_el_adjustments(self) -> None:
        refs = {col.ref for col in B31_C08_COLUMNS}
        assert "0281" in refs
        assert "0282" in refs

    def test_b31_c08_refs_unique(self) -> None:
        refs = [col.ref for col in B31_C08_COLUMNS]
        assert len(refs) == len(set(refs))


class TestIRBRowSections:
    """Tests for IRB row section definitions (C 08.01 / OF 08.01)."""

    def test_crr_irb_has_3_sections(self) -> None:
        assert len(CRR_IRB_ROW_SECTIONS) == 3

    def test_crr_irb_section_names(self) -> None:
        names = [s.name for s in CRR_IRB_ROW_SECTIONS]
        assert "Total and Supporting Factors" in names
        assert "Breakdown by Exposure Types" in names
        assert "Calculation Approaches" in names

    def test_crr_irb_total_starts_with_0010(self) -> None:
        total_section = CRR_IRB_ROW_SECTIONS[0]
        assert total_section.rows[0].ref == "0010"

    def test_crr_irb_has_supporting_factor_rows(self) -> None:
        total_section = CRR_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" in refs
        assert "0016" in refs

    def test_crr_irb_has_alt_re_treatment(self) -> None:
        calc_section = CRR_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" in refs

    def test_crr_irb_all_refs_unique(self) -> None:
        all_refs = [r.ref for s in CRR_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))

    def test_b31_irb_has_3_sections(self) -> None:
        assert len(B31_IRB_ROW_SECTIONS) == 3

    def test_b31_irb_no_supporting_factor_rows(self) -> None:
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0015" not in refs
        assert "0016" not in refs

    def test_b31_irb_has_revolving_commitments(self) -> None:
        total_section = B31_IRB_ROW_SECTIONS[0]
        refs = [r.ref for r in total_section.rows]
        assert "0017" in refs

    def test_b31_irb_has_ccf_breakdown_rows(self) -> None:
        exp_section = B31_IRB_ROW_SECTIONS[1]
        refs = [r.ref for r in exp_section.rows]
        assert "0031" in refs
        assert "0032" in refs
        assert "0033" in refs
        assert "0034" in refs
        assert "0035" in refs

    def test_b31_irb_no_alt_re_treatment(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0160" not in refs

    def test_b31_irb_has_purchased_receivables(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0175" in refs

    def test_b31_irb_has_ecai_rows(self) -> None:
        calc_section = B31_IRB_ROW_SECTIONS[2]
        refs = [r.ref for r in calc_section.rows]
        assert "0190" in refs
        assert "0200" in refs

    def test_b31_irb_all_refs_unique(self) -> None:
        all_refs = [r.ref for s in B31_IRB_ROW_SECTIONS for r in s.rows]
        assert len(all_refs) == len(set(all_refs))


class TestB31SAWeightBands:
    """Tests for Basel 3.1 risk weight bands."""

    def test_b31_rw_bands_ascending(self) -> None:
        rw_values = [rw for rw, _ in B31_SA_RISK_WEIGHT_BANDS]
        assert rw_values == sorted(rw_values)

    def test_b31_rw_bands_has_27_entries(self) -> None:
        assert len(B31_SA_RISK_WEIGHT_BANDS) == 27

    def test_b31_rw_bands_has_new_weights(self) -> None:
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 0.15 in rw_dict
        assert 0.25 in rw_dict
        assert 0.30 in rw_dict
        assert 0.40 in rw_dict
        assert 0.45 in rw_dict
        assert 0.60 in rw_dict
        assert 0.65 in rw_dict

    def test_b31_rw_bands_has_400pct(self) -> None:
        rw_dict = dict(B31_SA_RISK_WEIGHT_BANDS)
        assert 4.00 in rw_dict
        assert 3.70 not in rw_dict


class TestFrameworkHelpers:
    """Tests for framework-aware helper functions."""

    def test_get_c07_columns_crr(self) -> None:
        assert get_c07_columns("CRR") is CRR_C07_COLUMNS

    def test_get_c07_columns_b31(self) -> None:
        assert get_c07_columns("BASEL_3_1") is B31_C07_COLUMNS

    def test_get_c08_columns_crr(self) -> None:
        assert get_c08_columns("CRR") is CRR_C08_COLUMNS

    def test_get_c08_columns_b31(self) -> None:
        assert get_c08_columns("BASEL_3_1") is B31_C08_COLUMNS

    def test_get_sa_row_sections_crr(self) -> None:
        assert get_sa_row_sections("CRR") is CRR_SA_ROW_SECTIONS

    def test_get_sa_row_sections_b31(self) -> None:
        assert get_sa_row_sections("BASEL_3_1") is B31_SA_ROW_SECTIONS

    def test_get_irb_row_sections_crr(self) -> None:
        assert get_irb_row_sections("CRR") is CRR_IRB_ROW_SECTIONS

    def test_get_irb_row_sections_b31(self) -> None:
        assert get_irb_row_sections("BASEL_3_1") is B31_IRB_ROW_SECTIONS

    def test_get_sa_risk_weight_bands_crr(self) -> None:
        assert get_sa_risk_weight_bands("CRR") is SA_RISK_WEIGHT_BANDS

    def test_get_sa_risk_weight_bands_b31(self) -> None:
        assert get_sa_risk_weight_bands("BASEL_3_1") is B31_SA_RISK_WEIGHT_BANDS
