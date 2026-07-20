"""
Cross-template consistency (tie-out) checker for the regulatory reporting estate.

Pipeline position:
    COREPGenerator + Pillar3Generator  ->  check_cross_template_consistency
        ->  list[CalculationError]

Key responsibilities:
- Assert that the independently-generated COREP (C 02.00, C 07.00, C 08.01)
  and Pillar 3 (OV1) template DataFrames foot to one another, so a regression
  that silently drifts one template's aggregation is caught rather than shipped
  in a supervisory return.
- Do so through an EXPLICIT, curated list of genuinely comparable aggregate
  pairs (``TIE_OUTS``) — never a blind equality sweep. Per-template reporting
  bases differ BY REGULATION (obligor basis, post-substitution basis, raw
  origination class, two-basis geographic splits), so pairs that are NOT
  comparable are recorded as ``NonComparablePair`` with the regulatory reason
  and deliberately left un-tied.
- Report each break on the error channel as a non-blocking ``CalculationError``
  (never raise), following the accumulate-don't-throw contract.

Why a tie-out layer at all: the estate reshapes one sealed per-leg ledger into
many fixed-format templates, but until now nothing asserted the templates
reconcile with each other. This is the first in-house analogue of the
supervisory validation rules (e.g. the EBA COREP/Pillar 3 validation rules)
that check exactly these cross-template identities.

The comparable ties (all hold on both frameworks on a real IRB+SA pipeline run):

- ``total_rwea_c02_vs_ov1``    C 02.00 [0010] (total RWEA) == OV1 [29] (total).
- ``credit_risk_rollup_c02``   C 02.00 [0050] == [0060] + [0220] (SA incl.
                               equity + IRB of-which = total credit risk).
- ``sa_rwea_c07_vs_c02``       Σ C 07.00 sheets [0010][0220] == C 02.00 [0060]
                               minus [0420] (SA of-which line net of the equity
                               RWEA folded into it — C 07.00 has no equity
                               sheet, so the equity term must be removed).
- ``irb_rwea_c08_01_vs_c02``   Σ C 08.01 sheets [0010][0260] == C 02.00 [0220]
                               (IRB of-which line).
- ``irb_rwea_c08_01_vs_ov1``   Σ C 08.01 sheets [0010][0260] == OV1 [3]+[4]+[5]
                               (F-IRB + slotting + A-IRB) — same origin basis.

References:
- CRR Art. 92(3) (own-funds requirement roll-up); COREP Annex II C 02.00 /
  C 07.00 / C 08.01; Pillar 3 (CRR) / (UKB) OV1 (CRR Art. 438).
- PRA PS1/26 Annex II (OF 02.00 / OF 07.00 / OF 08.01), Annex XX (OV1),
  Annex XXII (the obligor-basis disclosures recorded non-comparable below).
- docs/plans/phase7-declarative-reporting.md §6 (the per-template basis
  decisions F3/F4/F9 that make the non-comparable pairs non-comparable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import ERROR_CROSS_TEMPLATE_INCONSISTENCY
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

# ``ERROR_CROSS_TEMPLATE_INCONSISTENCY`` ("TIE001") is the single coded failure
# mode — two comparable template aggregates disagree beyond tolerance. It lives
# in contracts/errors.py with the other domain codes; the specific tie is carried
# on the finding's ``field_name`` and the two figures in the message (the
# reconciliation-warning roll-up pattern: one code per failure mode, not one per
# instance).

# Golden convention: relative 1e-9 with a small absolute floor for near-zero
# sums. Float-sum nondeterminism across the eager (C 02.00 pre-pass) and lazy
# (executor) aggregation paths is expected; byte-exact equality would be wrong.
DEFAULT_RTOL = 1e-9
DEFAULT_ATOL = 1e-6

# The frameworks every curated tie applies to (both, for the current set).
_ALL_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")

# Template ids reused as standalone tie / non-comparable-pair members. Named so
# the same id string is not a duplicated literal across the tuples; the prose
# descriptions/reasons keep the id inline (a substring of a longer sentence, not
# a standalone literal).
_TEMPLATE_C02 = "C 02.00"
_TEMPLATE_C07 = "C 07.00"
_TEMPLATE_C08_01 = "C 08.01"

# A tie extractor reads one scalar aggregate out of the two bundles, or returns
# None to signal "this template / cell was not produced — skip the tie".
type _Extractor = Callable[["COREPTemplateBundle", "Pillar3TemplateBundle"], float | None]


@dataclass(frozen=True)
class TieOut:
    """One curated cross-template identity that must hold within tolerance.

    ``lhs`` / ``rhs`` are pure extractor callables over the (COREP, Pillar 3)
    bundle pair. Each returns a scalar, or ``None`` when its template/cell is
    absent — in which case the whole tie is SKIPPED (an absent template is not a
    break). A tie fires a finding only when both sides resolve and disagree by
    more than ``atol + rtol * max(|lhs|, |rhs|)``.

    Attributes:
        name: Stable machine identifier (goes on the finding's ``field_name``).
        description: One-line human statement of the identity.
        regulatory_reference: Docstring-style reference (CRR article + the
            template Annex). Template-annex references live here rather than as
            ``@cites`` decorators — the watchfire grammar targets code paths that
            implement a single article, not a cross-template reconciliation.
        templates: The template ids this tie reconciles (used by the
            non-comparable guard test; also documents coverage).
        lhs_label / rhs_label: Human labels for the two sides, quoted verbatim
            in the finding so a reviewer sees which cells disagreed.
        lhs / rhs: The extractor callables.
        rtol / atol: Per-tie tolerance overrides (default to the golden values).
        frameworks: Which frameworks the tie applies to (both, by default).
    """

    name: str
    description: str
    regulatory_reference: str
    templates: tuple[str, ...]
    lhs_label: str
    rhs_label: str
    lhs: _Extractor
    rhs: _Extractor
    rtol: float = DEFAULT_RTOL
    atol: float = DEFAULT_ATOL
    frameworks: tuple[str, ...] = _ALL_FRAMEWORKS


@dataclass(frozen=True)
class NonComparablePair:
    """A pair of templates that must NOT be tied, with the regulatory reason.

    Recorded so a future maintainer does not "close the gap" by adding a naive
    equality assertion between two templates whose reporting bases differ by
    regulation. Asserting equality here would flag a CORRECT figure as a break.

    Attributes:
        pair: The two template ids (e.g. ``("UK CR6", "C 08.01")``).
        reason: Why the two are on different bases and cannot be equated.
        regulatory_reference: The governing article / annex.
    """

    pair: tuple[str, str]
    reason: str
    regulatory_reference: str


def check_cross_template_consistency(
    corep: COREPTemplateBundle,
    pillar3: Pillar3TemplateBundle,
    framework: str,
) -> list[CalculationError]:
    """Check the curated cross-template tie-outs and return any breaks.

    Findings are accumulated on the error channel (never raised). A tie whose
    lhs or rhs extractor returns ``None`` (its template / cell was not produced)
    is skipped silently — a missing template is not an inconsistency. Only a
    tie whose two sides both resolve and disagree beyond tolerance yields a
    ``TIE001`` finding.

    Args:
        corep: The generated COREP template bundle.
        pillar3: The generated Pillar 3 template bundle.
        framework: ``"CRR"`` or ``"BASEL_3_1"`` — selects the applicable ties.

    Returns:
        A list of ``CalculationError`` (one per broken tie); empty when every
        applicable, resolvable tie holds.
    """
    errors: list[CalculationError] = []
    for tie in TIE_OUTS:
        if framework not in tie.frameworks:
            continue
        lhs = tie.lhs(corep, pillar3)
        rhs = tie.rhs(corep, pillar3)
        if lhs is None or rhs is None:
            continue
        if not _within_tolerance(lhs, rhs, tie.rtol, tie.atol):
            errors.append(_inconsistency_finding(tie, lhs, rhs))
    return errors


# =============================================================================
# The curated tie-outs and the recorded non-comparable pairs
# =============================================================================
# Each ``lhs`` / ``rhs`` is a lambda over (corep, pillar3) that defers to the
# scalar-reader helpers at the bottom of the module, so the reader sees the
# identity here and the extraction mechanics separately.
#
# Basis note for the C 02.00 ties (sa_rwea_c07_vs_c02 / irb_rwea_c08_01_vs_c02):
# C 02.00 keys the APPLIED approach (approach_applied) while C 07.00 / C 08.01
# key the ORIGIN approach (reporting_approach_origin). These coincide today
# because CRM substitution does NOT retarget an exposure's approach (the open
# F-decision recorded in the c07/cr4 module docstrings). If that retarget ever
# lands, these two ties may legitimately diverge and must be re-derived — unlike
# the obligor-basis pairs below, which diverge by REGULATION even today.


TIE_OUTS: list[TieOut] = [
    TieOut(
        name="total_rwea_c02_vs_ov1",
        description=(
            "Total RWEA in COREP C 02.00 (row 0010) equals the Pillar 3 OV1 total (row 29)."
        ),
        regulatory_reference=(
            "CRR Art. 92(3); COREP Annex II C 02.00 row 0010; Pillar 3 OV1 "
            "row 29 (CRR Art. 438; PS1/26 Annex XX)"
        ),
        templates=(_TEMPLATE_C02, "OV1"),
        lhs_label="C 02.00 [0010][0010] total RWEA",
        rhs_label="OV1 [29][a] total RWEA",
        lhs=lambda c, _p: _cell(c.c_02_00, "0010", "0010"),
        rhs=lambda _c, p: _cell(p.ov1, "29", "a"),
    ),
    TieOut(
        name="credit_risk_rollup_c02",
        description=(
            "COREP C 02.00 total credit-risk RWEA (row 0050) equals the SA "
            "of-which line incl. equity (row 0060) plus the IRB of-which line "
            "(row 0220)."
        ),
        regulatory_reference=(
            "CRR Art. 92(3)(a); COREP Annex II C 02.00 rows 0050/0060/0220 "
            "(PS1/26 Annex II OF 02.00)"
        ),
        templates=(_TEMPLATE_C02,),
        lhs_label="C 02.00 [0050][0010] credit-risk RWEA",
        rhs_label="C 02.00 [0060]+[0220] (SA incl. equity + IRB)",
        lhs=lambda c, _p: _cell(c.c_02_00, "0050", "0010"),
        rhs=lambda c, _p: _rows_sum(c.c_02_00, ("0060", "0220"), "0010"),
    ),
    TieOut(
        name="sa_rwea_c07_vs_c02",
        description=(
            "Aggregate SA RWEA across the C 07.00 obligor-class sheets equals "
            "the C 02.00 SA of-which line (row 0060) net of the equity RWEA "
            "(row 0420) folded into it — C 07.00 has no equity sheet."
        ),
        regulatory_reference=(
            "CRR Art. 92(3)(a); COREP Annex II C 07.00 col 0220 / C 02.00 rows "
            "0060/0420 (PS1/26 Annex II OF 07.00 / OF 02.00)"
        ),
        templates=(_TEMPLATE_C07, _TEMPLATE_C02),
        lhs_label="Σ C 07.00 [0010][0220] SA RWEA",
        rhs_label="C 02.00 [0060]-[0420] (SA of-which net of equity)",
        lhs=lambda c, _p: _sheet_total(c.c07_00, "0220"),
        rhs=lambda c, _p: _cell_diff(c.c_02_00, "0060", "0420", "0010"),
    ),
    TieOut(
        name="irb_rwea_c08_01_vs_c02",
        description=(
            "Aggregate IRB RWEA across the C 08.01 obligor-class sheets equals "
            "the C 02.00 IRB of-which line (row 0220)."
        ),
        regulatory_reference=(
            "CRR Art. 92(3)(a); COREP Annex II C 08.01 col 0260 / C 02.00 row "
            "0220 (PS1/26 Annex II OF 08.01 / OF 02.00)"
        ),
        templates=(_TEMPLATE_C08_01, _TEMPLATE_C02),
        lhs_label="Σ C 08.01 [0010][0260] IRB RWEA",
        rhs_label="C 02.00 [0220][0010] IRB of-which RWEA",
        lhs=lambda c, _p: _sheet_total(c.c08_01, "0260"),
        rhs=lambda c, _p: _cell(c.c_02_00, "0220", "0010"),
    ),
    TieOut(
        name="irb_rwea_c08_01_vs_ov1",
        description=(
            "Aggregate IRB RWEA across the C 08.01 obligor-class sheets equals "
            "the Pillar 3 OV1 IRB rows (F-IRB row 3 + slotting row 4 + A-IRB "
            "row 5) — the same reporting-approach-origin basis."
        ),
        regulatory_reference=(
            "COREP Annex II C 08.01 col 0260; Pillar 3 OV1 rows 3/4/5 "
            "(CRR Art. 438; PS1/26 Annex XX)"
        ),
        templates=(_TEMPLATE_C08_01, "OV1"),
        lhs_label="Σ C 08.01 [0010][0260] IRB RWEA",
        rhs_label="OV1 [3]+[4]+[5] IRB RWEA",
        lhs=lambda c, _p: _sheet_total(c.c08_01, "0260"),
        rhs=lambda _c, p: _rows_sum(p.ov1, ("3", "4", "5"), "a"),
    ),
]


NON_COMPARABLE_PAIRS: list[NonComparablePair] = [
    NonComparablePair(
        pair=("UK CR6", _TEMPLATE_C08_01),
        reason=(
            "Both CR6 and C 08.01 key the OBLIGOR's exposure class "
            "(reporting_class_origin), so the row AXIS matches — the divergence "
            "is in the RWEA VALUES bucketed under that class. PS1/26 Annex XXII "
            "bars substitution effects from CR6, so CR6 reports the RWEA the "
            "obligor's own exposure would carry BEFORE any guarantee / "
            "credit-derivative substitution, whereas C 08.01 buckets the actual "
            "post-CRM RWEA under the same obligor class. The two therefore differ "
            "by exactly the substitution's RWA benefit whenever CRM substitution "
            "occurs, so no CR6 class aggregate may be equated with a C 08.01 sheet."
        ),
        regulatory_reference="PS1/26 Art. 452(g), Annex XXII; CRR Art. 92(3)(a)",
    ),
    NonComparablePair(
        pair=("UK CR7", _TEMPLATE_C08_01),
        reason=(
            "CR7 (credit-derivatives effect on IRB RWEA) is likewise an "
            "obligor-basis disclosure (PS1/26 Annex XXII) and carries a recorded "
            "pre==post (a==b) approximation for the credit-derivative columns; "
            "its RWEA is not the post-substitution C 08.01 figure."
        ),
        regulatory_reference="PS1/26 Art. 453(j), Annex XXII",
    ),
    NonComparablePair(
        pair=("UKB CR9", "C 08.05"),
        reason=(
            "CR9 (IRB PD back-testing) reports on the obligor basis over "
            "leaf-class sheets (PS1/26 Annex XXII) and carries point-in-time "
            "proxy columns for the prior-year / historical carriers; it is a "
            "back-testing disclosure, not a post-substitution RWEA aggregate "
            "comparable with C 08.05."
        ),
        regulatory_reference="PS1/26 Art. 452(h), Annex XXII paras 12-15",
    ),
    NonComparablePair(
        pair=("C 08.07", _TEMPLATE_C08_01),
        reason=(
            "C 08.07 (IRB scope of use) keeps the RAW Art. 147 origination class "
            "(number-changing vs the applied class) and reads the FULL population "
            "(SA enters every denominator; null approach falls to SA; slotting "
            "counts as IRB). It is a coverage-percentage table, not a "
            "post-substitution class RWEA aggregate, so it does not tie to "
            "C 08.01's obligor-class RWEA."
        ),
        regulatory_reference="CRR Art. 147(2); COREP Annex II C 08.07",
    ),
    NonComparablePair(
        pair=("C 09.01", _TEMPLATE_C07),
        reason=(
            "C 09.01 (geographical breakdown, SA) is a per-country, two-basis "
            "breakdown (F9): its class rows are keyed differently from the "
            "C 07.00 obligor-class sheets, and it partitions by counterparty "
            "country. Neither its per-country nor its total aggregates share "
            "C 07.00's single-basis obligor-class definition."
        ),
        regulatory_reference="COREP Annex II C 09.01; PS1/26 Annex II OF 09.01",
    ),
    NonComparablePair(
        pair=("UK CR4", _TEMPLATE_C07),
        reason=(
            "CR4 (SA exposure and CRM effects) mixes bases PER COLUMN BLOCK "
            "(F3): cols a/b are on the origin class, cols c-f on the "
            "post-substitution class; and its standardised-origin population "
            "scopes counterparty credit risk out (disclosed separately in "
            "CCR1-CCR8) whereas C 07.00 INCLUDES CCR by risk_type. No single "
            "CR4 column reconciles to C 07.00's obligor-class RWEA."
        ),
        regulatory_reference="CRR Art. 444(e); COREP Annex II C 07.00 / CR4",
    ),
]


# =============================================================================
# Private helpers — scalar readers over the template DataFrames and the finding
# =============================================================================


def _cell(df: pl.DataFrame | None, row_ref: str, col_ref: str) -> float | None:
    """Read one numeric cell (row_ref, col_ref) from a template DataFrame.

    Returns ``None`` when the DataFrame is absent, the row is missing, the
    column is absent for this framework, or the cell value is null — every one
    of which means "not available", so the caller skips the tie.
    """
    if df is None or col_ref not in df.columns:
        return None
    matched = df.filter(pl.col("row_ref") == row_ref)
    if matched.height == 0:
        return None
    value = matched[col_ref][0]
    return float(value) if value is not None else None


def _cell_diff(
    df: pl.DataFrame | None, minuend_ref: str, subtrahend_ref: str, col_ref: str
) -> float | None:
    """``df[minuend_ref][col] - df[subtrahend_ref][col]``; None if either absent."""
    minuend = _cell(df, minuend_ref, col_ref)
    subtrahend = _cell(df, subtrahend_ref, col_ref)
    if minuend is None or subtrahend is None:
        return None
    return minuend - subtrahend


def _rows_sum(df: pl.DataFrame | None, row_refs: tuple[str, ...], col_ref: str) -> float | None:
    """Sum one column over several rows of a single template DataFrame.

    Returns ``None`` unless EVERY listed row resolves to a value — a partial
    sum is never a valid rhs (it would silently understate the aggregate), so
    a single missing row fail-safe skips the whole tie.
    """
    total = 0.0
    for row_ref in row_refs:
        value = _cell(df, row_ref, col_ref)
        if value is None:
            return None
        total += value
    return total


def _sheet_total(
    sheets: dict[str, pl.DataFrame], col_ref: str, *, row_ref: str = "0010"
) -> float | None:
    """Sum the total-row (``row_ref``, default 0010) cell across per-class sheets.

    Returns ``None`` when the sheet dict is empty (the template was not
    produced) or no sheet carries the column — so an absent template skips the
    tie rather than asserting a zero.
    """
    if not sheets:
        return None
    total = 0.0
    resolved = False
    for df in sheets.values():
        value = _cell(df, row_ref, col_ref)
        if value is not None:
            total += value
            resolved = True
    return total if resolved else None


def _within_tolerance(lhs: float, rhs: float, rtol: float, atol: float) -> bool:
    """Golden-convention closeness: ``|lhs-rhs| <= atol + rtol*max(|lhs|,|rhs|)``."""
    return abs(lhs - rhs) <= atol + rtol * max(abs(lhs), abs(rhs))


def _inconsistency_finding(tie: TieOut, lhs: float, rhs: float) -> CalculationError:
    """Build the TIE001 CalculationError for one broken tie."""
    from rwa_calc.contracts.errors import CalculationError

    return CalculationError(
        code=ERROR_CROSS_TEMPLATE_INCONSISTENCY,
        message=(
            f"Cross-template tie-out '{tie.name}' failed: "
            f"{tie.lhs_label} = {lhs:,.4f} vs {tie.rhs_label} = {rhs:,.4f} "
            f"(difference {lhs - rhs:,.4f}; rtol={tie.rtol}, atol={tie.atol}). "
            f"{tie.description}"
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.BUSINESS_RULE,
        regulatory_reference=tie.regulatory_reference,
        field_name=tie.name,
        expected_value=f"{rhs:,.4f}",
        actual_value=f"{lhs:,.4f}",
    )
