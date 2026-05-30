"""Contract tests for CCF regulatory scalars living in the data layer.

These tests close the convention gap that ``scripts/arch_check.py`` check 5
cannot see: the AST checker only flags module-level UPPER_SNAKE_CASE
assignments, but inline ``pl.lit(<float>)`` calls inside function bodies
are equally a violation of the "regulatory values live in
``src/rwa_calc/data/tables/``" rule documented in ``CLAUDE.md``.

Two layers of assertion:

1. The values in ``data/tables/ccf.py`` match the regulatory tables
   (CRR Art. 111, PRA PS1/26 Table A1, CRR Art. 166(8)/(10)). One
   assertion per row — documentation-as-test.
2. ``engine/ccf.py`` does not declare any new CCF percentages inline:
   every ``pl.lit(<float>)`` whose value appears in any CCF table must
   come via an import from ``data/tables/ccf.py``. The two A-IRB floor
   multipliers (CRE32.27 and Art. 166D(5)(b), both 0.5) are documented
   exceptions pending relocation to a future ``airb_floors.py``.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from rwa_calc.data.tables.ccf import (
    FIRB_CREDIT_LINE_CCF,
    FIRB_OBS_FALLBACK,
    FIRB_TRADE_LC_CCF,
    OC_SHORT_MATURITY_CCF,
    OC_SHORT_MATURITY_THRESHOLD_DAYS,
    SA_CCF_B31,
    SA_CCF_CRR,
    SA_CCF_DEFAULT,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_CCF = REPO_ROOT / "src" / "rwa_calc" / "engine" / "ccf.py"


# =============================================================================
# Layer 1 — table values match the regulatory schedules
# =============================================================================


def test_sa_ccf_crr_matches_art_111() -> None:
    """CRR Art. 111: FR/FRC=100%, MR=50%, OC=50% (>1yr default), MLR=20%, LR=0%."""
    assert {
        "FR": Decimal("1.00"),
        "FRC": Decimal("1.00"),
        "MR": Decimal("0.50"),
        "MR_ISSUED": Decimal(
            "0.50"
        ),  # P2.30: Annex I Row 3 issued-OBS, identical 50% CCF to MR (Row 4)
        "OC": Decimal("0.50"),
        "MLR": Decimal("0.20"),
        "LR": Decimal("0.00"),
    } == SA_CCF_CRR


def test_sa_ccf_b31_matches_pra_table_a1() -> None:
    """PRA PS1/26 Art. 111 Table A1: OC=40% (Row 5), LR/UCC=10% (Row 6)."""
    assert {
        "FR": Decimal("1.00"),
        "FRC": Decimal("1.00"),
        "MR": Decimal("0.50"),
        "MR_ISSUED": Decimal(
            "0.50"
        ),  # P2.30: Annex I Row 3 issued-OBS, identical 50% CCF to MR (Row 4)
        "OC": Decimal("0.40"),
        "MLR": Decimal("0.20"),
        "LR": Decimal("0.10"),
    } == SA_CCF_B31


def test_firb_obs_fallback_matches_art_166_10() -> None:
    """CRR Art. 166(10): FR=100%, MR/OC=50%, MLR=20%, LR=0%."""
    assert {
        "FR": Decimal("1.00"),
        "FRC": Decimal("1.00"),
        "MR": Decimal("0.50"),
        "MR_ISSUED": Decimal(
            "0.50"
        ),  # P2.30: Annex I Row 3 issued-OBS, identical 50% CCF to MR (Row 4)
        "OC": Decimal("0.50"),
        "MLR": Decimal("0.20"),
        "LR": Decimal("0.00"),
    } == FIRB_OBS_FALLBACK


def test_firb_bespoke_ccfs_match_art_166_8() -> None:
    """CRR Art. 166(8): trade LC=20% (8)(b), credit lines=75% (8)(d)."""
    assert Decimal("0.20") == FIRB_TRADE_LC_CCF
    assert Decimal("0.75") == FIRB_CREDIT_LINE_CCF


def test_sa_ccf_default_is_mr_equivalent() -> None:
    """Unrecognised risk_type falls back to MR-equivalent 50% (conservative)."""
    assert Decimal("0.50") == SA_CCF_DEFAULT


def test_oc_short_maturity_override_matches_art_111() -> None:
    """CRR Art. 111: OC mapped to MLR (20%) when remaining maturity <= 1yr."""
    assert Decimal("0.20") == OC_SHORT_MATURITY_CCF
    assert OC_SHORT_MATURITY_THRESHOLD_DAYS == 365


# =============================================================================
# Layer 2 — no inline pl.lit(<ccf>) literals in engine/ccf.py
# =============================================================================

# Values that show up as CCFs in the data layer but are also universally
# common as column defaults (``interest=0.0``, ``provision=0.0``),
# nominal-is-zero guards (``then(pl.lit(0.0))``), or A-IRB floor multipliers
# (``* 0.5`` for CRE32.27 / Art. 166D(5)(b), tracked by TODOs in
# ``engine/ccf.py`` pending relocation to ``data/tables/airb_floors.py``).
# Excluded from the inline-literal scan because a hit on these values is
# overwhelmingly likely to be structural, not a regulatory CCF. The
# distinctive CCF values (0.10, 0.20, 0.40, 0.75) have no such structural
# overlap and are checked strictly.
_STRUCTURAL_OR_DEFERRED_VALUES: set[float] = {0.0, 0.5, 1.0}


def _distinctive_ccf_values() -> set[float]:
    """CCF percentages with no plausible non-regulatory interpretation."""
    values: set[Decimal] = set()
    for table in (SA_CCF_CRR, SA_CCF_B31, FIRB_OBS_FALLBACK):
        values.update(table.values())
    values.update(
        {
            FIRB_TRADE_LC_CCF,
            FIRB_CREDIT_LINE_CCF,
            SA_CCF_DEFAULT,
            OC_SHORT_MATURITY_CCF,
        }
    )
    return {float(v) for v in values} - _STRUCTURAL_OR_DEFERRED_VALUES


def _iter_pl_lit_numeric_args(tree: ast.AST):
    """Yield (lineno, float_value) for every ``pl.lit(<numeric literal>)`` call.

    Excludes bool literals (``pl.lit(True)`` / ``pl.lit(False)``) because
    ``bool`` is a subclass of ``int`` in Python and would otherwise be
    coerced to 1.0 / 0.0 by ``float()``.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "lit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "pl"
        ):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, int | float)
            and not isinstance(arg.value, bool)
        ):
            yield node.lineno, float(arg.value)


def test_engine_ccf_module_has_no_inline_ccf_literals() -> None:
    """No ``pl.lit(<float>)`` in engine/ccf.py should match a distinctive CCF.

    Any new CCF percentage introduced into the engine must come via an
    import from ``data/tables/ccf.py`` (e.g.
    ``pl.lit(float(SA_CCF_DEFAULT))``). The scan is limited to values
    without a plausible structural alternative — 0.0, 0.5, and 1.0 are
    excluded because they routinely appear as column defaults, mathematical
    zero guards, and A-IRB floor multipliers (the latter tracked by
    ``TODO: move ... to data/tables/airb_floors.py`` comments in
    ``engine/ccf.py``).
    """
    tree = ast.parse(ENGINE_CCF.read_text(encoding="utf-8"))
    bad: set[float] = _distinctive_ccf_values()
    violations = [
        f"  engine/ccf.py:{lineno}: pl.lit({value!r}) matches a regulatory "
        f"CCF table value — import from data/tables/ccf.py instead"
        for lineno, value in _iter_pl_lit_numeric_args(tree)
        if value in bad
    ]
    assert not violations, (
        "Inline pl.lit(<ccf>) literal in engine/ccf.py — every regulatory "
        "CCF percentage must be sourced from data/tables/ccf.py:\n" + "\n".join(violations)
    )
