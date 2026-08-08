"""
Oracle test suite -- the shadow calculator.

Validates engine outputs against independent hand-calculations whose arithmetic
is documented in ORACLE_DERIVATIONS.md and reproduced programmatically by
derive.py + derivations/ (stdlib-only). The point of this suite is to break the
self-referential loop in tests/expected_outputs/{crr,basel31}/, where expected
values are recorded engine outputs and therefore cannot detect a wrong
implementation -- only a *regression* relative to current behaviour.

It is also the only layer that can see a **wrong constant**. If a risk weight
is 45% where the regulation says 50%, conservation still holds, monotonicity
still holds, bounds still hold, and every property in tests/properties/ passes.
Only an independent re-derivation catches that.

Lock mechanism: expected_values.json embeds a SHA-256 hash of
ORACLE_DERIVATIONS.md (with line endings normalised to LF). The first test
below asserts that hash is current. If the doc changes without a corresponding
re-derivation, that test fails loudly with instructions on how to recover -- so
it is impossible to silently re-pin oracle values to engine output.

Independence: test_derivations_never_import_rwa_calc parses every derivation
module and fails on any rwa_calc import. Only drivers.py -- which supplies
*inputs* and collects outputs, never expected values -- is allowed to.

Tolerance: relative error <= 1e-6 against the hand-derived value. This is far
tighter than the 1% used by the regression-style acceptance tests, because the
oracle is testing analytical correctness, not data-quality robustness.

Pipeline position tested: each oracle calls the relevant calculator's
`calculate_branch` directly via tests/oracle/drivers.py. This deliberately
bypasses hierarchy / classifier / CRM so the oracle exercises only the
regulatory math. Pipeline-integration concerns are tested elsewhere.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.oracle import drivers

HERE = Path(__file__).parent
DOC_PATH = HERE / "ORACLE_DERIVATIONS.md"
JSON_PATH = HERE / "expected_values.json"
DERIVATIONS_DIR = HERE / "derivations"

PAYLOAD: dict[str, Any] = json.loads(JSON_PATH.read_text())
ORACLES: list[dict[str, Any]] = PAYLOAD["oracles"]
TOLERANCE = PAYLOAD["tolerance_relative"]


# =============================================================================
# Known disagreements between the oracle and the engine
# =============================================================================
#
# An entry here is a *finding*, not a fix. Adjusting a derivation so it agrees
# with the engine would destroy the only independent evidence this suite
# produces. Each entry records the article, both figures, and which
# intermediate diverges, so it is triageable rather than merely red.
#
# Remove an entry only when the engine changes, never when the oracle does.
_ART_121_TABLE_5 = (
    "CRR Art. 121(1) Table 5 is not applied to the institution exposure class. "
    "An unrated institution incorporated in a jurisdiction whose central "
    "government carries a CQS should be weighted off that CQS "
    "(1 -> 20%, 2 -> 50%, 3/4/5 -> 100%, 6 -> 150%); the engine returns a flat "
    "100% for every sovereign CQS. Differing intermediate: risk_weight. The "
    "sovereign-derived ladder itself is correct and is used for the RGLA and "
    "PSE classes (and, via the MDB branch, from the very table named "
    "INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED) -- it is only the INSTITUTION "
    "branch that never reads cp_sovereign_cqs. "
    "DIRECTION IS NOT UNIFORM across the ladder: CQS 1 and 2 are OVERSTATED "
    "(conservative), CQS 3/4/5 agree only because the flat fallback coincides "
    "with Table 5 there, and CQS 6 is UNDERSTATED at 100% against a required "
    "150% -- an anti-conservative limb and a capital shortfall. Art. 121(2) "
    "(null sovereign CQS -> 100%) is correct."
)

_ART_154_4A_B_SCOPE = (
    "PS1/26 Art. 154(4A)(b) confines the 10% RWEA floor to (i) NON-DEFAULTED, "
    "(ii) RETAIL exposures secured by RESIDENTIAL immovable property, (iii) in "
    "the UK. Since P1.319, engine/irb/adjustments.py gates on the first two and "
    "not the third. Limb (i) is exact, off is_defaulted. Limb (ii) is the "
    "engine's closest available proxy -- exposure_class == retail_mortgage -- "
    "which is OVER-INCLUSIVE: hierarchy/enrich.py computes "
    "property_collateral_value over both residential AND commercial property by "
    "design, so classify/attributes.py sets is_mortgage for either, and a retail "
    "exposure secured only on commercial property still carries the class and "
    "still takes the floor. Limb (iii) is UNREPRESENTABLE (see ORC-142). "
    "Differing intermediate: mortgage_rwea_floor_adjustment. Direction: the "
    "floor can only raise RWEA, so every limb of the residual over-reach is "
    "conservative -- unlike the Art. 121 finding, that holds for the whole "
    "domain and does not depend on which cases were sampled."
)

KNOWN_DISAGREEMENTS: dict[str, str] = {
    "ORC-105": f"{_ART_121_TABLE_5} Here: CQS 1, oracle 20%, engine 100% (overstated).",
    "ORC-020": f"{_ART_121_TABLE_5} Here: CQS 2, oracle 50%, engine 100% (overstated).",
    "ORC-109": (
        f"{_ART_121_TABLE_5} Here: CQS 6, oracle 150%, engine 100% -- "
        "UNDERSTATED by a third. This is the capital-shortfall limb and the "
        "reason the family is pinned across its whole domain rather than at "
        "the two steps that were looked at first."
    ),
    # ORC-140 (limb (i), defaulted) and ORC-141 (limb (ii), commercial real
    # estate) were entries here until P1.319 narrowed the gate. They now AGREE
    # with the oracle and must run as ordinary passing cases -- these marks are
    # xfail(strict=True), so leaving them would turn the fix into an XPASS, i.e.
    # a hard failure. Do not re-add them without an engine change that re-breaks
    # them.
    "ORC-142": (
        f"{_ART_154_4A_B_SCOPE} Here: limb (iii). The floor is applied to "
        "residential property outside the UK. Note this limb is not merely "
        "mis-gated but UNREPRESENTABLE: no module under engine/irb/ reads any "
        "obligor or property country column at all (the only country carrier "
        "there is guarantor_country_code, for the guarantee substitution path), "
        "so no input could switch it off. Oracle floor adjustment 0.00, engine "
        "373,345.27."
    ),
}


# =============================================================================
# Locks -- doc hash and derivation independence
# =============================================================================


def _normalised_doc_hash() -> str:
    raw = DOC_PATH.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def test_derivations_doc_hash_matches_lock() -> None:
    """ORACLE_DERIVATIONS.md and expected_values.json may not drift apart.

    If this fails, ORACLE_DERIVATIONS.md has been edited since
    expected_values.json was last regenerated. To recover:

      1. Confirm the new derivations are correct.
      2. Update tests/oracle/derivations/ to match (constants, formulas).
      3. Run: uv run python tests/oracle/derive.py
      4. Re-run this test suite.

    Do NOT hand-edit expected_values.json to silence this failure -- that
    defeats the purpose of the oracle.
    """
    actual = _normalised_doc_hash()
    expected = PAYLOAD["derivations_doc_hash"]
    assert actual == expected, (
        f"\nORACLE_DERIVATIONS.md hash drift detected.\n"
        f"  doc (actual):  {actual}\n"
        f"  json (locked): {expected}\n"
        f"Re-run: uv run python tests/oracle/derive.py"
    )


def test_derivations_never_import_rwa_calc() -> None:
    """The derivation chain must stay causally independent of the engine.

    An expected value that came from ``rwa_calc`` -- however indirectly -- is
    worthless as evidence about ``rwa_calc``. This walks the AST of every
    derivation module plus ``derive.py`` and fails on any import of the
    package under test.
    """
    sources = [HERE / "derive.py", *sorted(DERIVATIONS_DIR.glob("*.py"))]
    offenders: list[str] = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "rwa_calc" or name.startswith("rwa_calc."):
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert not offenders, (
        "\nThe oracle derivations imported the engine they are meant to check:\n  "
        + "\n  ".join(offenders)
        + "\nDerive every expected value from the regulation instead."
    )


def test_every_oracle_has_a_derivation_section() -> None:
    """Each ORC-nnn in the JSON has a matching section in the derivations doc."""
    doc = DOC_PATH.read_text(encoding="utf-8")
    missing = [o["exposure_id"] for o in ORACLES if f"## {o['exposure_id']}" not in doc]
    assert not missing, (
        f"\n{len(missing)} oracle(s) have no section in ORACLE_DERIVATIONS.md: "
        f"{missing}\nEvery oracle must carry a worked derivation and a citation."
    )


def test_every_oracle_carries_a_citation() -> None:
    """No oracle may exist without naming the article it came from."""
    uncited = [
        o["exposure_id"]
        for o in ORACLES
        if not any(token in o["regulation"] for token in ("Art.", "Article"))
    ]
    assert not uncited, f"oracles with no article citation: {uncited}"


# =============================================================================
# Engine comparison
# =============================================================================

#: Oracle key -> engine column candidates, in the order the calculation
#: performs them. The FIRST entry that disagrees is the one reported as the
#: driver of the difference, so a mismatch says "the correlation is wrong"
#: rather than only "the RWA is wrong".
_COMPARISONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ead", ("ead_final",)),
    ("pd_applied", ("pd_floored",)),
    ("firb_supervisory_lgd", ("lgd",)),
    ("lgd_applied", ("lgd_floored",)),
    ("maturity_applied", ("irb_maturity_m",)),
    ("correlation_R", ("correlation",)),
    ("maturity_adj_MA", ("maturity_adjustment",)),
    ("scaling_factor", ("scaling_factor",)),
    ("risk_weight", ("risk_weight",)),
    ("mortgage_rwea_floor_adjustment", ("mortgage_rw_floor_adjustment",)),
    ("supporting_factor", ("supporting_factor",)),
    ("rwa", ("rwa_final", "rwa_post_factor", "rwa")),
)


def _params() -> list[Any]:
    out = []
    for record in ORACLES:
        oid = record["exposure_id"]
        marks = []
        if oid in KNOWN_DISAGREEMENTS:
            marks.append(pytest.mark.xfail(strict=True, reason=KNOWN_DISAGREEMENTS[oid]))
        out.append(pytest.param(record, id=oid, marks=marks))
    return out


@pytest.mark.parametrize("record", _params())
def test_engine_matches_oracle(record: dict[str, Any]) -> None:
    """The engine reproduces the independently-derived figure for one exposure."""
    actual = _run(record)
    expected = _expected_values(record)

    unasserted = set(record.get("unasserted", ()))

    diffs: list[tuple[str, float, float, float]] = []
    for key, candidates in _COMPARISONS:
        if key not in expected or key in unasserted:
            continue
        engine_value = _pick(actual, candidates)
        if engine_value is None:
            continue
        want = float(expected[key])
        got = float(engine_value)
        error = _relative_error(want, got)
        if error > TOLERANCE:
            diffs.append((key, want, got, error))

    assert not diffs, _report(record, diffs, actual)


# =============================================================================
# Private helpers
# =============================================================================

_IRB_APPROACH_COLUMN = {"FIRB": "foundation_irb", "AIRB": "advanced_irb"}


def _run(record: dict[str, Any]) -> dict[str, Any]:
    """Drive the engine with the oracle's inputs."""
    inputs = dict(record["inputs"])
    ead = inputs.pop("ead")
    framework = record["framework"]
    approach = record["approach"]

    if approach == "SA":
        return drivers.run_sa(framework=framework, ead=ead, **inputs)
    if approach in _IRB_APPROACH_COLUMN:
        return drivers.run_irb(
            framework=framework,
            ead=ead,
            pd_value=inputs.pop("pd_value"),
            lgd=inputs.pop("lgd"),
            approach=_IRB_APPROACH_COLUMN[approach],
            **inputs,
        )
    if approach == "SLOTTING":
        return drivers.run_slotting(framework=framework, ead=ead, **inputs)
    if approach == "EQUITY":
        permission = drivers.PermissionMode.STANDARDISED
        if inputs.pop("permission", None) == "IRB":
            permission = drivers.PermissionMode.IRB
        return drivers.run_equity(framework=framework, ead=ead, permission=permission, **inputs)
    raise ValueError(f"{record['exposure_id']}: unknown approach {approach!r}")


def _expected_values(record: dict[str, Any]) -> dict[str, Any]:
    """Everything the oracle claims, keyed the way _COMPARISONS expects."""
    return {
        "ead": record["inputs"]["ead"],
        **record.get("intermediate", {}),
        **record["expected"],
    }


def _pick(row: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    for name in candidates:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _relative_error(want: float, got: float) -> float:
    if want == 0.0:
        return 0.0 if got == 0.0 else float("inf")
    return abs(got - want) / abs(want)


def _report(
    record: dict[str, Any],
    diffs: list[tuple[str, float, float, float]],
    actual: dict[str, Any],
) -> str:
    """A triageable failure message: what diverged first, and by how much."""
    oid = record["exposure_id"]
    driver, *_ = diffs
    lines = [
        "",
        f"{oid} ({record['framework']} {record['approach']} "
        f"{record['exposure_class']}) disagrees with the oracle.",
        f"  regulation:   {record['regulation']}",
        f"  first divergence: {driver[0]}",
        "",
        f"  {'field':<20}{'oracle (derived)':>24}{'engine':>24}{'rel err':>12}",
    ]
    for key, want, got, error in diffs:
        lines.append(f"  {key:<20}{want:>24.10f}{got:>24.10f}{error:>12.2e}")
    lines += [
        "",
        "  This is either an engine defect or an error in the derivation.",
        f"  Read the worked arithmetic at ORACLE_DERIVATIONS.md '## {oid}'",
        "  and settle it against the article text. Do NOT adjust the oracle",
        "  to match the engine -- record the disagreement in",
        "  KNOWN_DISAGREEMENTS instead.",
        "",
        f"  engine approach_applied = {actual.get('approach_applied')}",
    ]
    return "\n".join(lines)
