"""Unit tests for D4.80: the Basel 3.1 UKB CR5 columns sit at their published letters.

Tests cover:
    - The risk-weight block of UKB CR5 is a-y, aa, ab (27 named weights), then
      ac Others, ad Total, ae Of which unrated, then ba-bd. The letter z is not
      used, so no column z is emitted and no band is 300%.
    - Each published weight's exposure value is reported in that weight's
      published column (the guard against re-lettering the block in sequence,
      which would move 400% to z, 1250% to aa and Others to ab).
    - A leg at a weight the template does not name (300%, e.g. a blended CIU
      look-through weight) is reported in ac "Others", not in a column z.
    - UK CR5 (CRR) keeps its own layout, a-n bands, o Other, p Total, q unrated.
    - When the published workbook is on disk, the transcription below is read
      back from it (skips otherwise: docs/assets is git-ignored).

Why: UKB CR5 is a fixed-format template. A column the template does not have
cannot be disclosed, and an exposure in it is missing from the "Others" column
where the template puts it. The code emitted a 28th band, z "300%", which no
PS1/26 rule assigns and the published layout does not hold.

References:
    - PS1/26 Disclosure (CRR) Part Art. 11(c) (docs/assets/ps126app1.pdf page
      index 467): CR5 is disclosed "in accordance with the Template UKB CR5 of
      Annex XIX and the relevant instructions set out in Annex XX"; para 6.50
      (page index 470) links the Annex XIX workbook.
    - PS1/26 Annex XIX, sheet 'UKB CR5', rows 11-12
      (docs/assets/ps1-26-annex-xix-credit-risk-sa-disclosure-templates.xlsx,
      fetched by scripts/download_docs.py): the weights and their letters.
    - PS1/26 Annex XX (docs/assets/ps1-26-annex-xx-credit-risk-sa-disclosure-instructions.pdf
      page index 4-6): "Fixed format", columns "a - ac Risk weight", "ad Total",
      "ae Of which unrated", "ba".."bd".
    - CRR Annex XX (docs/assets/crr-annex-xx-instructions-regarding-disclosure.PDF
      page index 3): UK CR5 columns "a - o Risk weight", "p Total", "q Of which unrated".
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_calc.reporting.pillar3.templates import get_cr5_columns, get_cr5_risk_weights
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# The published layouts, transcribed from the templates (not from the code)
# ---------------------------------------------------------------------------

# PS1/26 Annex XIX, sheet 'UKB CR5': row 11 holds the weights, row 12 the letters.
# z is absent between y (250%) and aa (400%).
_PUBLISHED_UKB_CR5_BANDS: tuple[tuple[str, float], ...] = (
    ("a", 0.00),
    ("b", 0.02),
    ("c", 0.04),
    ("d", 0.10),
    ("e", 0.15),
    ("f", 0.20),
    ("g", 0.25),
    ("h", 0.30),
    ("i", 0.35),
    ("j", 0.40),
    ("k", 0.45),
    ("l", 0.50),
    ("m", 0.60),
    ("n", 0.65),
    ("o", 0.70),
    ("p", 0.75),
    ("q", 0.80),
    ("r", 0.85),
    ("s", 1.00),
    ("t", 1.05),
    ("u", 1.10),
    ("v", 1.30),
    ("w", 1.35),
    ("x", 1.50),
    ("y", 2.50),
    ("aa", 4.00),
    ("ab", 12.50),
)
_UKB_OTHERS, _UKB_TOTAL, _UKB_UNRATED = "ac", "ad", "ae"
_UKB_EXPOSURE_BREAKDOWN = ("ba", "bb", "bc", "bd")

_PUBLISHED_REFS: dict[str, list[str]] = {
    "BASEL_3_1": [
        *(ref for ref, _ in _PUBLISHED_UKB_CR5_BANDS),
        _UKB_OTHERS,
        _UKB_TOTAL,
        _UKB_UNRATED,
        *_UKB_EXPOSURE_BREAKDOWN,
    ],
    # CRR Annex XX: a-o risk weight (14 named weights + Others at o), p Total, q unrated.
    "CRR": list("abcdefghijklmnopq"),
}

_ASSETS = Path(__file__).resolve().parents[4] / "docs" / "assets"
_ANNEX_XIX = "ps1-26-annex-xix-credit-risk-sa-disclosure-templates.xlsx"

# CR5 row 7 = Corporates, row 14 = Collective investment undertakings.
_CORPORATES_ROW = "7"
_CIU_ROW = "14"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sa_legs(classes: list[str], risk_weights: list[float], eads: list[float]) -> pl.LazyFrame:
    """Minimal standardised legs, one per (class, risk weight, EAD); all unrated."""
    n = len(classes)
    return pl.LazyFrame(
        {
            "exposure_reference": [f"D480_{i}" for i in range(n)],
            "approach_applied": ["standardised"] * n,
            "exposure_class": classes,
            "ead_final": eads,
            "rwa_final": [ead * rw for ead, rw in zip(eads, risk_weights, strict=True)],
            "risk_weight": risk_weights,
            "drawn_amount": eads,
            "interest": [0.0] * n,
            "nominal_amount": [0.0] * n,
            "undrawn_amount": [0.0] * n,
            "exposure_type": ["loan"] * n,
        }
    )


def _cr5_row(generator: Pillar3Generator, data: pl.LazyFrame, row_ref: str) -> dict[str, object]:
    bundle = generator.generate_from_lazyframe(data, framework="BASEL_3_1")
    assert bundle.cr5 is not None, "CR5 was not emitted"
    rows = bundle.cr5.filter(pl.col("row_ref") == row_ref).to_dicts()
    assert len(rows) == 1, f"expected one CR5 row {row_ref!r}, got {len(rows)}"
    return rows[0]


@pytest.fixture
def generator() -> Pillar3Generator:
    return LedgerShimPillar3Generator()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class TestCR5PublishedColumnRefs:
    """The CR5 column refs are the published template's, in both regimes."""

    @pytest.mark.parametrize("framework", ["BASEL_3_1", "CRR"])
    def test_cr5_column_refs_match_the_published_template(self, framework: str) -> None:
        """UKB CR5 skips z (a-y, aa-ae, ba-bd); UK CR5 runs a-q.

        Fails before the fix for Basel 3.1 only: the code emitted z "300%".
        """
        # Arrange
        expected = _PUBLISHED_REFS[framework]

        # Act
        refs = [col.ref for col in get_cr5_columns(framework)]

        # Assert
        assert refs == expected

    def test_b31_cr5_band_weights_are_the_published_weights(self) -> None:
        """The Basel 3.1 band ladder is the 27 published weights, with no 300%."""
        # Arrange
        expected = [rate for _, rate in _PUBLISHED_UKB_CR5_BANDS]

        # Act
        rates = [rate for rate, _label in get_cr5_risk_weights("BASEL_3_1")]

        # Assert
        assert rates == pytest.approx(expected)
        assert 3.00 not in rates


# ---------------------------------------------------------------------------
# Behaviour: where an exposure is reported
# ---------------------------------------------------------------------------


class TestCR5PublishedColumnAllocation:
    """An exposure value is reported in the column the template gives its weight."""

    def test_b31_each_published_weight_reports_in_its_published_column(
        self, generator: Pillar3Generator
    ) -> None:
        """One corporate leg per published weight, each with its own EAD.

        Guards the published letters against a sequential re-lettering: with
        z dropped by position, 400% would report in z and 1250% in aa.
        """
        # Arrange
        rates = [rate for _, rate in _PUBLISHED_UKB_CR5_BANDS]
        eads = [1_000.0 + i for i in range(len(rates))]
        data = _sa_legs(["corporate"] * len(rates), rates, eads)
        expected = {ref: ead for (ref, _), ead in zip(_PUBLISHED_UKB_CR5_BANDS, eads, strict=True)}

        # Act
        row = _cr5_row(generator, data, _CORPORATES_ROW)

        # Assert
        assert {ref: row[ref] for ref in expected} == pytest.approx(expected)
        assert row[_UKB_OTHERS] == pytest.approx(0.0)
        assert row[_UKB_TOTAL] == pytest.approx(sum(eads))

    def test_b31_leg_at_an_unpublished_weight_reports_in_others(
        self, generator: Pillar3Generator
    ) -> None:
        """A 300% CIU leg (a blended look-through weight) is reported in ac Others.

        No PS1/26 column names 300%, so the template's "Others" column carries
        it. Before the fix it was reported in a column z the template lacks,
        and ac Others held 0.
        """
        # Arrange
        data = _sa_legs(["ciu"], [3.00], [250_000.0])

        # Act
        row = _cr5_row(generator, data, _CIU_ROW)

        # Assert
        assert "z" not in row
        assert row[_UKB_OTHERS] == pytest.approx(250_000.0)
        assert row[_UKB_TOTAL] == pytest.approx(250_000.0)


# ---------------------------------------------------------------------------
# Provenance: the transcription above is the workbook's
# ---------------------------------------------------------------------------


def test_transcription_matches_the_published_annex_xix_workbook() -> None:
    """Rows 11-12 of sheet 'UKB CR5' hold exactly the transcribed weights and letters.

    The workbook is git-ignored, so this skips without it
    (``scripts/download_docs.py`` fetches it).
    """
    # Arrange
    path = _ASSETS / _ANNEX_XIX
    if not path.exists():
        pytest.skip(f"{_ANNEX_XIX} is not in docs/assets (git-ignored): run download_docs.py")
    openpyxl = pytest.importorskip("openpyxl")
    sheet = openpyxl.load_workbook(path, read_only=True, data_only=True)["UKB CR5"]

    # Act
    weights, letters = (
        [cell for cell in row if cell is not None]
        for row in sheet.iter_rows(min_row=11, max_row=12, min_col=3, values_only=True)
    )
    published = list(zip(letters, weights, strict=False))

    # Assert
    assert published[: len(_PUBLISHED_UKB_CR5_BANDS) - 1] == list(_PUBLISHED_UKB_CR5_BANDS[:-1])
    assert published[len(_PUBLISHED_UKB_CR5_BANDS) - 1 :] == [("ab", "1 250%"), ("ac", "Others")]
    assert letters[-2:] == [_UKB_TOTAL, _UKB_UNRATED]
