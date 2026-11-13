"""
The filing page — whether a completed run can be filed as an XBRL return.

Pipeline position:
    api.rest.filing_status (verdict payload) -> ui.views.filing -> filing.html

Key responsibilities:
- Turn the REST verdict into what the page shows: one headline, what stands in
  the way and how much of it, and which downloads may be offered.
- Decide the downloads in ONE place. A file is offered as the return only when
  nothing stands in the way; a file with figures left out or rules broken is
  offered only under a label that says so; a structure finding offers nothing,
  because no valid file can be written from it.

This module holds no filing logic: every number comes from the payload, which
``rwa_calc.reporting.filing`` and ``rwa-filer`` produce.

References:
- src/rwa_calc/api/rest.py — ``filing_status`` / ``filing_package``
- Bank of England Banking Taxonomy v4.1.1 (PRA001); BoE XBRL Filing Manual
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Findings listed on the page. The JSON verdict carries them all.
FINDINGS_SHOWN: Final = 25

BLOCKED_BY_UNPLACED: Final = "unplaced_figures"
BLOCKED_BY_STRUCTURE: Final = "structure"
BLOCKED_BY_RULES: Final = "rules"

_HEADLINES: Final[Mapping[str | None, tuple[str, str]]] = {
    None: (
        "info",
        "Nothing stands in the way: the return validates and can be written for submission.",
    ),
    BLOCKED_BY_UNPLACED: (
        "warn",
        "Not written: this run reports figures the PRA001 taxonomy has no cell for. A file "
        "without them would be an incomplete return.",
    ),
    BLOCKED_BY_STRUCTURE: (
        "error",
        "Not written: the taxonomy cannot express some of the placed figures. No valid file "
        "can be produced until the findings below are resolved.",
    ),
    BLOCKED_BY_RULES: (
        "error",
        "Not written: the return breaks validation rules the Bank of England's gateway would "
        "reject it for.",
    ),
}


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class Download:
    """One download link, and what the file it gives is."""

    label: str
    url: str
    caution: str = ""


@dataclass(frozen=True)
class FilingPage:
    """Everything ``filing.html`` renders.

    Attributes:
        run_id / framework: The run the page is about.
        entity_identifier: The identifier the verdict was asked for; empty
            before the form is submitted.
        problem: Why there is no verdict (not a Basel 3.1 run, no taxonomy for
            the date); empty otherwise.
        status: The REST verdict payload, or ``None`` before the form is
            submitted or where there is a ``problem``.
        review: The verdict with every override applied — what would still
            stand in the way of a file for review. It carries the validation
            findings even where unplaced figures block ``status``.
        tone / headline: The callout's style and its one sentence.
        downloads: The files that may be offered, most trustworthy first.
        findings: The first ``FINDINGS_SHOWN`` findings.
        findings_hidden: How many more the verdict holds.
    """

    run_id: str
    framework: str
    entity_identifier: str = ""
    problem: str = ""
    status: Mapping[str, Any] | None = None
    review: Mapping[str, Any] | None = None
    tone: str = "info"
    headline: str = ""
    downloads: tuple[Download, ...] = ()
    findings: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    findings_hidden: int = 0


def filing_page(
    run_id: str,
    framework: str,
    *,
    entity_identifier: str = "",
    status: Mapping[str, Any] | None = None,
    review: Mapping[str, Any] | None = None,
    problem: str = "",
) -> FilingPage:
    """Build the page model.

    Args:
        run_id: The run.
        framework: Its framework label, for the heading.
        entity_identifier: The reporting entity's identifier, as entered.
        status: ``api.rest.filing_status``'s payload for that identifier.
        review: The same with ``allow_incomplete`` and ``allow_rule_breaks``;
            omitted, no file for review is offered.
        problem: Why no verdict could be reached, in place of ``status``.
    """
    if status is None:
        return FilingPage(run_id, framework, entity_identifier=entity_identifier, problem=problem)
    blocked_by = status["blocked_by"]
    tone, headline = _HEADLINES.get(blocked_by, _HEADLINES[BLOCKED_BY_STRUCTURE])
    validated = status if status.get("validation") else (review or status)
    findings = tuple((validated.get("validation") or {}).get("findings", ()))
    reviewable = review is not None and bool(review["written"])
    return FilingPage(
        run_id=run_id,
        framework=framework,
        entity_identifier=entity_identifier,
        status=status,
        review=review,
        tone=tone,
        headline=headline,
        downloads=_downloads(run_id, entity_identifier, blocked_by, reviewable=reviewable),
        findings=findings[:FINDINGS_SHOWN],
        findings_hidden=max(0, len(findings) - FINDINGS_SHOWN),
    )


# =============================================================================
# Private helpers
# =============================================================================


def _downloads(
    run_id: str, entity_identifier: str, blocked_by: str | None, *, reviewable: bool
) -> tuple[Download, ...]:
    """The downloads the verdict allows.

    Nothing in the way: the return. Otherwise, where a file can still be
    written with the overrides (``reviewable``): that file, labelled for what
    it is. A structure finding leaves nothing to offer — no valid file exists.
    """

    def url(**allow: bool) -> str:
        query = {"run_id": run_id, "entity_identifier": entity_identifier}
        query.update({name: "true" for name, wanted in allow.items() if wanted})
        return f"/api/filing/package?{urlencode(query)}"

    if blocked_by is None:
        return (Download("Download the filing package", url()),)
    if not reviewable:
        return ()
    return (
        Download(
            "Download for review (not a submittable return)",
            url(allow_incomplete=True, allow_rule_breaks=True),
            caution=(
                "Written with whatever stands in the way overridden. The package's manifest "
                "records that it is not submittable, and where figures were left out the "
                "package lists each one."
            ),
        ),
    )
