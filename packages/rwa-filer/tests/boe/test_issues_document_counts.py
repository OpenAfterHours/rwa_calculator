"""
The shareable register states what the gateway runs and what an example holds, in their own units.

Pipeline position:
    boe/data/issues/<release>.json  ->  boe.issues_document.render_document
        ->  docs/rwa-filer/publisher-issues.md (the copy sent to the Bank)

What is pinned, for the two counts the document gives that a reader at the
Bank can check against their own configuration and against Arelle:

- The rule-book line says how many rules are PUBLISHED for the module and how
  many the gateway RUNS on the day the cited deny list was published: a rule the
  list deactivates is not run, and the line next to it cites that list. Before
  this, it gave the published population (1,441) as the number "run" while the
  list deactivated 7 of them.
- Each worked example's collapsed table is headed with the number of template
  CELLS it lists. Two cells can share one data point, so the return holds fewer
  XBRL facts than cells, and calling the cells "facts" disagreed with Arelle's
  fact count on 8 of the 37 examples (PI-35's own text says "25 facts for 28
  cells" under a heading that said 28 facts).

References:
- rwa_filer.boe.issues_document — the rendering
- rwa_filer.boe.deny — the Bank's validations deny list
- packages/rwa-filer/tests/releases/4.1.1/oracles/publisher_issues_oracle.json — Arelle's fact counts
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from rwa_filer.boe.issues import load_issues
from rwa_filer.boe.issues_document import render_document
from rwa_filer.release import release_deny_list, release_rulebook

RELEASE = "4.1.1"
MODULE = "PRA001"
ORACLE = (
    Path(__file__).resolve().parents[1]
    / "releases"
    / RELEASE
    / "oracles"
    / "publisher_issues_oracle.json"
)


def test_the_rule_book_line_says_how_many_rules_the_gateway_runs_after_the_deny_list() -> None:
    """Published, deactivated and run, on the deny list's own publication date.

    Arrange: the release's rule book and deny list, and the day the list was published.
    Act:     render the document and read the PRA001 rule-book line.
    Assert:  it gives the published count, the deactivated count and their difference.
    """
    # Arrange
    book = release_rulebook(RELEASE, MODULE)
    deny_list = release_deny_list(RELEASE)
    assert book is not None
    published = date.fromisoformat(str(deny_list.source["published"]))
    off = {
        code for code, item in deny_list.in_force(MODULE, published).items() if item.is_deactivation
    }
    enforced = book.enforced(MODULE)
    switched_off = sum(1 for rule in enforced if rule.rule_id in off)
    assert switched_off, "the deny list deactivates no PRA001 rule: this test would prove nothing"

    # Act
    text = render_document([load_issues(RELEASE)])
    line = next(
        item for item in text.splitlines() if item.startswith(f"- **Rule book ({MODULE}):**")
    )

    # Assert
    assert f"{len(enforced):,} rules are published for a {MODULE} return" in line
    assert (
        f"the Bank's gateway runs {len(enforced) - switched_off:,} of them: the deny list "
        f"deactivates {switched_off} as at 16 November 2026"
    ) in line
    assert "rules run on a" not in line


def test_each_example_heading_counts_cells_not_facts() -> None:
    """The collapsed table is headed by the number of cells it lists, called cells.

    Arrange: the register's examples.
    Act:     render the document and read every example heading.
    Assert:  one heading per example, each "The example's N cell(s)" with N the
             number of cells an example lists; none calls them facts.
    """
    # Arrange
    register = load_issues(RELEASE)
    expected = [len(issue.example.facts) for issue in register.issues if issue.example is not None]

    # Act
    text = render_document([register])
    headings = re.findall(r"<summary>(.*?)</summary>", text)

    # Assert
    assert [heading for heading in headings if "facts" in heading] == []
    # (the document groups issues by kind, so compare as sorted lists)
    assert sorted(headings) == sorted(
        f"The example's {count} cell{'s' if count != 1 else ''}" for count in expected
    )


def test_an_example_with_shared_data_points_lists_more_cells_than_arelle_counts_facts() -> None:
    """The adequacy of the test above: the two units really differ somewhere.

    Arrange: Arelle's fact count per example, and the cells each lists.
    Act:     find the examples where the counts differ.
    Assert:  there is at least one (PI-35 among them), and on none does Arelle
             count MORE facts than cells.
    """
    # Arrange
    arelle = json.loads(ORACLE.read_text(encoding="utf-8"))["returns"]
    cells = {
        issue.id: len(issue.example.facts)
        for issue in load_issues(RELEASE).issues
        if issue.example is not None
    }

    # Act
    differ = {
        key: (cells[key], arelle[key]["facts"])
        for key in cells
        if cells[key] != arelle[key]["facts"]
    }

    # Assert
    assert "PI-35" in differ, differ
    assert all(listed > counted for listed, counted in differ.values()), differ
