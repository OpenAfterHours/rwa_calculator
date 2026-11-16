"""
OF 08.01 column 0010 (PD) on the registered Basel 3.1 IRB portfolios - through the gateway engine.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer trace_return (the gateway engine, ``rwa_filer.boe``)

The Basel 3.1 OF 08.01 layout left column 0010 out, so every return left it
blank: ``boe_b0356`` ("if c0110 > 0 then c0010 >= 0.05%", Warning) failed at 97
places across the seven registered IRB portfolios and ``boe_b0410``
("c0010 <= 100%") was never evaluated. The column is reported now: the
exposure-weighted average of the post-input-floor PD over the row's legs that
carry a PD.

What stays failing, and why, is pinned here place by place. A Warning sits in no
ratchet - not the supervisory register (which cannot parse ``boe_b0356``'s
conditional at all) and not the gateway's Error-break count - so without this
the residual could grow unseen:

- Sheet 0010 rows 0010 / 0020 / 0030 on a book whose specialised lending there is
  all slotting. Slotting exposure has no PD: the taxonomy has no c0010 cell on
  the slotting row 0080 (a PD filed there is refused, STR002) and Annex II
  §3.3.4 ¶77A keeps slotting out of OF 08.02. The rule asks every in-scope row
  with exposure for a PD, and these rows hold exposure that has none - a limit
  of the published rule, confirmed with Arelle on the Bank's package.
- ``crm-substitution`` sheet 0006 row 0190: column 0110 is on the
  post-substitution basis (legs that arrived from corporate obligors) and
  column 0010 on the obligor basis (no leg of its own there). Ours, open.

References:
- PRA PS1/26 Annex I OF 08.01 (column 0010, shaded on rows 0080 and 0170);
  Annex II §3.3.4 ¶77A
- PRA PS1/26 Art. 160(1) (PD input floor, 0.05%)
- Bank of England taxonomy v4.1.1 rules ``boe_b0356``, ``boe_b0410``
- tests/unit/reporting/corep/test_c08_01_pd_column.py
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
OF08_TABLE = "OF08.01.01.01"
PD_RULE = "boe_b0356"
RANGE_RULE = "boe_b0410"

#: The F-IRB non-SME corporate sheet of ``irb-classes`` (published code 0012):
#: sum(pd_floored x ead_final) over G01..G14 = 6,765,210 on 51,100,000. G01's
#: model PD of 0.02% is floored to 0.05% (Art. 160(1)); pre-floor it would read
#: 6,764,310 / 51,100,000.
IRB_CLASSES_CORPORATE_PD = 6_765_210 / 51_100_000
FLOOR_LEG = "IRC-LN-CORP-G01"

SLOTTING_ONLY = (
    "row holds slotting exposure only: a slotting exposure has no PD, the taxonomy "
    "has no c0010 cell on the slotting row 0080, and the rule still asks for one - "
    "a limit of the published rule (Arelle-confirmed)"
)
OBLIGOR_BASIS = (
    "OWNER: P2.81 - c0110 counts legs substituted in from corporate obligors "
    "(post-substitution basis) while c0010 is on the obligor basis, where the row "
    "has no leg"
)

#: Per registered Basel 3.1 IRB portfolio: every (sheet, row) where ``boe_b0356``
#: is unsatisfied, and why. Empty means the rule passes.
RESIDUAL: dict[str, dict[tuple[str, str], str]] = {
    "irb-classes": {},
    "art199": {},
    "facility-share-binding": {},
    "facility-share-nonbinding": {},
    "rich": {("0010", "0010"): SLOTTING_ONLY, ("0010", "0020"): SLOTTING_ONLY},
    "irb-shapes": {
        ("0010", "0010"): SLOTTING_ONLY,
        ("0010", "0020"): SLOTTING_ONLY,
        ("0010", "0030"): SLOTTING_ONLY,
    },
    "crm-substitution": {
        ("0010", "0010"): SLOTTING_ONLY,
        ("0010", "0020"): SLOTTING_ONLY,
        ("0006", "0190"): OBLIGOR_BASIS,
    },
}


class _Filed(NamedTuple):
    """One registered Basel 3.1 portfolio, generated and filed."""

    ledger: pl.DataFrame
    corep: COREPTemplateBundle
    canonical: CanonicalReturn
    unplaced: pl.DataFrame


@cache
def _filed(portfolio: str) -> _Filed:
    """The portfolio as ``export_filing_package`` files it (with the run's own
    floor summary)."""
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    mapping = build_canonical_return(corep, HEADER, pack=_pack())
    return _Filed(result.results.collect(), corep, mapping.canonical, mapping.unplaced)


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


def _trace(canonical: CanonicalReturn) -> tuple[dict[str, str], RuleTrace]:
    """Each rule's gateway status, and every evaluation behind it."""
    validation, trace = trace_return(canonical, _pack())
    assert validation.report is not None and trace is not None, "no rule book for PRA001"
    return {result.rule_id: result.status for result in validation.report.results}, trace


def _unsatisfied(trace: RuleTrace, rule_id: str) -> set[tuple[str, str]]:
    places = (dict(ev.place) for ev in trace.evaluations if ev.rule_id == rule_id and not ev.holds)
    return {(place["z"], place["r"]) for place in places}


def test_irb_classes_reports_the_exposure_weighted_post_floor_pd_and_both_rules_pass() -> None:
    # Arrange
    filed = _filed("irb-classes")
    legs = filed.ledger.filter(
        (pl.col("reporting_approach_origin") == "foundation_irb")
        & (pl.col("reporting_class_origin") == "corporate")
    )
    sheet = filed.corep.c08_01["corporate_non_sme_firb"]
    total = sheet.filter(pl.col("row_ref") == "0010")
    floor_leg = legs.filter(pl.col("exposure_reference") == FLOOR_LEG)
    # Adequacy: the recomputation reads exactly the sheet's legs, and one of them
    # sits below the input floor - else pre- and post-floor PD would agree.
    assert legs["ead_final"].sum() == pytest.approx(total["0110"][0], rel=1e-12)
    assert floor_leg["pd"][0] < floor_leg["pd_floored"][0]
    from_ledger = (legs["pd_floored"] * legs["ead_final"]).sum() / legs["ead_final"].sum()

    # Act
    statuses, trace = _trace(filed.canonical)
    pd_facts = filed.canonical.facts.filter(
        (pl.col("table") == OF08_TABLE) & (pl.col("column") == "0010")
    )
    unplaced_pd = filed.unplaced.filter(
        (pl.col("template") == "c08_01") & (pl.col("column") == "0010")
    )

    # Assert
    assert total["0010"][0] == pytest.approx(IRB_CLASSES_CORPORATE_PD, rel=1e-9)
    assert total["0010"][0] == pytest.approx(from_ledger, rel=1e-12)
    assert (statuses[PD_RULE], statuses[RANGE_RULE]) == (STATUS_PASS, STATUS_PASS)
    assert _unsatisfied(trace, PD_RULE) == set()
    assert pd_facts.height > 0
    assert set(pd_facts["row"].to_list()).isdisjoint({"0080", "0170"})
    assert unplaced_pd.height == 0


@pytest.mark.parametrize("portfolio", sorted(RESIDUAL))
def test_boe_b0356_fails_only_where_the_row_has_no_pd_to_report(portfolio: str) -> None:
    # Arrange
    filed = _filed(portfolio)
    expected = RESIDUAL[portfolio]

    # Act
    statuses, trace = _trace(filed.canonical)
    unsatisfied = _unsatisfied(trace, PD_RULE)

    # Assert
    assert unsatisfied == set(expected), {place: expected.get(place) for place in unsatisfied}
    assert statuses[RANGE_RULE] == STATUS_PASS
