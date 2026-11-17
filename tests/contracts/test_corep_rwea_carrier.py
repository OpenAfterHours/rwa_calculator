"""No COREP template may bind the post-floor RWEA carrier ``rwa_final`` directly.

Under Basel 3.1 the engine spreads a binding output floor's shortfall pro rata
over ``rwa_final`` on every floor-eligible leg and keeps the un-floored figure on
``rwa_pre_floor`` (``engine/aggregator/_floor.py``). PS1/26 Art. 92(2A) makes
the floor an entity-level maximum and Art. 92(3)(a) makes every template's RWEA
the amount the exposure's own approach produces; Annex II reports the floor in
one place only, OF 02.00 row 0010 column 0030. So a COREP RWEA figure is the
own-approach carrier, resolved through ``reporting.kernel.own_rwea`` — which
reads ``rwa_pre_floor`` where the floor ran and falls back to the ladder it is
given (``rwa_final``, ...) where it did not, because then no floor was applied.

This is the graduated gate for the 2026-11-16 escape (O-12, plan P1.369): the
OF 08 / OF 09.02 / C 08.04 / OF 08.07 / C 34 templates each summed ``rwa_final``
and reported the add-on inside per-class RWEA, which the Bank's rules
(``boe_b0621``, ``boe_b0751``, ``boe_b0763``) and the filing structure check
(STR007) rejected on every binding-floor return.

The scan is an AST walk of ``src/rwa_calc/reporting/corep/*.py``: the literal
``"rwa_final"`` may not be an argument of any call except ``own_rwea`` /
``with_own_rwea_as`` (where it is a fallback the helper reaches only when the
frame seals no ``rwa_pre_floor``, i.e. the floor never ran). That covers
``pick(cols, "rwa_final", ...)``, ``Sum("rwa_final")``, ``pl.col("rwa_final")``
and every other verb. It does NOT see a name bound to the literal and passed
on (``col = "rwa_final"; Sum(col)``) — keep carrier names literal at the call.

``ALLOWED_SITES`` is a strict list: an entry that no longer matches a call is
itself a failure, so the list can only shrink. Each entry names the reason.

References:
- PRA PS1/26 Appendix 1, Art. 92(2A) and 92(3) (pp.13-14)
- PRA PS1/26 Annex II, OF 08.01 col 0260 (p.112), OF 02.00 row 0010 (p.29)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

COREP_DIR = Path(__file__).resolve().parents[2] / "src" / "rwa_calc" / "reporting" / "corep"

#: The post-floor carrier no template may bind.
POST_FLOOR_CARRIER = "rwa_final"

#: The kernel helper whose fallback ladder may name it.
OWN_APPROACH_HELPER = "own_rwea"

#: Calls that resolve the own-approach carrier first, so may name the fallback.
OWN_APPROACH_RESOLVERS = frozenset({OWN_APPROACH_HELPER, "with_own_rwea_as"})


class Site(NamedTuple):
    """One call passing the post-floor carrier: module file, enclosing function."""

    module: str
    function: str


#: Sites that may still name ``rwa_final`` outside the helper, each with its reason.
ALLOWED_SITES: dict[Site, str] = {
    Site("c02.py", "generate_c02_00"): (
        "final_col feeds the engine-total log line only (the banked P1.367 caveat); "
        "column 0010 reads own_rwea"
    ),
}


def test_no_corep_template_binds_the_post_floor_carrier() -> None:
    """Every call naming ``rwa_final`` outside ``own_rwea`` is an allowed site."""
    # Arrange
    sites = _carrier_sites()
    # Act
    unexpected = sorted(
        f"{site.module}:{line} in {site.function}()"
        for site, lines in sites.items()
        if site not in ALLOWED_SITES
        for line in lines
    )
    # Assert
    assert unexpected == [], (
        "a COREP template binds the post-floor carrier rwa_final, which carries the output "
        "floor's add-on on a binding-floor return; resolve it through "
        f"reporting.kernel.own_rwea instead: {unexpected}"
    )


def test_every_allowed_site_still_exists() -> None:
    """The allowlist can only shrink: a fixed site must leave the list."""
    # Act
    stale = sorted(f"{s.module}:{s.function}" for s in ALLOWED_SITES if s not in _carrier_sites())
    # Assert
    assert stale == [], f"remove these fixed sites from ALLOWED_SITES: {stale}"


def test_the_scan_sees_every_kind_of_binding() -> None:
    """Adequacy: the scanner reports each shape it claims to (pick, a cellspec
    verb, ``pl.col``) and ignores the helper's own fallback and a presence test."""
    # Arrange
    source = (
        "def f(cols):\n"
        "    a = pick(cols, 'rwa_final', 'rwa')\n"
        "    b = Sum('rwa_final')\n"
        "    c = pl.col('rwa_final').sum()\n"
        "    d = own_rwea(cols, 'rwa_final', 'rwa')\n"
        "    e = 'rwa_final' in cols\n"
        "    g = with_own_rwea_as(frame, cols, 'rwa_final', 'rwa_final')\n"
    )
    # Act
    found = _scan(ast.parse(source), "probe.py")
    # Assert
    assert found == {Site("probe.py", "f"): [2, 3, 4]}


@pytest.mark.parametrize("module", ["c08.py", "c08_07.py", "c09.py", "c34.py", "c02.py"])
def test_the_rwea_templates_resolve_the_own_approach_carrier(module: str) -> None:
    """Adequacy: each module this gate was built for does call the helper, so a
    green scan is not explained by the module having stopped reading RWEA."""
    # Act
    tree = ast.parse((COREP_DIR / module).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if _call_name(node) == OWN_APPROACH_HELPER]
    # Assert
    assert calls, f"{module} no longer resolves RWEA through {OWN_APPROACH_HELPER}"


def _carrier_sites() -> dict[Site, list[int]]:
    """Every call in the COREP package naming the post-floor carrier, by site."""
    sites: dict[Site, list[int]] = {}
    for path in sorted(COREP_DIR.glob("*.py")):
        for site, lines in _scan(ast.parse(path.read_text(encoding="utf-8")), path.name).items():
            sites.setdefault(site, []).extend(lines)
    return sites


def _scan(tree: ast.Module, module: str) -> dict[Site, list[int]]:
    """Calls passing the literal carrier as an argument, keyed by the innermost
    enclosing function (``<module>`` at top level)."""
    lines = sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _call_name(node) not in OWN_APPROACH_RESOLVERS
        and any(_is_carrier(arg) for arg in [*node.args, *(k.value for k in node.keywords)])
    )
    # Narrowest span first, so the first span containing a line is its innermost function.
    spans = sorted(
        (
            (node.lineno, node.end_lineno or node.lineno, node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ),
        key=lambda span: span[1] - span[0],
    )
    found: dict[Site, list[int]] = {}
    for line in lines:
        name = next((name for start, end, name in spans if start <= line <= end), "<module>")
        found.setdefault(Site(module, name), []).append(line)
    return found


def _call_name(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _is_carrier(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == POST_FLOOR_CARRIER
