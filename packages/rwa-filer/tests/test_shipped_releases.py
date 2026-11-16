"""
The shipped releases — the packaged data held to ``releases.json``.

``releases.json`` is the one file edited by hand to add or retire a taxonomy
release. These tests make the packaged data agree with it exactly, so a release
cannot be half-added (a pack with no rule book, a release listed with nothing
packaged) or left behind (data of a release no longer listed), and they hold
the packaged data to a size budget in place of a cap on the number of releases.

References:
- docs/plans/taxonomy-release-selection.md — §7.1 (the contract), D3 (no cap)
"""

from __future__ import annotations

import zlib
from collections import Counter
from importlib import resources

from rwa_filer.boe.catalogue import RULEBOOKS_DIRECTORY, RULEBOOKS_PACKAGE, load_rulebook
from rwa_filer.boe.deny import available_deny_lists, load_deny_list
from rwa_filer.release import (
    RELEASES_FILE,
    RELEASES_PACKAGE,
    RETIRED_FILE,
    release_packs,
    release_rulebook,
    release_rulebooks,
    retired_releases,
    shipped_releases,
)
from rwa_filer.taxonomy.pack import PACKS_DIRECTORY, PACKS_PACKAGE, available_packs

#: The compressed size the packaged taxonomy data may reach. One release is
#: about 1.6 MB today (4.1.1: 1.36 MB of packs, 0.23 MB of rule books and its
#: deny list, which is counted with them under boe/data/deny), so this
#: is roughly 30 releases, well below PyPI's default 100 MB limit per file.
#: Reaching it is a prompt to retire releases or to revisit shipping each
#: release as its own package (plan §11) — not a number to raise quietly.
SIZE_BUDGET_BYTES = 50 * 1024 * 1024


def test_no_release_is_listed_twice_or_both_shipped_and_retired() -> None:
    shipped = shipped_releases()
    retired = [item.version for item in retired_releases()]

    assert shipped, "releases.json lists no release: nothing could be validated"
    assert [version for version, count in Counter(shipped).items() if count > 1] == []
    assert set(shipped).isdisjoint(retired)
    assert all(item.last_shipped_in for item in retired_releases())


def test_every_packaged_pack_belongs_to_a_shipped_release() -> None:
    shipped = set(shipped_releases())

    stray = sorted(info.key for info in available_packs() if info.version not in shipped)

    assert stray == [], f"packs of releases releases.json does not list: {stray}"


def test_every_pack_sits_in_the_directory_its_key_names() -> None:
    root = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY)
    directories = sorted(entry.name for entry in root.iterdir() if entry.is_dir())

    assert directories == sorted(info.key for info in available_packs())


def test_every_packaged_rule_book_belongs_to_a_shipped_release() -> None:
    shipped = set(shipped_releases())
    root = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY)

    stray = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.name.endswith(".json") and load_rulebook(entry.name).taxonomy not in shipped
    )

    assert stray == [], f"rule books of releases releases.json does not list: {stray}"


def test_every_shipped_release_packages_its_validations_deny_list() -> None:
    """A release without one would run every rule the Bank's gateway has switched off."""
    missing = sorted(set(shipped_releases()) - set(available_deny_lists()))

    assert missing == [], f"shipped releases with no packaged deny list: {missing}"


def test_every_packaged_deny_list_belongs_to_a_shipped_release() -> None:
    stray = sorted(set(available_deny_lists()) - set(shipped_releases()))

    assert stray == [], f"deny lists of releases releases.json does not list: {stray}"


def test_every_deny_list_entry_names_a_rule_of_its_module_in_its_release() -> None:
    """An entry the rule book cannot match would deny nothing, silently."""
    orphans = sorted(
        f"{version} {entry.module} {entry.rule_id}"
        for version in shipped_releases()
        for entry in load_deny_list(version).entries
        if (book := release_rulebook(version, entry.module)) is None
        or (rule := book.rule(entry.rule_id)) is None
        or entry.module not in rule.severities
    )

    assert orphans == []


def test_every_shipped_release_packages_packs_and_rule_books() -> None:
    empty = [
        version
        for version in shipped_releases()
        if not release_packs(version) or not release_rulebooks(version)
    ]

    assert empty == [], f"releases listed with nothing packaged: {empty}"


def test_every_packaged_pack_has_a_rule_book_in_its_own_release() -> None:
    """A pack with no rules would be checked for structure only, silently."""
    missing = sorted(
        info.key
        for version in shipped_releases()
        for info in release_packs(version)
        if release_rulebook(version, info.module) is None
    )

    assert missing == []


def test_no_module_is_in_two_rule_books_of_one_release() -> None:
    doubled = {
        version: sorted(module for module, count in modules.items() if count > 1)
        for version in shipped_releases()
        if (
            modules := Counter(
                module.upper()
                for file_name in release_rulebooks(version)
                for module in load_rulebook(file_name).modules
            )
        )
    }

    assert {version: found for version, found in doubled.items() if found} == {}


def test_the_packaged_taxonomy_data_stays_within_its_size_budget() -> None:
    # Arrange — compressed as a wheel compresses it (deflate).
    roots = (
        resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY),
        resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY),
    )
    files = [*_files(roots[0]), *_files(roots[1])]
    files += [
        resources.files(RELEASES_PACKAGE).joinpath(name) for name in (RELEASES_FILE, RETIRED_FILE)
    ]

    # Act
    size = sum(len(zlib.compress(item.read_bytes(), 6)) for item in files)

    # Assert
    assert files, "no packaged data found: the budget would be measured on nothing"
    assert size <= SIZE_BUDGET_BYTES, (
        f"{size / 1024 / 1024:.1f} MB of compressed taxonomy data exceeds the "
        f"{SIZE_BUDGET_BYTES / 1024 / 1024:.0f} MB budget"
    )


def _files(root):  # noqa: ANN001, ANN202 - importlib.resources Traversable
    """Every file under ``root``, recursively."""
    for entry in root.iterdir():
        if entry.is_dir():
            yield from _files(entry)
        elif entry.is_file():
            yield entry
