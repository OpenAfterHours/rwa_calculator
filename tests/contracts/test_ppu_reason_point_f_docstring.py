"""Contract tests for the regime status recorded on ``PpuReason.ART_150_1_F`` (P5.58).

Point (f) of Art. 150(1) lets an IRB firm keep "exposures between institutions
which meet the requirements set out in Article 113(7)" on the Standardised
Approach. Its status differs by regime, and the attribute docstring used to
state neither:

- UK CRR (to 31 Dec 2026): point (f) is unamended and still cross-refers to
  Art. 113(7), but S.I. 2018/1401 reg. 111(3) omitted that paragraph (the
  institutional protection scheme provision) on 31.12.2020. The limb is a
  dangling cross-reference no UK exposure can meet.
- Basel 3.1 (PS1/26, from 1 Jan 2027): point (f) is "[Note: Provision left
  blank]", i.e. deleted. PS1/26 also reuses the number 113(7) for an unrelated
  rule (the conditions attached to the paragraph 6 intragroup permission).

The stale "(IPS)" gloss, read as a live UK rule, seeded P1.268's wrong framing.
These tests pin the corrected text. The value is provenance only (C 07.00 row
0050 routes every ``art_150_1_*`` code by prefix), so nothing here moves RWA.

An attribute docstring is not reachable at runtime (``PpuReason.ART_150_1_F.__doc__``
returns the class docstring), so the module is read with ``ast``. The file is
located through the imported ``rwa_calc`` package, so the tests measure whichever
src tree is on ``sys.path``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import rwa_calc

# Resolve to .../src/rwa_calc regardless of which worktree is active.
_ENUMS_PATH = Path(rwa_calc.__file__).resolve().parent / "domain" / "enums.py"

# The phrase each regime's status must be stated with, taken from the instrument
# that sets it: "omitted" is legislation.gov.uk's wording for the UK CRR removal
# of the cross-referenced paragraph, "left blank" is PS1/26's deletion note.
_REGIME_STATUS: list[tuple[str, tuple[str, ...]]] = [
    ("crr", ("omitted", "S.I. 2018/1401")),
    ("basel_3_1", ("left blank",)),
]


def _ppu_reason_class() -> ast.ClassDef:
    tree = ast.parse(_ENUMS_PATH.read_text(encoding="utf-8"))
    classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PpuReason"
    ]
    assert len(classes) == 1, f"expected one PpuReason class in {_ENUMS_PATH}"
    return classes[0]


def _collapse(text: str) -> str:
    """Collapse runs of whitespace, so a phrase wrapped across docstring lines still matches."""
    return " ".join(text.split())


def _member_docstring(member: str) -> str:
    """Return the attribute docstring of ``PpuReason.<member>``, whitespace-collapsed."""
    return _collapse(_raw_member_docstring(member))


def _raw_member_docstring(member: str) -> str:
    """Return the string literal that immediately follows ``member = ...`` in PpuReason."""
    body = _ppu_reason_class().body
    for index, stmt in enumerate(body):
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == member for t in stmt.targets):
            continue
        following = body[index + 1] if index + 1 < len(body) else None
        assert (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ), f"PpuReason.{member} has no attribute docstring in {_ENUMS_PATH}"
        return following.value.value
    raise AssertionError(f"PpuReason.{member} not found in {_ENUMS_PATH}")


def test_point_f_docstring_is_the_art_150_1_f_member() -> None:
    """The AST lookup lands on the art_150_1_f member, so the tests below read the right text.

    Arrange: locate the ART_150_1_F assignment in PpuReason.
    Act:     read its assigned value and its docstring.
    Assert:  the value is the input code and the docstring opens on point (f).
    """
    # Arrange
    body = _ppu_reason_class().body
    assigns = [
        stmt
        for stmt in body
        if isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ART_150_1_F" for t in stmt.targets)
    ]

    # Act
    docstring = _member_docstring("ART_150_1_F")

    # Assert
    assert len(assigns) == 1
    assert isinstance(assigns[0].value, ast.Constant)
    assert assigns[0].value.value == "art_150_1_f"
    assert docstring.startswith("Art. 150(1)(f)")


def test_point_f_docstring_drops_the_ips_gloss() -> None:
    """The "(IPS)" gloss, which reads as a live UK institutional protection scheme rule, is gone.

    Arrange: read the ART_150_1_F attribute docstring.
    Act:     search it for the parenthetical gloss.
    Assert:  the gloss is absent.
    """
    # Arrange
    docstring = _member_docstring("ART_150_1_F")

    # Act / Assert
    assert "(IPS)" not in docstring, (
        "PpuReason.ART_150_1_F still glosses point (f) as '(IPS)': the paragraph it "
        "cross-refers to was omitted from the UK CRR on 31.12.2020"
    )


@pytest.mark.parametrize(
    ("regime", "phrases"), _REGIME_STATUS, ids=[regime for regime, _ in _REGIME_STATUS]
)
def test_point_f_docstring_states_regime_status(regime: str, phrases: tuple[str, ...]) -> None:
    """The docstring states point (f)'s status under each regime, independently.

    Arrange: read the ART_150_1_F attribute docstring.
    Act:     search it for the regime's status phrase(s).
    Assert:  every phrase is present — CRR: the cross-referenced paragraph was
             omitted by S.I. 2018/1401; Basel 3.1: the point is left blank.
    """
    # Arrange
    docstring = _member_docstring("ART_150_1_F")

    # Act
    missing = [phrase for phrase in phrases if phrase not in docstring]

    # Assert
    assert not missing, (
        f"PpuReason.ART_150_1_F does not state its {regime} status: missing {missing}"
    )


def test_point_f_summary_keeps_the_statutory_cross_reference() -> None:
    """Point (f)'s summary line names the paragraph the statute names, and only that one.

    Arrange: read the first line of the ART_150_1_F attribute docstring.
    Act:     search it for the cross-referenced paragraph numbers.
    Assert:  "113(7)" is present — the UK text of point (f) names it verbatim — and
             "113(6)" is absent: the paragraph 6 intragroup permission belongs to
             point (e)'s territory, and folding it into (f) is P1.268's misreading.
    """
    # Arrange
    summary = _raw_member_docstring("ART_150_1_F").splitlines()[0]

    # Act
    names_7 = "113(7)" in summary
    names_6 = "113(6)" in summary

    # Assert
    assert names_7 and not names_6, (
        f"PpuReason.ART_150_1_F summary must cross-refer to 113(7) alone: {summary!r}"
    )


def test_ppu_reason_class_docstring_states_the_basel_3_1_limbs() -> None:
    """The class docstring says which Art. 150(1) points Basel 3.1 leaves blank.

    Arrange: read the PpuReason class docstring.
    Act:     search it for PS1/26's deletion note.
    Assert:  "left blank" is present, so no limb reads as live under Basel 3.1.
    """
    # Arrange
    docstring = _collapse(ast.get_docstring(_ppu_reason_class()) or "")

    # Act / Assert
    assert "left blank" in docstring, (
        "PpuReason's class docstring lists the Art. 150(1)(a)-(j) points as the live "
        "set with no note that Basel 3.1 leaves all but point (e) blank"
    )
