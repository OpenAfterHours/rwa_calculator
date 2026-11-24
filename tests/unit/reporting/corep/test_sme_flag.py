"""The SA "of which: SME" flag (``corep/sme_flag.py``) and the two templates that read it.

Row 0020 of C 07.00 / OF 07.00 is "All exposures to SMEs" (PS1/26 Annex II
p.88; CRR Annex II C 07.00), OF 07.00 rows 0343 / 0344 are the SME of-which rows
of 0341 / 0342 (p.91), and the C 09.01 "of which: SME" rows are defined as "Same
definition as for row 0020". The flag used to read the exposure-class NAME, so
an SME obligor's leg under any other class name — the loan-splitter's
``commercial_mortgage`` / ``residential_mortgage`` secured leg, an SME's
``specialised_lending`` exposure — left every SME row while the sealed
``is_sme`` said SME (plan P1.339). C 09 carried a verbatim copy of the same
ladder, so a fix to one template alone would split the cross-template SME ties
(``boe_b0990``-``boe_b0992``).

The frames below carry only columns the aggregator exit seals
(``exposure_class``, ``is_sme``, ``exposure_subclass``), in combinations the
classifier and the splitter produce (LESSONS C11(c)).

References:
- PRA PS1/26 Annex II, OF 07.00 row 0020 (p.88) and rows 0341-0344 (p.91)
- CRR Annex II (COREP), C 07.00 row 0020; C 09.01 rows 0075 / 0085 / 0095
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep import c07, c09
from rwa_calc.reporting.corep.sme_flag import sme_exposure_expr

#: One leg per shape, and whether it is an exposure to an SME.
_LEGS: dict[str, tuple[str, bool, str | None, bool]] = {
    # reference: (exposure_class, is_sme, exposure_subclass, expected flag)
    "SME_SPLIT_SECURED": ("commercial_mortgage", True, "corporate_sme", True),
    "SME_SL": ("specialised_lending", True, None, True),
    "SME_CORPORATE": ("corporate_sme", True, "corporate_sme", True),
    "LARGE_CORPORATE": ("corporate", False, "corporate_financial_large", False),
    "NON_SME_SPLIT_SECURED": ("commercial_mortgage", False, "corporate_other", False),
    "RETAIL": ("retail_other", False, None, False),
}


def _sealed_legs() -> pl.DataFrame:
    """The ``_LEGS`` shapes as a sealed-ledger frame."""
    return pl.DataFrame(
        {
            "exposure_reference": list(_LEGS),
            "exposure_class": [leg[0] for leg in _LEGS.values()],
            "is_sme": [leg[1] for leg in _LEGS.values()],
            "exposure_subclass": [leg[2] for leg in _LEGS.values()],
        },
        schema_overrides={"exposure_subclass": pl.String},
    )


def _flags(frame: pl.DataFrame) -> list[bool]:
    expr = sme_exposure_expr(set(frame.columns))
    assert expr is not None, "the frame carries an SME source - the flag must be derived"
    return frame.select(expr.alias("flag"))["flag"].to_list()


class TestSealedSmeFlag:
    """The flag reads the obligor's sealed ``is_sme``, whatever the class name says."""

    def test_the_frame_holds_sme_legs_under_non_sme_class_names(self) -> None:
        """Adequacy: unless an SME leg carries a class name without "sme", the
        old class-name reading and the sealed reading agree and nothing here can
        fail."""
        frame = _sealed_legs()

        hidden = frame.filter(pl.col("is_sme") & ~pl.col("exposure_class").str.contains("sme"))

        assert set(hidden["exposure_reference"].to_list()) == {"SME_SPLIT_SECURED", "SME_SL"}

    def test_every_sme_obligor_leg_is_flagged(self) -> None:
        """The split secured leg and the SL exposure of an SME are exposures to
        an SME; the large corporate, the non-SME split leg and retail are not."""
        assert _flags(_sealed_legs()) == [leg[3] for leg in _LEGS.values()]

    def test_the_class_name_still_counts_when_the_flag_is_unset(self) -> None:
        """No leg the old reading counted leaves the SME rows: a corporate_sme
        class with ``is_sme`` null is still SME."""
        frame = pl.DataFrame(
            {"exposure_class": ["corporate_sme", "corporate"], "is_sme": [None, None]},
            schema_overrides={"is_sme": pl.Boolean},
        )

        assert _flags(frame) == [True, False]


class TestSyntheticFrameRungs:
    """Frames that seal neither ``is_sme`` nor ``exposure_subclass`` keep the old rungs."""

    def test_the_unsealed_supporting_factor_column_decides_before_the_class_name(self) -> None:
        frame = pl.DataFrame(
            {
                "exposure_class": ["corporate", "corporate_sme"],
                "sme_supporting_factor_eligible": [True, None],
            },
            schema_overrides={"sme_supporting_factor_eligible": pl.Boolean},
        )

        assert _flags(frame) == [True, False]

    def test_the_class_name_is_the_last_rung(self) -> None:
        frame = pl.DataFrame({"exposure_class": ["corporate_sme", "commercial_mortgage", None]})

        assert _flags(frame) == [True, False, False]

    def test_a_frame_with_no_sme_source_derives_no_flag(self) -> None:
        assert sme_exposure_expr({"exposure_reference", "ead_final"}) is None


class TestTemplatesShareOneFlag:
    """C 07.00 ``c07_sme`` and C 09 ``c09_sme`` are the same flag on every leg."""

    @pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
    def test_c09_selects_exactly_the_legs_c07_row_0020_selects(self, framework: str) -> None:
        """The C 09.01 of-which SME rows are "Same definition as for row 0020";
        one template reading the sealed flag and the other the class name breaks
        ``boe_b0990``-``boe_b0992`` on every SME leg under another class name."""
        frame = _sealed_legs()
        cols = set(frame.columns)

        c07_flag = c07._prepare(frame, cols, framework)["c07_sme"]
        c09_flag = frame.select(c09._sme_expr(cols).alias("c09_sme"))["c09_sme"]

        assert c07_flag.to_list() == [leg[3] for leg in _LEGS.values()]
        assert c09_flag.to_list() == c07_flag.to_list()
