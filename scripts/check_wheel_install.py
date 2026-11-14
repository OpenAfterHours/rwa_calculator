"""
Clean-environment install gate for the workspace's wheels.

Pipeline position:
    uv build -> check_distribution.py -> check_wheel_install.py -> gh-action-pypi-publish

Key responsibilities:
- Build every workspace package's wheel from this tree into a throwaway directory
- Install ONE package's wheel into a fresh virtual environment, on the interpreter
  its ``Requires-Python`` names as the floor, holding nothing but that wheel, the
  workspace wheels it declares, and whatever those declare in turn
- Import every module the wheel ships, resolve every console script it declares,
  run the package's own smoke probes (``PROBES``), and for rwa-calc serve the
  ``rwa-ui`` app and fetch its landing page and a static asset
- Fail when any of that cannot be done with the package's declared dependencies

Why this exists
---------------
Every rwa-calc release from 0.2.24 to 0.3.34 installed and could not be used:
79 modules under ``src/rwa_calc`` import ``watchfire`` at module level for the
``@cites`` decorator, and ``watchfire`` was declared only in the ``dev`` extra and
the ``dev`` dependency group. ``from rwa_calc.api import CreditRiskCalc`` raised
``ModuleNotFoundError: No module named 'watchfire'`` for every installer, and so
did ``rwa-ui``. Every other gate runs in the workspace dev environment, which
holds the dev extra and group, so every one of them passed.

The probes are shaped by the ways a shallower one would have passed that wheel:

- ``import rwa_calc`` alone SUCCEEDS on it — the package ``__init__`` reaches no
  module that needs ``watchfire`` — so the probe imports every module, not the
  package.
- Walking the installed package with ``pkgutil.walk_packages`` MISSES modules:
  ``rwa_calc/data/`` has no ``__init__.py``, so the walk never enters it and
  ``rwa_calc.data.schemas`` goes unimported. The module list therefore comes from
  the wheel's own file listing, which cannot be wrong about what ships.
- An editable install, or a run from the repository root, reads the SOURCE tree:
  missing package data and a missing dependency both hide. The probes run under
  ``python -I`` from a scratch directory, and each reports where it imported the
  package from; a path outside the fresh environment is a failure.
- ``uv pip install`` would happily take a workspace sibling from PyPI at an older
  version. The siblings a wheel declares are installed from this tree's own
  build, so the gate measures the tree it runs on.

Takes no path arguments, for the reason ``check_distribution.py`` gives: the
locations it touches are a fixed property of the repository plus a temporary
directory it creates itself.

References:
- docs/development/escape-log.md — 2026-11-14 entry (the watchfire escape)
- https://packaging.python.org/en/latest/specifications/core-metadata/
- https://packaging.python.org/en/latest/specifications/entry-points/
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import HeaderParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The ``--package`` value that checks every package in ``PROBES``.
ALL_PACKAGES = "all"

#: How long a probe subprocess may run before the gate gives up on it.
PROBE_TIMEOUT_SECONDS = 300
#: How long the served app has to answer its landing page.
SERVE_TIMEOUT_SECONDS = 90
#: How many trailing lines of a failed command's output a problem quotes.
OUTPUT_TAIL_LINES = 15

#: Environment variables that would let a probe see something other than the
#: fresh environment. ``-I`` already ignores the ``PYTHON*`` ones for the probes
#: run through the interpreter; console scripts are run directly, so they are
#: removed here as well.
_LEAKY_ENV_VARS = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
)

_REQUIRES_PYTHON_FLOOR_RE = re.compile(r">=\s*(?P<floor>\d+\.\d+)")
_REQUIREMENT_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")
_STATIC_ASSET_RE = re.compile(r"""(?:href|src)=["'](?P<path>/static/[^"'?#]+)""")


@dataclass(frozen=True)
class InstallProbe:
    """What, beyond importing every shipped module, proves one package usable.

    Attributes:
        import_name: The top-level import package the wheel ships.
        statements: Python statements that must run — the public API a user
            reaches first, named so a failure reads as the user's failure.
        commands: Console-script invocations that must exit 0, as
            ``(script, *args)``. Only ones that return promptly.
        app_factory: ``module:callable`` returning an ASGI app, served with
            uvicorn on a free loopback port; its ``/`` must answer 200.
    """

    import_name: str
    statements: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    app_factory: str | None = None


#: One entry per workspace package, by distribution name. A literal table on
#: purpose: ``--package`` selects from its keys via ``choices=``, and
#: ``tests/contracts/test_release_coverage.py`` fails until a new workspace member
#: has an entry here.
PROBES: dict[str, InstallProbe] = {
    "rwa-calc": InstallProbe(
        import_name="rwa_calc",
        statements=(
            "from rwa_calc.api import CreditRiskCalc",
            "from rwa_calc.ui.app.main import create_app",
        ),
        commands=(("rulepack-diff", "--help"),),
        # What `rwa-ui` serves. The console script itself binds a fixed port and
        # opens a browser, neither of which belongs in a gate; everything else it
        # does — building the app, its templates and static files — runs here.
        app_factory="rwa_calc.ui.app.main:create_app",
    ),
    "rwa-filer": InstallProbe(
        import_name="rwa_filer",
        commands=(("rwa-filer", "--version"),),
    ),
}


def main() -> int:
    """Build the workspace wheels and gate each selected package's clean install."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a built wheel cannot be imported, or its console scripts and "
            "app cannot start, in a fresh environment holding only its declared "
            "dependencies. Builds from this tree; takes no paths."
        )
    )
    parser.add_argument(
        "--package",
        choices=[*sorted(PROBES), ALL_PACKAGES],
        default=ALL_PACKAGES,
        help="Which workspace package's wheel to check (default: all)",
    )
    args = parser.parse_args()

    packages = sorted(PROBES) if args.package == ALL_PACKAGES else [args.package]
    with tempfile.TemporaryDirectory(prefix="wheel-install-") as scratch:
        return check_wheel_install(packages, Path(scratch))


def check_wheel_install(packages: list[str], scratch: Path) -> int:
    """Return 0 when every named package's wheel works from a clean install, 1 otherwise."""
    if shutil.which("uv") is None:
        sys.stderr.write("uv is not on PATH; this gate builds and installs with it.\n")
        return 1

    built = build_wheels(scratch / "wheels")
    if not built:
        sys.stderr.write(
            "The build produced no wheels. A gate with nothing to install must not "
            "report success.\n"
        )
        return 1

    failed: list[str] = []
    for name in packages:
        print(f"{name}:")
        problems = check_package(name, built, scratch / name)
        if problems:
            failed.append(name)
            sys.stderr.write(f"{name}: the wheel does not work from a clean install.\n")
            for problem in problems:
                sys.stderr.write(f"  - {problem}\n")

    if failed:
        sys.stderr.write(
            "\nA module the wheel ships needs a distribution the wheel does not declare, "
            "or a console script or the app cannot start without the dev environment.\n"
            "Fix: declare the missing distribution in [project].dependencies of the "
            "package's pyproject.toml — a dev extra or dependency group is not installed "
            "for users.\n"
        )
        return 1

    print(f"Every checked wheel works from a clean install: {', '.join(packages)}")
    return 0


def build_wheels(out_dir: Path) -> dict[str, Path]:
    """Build every workspace package's wheel into ``out_dir``; return them by name."""
    result = _run(
        ["uv", "build", "--all-packages", "--wheel", "-o", str(out_dir)],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        sys.stderr.write(f"uv build failed:\n{_tail(result)}\n")
        return {}
    return {
        _normalise(read_wheel_metadata(wheel)["Name"]): wheel
        for wheel in sorted(out_dir.glob("*.whl"))
    }


def check_package(name: str, wheels: dict[str, Path], workdir: Path) -> list[str]:
    """Install ``name``'s wheel into a fresh environment under ``workdir`` and probe it."""
    probe = PROBES[name]
    wheel = wheels.get(name)
    if wheel is None:
        return [f"the workspace build produced no wheel for {name}"]

    metadata = read_wheel_metadata(wheel)
    floor = python_floor(metadata.get("Requires-Python", ""))
    if floor is None:
        return [
            f"{wheel.name} declares Requires-Python {metadata.get('Requires-Python')!r}; "
            "this gate needs a '>=X.Y' floor to know which interpreter to install on"
        ]

    workdir.mkdir(parents=True)
    venv = workdir / "venv"
    created = _run(["uv", "venv", "--python", floor, str(venv)], cwd=workdir)
    if created.returncode != 0:
        return [f"could not create a Python {floor} environment:\n{_tail(created)}"]

    python = venv_python(venv)
    siblings = workspace_closure(name, wheels)
    installed = _run(
        ["uv", "pip", "install", "--python", str(python), str(wheel), *map(str, siblings)],
        cwd=workdir,
    )
    if installed.returncode != 0:
        return [f"uv pip install of {wheel.name} failed:\n{_tail(installed)}"]
    print(f"  installed {wheel.name} (+ {len(siblings)} workspace wheel(s)) on Python {floor}")

    return probe_install(venv, wheel, probe, workdir)


def probe_install(venv: Path, wheel: Path, probe: InstallProbe, workdir: Path) -> list[str]:
    """Run every probe against a wheel already installed in ``venv``.

    Split from :func:`check_package` so the contract tests can drive the probes
    against a hand-built wheel installed offline, without a network resolve.
    """
    home = workdir / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = probe_environment(home)

    problems = probe_modules(venv, wheel_modules(wheel, probe.import_name), probe, workdir, env)
    problems += probe_console_scripts(venv, console_scripts(wheel), workdir, env)
    if probe.statements:
        problems += probe_statements(venv, probe.statements, workdir, env)
    for command in probe.commands:
        problems += probe_command(venv, command, workdir, env)
    if probe.app_factory is not None:
        problems += probe_app(venv, probe.app_factory, workdir, env)
    return problems


def probe_modules(
    venv: Path, modules: list[str], probe: InstallProbe, workdir: Path, env: dict[str, str]
) -> list[str]:
    """Import every shipped module; report each that fails, and any vacuous run."""
    if not modules:
        return [f"the wheel ships no modules under {probe.import_name}/ — nothing was imported"]

    result = _run(
        [str(venv_python(venv)), "-I", "-c", _IMPORT_EVERY_MODULE, probe.import_name],
        cwd=workdir,
        env=env,
        stdin=json.dumps(modules),
    )
    report = _last_json_line(result.stdout)
    if result.returncode != 0 or report is None:
        return [f"importing {probe.import_name} failed outright:\n{_tail(result)}"]

    problems = [
        f"import {module} -> {error}" for module, error in sorted(report["failures"].items())
    ]
    problems += _foreign_origin(report["origin"], venv, probe.import_name)
    if report["attempted"] != len(modules):
        problems.append(
            f"asked to import {len(modules)} modules, the probe attempted {report['attempted']}"
        )
    if not problems:
        print(f"  imported all {len(modules)} modules from {report['origin']}")
    return problems


def probe_console_scripts(
    venv: Path, scripts: dict[str, str], workdir: Path, env: dict[str, str]
) -> list[str]:
    """Every declared console script is installed and resolves to a callable."""
    problems = [
        f"console script {script} was not installed into the environment"
        for script in sorted(scripts)
        if not venv_script(venv, script).exists()
    ]
    if not scripts:
        return problems

    result = _run(
        [str(venv_python(venv)), "-I", "-c", _RESOLVE_ENTRY_POINTS],
        cwd=workdir,
        env=env,
        stdin=json.dumps(scripts),
    )
    report = _last_json_line(result.stdout)
    if result.returncode != 0 or report is None:
        return [*problems, f"resolving console scripts failed:\n{_tail(result)}"]
    problems += [
        f"console script {script} = {scripts[script]} -> {error}"
        for script, error in sorted(report["failures"].items())
    ]
    if not problems:
        print(f"  resolved console scripts: {', '.join(sorted(scripts))}")
    return problems


def probe_statements(
    venv: Path, statements: tuple[str, ...], workdir: Path, env: dict[str, str]
) -> list[str]:
    """The package's named public-API statements run."""
    code = "\n".join(statements)
    result = _run([str(venv_python(venv)), "-I", "-c", code], cwd=workdir, env=env)
    if result.returncode != 0:
        return [f"{'; '.join(statements)} failed:\n{_tail(result)}"]
    print(f"  ran: {'; '.join(statements)}")
    return []


def probe_command(
    venv: Path, command: tuple[str, ...], workdir: Path, env: dict[str, str]
) -> list[str]:
    """A console-script invocation exits 0."""
    script, *args = command
    result = _run([str(venv_script(venv, script)), *args], cwd=workdir, env=env)
    if result.returncode != 0:
        return [f"`{' '.join(command)}` exited {result.returncode}:\n{_tail(result)}"]
    print(f"  ran: {' '.join(command)}")
    return []


def probe_app(venv: Path, factory: str, workdir: Path, env: dict[str, str]) -> list[str]:
    """Serve ``factory``'s app on a free loopback port; ``/`` and one static asset answer 200."""
    port = _free_port()
    log = workdir / "app.log"
    with log.open("w", encoding="utf-8") as sink:
        server = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [str(venv_python(venv)), "-I", "-c", _SERVE_APP, factory, str(port)],
            cwd=workdir,
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        try:
            return _probe_served_app(server, port, factory, log)
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def wheel_modules(wheel: Path, import_name: str) -> list[str]:
    """Every importable module the wheel ships under ``import_name``, dotted.

    Read from the archive listing rather than by walking the installed package:
    a walk does not enter a directory without ``__init__.py``, and this repository
    ships one (``rwa_calc/data/``). ``__main__`` modules are left out — importing
    one runs the program.
    """
    modules: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.namelist():
            parts = entry.removesuffix(".py").split("/")
            if not entry.endswith(".py") or parts[0] != import_name:
                continue
            if parts[-1] == "__main__" or not all(part.isidentifier() for part in parts):
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules.add(".".join(parts))
    return sorted(modules)


def console_scripts(wheel: Path) -> dict[str, str]:
    """``{script: "module:attr"}`` from the wheel's ``entry_points.txt``."""
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/entry_points.txt")]
        if not names:
            return {}
        text = archive.read(names[0]).decode("utf-8")
    parser = configparser.ConfigParser(delimiters=("=",), interpolation=None)
    parser.optionxform = str  # keep script names' case (the default lower-cases keys)
    parser.read_string(text)
    if not parser.has_section("console_scripts"):
        return {}
    return dict(parser.items("console_scripts"))


def read_wheel_metadata(wheel: Path) -> dict[str, str]:
    """The wheel's core metadata. Repeated fields keep their last value; use
    :func:`declared_dependencies` for ``Requires-Dist``."""
    return dict(_metadata_message(wheel).items())


def declared_dependencies(wheel: Path) -> list[str]:
    """Normalised names of the unconditional ``Requires-Dist`` entries.

    A requirement carrying a marker (``; extra == "dev"``, ``; python_version...``)
    is left out: this gate installs what every user gets, and the workspace closure
    built from these names must not drag an optional sibling in.
    """
    names: list[str] = []
    for requirement in _metadata_message(wheel).get_all("Requires-Dist") or []:
        if ";" in requirement:
            continue
        match = _REQUIREMENT_NAME_RE.match(requirement)
        if match is not None:
            names.append(_normalise(match.group("name")))
    return names


def workspace_closure(name: str, wheels: dict[str, Path]) -> list[Path]:
    """The other workspace wheels ``name`` depends on, directly or transitively."""
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        for dependency in declared_dependencies(wheels[current]):
            if dependency in wheels and dependency != name and dependency not in seen:
                seen.add(dependency)
                pending.append(dependency)
    return [wheels[dependency] for dependency in sorted(seen)]


def python_floor(requires_python: str) -> str | None:
    """``"3.13"`` from ``">=3.13"``; ``None`` when there is no ``>=`` floor."""
    match = _REQUIRES_PYTHON_FLOOR_RE.search(requires_python)
    return match.group("floor") if match else None


def probe_environment(home: Path) -> dict[str, str]:
    """The environment every probe runs in: no leaked paths, a throwaway home.

    ``HOME`` / ``USERPROFILE`` point into the scratch directory so that a probe
    which persists per-user state (the UI keeps a run index under ``~``) writes
    there, not into the account running the gate.
    """
    env = {key: value for key, value in os.environ.items() if key not in _LEAKY_ENV_VARS}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def venv_python(venv: Path) -> Path:
    """The environment's interpreter."""
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def venv_script(venv: Path, script: str) -> Path:
    """Where the installer puts a console script."""
    return venv / "Scripts" / f"{script}.exe" if os.name == "nt" else venv / "bin" / script


# ---------------------------------------------------------------------------
# Probe programs — run inside the fresh environment under `python -I`
# ---------------------------------------------------------------------------

#: Imports each module named on stdin. Reports, as one JSON line, where the
#: package was imported from, how many modules it tried, and every failure.
_IMPORT_EVERY_MODULE = r"""
import importlib, json, sys
package = importlib.import_module(sys.argv[1])
modules = json.loads(sys.stdin.read())
failures = {}
for module in modules:
    try:
        importlib.import_module(module)
    except BaseException as exc:
        failures[module] = f"{type(exc).__name__}: {exc}"
print(json.dumps({"origin": package.__file__, "attempted": len(modules), "failures": failures}))
"""

#: Resolves each ``{script: "module:attr"}`` on stdin to a callable.
_RESOLVE_ENTRY_POINTS = r"""
import importlib, json, sys
failures = {}
for script, target in json.loads(sys.stdin.read()).items():
    module, _, attr = target.partition(":")
    try:
        obj = importlib.import_module(module.strip())
        for part in attr.strip().split("."):
            obj = getattr(obj, part)
        if not callable(obj):
            failures[script] = f"{target} is not callable"
    except BaseException as exc:
        failures[script] = f"{type(exc).__name__}: {exc}"
print(json.dumps({"failures": failures}))
"""

#: Builds the app from ``module:callable`` and serves it on the loopback port given.
_SERVE_APP = r"""
import importlib, sys, uvicorn
module, _, attr = sys.argv[1].partition(":")
app = getattr(importlib.import_module(module), attr)()
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
"""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _probe_served_app(
    server: subprocess.Popen[bytes], port: int, factory: str, log: Path
) -> list[str]:
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + SERVE_TIMEOUT_SECONDS
    page: str | None = None
    while time.monotonic() < deadline:
        if server.poll() is not None:
            return [
                f"the app from {factory} exited with {server.returncode} before answering:\n{_tail_text(log.read_text(encoding='utf-8'))}"
            ]
        status, body = _http_get(f"{base}/")
        if status == 200:
            page = body
            break
        time.sleep(0.5)
    if page is None:
        return [
            f"the app from {factory} did not answer GET / with 200 within {SERVE_TIMEOUT_SECONDS}s:\n{_tail_text(log.read_text(encoding='utf-8'))}"
        ]

    asset = _STATIC_ASSET_RE.search(page)
    if asset is None:
        print(f"  served {factory}: GET / -> 200")
        return []
    status, _ = _http_get(f"{base}{asset.group('path')}")
    if status != 200:
        return [
            f"the app's landing page references {asset.group('path')}, which answered {status}: package data missing from the wheel?"
        ]
    print(f"  served {factory}: GET / -> 200, GET {asset.group('path')} -> 200")
    return []


def _http_get(url: str) -> tuple[int | None, str]:
    # A loopback request must never go through the proxy the environment configures.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None, ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _foreign_origin(origin: str, venv: Path, import_name: str) -> list[str]:
    try:
        inside = Path(origin).resolve().is_relative_to(venv.resolve())
    except (OSError, ValueError):
        inside = False
    if inside:
        return []
    return [
        f"{import_name} was imported from {origin}, outside the fresh environment — the "
        "probe measured another copy (a source tree on sys.path?), not the installed wheel"
    ]


def _metadata_message(wheel: Path) -> Message:
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if not names:
            raise ValueError(f"{wheel.name} contains no .dist-info/METADATA")
        return HeaderParser().parsestr(archive.read(names[0]).decode("utf-8"))


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _last_json_line(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            cwd=cwd,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(argv, 124, "", f"timed out after {exc.timeout}s")


def _tail(result: subprocess.CompletedProcess[str]) -> str:
    return _tail_text(f"{result.stdout}\n{result.stderr}")


def _tail_text(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(f"      {line}" for line in lines[-OUTPUT_TAIL_LINES:])


if __name__ == "__main__":
    sys.exit(main())
