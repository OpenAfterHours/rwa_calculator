"""
Offline integrity of the two packaged validation-rule extracts.

Pipeline position:
    rules/data/*.json (package data)  ->  load_rules  ->  everything downstream

Why this exists: ``rwa-filer rules check`` re-derives the extracts from the
publishers' workbooks, but those workbooks are not redistributed with the
package (and sit behind a download), so the regeneration path cannot run in CI.
This file is the offline substitute — it catches a corrupted, truncated or
half-regenerated extract with no network and no source spreadsheet.

Key responsibilities:
- The files parse with NO ``encoding=`` kwarg. They are deliberately pure ASCII,
  so a cp1252 Windows runner reading them with the platform default cannot
  mangle (or raise on) a publisher's typographic dash.
- The top-level shape is ``source`` / ``filter`` / ``rules``, and every rule
  object carries the fields the per-publisher parser reads unconditionally.
- The loaded and enforced counts are exactly what was extracted, checked BOTH
  against the pinned figures and against the extractor's own recorded tallies in
  the ``filter`` block — so a half-written file fails even if it parses.
- The ``rules/data/`` directory stays a plain data directory with no
  ``__init__.py``: it is read through ``importlib.resources``, never imported.

References:
- rwa_filer.rules.importer — the (offline-only) regeneration path
"""

from __future__ import annotations

from importlib import resources

import pytest

from filer_builders import (
    EXTRACT_FILES,
    extract_bytes,
    raw_extract,
)
from rwa_filer.rules.catalogue import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    RULES_DIRECTORY,
    RULES_PACKAGE,
    load_rules,
)

#: The pinned population per framework: (rules loaded, rules currently enforced).
#: A change here is a deliberate taxonomy refresh, never an accident.
EXPECTED_COUNTS: dict[str, tuple[int, int]] = {
    FRAMEWORK_CRR: (1011, 741),
    FRAMEWORK_BASEL_3_1: (820, 808),
}

#: Fields the EBA / BoE parsers index unconditionally — a missing one is a
#: ``KeyError`` at import of the first report, not a graceful degradation.
REQUIRED_RULE_FIELDS: dict[str, tuple[str, ...]] = {
    "EBA": (
        "id",
        "severity",
        "type",
        "status",
        "tables",
        "rows",
        "rows_scope",
        "columns",
        "columns_scope",
        "sheets",
        "sheets_scope",
        "formula",
        "prerequisites",
        "if_value_missing",
        "arithmetic_approach",
        "narrative",
        "reactivated_on",
    ),
    "BoE": (
        "id",
        "severity",
        "status",
        "tables",
        "expression",
        "expression_raw",
        "precondition",
        "precondition_raw",
        "scope",
        "where",
        "short_label",
    ),
}

FRAMEWORKS = [FRAMEWORK_CRR, FRAMEWORK_BASEL_3_1]


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_extract_contains_no_byte_above_ascii(framework: str) -> None:
    """Pure ASCII by construction — the property that makes the encoding moot."""
    # Arrange
    payload = extract_bytes(framework)

    # Act
    non_ascii = [index for index, byte in enumerate(payload) if byte > 127]

    # Assert
    assert non_ascii == [], f"{len(non_ascii)} non-ASCII byte(s), first at offset {non_ascii[:1]}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_extract_parses_without_an_explicit_encoding(framework: str) -> None:
    """Read with the platform default and it must still be JSON.

    ``raw_extract`` deliberately omits ``encoding=``; on a cp1252 runner that is
    the assertion, not an oversight.
    """
    # Arrange / Act
    payload = raw_extract(framework)

    # Assert
    assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_extract_has_the_expected_top_level_shape(framework: str) -> None:
    """``source`` (provenance), ``filter`` (what was selected), ``rules`` (the data)."""
    # Arrange / Act
    payload = raw_extract(framework)

    # Assert
    assert set(payload) == {"source", "filter", "rules"}


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_source_block_records_its_provenance(framework: str) -> None:
    """A rule extract with no traceable origin cannot be audited."""
    # Arrange / Act
    source = raw_extract(framework)["source"]

    # Assert
    assert {"publisher", "file", "url", "retrieved", "framework_version"} <= set(source)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_rule_object_carries_the_fields_its_parser_reads(framework: str) -> None:
    """One missing key anywhere in the file is a KeyError at the first report."""
    # Arrange
    payload = raw_extract(framework)
    required = set(REQUIRED_RULE_FIELDS[payload["source"]["publisher"]])

    # Act
    incomplete = [rule.get("id") for rule in payload["rules"] if not required <= set(rule)]

    # Assert
    assert incomplete == []


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_rule_declares_at_least_one_table(framework: str) -> None:
    """A rule with no table code can never be bound to a generated frame."""
    # Arrange / Act
    tableless = [rule["id"] for rule in raw_extract(framework)["rules"] if not rule["tables"]]

    # Assert
    assert tableless == []


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_loaded_and_enforced_counts_match_the_pinned_population(framework: str) -> None:
    """A truncated or re-scoped extract changes these figures and must be noticed."""
    # Arrange
    ruleset = load_rules(framework)

    # Act
    counts = (len(ruleset.rules), len(ruleset.enforced))

    # Assert
    assert counts == EXPECTED_COUNTS[framework]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_rule_count_matches_the_extractors_own_tally(framework: str) -> None:
    """``filter.matched`` is what the extractor said it wrote; the file must agree.

    Catches a half-written file that still parses: the header claims N rules and
    the array holds fewer.
    """
    # Arrange
    payload = raw_extract(framework)

    # Act / Assert
    assert len(payload["rules"]) == payload["filter"]["matched"]


def test_the_eba_enforced_count_matches_the_recorded_reactivation_tally() -> None:
    """The extractor recorded ``live_or_reactivated``; the loader must reproduce it."""
    # Arrange
    payload = raw_extract(FRAMEWORK_CRR)

    # Act / Assert
    assert len(load_rules(FRAMEWORK_CRR).enforced) == payload["filter"]["live_or_reactivated"]


def test_the_boe_enforced_count_matches_the_recorded_xbrl_tally() -> None:
    """The BoE population in force is the one included in XBRL."""
    # Arrange
    payload = raw_extract(FRAMEWORK_BASEL_3_1)

    # Act / Assert
    assert len(load_rules(FRAMEWORK_BASEL_3_1).enforced) == payload["filter"]["in_xbrl"]


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_extract_is_reachable_as_package_data(framework: str) -> None:
    """The loader reads through ``importlib.resources``, so must a wheel install."""
    # Arrange
    package = resources.files(RULES_PACKAGE)

    # Act
    extract = package.joinpath(RULES_DIRECTORY, EXTRACT_FILES[framework])

    # Assert
    assert extract.is_file()


def test_the_rules_data_directory_is_not_a_package() -> None:
    """The extracts are data: read through ``importlib.resources``, never imported."""
    # Arrange
    package = resources.files(RULES_PACKAGE)

    # Act
    marker = package.joinpath(RULES_DIRECTORY, "__init__.py")

    # Assert
    assert not marker.is_file()
