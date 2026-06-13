"""
Shared guarantor / entity SA risk-weight expression builder.

Pipeline position:
    Compiled by the guarantee-substitution stages — the IRB branch
    (``engine/irb/guarantee.py::_compute_guarantor_rw_sa``) and the SA
    namespace (``engine/sa/namespace.py::_build_guarantor_rw_expr``) — and
    by the hierarchy facility-share selection
    (``engine/stages/hierarchy/facility_undrawn.py`` via
    ``build_entity_rw_expr``). The builder is the single rulepack-compiled
    source for "what SA risk weight does this guarantor / entity attract?".

Key responsibilities:
- Reproduce the SA-side guarantor branch chain and order exactly
  (see ``engine/sa/namespace.py::_build_guarantor_rw_expr``), parameterised
  on column names and caller-owned expressions so SA, IRB and the hierarchy
  preview can all compile the same chain.
- Provide the entity-level SA-RW preview (``build_entity_rw_expr``) that
  routes an entity-type column through the ``ENTITY_TYPES_BY_SA_CLASS``
  buckets for the hierarchy facility-share riskiest-counterparty selection.
- Drive every regulatory value from the canonical table constants in
  ``crr_risk_weights`` / ``b31_risk_weights`` — this module declares zero
  new scalars.
- Delegate institution and corporate pricing to the existing
  ``build_institution_guarantor_rw_expr`` / ``build_corporate_guarantor_rw_expr``
  builders so the CQS dicts remain the single source of truth.

References:
- CRR Art. 114: central govt / central bank risk weights (incl. 114(4)/(7)
  domestic-currency 0%)
- CRR Art. 115: RGLA risk weights (115(1)(b) Table 1B own-rating)
- CRR Art. 116: PSE risk weights (116(2) Table 2A own-rating)
- CRR Art. 117: MDB risk weights (117(1) Table 2B; 117(2) named MDBs 0%)
- CRR Art. 118: international organisations — 0% unconditional
- CRR Art. 119-121: institution risk weights (via
  ``build_institution_guarantor_rw_expr``)
- CRR Art. 122: corporate risk weights (via
  ``build_corporate_guarantor_rw_expr``)
- CRR Art. 123: retail flat 75% (entity preview)
- CRR Art. 128: high-risk items flat 150% (entity preview)
- CRR Art. 235 / PRA PS1/26 Art. 235: SA risk-weight substitution method
  (RWSM) for unfunded credit protection
- CRR Art. 306, CRE54.14-15: QCCP 2% / 4% risk weights
- PRA PS1/26 Art. 114-122: Basel 3.1 equivalents (PSE / RGLA tables are
  framework-identical; institution ECRA / SCRA and corporate Table 6 differ
  and are selected via ``is_basel_3_1``)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    CORPORATE_RISK_WEIGHTS,
    HIGH_RISK_RW,
    IO_ZERO_RW,
    MDB_NAMED_ZERO_RW,
    MDB_RISK_WEIGHTS_TABLE_2B,
    MDB_UNRATED_RW,
    PSE_RISK_WEIGHTS_OWN_RATING,
    PSE_UNRATED_DEFAULT_RW,
    QCCP_CLIENT_CLEARED_RW,
    QCCP_PROPRIETARY_RW,
    RETAIL_RISK_WEIGHT,
    RGLA_DOMESTIC_CURRENCY_RW,
    RGLA_RISK_WEIGHTS_OWN_RATING,
    build_corporate_guarantor_rw_expr,
    build_institution_guarantor_rw_expr,
)
from rwa_calc.data.tables.entity_class_mapping import ENTITY_TYPES_BY_SA_CLASS
from rwa_calc.domain.enums import CQS, ExposureClass

if TYPE_CHECKING:
    from decimal import Decimal


@cites("CRR Art. 114")
@cites("CRR Art. 115")
@cites("CRR Art. 116")
@cites("CRR Art. 117")
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
    (``engine/sa/namespace.py::_build_guarantor_rw_expr``) branch-for-branch.

    Branch order (first match wins):
        no guarantee -> null (only when ``no_guarantee_expr`` is supplied)
        domestic CGCB sovereign (Art. 114(4)/(7)) -> 0%
        CGCB CQS table (Art. 114 Table 1)
        CCP (CRR Art. 306, CRE54.14-15)
        International Organisation (Art. 118) -> 0%
        Named MDB (Art. 117(2)) -> 0%
        MDB Table 2B (Art. 117(1))
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
            Table 6) when True, CRR tables when False. PSE / RGLA / MDB /
            IO / CCP values are framework-identical.
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

    cgcb_unrated = float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED])

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
                CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
                cgcb_unrated,
            )
        )
        # CCP guarantors: 2% proprietary / 4% client-cleared
        # (CRR Art. 306, CRE54.14-15) — overrides institution CQS weights.
        .when(pl.col(entity_type_col) == "ccp")
        .then(
            pl.when(pl.col(ccp_client_cleared_col).fill_null(False))
            .then(pl.lit(float(QCCP_CLIENT_CLEARED_RW)))
            .otherwise(pl.lit(float(QCCP_PROPRIETARY_RW)))
        )
        # International Organisation (Art. 118): 0% unconditional.
        .when(gec == "international_organisation")
        .then(pl.lit(float(IO_ZERO_RW)))
        # Named MDB (Art. 117(2)): 0% unconditional.
        .when((gec == "mdb") & (pl.col(entity_type_col).fill_null("") == "mdb_named"))
        .then(pl.lit(float(MDB_NAMED_ZERO_RW)))
        # Rated / unrated non-named MDB — Table 2B (Art. 117(1)).
        .when(gec == "mdb")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                MDB_RISK_WEIGHTS_TABLE_2B,
                float(MDB_UNRATED_RW),
            )
        )
        # Institution guarantors — RW driven from INSTITUTION_RISK_WEIGHTS_CRR /
        # INSTITUTION_RISK_WEIGHTS_B31_ECRA so the dicts remain the single source
        # of truth. When the short-term flag evaluates True (CRR/PS1/26
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
                PSE_RISK_WEIGHTS_OWN_RATING,
                sovereign_derived_unrated,
            )
        )
        # RGLA guarantors — Art. 115(1)(b) Table 1B for rated, sovereign-derived for unrated.
        .when(gec == "rgla")
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                RGLA_RISK_WEIGHTS_OWN_RATING,
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


@cites("CRR Art. 114")
@cites("CRR Art. 115")
@cites("CRR Art. 116")
@cites("CRR Art. 117")
@cites("CRR Art. 118")
@cites("CRR Art. 122")
@cites("CRR Art. 123")
def build_entity_rw_expr(
    *,
    entity_type_col: str,
    cqs_col: str,
    is_basel_3_1: bool,
    country_code_col: str | None = None,
) -> pl.Expr:
    """Build the entity-level SA risk-weight preview expression.

    Compiled by the hierarchy facility-share selection
    (``engine/stages/hierarchy/facility_undrawn.py::
    _derive_facility_share_counterparty``) to rank candidate counterparties
    by SA-equivalent risk weight. The preview is non-binding: the chosen
    counterparty still flows through the full classifier and SA/IRB pipeline
    downstream. Keeping the preview SA-only avoids a circular dependency with
    the classifier's IRB approach gating.

    Routes the lowercased ``entity_type`` through the SA exposure-class
    buckets (``ENTITY_TYPES_BY_SA_CLASS``) and maps CQS -> RW via the same
    table branches as :func:`build_guarantor_rw_expr`:

        sovereign (CGCB CQS Table 1, Art. 114)
        International Organisation (Art. 118) -> 0%
        Named MDB (Art. 117(2)) -> 0%
        MDB Table 2B (Art. 117(1))
        Institution (Art. 120 Table 3 / PS1/26 ECRA via
            ``build_institution_guarantor_rw_expr``)
        PSE (Art. 116(2) Table 2A, GB/other approximation for unrated)
        RGLA (Art. 115(1)(b) Table 1B, GB/other approximation for unrated)
        Corporate + covered bond (Art. 122 CRR Table 5 — see note below)
        Retail (Art. 123 flat 75%)
        High risk (Art. 128 flat 150%)
        else -> 1.0 (conservative preview default for unmatched entity
            types, e.g. equity / other items)

    Branch-parity notes (the pre-existing preview branches are preserved
    value-for-value):

    - The corporate branch always prices from ``CORPORATE_RISK_WEIGHTS``
      (CRR Art. 122 Table 5), NOT the Basel 3.1 Table 6 — matching the
      historical preview. Covered bonds use the corporate-equivalent CQS RWs
      in the preview; the precise covered-bond table only applies in real
      SA pricing.
    - The unrated PSE / RGLA fallback is the documented SA-side
      approximation (see :func:`build_guarantor_rw_expr`): GB -> 20%
      domestic-currency treatment, other / unknown country -> 100% unrated
      default. When ``country_code_col`` is ``None`` the 100% default
      applies unconditionally.

    Args:
        entity_type_col: Name of the entity-type column. Null-filled to ""
            and lowercased before bucket routing.
        cqs_col: Name of the integer CQS column; null / out-of-range values
            fall to each table's unrated default.
        is_basel_3_1: Select the PS1/26 institution ECRA table when True,
            CRR Art. 120 Table 3 when False. All other preview branches are
            framework-identical by construction (see corporate note above).
        country_code_col: Optional name of the country-code column driving
            the unrated PSE / RGLA GB-vs-other approximation. ``None`` falls
            back to the conservative 100% unrated default.

    Returns:
        Float64 Polars expression evaluating to the entity's SA-equivalent
        preview risk weight (never null — unmatched entity types yield 1.0).
    """
    et = pl.col(entity_type_col).fill_null("").str.to_lowercase()

    sovereign_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value])
    io_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.INTERNATIONAL_ORGANISATION.value])
    mdb_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.MDB.value])
    institution_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.INSTITUTION.value])
    pse_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.PSE.value])
    rgla_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.RGLA.value])
    corporate_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.CORPORATE.value])
    covered_bond_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.COVERED_BOND.value])
    retail_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.RETAIL_OTHER.value])
    high_risk_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.HIGH_RISK.value])

    unrated_pse_rgla = _pse_rgla_unrated_fallback_expr(country_code_col)

    return (
        # CGCB (Art. 114 Table 1 — sovereign weights).
        pl.when(et.is_in(sovereign_types))
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
                float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED]),
            )
        )
        # International Organisation (Art. 118): 0% unconditional.
        .when(et.is_in(io_types))
        .then(pl.lit(float(IO_ZERO_RW)))
        # Named MDB (Art. 117(2)): 0% unconditional — carved out ahead of Table 2B.
        .when(et == "mdb_named")
        .then(pl.lit(float(MDB_NAMED_ZERO_RW)))
        # Rated / unrated non-named MDB — Table 2B (Art. 117(1)).
        .when(et.is_in(mdb_types))
        .then(_cqs_table_lookup_expr(cqs_col, MDB_RISK_WEIGHTS_TABLE_2B, float(MDB_UNRATED_RW)))
        # Institution — Art. 120 Table 3 / PS1/26 ECRA via the shared builder
        # so the dicts remain the single source of truth.
        .when(et.is_in(institution_types))
        .then(build_institution_guarantor_rw_expr(cqs_col, is_basel_3_1))
        # PSE — Art. 116(2) Table 2A for rated, GB/other approximation for unrated.
        .when(et.is_in(pse_types))
        .then(_cqs_table_lookup_expr(cqs_col, PSE_RISK_WEIGHTS_OWN_RATING, unrated_pse_rgla))
        # RGLA — Art. 115(1)(b) Table 1B for rated, GB/other approximation for unrated.
        .when(et.is_in(rgla_types))
        .then(_cqs_table_lookup_expr(cqs_col, RGLA_RISK_WEIGHTS_OWN_RATING, unrated_pse_rgla))
        # Corporate + covered bond — CRR Art. 122 Table 5 (preview parity:
        # not framework-switched; see docstring).
        .when(et.is_in(corporate_types + covered_bond_types))
        .then(
            _cqs_table_lookup_expr(
                cqs_col,
                CORPORATE_RISK_WEIGHTS,
                float(CORPORATE_RISK_WEIGHTS[CQS.UNRATED]),
            )
        )
        # Retail (Art. 123): flat 75%.
        .when(et.is_in(retail_types))
        .then(pl.lit(float(RETAIL_RISK_WEIGHT)))
        # High-risk items (Art. 128): flat 150%.
        .when(et.is_in(high_risk_types))
        .then(pl.lit(float(HIGH_RISK_RW)))
        # Conservative preview default for unmatched entity types.
        .otherwise(pl.lit(1.0))
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
        return pl.lit(float(PSE_UNRATED_DEFAULT_RW))
    return (
        pl.when(pl.col(country_code_col).fill_null("") == "GB")
        .then(pl.lit(float(RGLA_DOMESTIC_CURRENCY_RW)))
        .otherwise(pl.lit(float(PSE_UNRATED_DEFAULT_RW)))
    )


def _cqs_table_lookup_expr(
    cqs_col: str,
    table: dict[CQS, Decimal],
    unrated_default: pl.Expr | float,
) -> pl.Expr:
    """Build a when/then chain mapping a CQS-bearing column to RW from a CQS table.

    Mirrors ``engine/sa/namespace.py::_cqs_table_lookup_expr`` so the SA path
    can adopt the shared builder byte-identically. Parameterised on the CQS
    source column so it can drive any CQS-keyed regulatory table (CGCB
    Art. 114, MDB Table 2B Art. 117(1), PSE Table 2A Art. 116(2), RGLA
    Table 1B Art. 115(1)(b)). Caller controls the unrated fallback (constant
    or Polars expression).
    """
    cqs_order: list[CQS] = [CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]
    expr = pl.when(pl.col(cqs_col) == int(cqs_order[0])).then(pl.lit(float(table[cqs_order[0]])))
    for cqs_val in cqs_order[1:]:
        expr = expr.when(pl.col(cqs_col) == int(cqs_val)).then(pl.lit(float(table[cqs_val])))
    if isinstance(unrated_default, pl.Expr):
        return expr.otherwise(unrated_default)
    return expr.otherwise(pl.lit(unrated_default))
