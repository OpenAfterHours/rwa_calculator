"""
The XBRL reader's parse: what one context, and one namespace scope, is read as.

Pipeline position:
    instance bytes  ->  reader._parse  ->  _Document(contexts, units, facts)  ->  read_instance

Why this exists: the parse reads each context in one walk of its children and
resolves prefixed names through one scope object per set of namespace
declarations. Both replaced something slower that was correct by construction —
three path searches per context, and a prefix table rebuilt per element. Every
context this package writes has one entity, one period, no segment and its
namespaces on the root, so a walk that took the LAST identifier, or a scope
that missed a declaration made lower down, would read every benchmark return
correctly. A file from another system need not look like that, and the header
of the whole return (who is reporting, as at when) is read from a context.

Each test below is a shape the benchmark returns do not have. The expected
values are what the path searches gave: the first identifier under any entity,
the first instant under any period, a segment directly under any entity, and
for a prefix the declaration read most recently — the reader's current
reading, which is not XML Namespaces scoping (plan item P6.66).
"""

from __future__ import annotations

import pytest

from rwa_filer.xbrl.reader import _Context, _parse

DIM_ONE = "http://example.test/dim/one"
DIM_TWO = "http://example.test/dim/two"
MEMBERS = "http://example.test/members"
TYPED = "http://example.test/typed"

ROOT = (
    '<xbrl xmlns="http://www.xbrl.org/2003/instance"'
    ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
    ' xmlns:iso4217="http://www.xbrl.org/2003/iso4217"'
    f' xmlns:d="{DIM_ONE}" xmlns:m="{MEMBERS}" xmlns:t="{TYPED}">'
)
ENTITY = '<entity><identifier scheme="lei">FIRM</identifier></entity>'
PERIOD = "<period><instant>2027-03-31</instant></period>"


def parse(body: str) -> dict[str, _Context]:
    return _parse(f"{ROOT}{body}</xbrl>".encode()).contexts


def context(body: str) -> _Context:
    return parse(f'<context id="c">{body}</context>')["c"]


# ---------------------------------------------------------------------------
# Who is reporting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entities", "identifier", "scheme"),
    [
        (
            '<entity><identifier scheme="one">FIRST</identifier></entity>'
            '<entity><identifier scheme="two">SECOND</identifier></entity>',
            "FIRST",
            "one",
        ),
        (
            '<entity/><entity><identifier scheme="two"> SECOND </identifier></entity>',
            "SECOND",
            "two",
        ),
        (
            '<entity><identifier scheme="one">FIRST</identifier>'
            '<identifier scheme="other">ALSO</identifier></entity>',
            "FIRST",
            "one",
        ),
        ("<entity/>", "", ""),
        ('<entity><identifier scheme="one"/></entity>', "", "one"),
    ],
    ids=["two-entities", "first-entity-empty", "two-identifiers", "none", "no-text"],
)
def test_the_identifier_is_the_first_one_under_any_entity(
    entities: str, identifier: str, scheme: str
) -> None:
    # Act
    read = context(f"{entities}{PERIOD}")

    # Assert
    assert (read.identifier, read.scheme) == (identifier, scheme)


def test_an_identifier_that_is_not_directly_under_an_entity_is_not_the_reporter() -> None:
    # Arrange — one inside a segment, one directly under the context.
    body = (
        '<identifier scheme="stray">STRAY</identifier>'
        '<entity><segment><identifier scheme="deep">DEEP</identifier></segment></entity>'
    )

    # Act
    read = context(f"{body}{PERIOD}")

    # Assert
    assert (read.identifier, read.scheme) == ("", "")


# ---------------------------------------------------------------------------
# As at when
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("periods", "instant"),
    [
        (
            "<period><instant>2027-03-31</instant></period>"
            "<period><instant>2026-12-31</instant></period>",
            "2027-03-31",
        ),
        (
            "<period><startDate>2026-01-01</startDate><endDate>2026-12-31</endDate></period>"
            "<period><instant> 2027-03-31 </instant></period>",
            "2027-03-31",
        ),
        (
            "<period><instant>2027-03-31</instant><instant>2026-12-31</instant></period>",
            "2027-03-31",
        ),
        ("<period><forever/></period>", None),
        ("<period><instant/></period>", None),
        (
            "<period><instant/></period><period><instant>2026-12-31</instant></period>",
            None,
        ),
        ("<instant>2027-03-31</instant>", None),
    ],
    ids=[
        "two-periods",
        "first-period-is-a-duration",
        "two-instants",
        "no-instant",
        "empty-instant",
        "empty-instant-then-a-dated-one",
        "instant-outside-a-period",
    ],
)
def test_the_instant_is_the_first_one_under_any_period(periods: str, instant: str | None) -> None:
    # Act
    read = context(f"{ENTITY}{periods}")

    # Assert
    assert read.instant == instant


# ---------------------------------------------------------------------------
# A segment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "has_segment"),
    [
        (f"{ENTITY}{PERIOD}", False),
        (
            '<entity><identifier scheme="lei">FIRM</identifier><segment/></entity>',
            True,
        ),
        (
            '<entity><segment/><identifier scheme="lei">FIRM</identifier></entity>',
            True,
        ),
        (f"{ENTITY}<entity><segment/></entity>{PERIOD}", True),
        (f"{ENTITY}{PERIOD}<segment/>", False),
        (f"{ENTITY}{PERIOD}<scenario><segment/></scenario>", False),
    ],
    ids=[
        "none",
        "first-entity",
        "before-the-identifier",
        "second-entity",
        "under-the-context",
        "under-the-scenario",
    ],
)
def test_a_segment_directly_under_any_entity_is_seen(body: str, has_segment: bool) -> None:
    # Act
    read = context(body)

    # Assert
    assert read.has_segment is has_segment


# ---------------------------------------------------------------------------
# Dimension members
# ---------------------------------------------------------------------------


def test_members_are_read_wherever_they_sit_explicit_ones_first() -> None:
    """A segment's, a scenario's, and one nested below a typed member's own value."""
    # Arrange
    body = (
        '<entity><identifier scheme="lei">FIRM</identifier><segment>'
        '<xbrldi:explicitMember dimension="d:SEG">m:s1</xbrldi:explicitMember>'
        "</segment></entity>"
        f"{PERIOD}<scenario>"
        '<xbrldi:typedMember dimension="d:TYP"><t:code> K1 '
        '<xbrldi:explicitMember dimension="d:NESTED"> m:n1 </xbrldi:explicitMember>'
        "</t:code><t:ignored>second child</t:ignored></xbrldi:typedMember>"
        '<xbrldi:explicitMember dimension="d:SCN">m:x1</xbrldi:explicitMember>'
        '<xbrldi:typedMember dimension="d:EMPTY"/>'
        "</scenario>"
    )

    # Act
    read = context(body)

    # Assert
    assert read == _Context(
        identifier="FIRM",
        scheme="lei",
        instant="2027-03-31",
        members=(
            (f"{{{DIM_ONE}}}SEG", (f"{{{MEMBERS}}}s1", None)),
            (f"{{{DIM_ONE}}}NESTED", (f"{{{MEMBERS}}}n1", None)),
            (f"{{{DIM_ONE}}}SCN", (f"{{{MEMBERS}}}x1", None)),
            (f"{{{DIM_ONE}}}TYP", ("K1", f"{{{TYPED}}}code")),
        ),
        has_segment=True,
    )


def test_an_undeclared_prefix_has_no_namespace_and_a_bare_name_takes_the_default_one() -> None:
    # Arrange
    body = (
        f"{ENTITY}{PERIOD}<scenario>"
        '<xbrldi:explicitMember dimension="zz:DIM">plain</xbrldi:explicitMember>'
        "</scenario>"
    )

    # Act
    read = context(body)

    # Assert
    assert read.members == (("{}DIM", ("{http://www.xbrl.org/2003/instance}plain", None)),)


# ---------------------------------------------------------------------------
# Namespace prefixes declared below the root — the reader's CURRENT reading
#
# The two tests below pin what the reader does today, which is NOT XML
# Namespaces scoping: a declaration made on an inner element stays in force for
# everything after it in the file, where XML Namespaces 1.0 confines it to that
# element and its descendants. The fix is plan item P6.66; it changes these
# readings, and these tests with them. Until then they keep a performance
# change from altering the reading by accident.
# ---------------------------------------------------------------------------

_MEMBER = '<xbrldi:explicitMember dimension="d:DIM">m:x1</xbrldi:explicitMember>'


def test_current_reading_a_prefix_redeclared_inside_a_context_stays_in_force_after_it() -> None:
    """The same text, ``d:DIM``, is three contexts' dimension — in two namespaces.

    Pins the reader's current reading, not XML Namespaces scoping: the
    redeclaration sits on ``within``'s scenario, yet ``after`` is read under it
    too. Scoped as XML Namespaces scopes it, ``after`` would read ``DIM_ONE``
    (plan item P6.66).
    """
    # Arrange
    body = (
        f'<context id="before">{ENTITY}{PERIOD}<scenario>{_MEMBER}</scenario></context>'
        f'<context id="within">{ENTITY}{PERIOD}'
        f'<scenario xmlns:d="{DIM_TWO}">{_MEMBER}</scenario></context>'
        f'<context id="after">{ENTITY}{PERIOD}<scenario>{_MEMBER}</scenario></context>'
    )

    # Act
    contexts = parse(body)

    # Assert
    member = (f"{{{MEMBERS}}}x1", None)
    assert contexts["before"].members == ((f"{{{DIM_ONE}}}DIM", member),)
    assert contexts["within"].members == ((f"{{{DIM_TWO}}}DIM", member),)
    assert contexts["after"].members == ((f"{{{DIM_TWO}}}DIM", member),)


def test_current_reading_a_prefix_redeclared_on_a_fact_stays_in_force_for_later_units() -> None:
    """Each fact and unit is read under every declaration made earlier in the file.

    Pins the reader's current reading, not XML Namespaces scoping: the
    redeclaration of ``iso4217`` sits on the fact ``second`` alone, yet the
    unit ``late`` after it is read under it. Scoped as XML Namespaces scopes
    it, ``late`` would read the root's ``iso4217`` (plan item P6.66).
    """
    # Arrange — the second unit and fact follow an element that redeclares ``iso4217``.
    body = (
        f'<context id="c">{ENTITY}{PERIOD}</context>'
        '<unit id="early"><measure>iso4217:GBP</measure></unit>'
        '<m:first contextRef="c">iso4217:GBP</m:first>'
        '<m:second contextRef="c" xmlns:iso4217="urn:other">iso4217:GBP</m:second>'
        '<unit id="late"><measure>iso4217:GBP</measure></unit>'
    )

    # Act
    document = _parse(f"{ROOT}{body}</xbrl>".encode())
    first, second = document.facts

    # Assert
    assert document.units == {
        "early": ("http://www.xbrl.org/2003/iso4217", "GBP"),
        "late": ("urn:other", "GBP"),
    }
    assert dict(first.prefixes)["iso4217"] == "http://www.xbrl.org/2003/iso4217"
    assert dict(second.prefixes)["iso4217"] == "urn:other"
    assert second.prefixes[: len(first.prefixes)] == first.prefixes
    assert second.prefixes[-1] == ("iso4217", "urn:other")
    assert document.uris["iso4217"] == "urn:other"
