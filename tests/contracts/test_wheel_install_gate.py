"""
Contract tests for the clean-environment wheel-install gate.

Pipeline position:
    uv build -> scripts/check_distribution.py -> scripts/check_wheel_install.py
    -> gh-action-pypi-publish

Key responsibilities:
- The probes FAIL a wheel whose module imports a distribution the wheel does not
  declare — the shape of the watchfire escape — while its top-level package
  imports cleanly, which is the shallow check that escape slipped past
- The same probes PASS that wheel once the module is clean, so the red above is
  the import and not the harness
- A module under a directory with no ``__init__.py`` is still imported, because
  the module list is the wheel's own and not a ``pkgutil`` walk
- CI, the publish workflow and the release script still run the gate — a gate
  nothing calls reports success forever
- ``watchfire`` stays a runtime dependency; the gate itself needs the network and
  runs in CI, so this is the dev-loop tripwire for the specific regression

The behavioural tests install a hand-built wheel OFFLINE (``--no-deps``) into a
virtual environment made from the running interpreter, and drive
``probe_install`` — everything the gate does after its network resolve.

References:
- docs/development/escape-log.md — 2026-11-14 entry (the watchfire escape)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from tests.contracts._ci_workflow import gate_wiring_problems, without_comments

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_wheel_install as gate  # noqa: E402
import deploy  # noqa: E402

CI_JOB = "wheel-install"
_INVOKES_GATE_FOR_EVERY_PACKAGE = re.compile(
    r"\bscripts/check_wheel_install\.py(?:\s+--package\s+all)?\s*$"
)
_PUBLISH_INVOKES_GATE = re.compile(
    r"^\s*run:\s*python\s+scripts/check_wheel_install\.py\s+--package\s+\"\$PACKAGE\"\s*$",
    re.MULTILINE,
)

_PACKAGE = "gate_probe_pkg"
_ABSENT = "gate_probe_absent_dependency"
_PROBE = gate.InstallProbe(import_name=_PACKAGE)


def _write_wheel(directory: Path, modules: dict[str, str], entry_points: str = "") -> Path:
    """A minimal installable wheel shipping ``modules`` (path under the package -> source)."""
    files = {f"{_PACKAGE}/{path}": source for path, source in modules.items()}
    info = f"{_PACKAGE}-1.0.dist-info"
    files[f"{info}/METADATA"] = (
        "Metadata-Version: 2.1\nName: gate-probe-pkg\nVersion: 1.0\nRequires-Python: >=3.13\n"
    )
    files[f"{info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    if entry_points:
        files[f"{info}/entry_points.txt"] = entry_points
    record = "".join(f"{name},,\n" for name in files) + f"{info}/RECORD,,\n"

    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{_PACKAGE}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, source in files.items():
            archive.writestr(name, source)
        archive.writestr(f"{info}/RECORD", record)
    return wheel


def _install_offline(wheel: Path, workdir: Path) -> Path:
    """A fresh virtual environment holding ``wheel`` alone. Returns the environment."""
    assert shutil.which("uv") is not None, "uv must be on PATH — the gate itself runs on it"
    venv = workdir / "venv"
    for argv in (
        ["uv", "venv", "--python", sys.executable, str(venv)],
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(gate.venv_python(venv)),
            str(wheel),
        ],
    ):
        result = subprocess.run(argv, cwd=workdir, capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{' '.join(argv)} failed:\n{result.stderr}"
    return venv


def _python(venv: Path, code: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(gate.venv_python(venv)), "-I", "-c", code],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Behaviour: the probes catch the escape's shape
# ---------------------------------------------------------------------------


def test_probes_fail_a_wheel_whose_module_imports_an_undeclared_distribution(
    tmp_path: Path,
) -> None:
    # Arrange — the watchfire shape: a clean package __init__, and a module whose
    # module-level import names a distribution the wheel never declares.
    wheel = _write_wheel(
        tmp_path / "wheels",
        {
            "__init__.py": "",
            "clean.py": "VALUE = 1\n",
            "cited.py": f"from {_ABSENT} import cites\n\ndef main():\n    return 0\n",
        },
        entry_points=f"[console_scripts]\ngate-probe = {_PACKAGE}.cited:main\n",
    )
    venv = _install_offline(wheel, tmp_path)
    shallow = _python(venv, f"import {_PACKAGE}", tmp_path)
    assert shallow.returncode == 0, (
        "the package itself must import cleanly, or this test would not show that the "
        "gate catches what `import <package>` misses — which is how the escape shipped"
    )

    # Act
    problems = gate.probe_install(venv, wheel, _PROBE, tmp_path)

    # Assert
    expected_import = f"import {_PACKAGE}.cited -> ModuleNotFoundError: No module named '{_ABSENT}'"
    assert expected_import in problems
    assert any(problem.startswith("console script gate-probe") for problem in problems)
    assert not any(f"{_PACKAGE}.clean" in problem for problem in problems)


def test_probes_pass_the_same_wheel_once_its_modules_are_clean(tmp_path: Path) -> None:
    # Arrange
    wheel = _write_wheel(
        tmp_path / "wheels",
        {
            "__init__.py": "",
            "clean.py": "VALUE = 1\n",
            "cited.py": "def main():\n    return 0\n",
        },
        entry_points=f"[console_scripts]\ngate-probe = {_PACKAGE}.cited:main\n",
    )
    venv = _install_offline(wheel, tmp_path)

    # Act
    problems = gate.probe_install(venv, wheel, _PROBE, tmp_path)

    # Assert
    assert problems == []


def test_a_module_under_a_directory_without_init_is_still_imported(tmp_path: Path) -> None:
    # Arrange — rwa_calc/data/ has no __init__.py, and holds rwa_calc.data.schemas.
    wheel = _write_wheel(
        tmp_path / "wheels",
        {"__init__.py": "", "nsdir/deep.py": f"import {_ABSENT}\n"},
    )
    venv = _install_offline(wheel, tmp_path)
    walked = _python(
        venv,
        f"import pkgutil, {_PACKAGE} as p; "
        f"print(sorted(m.name for m in pkgutil.walk_packages(p.__path__, '{_PACKAGE}.')))",
        tmp_path,
    )
    assert f"{_PACKAGE}.nsdir.deep" not in walked.stdout, (
        "pkgutil.walk_packages now enters a directory without __init__.py, so this "
        "test no longer shows why the module list must come from the wheel"
    )

    # Act
    problems = gate.probe_install(venv, wheel, _PROBE, tmp_path)

    # Assert
    assert f"{_PACKAGE}.nsdir.deep" in gate.wheel_modules(wheel, _PACKAGE)
    assert any(problem.startswith(f"import {_PACKAGE}.nsdir.deep ->") for problem in problems)


def test_a_wheel_shipping_no_modules_fails_rather_than_passes(tmp_path: Path) -> None:
    # Arrange
    wheel = _write_wheel(tmp_path / "wheels", {})
    venv = tmp_path / "venv-never-created"

    # Act
    problems = gate.probe_modules(venv, gate.wheel_modules(wheel, _PACKAGE), _PROBE, tmp_path, {})

    # Assert
    assert len(problems) == 1
    assert "nothing was imported" in problems[0]


# ---------------------------------------------------------------------------
# Metadata readers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requires_python", "floor"),
    [(">=3.13", "3.13"), (">= 3.14, <4", "3.14"), ("", None), ("~=3.13", None)],
)
def test_python_floor_reads_the_lower_bound(requires_python: str, floor: str | None) -> None:
    assert gate.python_floor(requires_python) == floor


def test_declared_dependencies_are_the_unconditional_ones_normalised(tmp_path: Path) -> None:
    # Arrange
    wheel = tmp_path / "x-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "x-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: x\nVersion: 1.0\n"
            "Requires-Dist: Rwa_Filer<0.2,>=0.1\n"
            "Requires-Dist: polars>=1.0.0\n"
            'Requires-Dist: watchfire==0.3.1; extra == "dev"\n',
        )

    # Act / Assert
    assert gate.declared_dependencies(wheel) == ["rwa-filer", "polars"]


# ---------------------------------------------------------------------------
# Wiring: a gate nothing calls is not a gate
# ---------------------------------------------------------------------------


def test_ci_runs_the_gate_for_every_package_and_it_can_fail_the_build() -> None:
    assert gate_wiring_problems(CI_JOB, _INVOKES_GATE_FOR_EVERY_PACKAGE) == []


def test_the_publish_workflow_runs_the_gate_on_the_package_it_publishes() -> None:
    # Arrange
    live = without_comments(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))

    # Assert
    assert _PUBLISH_INVOKES_GATE.search(live), (
        "publish.yml no longer runs scripts/check_wheel_install.py on the package it "
        "is about to upload"
    )


@pytest.mark.parametrize("package", [deploy.ROOT_PACKAGE, *sorted(deploy.MEMBER_RELEASES)])
def test_every_release_build_runs_the_gate_after_building(
    package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — record every command instead of running it.
    commands: list[list[str]] = []
    monkeypatch.setattr(
        deploy, "run_command", lambda cmd, description: commands.append(list(cmd)) or True
    )
    monkeypatch.setattr(deploy, "member_distributions", lambda member: [])

    # Act
    if package == deploy.ROOT_PACKAGE:
        built = deploy.build_release("9.9.9")
    else:
        built = deploy.build_member(deploy.MEMBER_RELEASES[package])

    # Assert
    gate_command = deploy.wheel_install_command(package)
    assert built
    assert gate_command in commands, f"the {package} release build never runs {gate_command}"
    last_build = max(i for i, cmd in enumerate(commands) if cmd[:2] == ["uv", "build"])
    assert commands.index(gate_command) > last_build


def test_watchfire_is_a_runtime_dependency() -> None:
    # Arrange
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    # Act
    runtime = [requirement.split("==")[0].strip() for requirement in project["dependencies"]]

    # Assert
    assert "watchfire" in runtime, (
        "79 modules under src/rwa_calc import `watchfire` at module level for @cites; "
        "declaring it only as a dev dependency ships a wheel that cannot import "
        "rwa_calc.api (escape log, 2026-11-14)"
    )
