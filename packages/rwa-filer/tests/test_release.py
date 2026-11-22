"""
Choosing the taxonomy release a run uses — ``rwa_filer.release``.

The packaged data holds one release, so the rules for choosing between several
are tested on synthetic releases: the resolver's package-data readers are
swapped for an in-memory set of packs and rule books (``releases`` fixture).
The last section checks the same resolver against the real packaged data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from boe_builders import book
from pack_builders import SAMPLE_MODULE, build_pack
from rwa_filer import release as release_module
from rwa_filer.boe.catalogue import RuleBook
from rwa_filer.boe.deny import DenyList
from rwa_filer.boe.issues import IssueRegister
from rwa_filer.release import (
    CHOSEN_DEFAULT,
    CHOSEN_PACK,
    CHOSEN_VERSION,
    STATUS_FUTURE,
    STATUS_LIVE,
    STATUS_SUPERSEDED,
    Release,
    ReleaseNotFoundError,
    choose_release,
    default_release_version,
    long_date,
    release_for_pack,
    release_lines,
    release_packs,
    release_record,
    resolve_release,
    shipped_releases,
    status_on,
    version_key,
)
from rwa_filer.taxonomy.pack import PackInfo, TaxonomyPack

TODAY = date(2027, 3, 31)
ENTRY_A = "http://example.test/fws/test/2027-01-01/mod/tst001.xsd"
ENTRY_B = "http://example.test/fws/test/2028-01-01/mod/tst001.xsd"


class Releases:
    """An in-memory set of shipped releases the resolver reads instead of package data."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, base: TaxonomyPack) -> None:
        self._monkeypatch = monkeypatch
        self._base = base
        self.versions: list[str] = []
        self.retired: list[dict[str, object]] = []
        self.packs: dict[str, TaxonomyPack] = {}
        self.books: dict[str, RuleBook] = {}
        monkeypatch.setattr(release_module, "_releases_payload", self._releases)
        monkeypatch.setattr(release_module, "_retired_payload", self._retired)
        monkeypatch.setattr(release_module, "pack_info", self._info)
        monkeypatch.setattr(release_module, "load_packaged", lambda key: self.packs[key])
        monkeypatch.setattr(release_module, "available_packs", self._available)
        monkeypatch.setattr(
            release_module, "available_rulebooks", lambda: tuple(sorted(self.books))
        )
        monkeypatch.setattr(release_module, "load_rulebook", lambda name: self.books[name])
        # The in-memory releases ship no validations deny list and no issue register.
        monkeypatch.setattr(release_module, "load_deny_list", DenyList.empty)
        monkeypatch.setattr(release_module, "load_issues", IssueRegister.empty)

    def add(
        self,
        version: str,
        valid_from: date,
        valid_to: date | None = None,
        *,
        entry_point: str = ENTRY_A,
        rulebook: bool = True,
    ) -> None:
        """Ship ``version`` with a TST001 pack (and, by default, a rule book)."""
        info = replace(
            self._base.info,
            version=version,
            valid_from=valid_from,
            valid_to=valid_to,
            entry_point=entry_point,
        )
        self.packs[info.key] = replace(self._base, info=info)
        if rulebook:
            self.books[f"test-{version}.json"] = replace(
                book(), taxonomy=version, source={"taxonomy": version}
            )
        self.versions.append(version)

    def _releases(self) -> dict[str, object]:
        return {"format": 1, "releases": [{"version": version} for version in self.versions]}

    def _retired(self) -> dict[str, object]:
        return {"format": 1, "releases": self.retired}

    def _info(self, key: str) -> PackInfo | None:
        pack = self.packs.get(key)
        return pack.info if pack is not None else None

    def _available(self) -> tuple[PackInfo, ...]:
        return tuple(pack.info for pack in self.packs.values())


@pytest.fixture
def releases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Releases:
    return Releases(monkeypatch, build_pack(tmp_path / "pack"))


# ---------------------------------------------------------------------------
# Ordering and status
# ---------------------------------------------------------------------------


def test_versions_are_ordered_as_numbers_not_text() -> None:
    assert version_key("4.10.0") > version_key("4.9.0") > version_key("4.1.1")
    assert sorted(["4.9.0", "4.10.0", "4.1.1"], key=version_key) == ["4.1.1", "4.9.0", "4.10.0"]


def test_the_shipped_releases_are_listed_newest_first(releases: Releases) -> None:
    for version in ("4.9.0", "4.10.0", "4.1.1"):
        releases.add(version, date(2027, 1, 1))

    assert shipped_releases() == ("4.10.0", "4.9.0", "4.1.1")


def test_a_modules_status_follows_its_pack_dates_inclusively() -> None:
    info = PackInfo("M", "", "", "1", "x", date(2027, 1, 1), date(2027, 12, 31))

    assert status_on(info, date(2026, 12, 31)) == STATUS_FUTURE
    assert status_on(info, date(2027, 1, 1)) == STATUS_LIVE
    assert status_on(info, date(2027, 12, 31)) == STATUS_LIVE
    assert status_on(info, date(2028, 1, 1)) == STATUS_SUPERSEDED


def test_a_date_reads_as_day_month_year() -> None:
    assert long_date(date(2027, 1, 1)) == "1 January 2027"


# ---------------------------------------------------------------------------
# The default
# ---------------------------------------------------------------------------


def test_the_default_is_the_live_release_even_when_a_newer_one_is_shipped(
    releases: Releases,
) -> None:
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1), date(2027, 12, 31))
    releases.add("4.2.0", date(2028, 1, 1))

    # Act
    chosen = resolve_release(SAMPLE_MODULE, today=TODAY)

    # Assert
    assert (chosen.version, chosen.status, chosen.chosen_by) == ("4.1.1", STATUS_LIVE, "default")
    assert [option.version for option in chosen.others] == ["4.2.0"]


def test_with_several_live_releases_the_default_is_the_newest(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.1.2", date(2027, 1, 1))

    assert resolve_release(SAMPLE_MODULE, today=TODAY).version == "4.1.2"


def test_with_no_live_release_the_only_future_one_is_the_default(releases: Releases) -> None:
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1))

    # Act
    chosen = resolve_release(SAMPLE_MODULE, today=date(2026, 11, 15))

    # Assert
    assert (chosen.version, chosen.status) == ("4.1.1", STATUS_FUTURE)


def test_with_no_live_release_and_several_future_ones_the_user_must_choose(
    releases: Releases,
) -> None:
    # Arrange
    releases.add("4.2.0", date(2028, 1, 1))
    releases.add("4.3.0", date(2028, 7, 1))

    # Act / Assert
    with pytest.raises(ReleaseNotFoundError) as caught:
        resolve_release(SAMPLE_MODULE, today=TODAY)
    message = str(caught.value)
    assert "--taxonomy VERSION" in message
    assert "4.2.0 (future from 1 January 2028)" in message
    assert "4.3.0 (future from 1 July 2028)" in message


def test_a_future_release_is_preferred_to_a_superseded_one(releases: Releases) -> None:
    releases.add("4.0.0", date(2026, 1, 1), date(2026, 12, 31))
    releases.add("4.1.1", date(2028, 1, 1))

    assert resolve_release(SAMPLE_MODULE, today=TODAY).version == "4.1.1"


def test_a_lone_superseded_release_is_still_the_default(releases: Releases) -> None:
    releases.add("4.0.0", date(2026, 1, 1), date(2026, 12, 31))

    chosen = resolve_release(SAMPLE_MODULE, today=TODAY)

    assert (chosen.version, chosen.status) == ("4.0.0", STATUS_SUPERSEDED)


def test_the_module_is_matched_whatever_its_case(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    assert resolve_release(SAMPLE_MODULE.lower(), today=TODAY).module == SAMPLE_MODULE


def test_a_module_no_shipped_release_has_is_refused(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    with pytest.raises(
        ReleaseNotFoundError, match=r"No shipped taxonomy release has module XYZ999"
    ):
        resolve_release("XYZ999", today=TODAY)


# ---------------------------------------------------------------------------
# The default's version, with nothing loaded
# ---------------------------------------------------------------------------

#: Four releases that never overlap, with a gap in 2027: on one run date or
#: another every way the default is chosen — or refused — is reached.
LADDER = (
    ("4.0.0", date(2025, 1, 1), date(2025, 12, 31)),
    ("4.1.0", date(2026, 1, 1), date(2026, 12, 31)),
    ("4.2.0", date(2028, 1, 1), date(2028, 12, 31)),
    ("4.3.0", date(2029, 1, 1), date(2029, 12, 31)),
)
#: Two releases live at once from 2027, and one release alone.
OVERLAP = (("4.1.1", date(2027, 1, 1), None), ("4.1.2", date(2027, 1, 1), None))
ALONE = (("4.1.1", date(2027, 1, 1), date(2027, 12, 31)),)
SHIPPED = {"ladder": LADDER, "overlap": OVERLAP, "alone": ALONE}


def _default_or_refusal(
    resolve: Callable[..., str | Release], module: str, day: date
) -> tuple[str, str]:
    """What asking for the default gave: ``("version", v)`` or ``("refused", message)``."""
    try:
        chosen = resolve(module, today=day)
    except ReleaseNotFoundError as refusal:
        return "refused", str(refusal)
    return "version", chosen if isinstance(chosen, str) else chosen.version


@pytest.mark.parametrize(
    ("shipped", "module", "day", "expected"),
    [
        pytest.param("ladder", SAMPLE_MODULE, date(2025, 6, 30), "4.0.0", id="the-live-one"),
        pytest.param("ladder", SAMPLE_MODULE, date(2028, 6, 30), "4.2.0", id="a-later-live-one"),
        pytest.param("overlap", SAMPLE_MODULE, TODAY, "4.1.2", id="newest-of-two-live"),
        pytest.param("alone", SAMPLE_MODULE, date(2026, 11, 15), "4.1.1", id="the-only-future"),
        pytest.param("alone", SAMPLE_MODULE, date(2030, 1, 1), "4.1.1", id="a-lone-superseded"),
        pytest.param("alone", SAMPLE_MODULE.lower(), TODAY, "4.1.1", id="module-in-lower-case"),
        pytest.param("ladder", SAMPLE_MODULE, date(2024, 6, 30), None, id="four-future"),
        pytest.param("ladder", SAMPLE_MODULE, date(2027, 6, 30), None, id="two-future-two-past"),
        pytest.param("ladder", SAMPLE_MODULE, date(2030, 6, 30), None, id="four-superseded"),
        pytest.param("alone", "XYZ999", TODAY, None, id="no-release-has-the-module"),
    ],
)
def test_the_defaults_version_is_what_resolving_the_release_gives(
    releases: Releases, shipped: str, module: str, day: date, expected: str | None
) -> None:
    """The same version — or the same refusal, word for word."""
    # Arrange
    for version, valid_from, valid_to in SHIPPED[shipped]:
        releases.add(version, valid_from, valid_to)

    # Act
    shortcut = _default_or_refusal(default_release_version, module, day)
    resolved = _default_or_refusal(resolve_release, module, day)

    # Assert — the expectation is written out, so the two cannot be wrong together.
    assert resolved[0] == ("refused" if expected is None else "version")
    assert expected is None or resolved[1] == expected
    assert shortcut == resolved


def test_the_defaults_version_is_found_without_loading_the_release(
    releases: Releases, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — a release whose pack, rule book, deny list and issues cannot be loaded.
    releases.add("4.1.1", date(2027, 1, 1))

    def unloadable(*_args: object) -> None:
        raise AssertionError("the release was loaded to name its version")

    for loader in ("load_packaged", "load_rulebook", "load_deny_list", "load_issues"):
        monkeypatch.setattr(release_module, loader, unloadable)

    # Act
    version = default_release_version(SAMPLE_MODULE, today=TODAY)

    # Assert — and resolving it does load: the stand-ins are where the loading goes.
    assert version == "4.1.1"
    with pytest.raises(AssertionError, match="the release was loaded"):
        resolve_release(SAMPLE_MODULE, today=TODAY)


# ---------------------------------------------------------------------------
# A release the user names
# ---------------------------------------------------------------------------


def test_a_named_release_is_used_even_when_it_is_not_the_default(releases: Releases) -> None:
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.2.0", date(2028, 1, 1))

    # Act
    chosen = resolve_release(SAMPLE_MODULE, "4.2.0", today=TODAY)

    # Assert
    assert (chosen.version, chosen.status, chosen.chosen_by) == ("4.2.0", STATUS_FUTURE, "version")


def test_the_pack_and_the_rule_book_always_come_from_the_same_release(releases: Releases) -> None:
    """The defect this module replaced: the first rule book by file name won.

    With 4.1.1 and 4.10.0 both shipped, ``test-4.1.1.json`` sorts first, so the
    old lookup handed 4.10.0's pack the 4.1.1 rules.
    """
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.10.0", date(2028, 1, 1))
    assert sorted(releases.books)[0] == "test-4.1.1.json", "the old order must favour 4.1.1"

    # Act
    newer = resolve_release(SAMPLE_MODULE, "4.10.0", today=TODAY)
    older = resolve_release(SAMPLE_MODULE, "4.1.1", today=TODAY)

    # Assert
    assert newer.rulebook is not None and newer.rulebook.taxonomy == "4.10.0"
    assert older.rulebook is not None and older.rulebook.taxonomy == "4.1.1"
    assert newer.pack.info.version == "4.10.0"


def test_a_release_that_is_not_shipped_is_refused_with_what_is(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    with pytest.raises(
        ReleaseNotFoundError, match=r"9\.9\.9 is not shipped.*Shipped releases: 4\.1\.1"
    ):
        resolve_release(SAMPLE_MODULE, "9.9.9", today=TODAY)


def test_a_retired_release_says_which_rwa_filer_version_last_shipped_it(
    releases: Releases,
) -> None:
    releases.add("4.1.1", date(2027, 1, 1))
    releases.retired.append({"version": "4.0.0", "last_shipped_in": "0.3.2"})

    with pytest.raises(ReleaseNotFoundError, match=r'no longer shipped.*uvx "rwa-filer@0\.3\.2"'):
        resolve_release(SAMPLE_MODULE, "4.0.0", today=TODAY)


def test_a_named_release_without_the_module_is_refused(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.2.0", date(2028, 1, 1))
    del releases.packs[f"{SAMPLE_MODULE}-4.2.0".lower()]

    with pytest.raises(ReleaseNotFoundError, match=r"4\.2\.0 has no pack for module TST001"):
        resolve_release(SAMPLE_MODULE, "4.2.0", today=TODAY)


# ---------------------------------------------------------------------------
# A file that names its entry point
# ---------------------------------------------------------------------------


def test_a_files_entry_point_narrows_the_default_to_the_releases_that_have_it(
    releases: Releases,
) -> None:
    # Arrange — 4.2.0 is the live one, but only 4.1.1 has the file's entry point.
    releases.add("4.1.1", date(2026, 1, 1), date(2026, 12, 31), entry_point=ENTRY_A)
    releases.add("4.2.0", date(2027, 1, 1), entry_point=ENTRY_B)

    # Act
    chosen = resolve_release(None, entry_point=ENTRY_A, today=TODAY)

    # Assert
    assert (chosen.module, chosen.version) == (SAMPLE_MODULE, "4.1.1")


def test_a_named_release_with_another_entry_point_cannot_read_the_file(
    releases: Releases,
) -> None:
    releases.add("4.1.1", date(2027, 1, 1), entry_point=ENTRY_A)
    releases.add("4.2.0", date(2028, 1, 1), entry_point=ENTRY_B)

    with pytest.raises(ReleaseNotFoundError) as caught:
        resolve_release(None, "4.2.0", entry_point=ENTRY_A, today=TODAY)
    assert ENTRY_A in str(caught.value) and ENTRY_B in str(caught.value)


def test_an_entry_point_no_shipped_release_has_is_refused(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    with pytest.raises(
        ReleaseNotFoundError, match="No shipped taxonomy release has the entry point"
    ):
        resolve_release(None, entry_point="http://example.test/other/mod/tst001.xsd", today=TODAY)


def test_an_entry_point_of_a_retired_release_names_where_it_went(releases: Releases) -> None:
    releases.add("4.2.0", date(2028, 1, 1), entry_point=ENTRY_B)
    releases.retired.append(
        {"version": "4.1.1", "last_shipped_in": "0.2.0", "entry_points": [ENTRY_A]}
    )

    with pytest.raises(ReleaseNotFoundError, match=r"only taxonomy 4\.1\.1 has.*rwa-filer 0\.2\.0"):
        resolve_release(None, entry_point=ENTRY_A, today=TODAY)


# ---------------------------------------------------------------------------
# A pack a library caller passes, and choosing among the ways of saying it
# ---------------------------------------------------------------------------


def test_a_pack_passed_in_takes_the_rule_book_of_its_own_release(releases: Releases) -> None:
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.2.0", date(2028, 1, 1))
    pack = releases.packs[f"{SAMPLE_MODULE}-4.2.0".lower()]

    # Act
    chosen = release_for_pack(pack, today=TODAY)

    # Assert
    assert chosen.chosen_by == CHOSEN_PACK
    assert chosen.rulebook is not None and chosen.rulebook.taxonomy == "4.2.0"


def test_a_pack_of_an_unshipped_release_has_no_rule_book(tmp_path: Path) -> None:
    chosen = release_for_pack(build_pack(tmp_path), today=TODAY)

    assert chosen.rulebook is None


def test_only_one_way_of_choosing_a_release_may_be_given(tmp_path: Path) -> None:
    pack = build_pack(tmp_path)

    with pytest.raises(ValueError, match="pack and taxonomy"):
        choose_release(SAMPLE_MODULE, pack=pack, taxonomy="4.1.1")


def test_a_rule_book_given_beside_a_release_replaces_the_releases(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))
    own = replace(book(), framework_version="mine")

    chosen = choose_release(SAMPLE_MODULE, taxonomy="4.1.1", rulebook=own, today=TODAY)

    assert chosen.rulebook is own and chosen.chosen_by == CHOSEN_VERSION


# ---------------------------------------------------------------------------
# Saying what was used
# ---------------------------------------------------------------------------


def test_the_output_names_the_release_why_and_the_others_shipped(releases: Releases) -> None:
    # Arrange
    releases.add("4.1.1", date(2027, 1, 1))
    releases.add("4.2.0", date(2028, 1, 1))
    releases.add("4.3.0", date(2028, 7, 1))

    # Act
    lines = release_lines(resolve_release(SAMPLE_MODULE, today=TODAY))

    # Assert
    assert lines == (
        "Taxonomy 4.1.1 (default) — TST001 live since 1 January 2027",
        "Also shipped for TST001: 4.3.0 future from 1 July 2028 (--taxonomy 4.3.0)",
        "                         4.2.0 future from 1 January 2028 (--taxonomy 4.2.0)",
    )


def test_a_default_that_is_not_live_says_no_live_release_is_shipped(releases: Releases) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    (line,) = release_lines(resolve_release(SAMPLE_MODULE, today=date(2026, 11, 15)))

    assert line == (
        "Taxonomy 4.1.1 (default) — TST001 future from 1 January 2027; no live release shipped"
    )


def test_the_record_carries_the_status_its_dates_and_why_it_was_chosen(
    releases: Releases,
) -> None:
    releases.add("4.1.1", date(2027, 1, 1))

    record = release_record(resolve_release(SAMPLE_MODULE, today=TODAY), date(2026, 12, 31))

    assert record == {
        "module": SAMPLE_MODULE,
        "version": "4.1.1",
        "entry_point": ENTRY_A,
        "status": STATUS_LIVE,
        "applies_from": "2027-01-01",
        "applies_to": None,
        "run_date": "2027-03-31",
        "chosen_by": CHOSEN_DEFAULT,
        "shipped": ["4.1.1"],
        "covers_reference_date": False,
    }


# ---------------------------------------------------------------------------
# The real packaged data
# ---------------------------------------------------------------------------


def test_pra001_defaults_to_4_1_1_as_future_before_1_january_2027_and_live_after() -> None:
    before = resolve_release("PRA001", today=date(2026, 11, 15))
    after = resolve_release("PRA001", today=date(2027, 1, 1))

    assert (before.version, before.status) == ("4.1.1", STATUS_FUTURE)
    assert (after.version, after.status) == ("4.1.1", STATUS_LIVE)
    assert before.rulebook is not None and before.rulebook.taxonomy == "4.1.1"


def test_a_module_of_the_same_release_can_be_live_while_pra001_is_future() -> None:
    """Status belongs to a module, not to a release."""
    day = date(2026, 11, 15)

    assert resolve_release("LVR001", today=day).status == STATUS_LIVE
    assert resolve_release("PRA001", today=day).status == STATUS_FUTURE


@pytest.mark.parametrize(
    "day",
    [date(2020, 1, 1), date(2026, 1, 15), date(2026, 11, 22), date(2027, 1, 1), date(2030, 6, 30)],
    ids=lambda day: day.isoformat(),
)
def test_every_shipped_modules_default_version_is_its_resolved_releases(day: date) -> None:
    """Past, present and future run dates, on every module the package ships."""
    # Arrange
    modules = sorted(
        {info.module for version in shipped_releases() for info in release_packs(version)}
    )
    assert len(modules) >= 14, f"only {modules} shipped: the packaged data is not what this reads"

    # Act
    shortcut = {module: default_release_version(module, today=day) for module in modules}

    # Assert
    assert shortcut == {module: resolve_release(module, today=day).version for module in modules}
