"""
``ui.views.filing`` — the filing page's model.

Pipeline position:
    api.rest.filing_status payload -> ui.views.filing.filing_page -> filing.html

What is pinned is the one decision the page makes for itself: which downloads
may be offered for a verdict. Everything else on the page is the payload.

References:
- src/rwa_calc/ui/views/filing.py
"""

from __future__ import annotations

from typing import Any

import pytest

from rwa_calc.ui.views.filing import FINDINGS_SHOWN, filing_page


def status(
    blocked_by: str | None, *, written: bool | None = None, findings: int = 0
) -> dict[str, Any]:
    """A ``filing_status`` payload with only what the page model reads."""
    return {
        "blocked_by": blocked_by,
        "written": blocked_by is None if written is None else written,
        "is_submittable": blocked_by is None,
        "validation": {
            "findings": [
                {"code": "VAL001", "severity": "ERROR", "message": f"rule {n}"}
                for n in range(findings)
            ]
        }
        if findings
        else None,
    }


def test_before_an_identifier_is_entered_there_is_only_the_form() -> None:
    # Act
    page = filing_page("run-1", "BASEL_3_1")

    # Assert
    assert page.status is None and page.downloads == () and not page.problem


def test_a_run_there_is_no_return_for_carries_the_reason_and_no_download() -> None:
    # Act
    page = filing_page(
        "run-1", "CRR", entity_identifier="X", problem="a filing package needs a Basel 3.1 run"
    )

    # Assert
    assert page.problem.startswith("a filing package needs")
    assert page.status is None and page.downloads == ()


def test_a_clean_return_offers_the_package_and_nothing_overridden() -> None:
    # Act
    page = filing_page("run-1", "BASEL_3_1", entity_identifier="LEI1", status=status(None))

    # Assert
    (download,) = page.downloads
    assert download.url == "/api/filing/package?run_id=run-1&entity_identifier=LEI1"
    assert not download.caution
    assert page.tone == "info"


@pytest.mark.parametrize("blocked_by", ["unplaced_figures", "rules"])
def test_a_blocked_return_offers_only_a_file_labelled_for_review(blocked_by: str) -> None:
    """Never the plain package: the link itself says what the file is."""
    # Act
    page = filing_page(
        "run-1",
        "BASEL_3_1",
        entity_identifier="LEI1",
        status=status(blocked_by),
        review=status(None, written=True),
    )

    # Assert
    (download,) = page.downloads
    assert "not a submittable return" in download.label
    assert "allow_incomplete=true" in download.url and "allow_rule_breaks=true" in download.url
    assert download.caution
    assert page.tone in ("warn", "error")


def test_nothing_is_offered_when_no_file_can_be_written_even_with_the_overrides() -> None:
    """A structure finding behind the unplaced figures: the review file does not exist."""
    # Act
    page = filing_page(
        "run-1",
        "BASEL_3_1",
        entity_identifier="LEI1",
        status=status("unplaced_figures"),
        review=status("structure", written=False),
    )

    # Assert
    assert page.downloads == ()


def test_a_structure_finding_offers_nothing() -> None:
    # Act
    page = filing_page(
        "run-1",
        "BASEL_3_1",
        entity_identifier="LEI1",
        status=status("structure"),
        review=status("structure", written=False),
    )

    # Assert
    assert page.downloads == () and page.tone == "error"


def test_the_findings_come_from_the_review_verdict_when_the_return_was_not_validated() -> None:
    """Unplaced figures stop the return before it is validated; the review run is."""
    # Act
    page = filing_page(
        "run-1",
        "BASEL_3_1",
        entity_identifier="LEI1",
        status=status("unplaced_figures"),
        review=status("rules", written=True, findings=3),
    )

    # Assert
    assert [finding["message"] for finding in page.findings] == ["rule 0", "rule 1", "rule 2"]


def test_a_long_list_of_findings_is_cut_and_the_rest_counted() -> None:
    # Act
    page = filing_page(
        "run-1",
        "BASEL_3_1",
        entity_identifier="LEI1",
        status=status("rules", findings=FINDINGS_SHOWN + 7),
    )

    # Assert
    assert len(page.findings) == FINDINGS_SHOWN
    assert page.findings_hidden == 7


def test_the_identifier_is_escaped_into_the_download_link() -> None:
    # Act
    page = filing_page("run-1", "BASEL_3_1", entity_identifier="A&B=C D", status=status(None))

    # Assert
    assert page.downloads[0].url.endswith("entity_identifier=A%26B%3DC+D")
