"""
Where a workflow names a Python interpreter, it names an exact minor version.

Pipeline position:
    (no pipeline stage — a contract on ``.github/workflows/*.yml``)

``docs.yml`` asked ``actions/setup-python`` for ``3.x``, which resolves to the
newest CPython in the runner's tool cache. When CPython 3.15 reached it, the docs
job's interpreter moved with no commit: ``marimo`` (a runtime dependency) pulls in
``loro``, which had no cp315 wheel, and its source build stopped in PyO3 ("the
configured Python interpreter version (3.15) is newer than PyO3's maximum
supported version (3.14)"). Deploy Documentation then failed on every push to
master from 2026-11-13. CI's own jobs stayed green on the runner image's 3.14, and
``docs.yml`` fires only on master, so nothing that runs on a pull request could
see it.

The contract is the narrow one that failure licenses: an interpreter a workflow
NAMES is an exact ``3.N`` (or ``3.N.M``), never a range or a wildcard. It does not
require every job to name one. The jobs in ``ci.yml`` name none and take the
runner image's ``python3``; whether to pin them is the open CI-cost decision filed
as P5.72 in ``IMPLEMENTATION_PLAN.md``, and this test must not make that decision
by the back door.

A ``${{ ... }}`` expression (a matrix entry) is not followed: its values live
elsewhere in the file, and none of today's workflows uses one.

References:
- IMPLEMENTATION_PLAN.md P5.72 — CI's interpreter is picked by the runner image
"""

from __future__ import annotations

import re

from tests.contracts._ci_workflow import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: A ``python-version:`` key, as a step input or a mapping entry, and its value.
_PYTHON_VERSION_KEY = re.compile(r"^[ \t]*(?:-[ \t]+)?python-version:[ \t]*(\S.*?)[ \t]*$")

#: An exact minor (``3.14``) or patch (``3.14.4``) release, quoted or bare.
_EXACT_VERSION = re.compile(r"""^(["']?)3\.\d+(?:\.\d+)?\1$""")


def test_no_workflow_names_a_floating_python_version() -> None:
    """A named interpreter is ``3.N`` or ``3.N.M``: never ``3.x``, a range or ``*``."""
    # Arrange
    workflows = sorted(WORKFLOWS_DIR.glob("*.yml"))
    pins: list[tuple[str, int, str]] = []
    for path in workflows:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue  # a commented-out pin selects nothing
            match = _PYTHON_VERSION_KEY.match(line)
            if match is not None:
                value = re.sub(r"[ \t]+#.*$", "", match.group(1))
                pins.append((path.name, number, value))

    # Act
    floating = [
        f"{name}:{number}: python-version: {value}"
        for name, number, value in pins
        if not value.startswith("${{") and not _EXACT_VERSION.match(value)
    ]

    # Assert
    assert workflows, f"no workflow files under {WORKFLOWS_DIR}; the scan read nothing"
    assert pins, (
        "no `python-version:` key in any workflow; docs.yml names one, so the scan "
        "is not reading what it should"
    )
    assert not floating, (
        "A workflow names a floating Python version. It resolves to the newest "
        "interpreter on the runner, so the job's interpreter moves without a commit "
        "and breaks when a dependency has no wheel for it yet (Deploy Documentation, "
        "2026-11-13: `3.x` became 3.15 and `loro` would not build). Name an exact "
        "`3.N`:\n  " + "\n  ".join(floating)
    )
