"""
The Bank's validations deny list, as packaged: what it says, and when each entry applies.

Pipeline position:
    boe/data/deny/<release>.json  ->  boe.deny.load_deny_list  ->  DenyList

What is pinned here is the DATA MODEL — which entries are in force on a day, how
an entry reads in words, and that a list is keyed by module AND code — plus what
the packaged 4.1.1 list holds of the Bank's November 2026 workbook. How a list
changes a verdict is pinned in ``tests/validate/test_deny_application.py``.

References:
- Bank of England, "Banking validations deny list" (November 2026), sheet "Note"
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_filer.boe.catalogue import available_rulebooks
from rwa_filer.boe.deny import (
    DENY_DEACTIVATED,
    DENY_DOWNGRADED,
    DenyEntry,
    DenyList,
    DenyListNotFoundError,
    available_deny_lists,
    deny_list_from,
    deny_summary,
    load_deny_list,
)

APPLIED = date(2026, 10, 19)
B0710 = DenyEntry("boe_b0710", "PRA001", DENY_DEACTIVATED, APPLIED, known_issue=22)
B4008 = DenyEntry("boe_b4008_1", "MRL001", DENY_DOWNGRADED, APPLIED, known_issue=24)
PENDING = DenyEntry("boe_b0999", "PRA001", DENY_DEACTIVATED, None)
LATER = DenyEntry("boe_b0272", "PRA001", DENY_DEACTIVATED, date(2026, 11, 16), known_issue=29)


def _list(*entries: DenyEntry) -> DenyList:
    return DenyList(release="9.9.9", entries=entries)


# ---------------------------------------------------------------------------
# When an entry applies
# ---------------------------------------------------------------------------


def test_an_entry_is_in_force_from_the_day_it_was_applied_at_the_gateway() -> None:
    assert not B0710.in_force_on(date(2026, 10, 18))
    assert B0710.in_force_on(APPLIED)
    assert B0710.in_force_on(date(2027, 3, 31))


def test_an_entry_with_no_date_applied_is_pending_and_never_in_force() -> None:
    """The Note sheet: a blank Date Applied is identified, "not implemented yet"."""
    assert PENDING.is_pending
    assert not PENDING.in_force_on(date(2099, 1, 1))


def test_the_list_in_force_on_a_day_leaves_pending_and_later_entries_out() -> None:
    deny_list = _list(B0710, PENDING, LATER)

    in_force = deny_list.in_force("PRA001", date(2026, 11, 1))
    not_in_force = deny_list.not_in_force("PRA001", date(2026, 11, 1))

    assert set(in_force) == {"boe_b0710"}
    assert {item.rule_id for item in not_in_force} == {"boe_b0999", "boe_b0272"}


def test_an_entry_belongs_to_its_module_only() -> None:
    """The same code names different rules in different rule books (boe_b1022)."""
    deny_list = _list(DenyEntry("boe_b1022", "PRA115", DENY_DEACTIVATED, APPLIED))

    assert deny_list.entry("PRA115", "boe_b1022") is not None
    assert deny_list.entry("PRA001", "boe_b1022") is None
    assert deny_list.in_force("PRA001", APPLIED) == {}


# ---------------------------------------------------------------------------
# How an entry reads
# ---------------------------------------------------------------------------


def test_a_deactivation_names_the_bank_the_date_and_the_known_issue() -> None:
    assert B0710.describe() == (
        "deactivated by the Bank of England on 19 October 2026 "
        "(validations deny list; known issues log #22)"
    )


def test_a_downgrade_says_from_error_to_warning() -> None:
    assert B4008.describe().startswith(
        "downgraded from Error to Warning by the Bank of England on 19 October 2026"
    )


def test_a_resolved_typo_names_the_code_as_the_bank_wrote_it() -> None:
    entry = DenyEntry(
        "boe_b4006_1", "MRL001", DENY_DOWNGRADED, APPLIED, 23, published_code="boe_b04006_1"
    )

    assert "listed as boe_b04006_1" in entry.describe()


def test_the_summary_lists_what_was_applied_and_what_was_not() -> None:
    summary = deny_summary(_list(B0710, PENDING, LATER), "PRA001", date(2026, 11, 1))

    assert summary["applied_on"] == "2026-11-01"
    assert summary["deactivated"] == ["boe_b0710"]
    assert summary["downgraded"] == []
    assert [item["rule_id"] for item in summary["not_applied"]] == ["boe_b0999", "boe_b0272"]


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_a_list_round_trips_through_its_file_content() -> None:
    deny_list = _list(B0710, PENDING)

    again = deny_list_from(deny_list.to_payload())

    assert again.entries == deny_list.entries
    assert again.content_sha256


def test_a_file_in_another_format_is_refused() -> None:
    with pytest.raises(ValueError, match="format"):
        deny_list_from({"format": 99, "release": "1.0.0"})


def test_a_deny_type_the_package_does_not_know_is_refused() -> None:
    payload = _list(B0710).to_payload()
    payload["entries"][0]["deny_type"] = "suspended"

    with pytest.raises(ValueError, match="deny type"):
        deny_list_from(payload)


def test_a_release_with_no_packaged_list_is_a_lookup_error() -> None:
    with pytest.raises(DenyListNotFoundError):
        load_deny_list("0.0.0")


# ---------------------------------------------------------------------------
# What the packaged 4.1.1 list holds (the Bank's November 2026 workbook)
# ---------------------------------------------------------------------------


def test_the_packaged_list_is_not_read_as_a_rule_book() -> None:
    """It sits in a subdirectory, which the rule-book listing does not enter."""
    assert "4.1.1" in available_deny_lists()
    assert all(not name.startswith("4.1.1.") for name in available_rulebooks())


def test_the_packaged_4_1_1_list_deactivates_the_b0710_family_for_pra001() -> None:
    deny_list = load_deny_list("4.1.1")

    in_force = deny_list.in_force("PRA001", date(2026, 11, 16))

    assert {
        rule_id
        for rule_id in ("boe_b0710", "boe_b0710_1", "boe_b0710_2", "boe_b0710_3", "boe_b0746")
        if in_force[rule_id].is_deactivation and in_force[rule_id].date_applied == APPLIED
    } == {"boe_b0710", "boe_b0710_1", "boe_b0710_2", "boe_b0710_3", "boe_b0746"}
    assert in_force["boe_b0710"].known_issue == 22


def test_the_packaged_4_1_1_list_applies_b0272_and_b0274_from_16_november_2026() -> None:
    deny_list = load_deny_list("4.1.1")

    assert "boe_b0272" not in deny_list.in_force("PRA001", date(2026, 11, 15))
    assert {"boe_b0272", "boe_b0274"} <= set(deny_list.in_force("PRA001", date(2026, 11, 16)))


def test_the_packaged_4_1_1_list_downgrades_mrl001_and_keeps_the_banks_spelling() -> None:
    """The workbook writes boe_b04006_1; the rule book's rule is boe_b4006_1 (known issue #23)."""
    deny_list = load_deny_list("4.1.1")

    entry = deny_list.entry("MRL001", "boe_b4006_1")

    assert entry is not None
    assert (entry.deny_type, entry.published_code, entry.known_issue) == (
        DENY_DOWNGRADED,
        "boe_b04006_1",
        23,
    )
    assert deny_list.unmatched == ()
