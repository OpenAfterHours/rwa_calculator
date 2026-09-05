"""
Guarantor SA risk-weight expression builders.

Pipeline position:
    Compiled by the guarantee-substitution paths — the IRB branch
    (``engine/irb/guarantee.py::_compute_guarantor_rw_sa``) and the SA
    branch (``engine/sa/rw_adjustments.py::_build_guarantor_rw_expr``). This
    module is the single source for "what SA risk weight does this guarantor
    attract?".

Key responsibilities:
- Reproduce the SA-side guarantor branch chain and order exactly so SA and
  IRB compile the same chain (``build_guarantor_rw_expr``), parameterised on
  column names and caller-owned expressions.
- Drive every regulatory value from the rulepack (CQS risk-weight
  LookupTables + invariant scalars) so the pack is the single source of
  truth and this module declares zero new regulatory literals.
- Delegate institution and corporate pricing to
  ``build_institution_guarantor_rw_expr`` / ``build_corporate_guarantor_rw_expr``.

References:
- CRR Art. 114: central govt / central bank risk weights (incl. 114(4)/(7)
  domestic-currency 0% and the unconditional, regime-invariant 114(3) ECB 0%)
- CRR Art. 115: RGLA risk weights (115(1)(b) Table 1B own-rating)
- CRR Art. 116: PSE risk weights (116(2) Table 2A own-rating)
- CRR Art. 117: MDB risk weights — 117(1) non-named MDBs take the institution
  treatment (Art. 120/121, no short-term preferential); 117(2) named MDBs 0%.
  The dedicated MDB Table 2B is PRA PS1/26 Art. 117(1)(a)/(b) only.
- CRR Art. 118: international organisations — 0% unconditional
- CRR Art. 119-121: institution risk weights (via
  ``build_institution_guarantor_rw_expr``)
- CRR Art. 122: corporate risk weights (via
  ``build_corporate_guarantor_rw_expr``)
- CRR Art. 235 / PRA PS1/26 Art. 235: SA risk-weight substitution method
  (RWSM) for unfunded credit protection
- CRR Art. 306, CRE54.14-15: QCCP 2% / 4% risk weights
- PRA PS1/26 Art. 114-122: Basel 3.1 equivalents (PSE / RGLA tables are
  framework-identical; institution ECRA / SCRA, corporate Table 6 and the
  non-named-MDB treatment differ and are selected via ``is_basel_3_1``)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from decimal import Decimal

# =============================================================================
# RULEPACK-SOURCED REGULATORY VALUES
#
# The CQS risk-weight LookupTables and invariant SA scalars live in the
# common/CRR/B31 rulepack packs. They are read back here once at module load
# as the canonical Decimal maps / scalars the builders index — keeping the
# pack the single source of truth while the builder bodies stay byte-identical
# (``float(table[key])`` at the same conversion boundary as before).
# =============================================================================

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# CQS-enum-keyed CRR risk-weight tables (Art. 114-122, 129).
_CGCB_RW = cast("dict[CQS, Decimal]", dict(_CRR_PACK.lookup("cgcb_risk_weights").entries))
_MDB_RW = cast("dict[CQS, Decimal]", dict(_CRR_PACK.lookup("mdb_risk_weights_table_2b").entries))
_PSE_OWN_RW = cast(
    "dict[CQS, Decimal]", dict(_CRR_PACK.lookup("pse_risk_weights_own_rating").entries)
)
_RGLA_OWN_RW = cast(
    "dict[CQS, Decimal]", dict(_CRR_PACK.lookup("rgla_risk_weights_own_rating").entries)
)
_CORPORATE_RW = cast("dict[CQS, Decimal]", dict(_CRR_PACK.lookup("corporate_risk_weights").entries))
_INSTITUTION_RW_CRR = cast(
    "dict[CQS, Decimal]", dict(_CRR_PACK.lookup("institution_rw_crr").entries)
)
_INSTITUTION_SHORT_TERM_RW_CRR = cast(
    "dict[CQS, Decimal]", dict(_CRR_PACK.lookup("institution_short_term_rw_crr").entries)
)

# Basel-3.1 institution ECRA tables (PS1/26 Art. 120) — sourced from the B31 overlay.
_INSTITUTION_RW_B31_ECRA = cast(
    "dict[CQS, Decimal]", dict(_B31_PACK.lookup("institution_rw_b31_ecra").entries)
)
_INSTITUTION_SHORT_TERM_RW_B31_ECRA = cast(
    "dict[CQS, Decimal]", dict(_B31_PACK.lookup("institution_short_term_rw_b31_ecra").entries)
)

# Basel-3.1 SCRA grade -> RW (PS1/26 Art. 121, str-keyed) and corporate Table 6
# (PS1/26 Art. 122(2), raw int|None keys).
_B31_SCRA_RW = cast("dict[str, Decimal]", dict(_B31_PACK.lookup("b31_scra_risk_weights").entries))
_B31_SCRA_SHORT_TERM_RW = cast(
    "dict[str, Decimal]", dict(_B31_PACK.lookup("b31_scra_short_term_risk_weights").entries)
)
_B31_CORPORATE_RW = cast(
    "dict[int | None, Decimal]", dict(_B31_PACK.lookup("b31_corporate_risk_weights").entries)
)

# Invariant SA risk-weight scalars (Decimal, float()-ed inline by the builders).
_IO_ZERO_RW: Decimal = _CRR_PACK.scalar_param("io_zero_rw").value
_MDB_NAMED_ZERO_RW: Decimal = _CRR_PACK.scalar_param("mdb_named_zero_rw").value
_MDB_UNRATED_RW: Decimal = _CRR_PACK.scalar_param("mdb_unrated_rw").value
_PSE_UNRATED_DEFAULT_RW: Decimal = _CRR_PACK.scalar_param("pse_unrated_default_rw").value
_RGLA_DOMESTIC_CURRENCY_RW: Decimal = _CRR_PACK.scalar_param("rgla_domestic_currency_rw").value

# Invariant SA risk weights pre-converted to float (QCCP Art. 306).
_QCCP_CLIENT_CLEARED_RW = scalar_value(_CRR_PACK.scalar_param("qccp_client_cleared_rw"))
_QCCP_PROPRIETARY_RW = scalar_value(_CRR_PACK.scalar_param("qccp_proprietary_rw"))


@cites("CRR Art. 114")
@cites("CRR Art. 115")
@cites("CRR Art. 116")
@cites("CRR Art. 117")
@cites("PS1/26, paragraph 117")
@cites("CRR Art. 118")
@cites("CRR Art. 235")
def build_guarantor_rw_expr(
    *,
    exposure_class_col: str,
    entity_type_col: str,
    cqs_col: str,
    country_code_col: str,
    ccp_client_cleared_col: str,
    scra_grade_col: str,
    is_basel_3_1: bool,
    domestic_cgcb_expr: pl.Expr | None = None,
    short_term_flag_col: str | None = None,
    no_guarantee_expr: pl.Expr | None = None,
) -> pl.Expr:
    """Build the full when/then chain that maps a guarantor to its SA RW.

    Dispatches on the guarantor's SA exposure class (derived from
    ``ENTITY_TYPE_TO_SA_CLASS`` by the caller — e.g. the CRM processor)
    rather than regex on entity_type, ensuring all valid entity types are
    covered. Reproduces the SA-side reference chain
    (``engine/sa/rw_adjustments.py::_build_guarantor_rw_expr``) branch-for-branch.

    Branch order (first match wins):
        no guarantee -> null (only when ``no_guarantee_expr`` is supplied)
        domestic CGCB sovereign (Art. 114(4)/(7)) -> 0%
        CGCB CQS table (Art. 114 Table 1)
        CCP (CRR Art. 306, CRE54.14-15)
        International Organisation (Art. 118) -> 0%
        Named MDB (Art. 117(2)) -> 0%
        Non-named MDB (Art. 117(1)) — PS1/26 Table 2B under Basel 3.1;
            institution treatment (Art. 120 Table 3 / Art. 121 unrated,
            no short-term preferential) under CRR
        Institution (ECRA / SCRA via build_institution_guarantor_rw_expr —
            short-term Art. 120(2) Table 4 when ``short_term_flag_col``
            evaluates True, otherwise long-term Table 3)
        PSE (Art. 116(2) Table 2A, sovereign-derived for unrated)
        RGLA (Art. 115(1)(b) Table 1B, sovereign-derived for unrated)
        Corporate (Art. 122 corporate CQS table)
        else -> null (no substitution)

    The unrated PSE / RGLA fallback is the documented SA-side approximation
    (no guarantor sovereign-CQS join exists in the CRM column production):
    a GB guarantor receives the 20% RGLA / PSE domestic-currency treatment,
    any other country the conservative 100% unrated default — NOT the full
    Art. 116(1) Table 2 / Art. 115(1)(a) Table 1A sovereign-derived lookup.

    Args:
        exposure_class_col: Name of the guarantor SA exposure-class column
            (e.g. ``guarantor_exposure_class``).
        entity_type_col: Name of the guarantor entity-type column — used for
            the CCP override and the named-MDB (``mdb_named``) carve-out.
        cqs_col: Name of the integer guarantor CQS column.
        country_code_col: Name of the guarantor country-code column — drives
            the unrated PSE / RGLA GB-vs-other approximation.
        ccp_client_cleared_col: Name of the Boolean client-cleared flag
            column (null -> proprietary 2%).
        scra_grade_col: Name of the guarantor SCRA-grade column threaded
            into ``build_institution_guarantor_rw_expr`` for the B31 unrated
            institution dispatch.
        is_basel_3_1: Select PS1/26 tables (institution ECRA / corporate
            Table 6 / MDB Table 2B) when True, CRR tables when False — for
            MDBs that means the Art. 117(1) institution treatment, since CRR
            has no MDB table. PSE / RGLA / IO / CCP values are
            framework-identical. Threaded by both live call sites from the
            cited ``sa_revised_risk_weight_tables`` pack Feature.
        domestic_cgcb_expr: Caller-supplied Art. 114(4)/(7) domestic-currency
            test (SA and IRB derive domesticity differently). ``None``
            disables the domestic 0% branch (treated as never-domestic).
        short_term_flag_col: Optional Boolean column routing institution
            guarantors to the Art. 120(2) Table 4 short-term dicts. The IRB
            chain passes ``None`` today.
        no_guarantee_expr: Caller-owned leading guard — rows where it
            evaluates True yield null (no substitution priced). ``None``
            omits the guard (the chain prices every row).

    Returns:
        Float64 Polars expression evaluating to the guarantor's SA RW, or
        null where no substitution treatment exists.
    """
    gec = pl.col(exposure_class_col).fill_null("")
    # PSE/RGLA Art. 116(2)/115(1)(b) unrated fallback: domestic-GB guarantors
    # get the RGLA/PSE 20% domestic-currency treatment; otherwise the
    # conservative 100% PSE/RGLA unrated default applies.
    sovereign_derived_unrated = _pse_rgla_unrated_fallback_expr(country_code_col)

    cgcb_unrated = float(_CGCB_RW[CQS.UNRATED])

    is_domestic_guarantor = domestic_cgcb_expr if domestic_cgcb_expr is not None else pl.lit(False)
    skip_substitution = no_guarantee_expr if no_guarantee_expr is not None else pl.lit(False)

    return (
        pl.when(skip_substitution)
        .then(pl.lit(None).cast(pl.Float64))
        # Art. 114(4)/(7): Domestic sovereign -> 0% regardless of CQS.
        .when((gec == "central_govt_central_bank") & is_domestic_guarantor)
        .then(pl.lit(0.0))
        # CGCB guarantors via CQS (Table 1 — sovereign weights).
        .when(gec == "central_govt_central_bank")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                _CGCB_RW,
                cgcb_unrated,
            )
        )
        # CCP guarantors: 2% proprietary / 4% client-cleared
        # (CRR Art. 306, CRE54.14-15) — overrides institution CQS weights.
        .when(pl.col(entity_type_col) == "ccp")
        .then(
            pl.when(pl.col(ccp_client_cleared_col).fill_null(False))
            .then(pl.lit(_QCCP_CLIENT_CLEARED_RW))
            .otherwise(pl.lit(_QCCP_PROPRIETARY_RW))
        )
        # International Organisation (Art. 118): 0% unconditional.
        .when(gec == "international_organisation")
        .then(pl.lit(float(_IO_ZERO_RW)))
        # Named MDB (Art. 117(2)): 0% unconditional.
        .when((gec == "mdb") & (pl.col(entity_type_col).fill_null("") == "mdb_named"))
        .then(pl.lit(float(_MDB_NAMED_ZERO_RW)))
        # Rated / unrated non-named MDB (Art. 117(1)) — framework-divergent:
        #   PS1/26 Art. 117(1)(a)/(b): the dedicated Basel 3.1 MDB Table 2B
        #     (CQS2 30%, unrated 50%).
        #   CRR Art. 117(1): non-named MDBs "shall be treated in the same manner
        #     as exposures to institutions" — Art. 120 Table 3 when rated, the
        #     Art. 121 unrated institution fallback (100%) otherwise. There is no
        #     MDB table in CRR. The Art. 119(2)/120(2)/121(3) short-term
        #     preferential "shall not be applied", so ``short_term_flag_col`` is
        #     deliberately NOT threaded into this branch (unlike the institution
        #     branch below). Mirrors the direct, non-guarantor CRR MDB path in
        #     ``sa/risk_weights.py::_apply_crr_risk_weight_overrides`` (P1.253).
        .when(gec == "mdb")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                _MDB_RW,
                float(_MDB_UNRATED_RW),
            )
            if is_basel_3_1
            else build_institution_guarantor_rw_expr(cqs_col, is_basel_3_1=False)
        )
        # Institution guarantors — RW driven from institution_rw_crr /
        # institution_rw_b31_ecra so the pack remains the single source of
        # truth. When the short-term flag evaluates True (CRR/PS1/26
        # Art. 120(2)), the short-term Table 4 dicts apply instead.
        .when(gec == "institution")
        .then(
            build_institution_guarantor_rw_expr(
                cqs_col,
                is_basel_3_1,
                short_term_flag_col=short_term_flag_col,
                scra_grade_col=scra_grade_col,
            )
        )
        # PSE guarantors — Art. 116(2) Table 2A for rated, sovereign-derived for unrated.
        .when(gec == "pse")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                _PSE_OWN_RW,
                sovereign_derived_unrated,
            )
        )
        # RGLA guarantors — Art. 115(1)(b) Table 1B for rated, sovereign-derived for unrated.
        .when(gec == "rgla")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                _RGLA_OWN_RW,
                sovereign_derived_unrated,
            )
        )
        # Corporate guarantors — Art. 122 corporate CQS table.
        # Basel 3.1 (PRA PS1/26 Art. 122(2) Table 6): CQS3 = 75% (CRR: 100%);
        # PRA retains CQS5 = 150%. Gated on framework so CRR runs are
        # unchanged.
        .when(gec.is_in(["corporate", "corporate_sme"]))
        .then(build_corporate_guarantor_rw_expr(cqs_col, is_basel_3_1))
        .otherwise(pl.lit(None).cast(pl.Float64))
    )


@cites("CRR Art. 119")
@cites("CRR Art. 120")
@cites("CRR Art. 121")
def build_institution_guarantor_rw_expr(
    cqs_col: str,
    is_basel_3_1: bool,
    short_term_flag_col: str | None = None,
    scra_grade_col: str | None = None,
) -> pl.Expr:
    """Build a CQS → institution risk weight expression from the canonical tables.

    Used by SA and IRB guarantee substitution to look up the RW to apply to the
    guaranteed portion when the guarantor is an institution. Drives values from
    ``institution_rw_crr`` / ``institution_rw_b31_ecra`` (long-term, Art. 120
    Table 3) or ``institution_short_term_rw_crr`` /
    ``institution_short_term_rw_b31_ecra`` (short-term, Art. 120(2) Table 4) so
    there is a single source of truth.

    Args:
        cqs_col: Name of the integer CQS column on the frame.
        is_basel_3_1: Select PS1/26 ECRA table when True, CRR Art. 120 Table 3
            when False.
        short_term_flag_col: Optional name of a Boolean column. When provided,
            rows where the column evaluates True route to the Art. 120(2)
            Table 4 short-term dict (residual maturity ≤ 3 months); rows where
            the column is False or null use the long-term Table 3 dict.
        scra_grade_col: Optional name of a Utf8 column carrying the guarantor's
            SCRA grade ("A" / "A_ENHANCED" / "B" / "C"). When provided AND
            ``is_basel_3_1`` is True, rows whose CQS column is null (i.e.
            unrated under ECRA) dispatch via PRA PS1/26 Art. 121 Table 5 SCRA
            grades using ``b31_scra_risk_weights`` (long-term) or
            ``b31_scra_short_term_risk_weights`` (short-term branch when the
            ``short_term_flag_col`` evaluates True). A null/missing SCRA grade
            falls back to ``b31_scra_risk_weights["C"]`` per CRE20.21
            conservative-fallback. The CRR path and the rated B31 path
            (CQS 1-6) are entirely unaffected.

    Returns:
        Float64 Polars expression evaluating to the institution RW.
    """
    long_term = _INSTITUTION_RW_B31_ECRA if is_basel_3_1 else _INSTITUTION_RW_CRR
    short_term = (
        _INSTITUTION_SHORT_TERM_RW_B31_ECRA if is_basel_3_1 else _INSTITUTION_SHORT_TERM_RW_CRR
    )
    col = pl.col(cqs_col)
    use_scra = is_basel_3_1 and scra_grade_col is not None

    def _scra_branch(table: dict[str, Decimal]) -> pl.Expr:
        scra = pl.col(cast("str", scra_grade_col))
        # CRE20.21 conservative fallback: null/missing SCRA grade -> Grade C.
        return (
            pl.when(scra == "A_ENHANCED")
            .then(pl.lit(float(table["A_ENHANCED"])))
            .when(scra == "A")
            .then(pl.lit(float(table["A"])))
            .when(scra == "B")
            .then(pl.lit(float(table["B"])))
            .otherwise(pl.lit(float(table["C"])))
        )

    def _branch(table: dict[CQS, Decimal], scra_table: dict[str, Decimal]) -> pl.Expr:
        rated = (
            pl.when(col == 1)
            .then(pl.lit(float(table[CQS.CQS1])))
            .when(col == 2)
            .then(pl.lit(float(table[CQS.CQS2])))
            .when(col == 3)
            .then(pl.lit(float(table[CQS.CQS3])))
            .when(col.is_in([4, 5]))
            .then(pl.lit(float(table[CQS.CQS4])))
            .when(col == 6)
            .then(pl.lit(float(table[CQS.CQS6])))
            .otherwise(pl.lit(float(table[CQS.UNRATED])))
        )
        if not use_scra:
            return rated
        # B31 + SCRA available: route unrated (null CQS) rows via SCRA grades.
        return pl.when(col.is_null()).then(_scra_branch(scra_table)).otherwise(rated)

    long_branch = _branch(long_term, _B31_SCRA_RW)
    short_branch = _branch(short_term, _B31_SCRA_SHORT_TERM_RW)

    if short_term_flag_col is None:
        return long_branch

    is_short_term = pl.col(short_term_flag_col).fill_null(False)
    return pl.when(is_short_term).then(short_branch).otherwise(long_branch)


@cites("CRR Art. 122")
def build_corporate_guarantor_rw_expr(
    cqs_col: str,
    is_basel_3_1: bool,
) -> pl.Expr:
    """Build a CQS → corporate risk weight expression from the canonical tables.

    Used by SA and IRB guarantee substitution to look up the RW to apply to the
    guaranteed portion when the guarantor is a corporate. Drives values from
    ``corporate_risk_weights`` (CRR Art. 122 Table 5) or
    ``b31_corporate_risk_weights`` (PRA PS1/26 Art. 122(2) Table 6) so there is
    a single source of truth — and B3.1 corporate CQS3 correctly maps to 75%
    (Table 6) instead of CRR Table 5's 100%.

    Args:
        cqs_col: Name of the integer CQS column on the frame.
        is_basel_3_1: Select PS1/26 Art. 122(2) Table 6 when True, CRR Art. 122
            Table 5 when False.

    Returns:
        Float64 Polars expression evaluating to the corporate RW.
    """
    col = pl.col(cqs_col)
    if is_basel_3_1:
        rw_1 = float(_B31_CORPORATE_RW[1])
        rw_2 = float(_B31_CORPORATE_RW[2])
        rw_3 = float(_B31_CORPORATE_RW[3])
        rw_4 = float(_B31_CORPORATE_RW[4])
        rw_5 = float(_B31_CORPORATE_RW[5])
        rw_6 = float(_B31_CORPORATE_RW[6])
        rw_unrated = float(_B31_CORPORATE_RW[None])
    else:
        rw_1 = float(_CORPORATE_RW[CQS.CQS1])
        rw_2 = float(_CORPORATE_RW[CQS.CQS2])
        rw_3 = float(_CORPORATE_RW[CQS.CQS3])
        rw_4 = float(_CORPORATE_RW[CQS.CQS4])
        rw_5 = float(_CORPORATE_RW[CQS.CQS5])
        rw_6 = float(_CORPORATE_RW[CQS.CQS6])
        rw_unrated = float(_CORPORATE_RW[CQS.UNRATED])

    return (
        pl.when(col == 1)
        .then(pl.lit(rw_1))
        .when(col == 2)
        .then(pl.lit(rw_2))
        .when(col == 3)
        .then(pl.lit(rw_3))
        .when(col == 4)
        .then(pl.lit(rw_4))
        .when(col == 5)
        .then(pl.lit(rw_5))
        .when(col == 6)
        .then(pl.lit(rw_6))
        .otherwise(pl.lit(rw_unrated))
    )


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _pse_rgla_unrated_fallback_expr(country_code_col: str | None) -> pl.Expr:
    """Unrated PSE / RGLA fallback: GB -> 20% domestic treatment, else -> 100%.

    The documented SA-side approximation (no guarantor sovereign-CQS join
    exists in the CRM column production): a GB entity receives the 20%
    RGLA / PSE domestic-currency treatment (Art. 115(5)), any other — or
    unknown (``country_code_col=None``) — country the conservative 100%
    unrated default. NOT the full Art. 116(1) Table 2 / Art. 115(1)(a)
    Table 1A sovereign-derived lookup.
    """
    if country_code_col is None:
        return pl.lit(float(_PSE_UNRATED_DEFAULT_RW))
    return (
        pl.when(pl.col(country_code_col).fill_null("") == "GB")
        .then(pl.lit(float(_RGLA_DOMESTIC_CURRENCY_RW)))
        .otherwise(pl.lit(float(_PSE_UNRATED_DEFAULT_RW)))
    )


def _cqs_table_lookup_expr(
    cqs_col: str,
    table: dict[CQS, Decimal],
    unrated_default: pl.Expr | float,
) -> pl.Expr:
    """Build a when/then chain mapping a CQS-bearing column to RW from a CQS table.

    Parameterised on the CQS source column so it can drive any CQS-keyed
    regulatory table (CGCB Art. 114, MDB Table 2B Art. 117(1), PSE Table 2A
    Art. 116(2), RGLA Table 1B Art. 115(1)(b)). Caller controls the unrated
    fallback (constant or Polars expression).
    """
    cqs_order: list[CQS] = [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]
    expr = pl.when(pl.col(cqs_col) == int(cqs_order[0])).then(pl.lit(float(table[cqs_order[0]])))
    for cqs_val in cqs_order[1:]:
        expr = expr.when(pl.col(cqs_col) == int(cqs_val)).then(pl.lit(float(table[cqs_val])))
    if isinstance(unrated_default, pl.Expr):
        return expr.otherwise(unrated_default)
    return expr.otherwise(pl.lit(unrated_default))
