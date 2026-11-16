"""
The packaged publisher-issue registers: well formed, and true to the rules they name.

Pipeline position:
    boe/data/issues/<release>.json  ->  load_issues  ->  IssueRegister
        ->  the labels on a verdict, and docs/rwa-filer/publisher-issues.md

A register is curated by hand, so these tests are what keeps it honest against
the release it is recorded for (``.claude/LESSONS.md`` B3 — anchored to the rule
book and the taxonomy pack, which a hand edit cannot drift with):
- it validates against ``schemas/publisher-issues-1.schema.json``;
- every rule it names is a rule of that module in that release's rule book, at
  the fingerprint and severity it records — a register that pinned a rule
  wrongly would label nothing, silently;
- a rule the gateway does not run is named only by an issue that does not
  label results, or in a role other than the subject;
- every footprint names tables, rows, columns and sheets the module's pack has;
- an issue's status agrees with its fields (raised on a date, acknowledged in
  the Bank's own log, fixed in a later release);
- every issue that labels a result has a subject rule and a minimal example;
- every quote names a document the register lists, with a page where the
  document is a PDF.

The quotes themselves are checked against the PDFs by the root
``tests/contracts/test_publisher_issue_quotes.py`` (the PDFs are not in the
repository); Arelle's counts on each example by ``test_publisher_issues_oracle.py``.

References:
- rwa_filer.boe.issues — the register
"""

from __future__ import annotations

import json
from importlib import resources

import jsonschema
import pytest

from rwa_filer.boe.issues import (
    ISSUES_DIRECTORY,
    ISSUES_PACKAGE,
    LABELLING_EFFECTS,
    LOG_ACKNOWLEDGES,
    ROLE_SUBJECT,
    STATUS_ACKNOWLEDGED,
    STATUS_FIXED,
    STATUS_RAISED,
    issue_register_file,
    load_issues,
)
from rwa_filer.release import release_rulebook, shipped_releases, version_key
from rwa_filer.schemas import PUBLISHER_ISSUES_SCHEMA, load_schema
from rwa_filer.taxonomy.pack import load_packaged

RELEASES = shipped_releases()


def _payload(version: str) -> dict[str, object]:
    resource = resources.files(ISSUES_PACKAGE).joinpath(
        *ISSUES_DIRECTORY, issue_register_file(version)
    )
    return json.loads(resource.read_text(encoding="utf-8"))


@pytest.mark.parametrize("version", RELEASES)
def test_the_register_validates_against_its_schema(version: str) -> None:
    # Act / Assert
    jsonschema.validate(_payload(version), load_schema(PUBLISHER_ISSUES_SCHEMA))


@pytest.mark.parametrize("version", RELEASES)
def test_the_register_is_the_releases_own(version: str) -> None:
    # Act
    register = load_issues(version)

    # Assert
    assert register.release == version
    assert register.issues, "a shipped release's register lists no issue"


@pytest.mark.parametrize("version", RELEASES)
def test_every_rule_named_is_the_rule_of_that_release_at_its_fingerprint(version: str) -> None:
    """A pin that does not match labels nothing: the register would look right and do nothing."""
    # Arrange
    register = load_issues(version)
    wrong: list[str] = []

    # Act
    for issue in register.issues:
        for entry in issue.rules:
            book = release_rulebook(version, entry.module)
            found = book.rule(entry.rule_id) if book is not None else None
            if found is None or entry.module not in found.severities:
                wrong.append(f"{issue.id} {entry.module} {entry.rule_id}: not a rule of the module")
                continue
            if found.fingerprint(entry.module) != entry.rule_sha256:
                wrong.append(f"{issue.id} {entry.rule_id}: rule_sha256 is not its fingerprint")
            if found.severity(entry.module) != entry.severity:
                wrong.append(f"{issue.id} {entry.rule_id}: severity is not the rule book's")

    # Assert
    assert wrong == []


@pytest.mark.parametrize("version", RELEASES)
def test_a_rule_the_gateway_does_not_run_is_never_a_labelled_subject(version: str) -> None:
    # Arrange
    register = load_issues(version)

    # Act
    unrun = [
        f"{issue.id} {entry.rule_id}"
        for issue in register.issues
        if issue.effect in LABELLING_EFFECTS
        for entry in issue.subject_rules
        if (book := release_rulebook(version, entry.module)) is not None
        and (found := book.rule(entry.rule_id)) is not None
        and not found.is_enforced(entry.module)
    ]

    # Assert
    assert unrun == []


@pytest.mark.parametrize("version", RELEASES)
def test_every_footprint_names_cells_the_modules_pack_has(version: str) -> None:
    # Arrange
    register = load_issues(version)
    unknown: list[str] = []

    # Act
    for issue in register.issues:
        for entry in issue.rules:
            pack = load_packaged(f"{entry.module}-{version}".lower())
            for selector in entry.footprint or ():
                table = pack.tables.get(selector.table)
                if table is None:
                    unknown.append(f"{issue.id} {entry.rule_id}: table {selector.table}")
                    continue
                for codes, known in (
                    ((*selector.rows, *selector.rows_except), table.row_codes),
                    ((*selector.columns, *selector.columns_except), table.column_codes),
                    ((*selector.sheets, *selector.sheets_except), table.sheet_codes),
                ):
                    unknown += [
                        f"{issue.id} {entry.rule_id}: {selector.table} has no {code}"
                        for code in codes
                        if code not in known
                    ]

    # Assert
    assert unknown == []


@pytest.mark.parametrize("version", RELEASES)
def test_each_status_agrees_with_what_the_issue_records(version: str) -> None:
    # Arrange
    register = load_issues(version)
    wrong: list[str] = []

    # Act
    for issue in register.issues:
        if (issue.fixed_in is not None) != (issue.status == STATUS_FIXED):
            wrong.append(f"{issue.id}: fixed_in is set if and only if it is fixed")
        if issue.fixed_in is not None and version_key(issue.fixed_in) <= version_key(version):
            wrong.append(f"{issue.id}: fixed in {issue.fixed_in}, not after {version}")
        if issue.status == STATUS_RAISED and issue.raised is None:
            wrong.append(f"{issue.id}: raised, with no date")
        acknowledged = any(entry.relation == LOG_ACKNOWLEDGES for entry in issue.publisher_log)
        if (issue.status == STATUS_ACKNOWLEDGED) != (
            issue.publisher_reference is not None and acknowledged
        ):
            wrong.append(
                f"{issue.id}: acknowledged if and only if the Bank's log acknowledges it "
                "and the reference says where"
            )

    # Assert
    assert wrong == []


@pytest.mark.parametrize("version", RELEASES)
def test_every_labelling_issue_has_a_subject_and_a_minimal_example(version: str) -> None:
    # Arrange
    register = load_issues(version)

    # Act
    short = [
        issue.id
        for issue in register.issues
        if issue.effect in LABELLING_EFFECTS
        and (
            not issue.subject_rules
            or issue.example is None
            or not issue.example.facts
            or not any(entry.role == ROLE_SUBJECT for entry in issue.rules)
        )
    ]

    # Assert
    assert short == []


@pytest.mark.parametrize("version", RELEASES)
def test_every_quote_names_a_listed_document_and_a_pdf_page(version: str) -> None:
    # Arrange
    register = load_issues(version)
    wrong: list[str] = []

    # Act
    for issue in register.issues:
        for item in issue.authority:
            document = register.documents.get(item.document)
            if document is None:
                wrong.append(f"{issue.id}: {item.document} is not a listed document")
                continue
            is_pdf = (document.file or "").endswith(".pdf")
            if is_pdf != (item.pdf_page is not None):
                wrong.append(f"{issue.id}: {item.document} page {item.pdf_page}")

    # Assert
    assert wrong == []
