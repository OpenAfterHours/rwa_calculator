"""
How a referee worker ends: its result complete and flushed, then no teardown.

Pipeline position:
    runner._run_guarded -> python -I worker.py < SPEC > RESULT -> (this exit)

A worker holds a multi-GB Arelle model when its session ends. Closing the
session and tearing the interpreter down would free every object of it and run
the garbage collector over the lot — about 13 seconds per worker, measured on
PRA001, after the result is already written — and none of it reaches the
result. So the worker run as a SCRIPT writes and flushes its result, then ends
the process at once (``os._exit``): no session close, no atexit hooks, no
interpreter teardown. ``main`` called in-process still returns, and still
closes the session.

What is pinned here, with a stand-in for Arelle (no Arelle is needed):
- the script's result arrives whole, however large;
- neither the session's close nor the interpreter's teardown runs after it;
- the result is the one the in-process path writes, byte for byte — it is
  harvested before the session closes, so whatever the close would log is in
  neither.

References:
- packages/rwa-filer/src/rwa_filer/referee/worker.py
- Python ``os._exit`` — ends the process without cleanup handlers or buffer flushes
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from rwa_filer.referee import worker

#: Enough assertions that the result is far larger than any stream buffer.
ASSERTIONS = 20_000

#: The stand-in ``arelle.api.Session``. Its close logs a message and says so on
#: stderr; the package's import registers an atexit hook that says so too.
SESSION_SOURCE = f"""
import logging, sys

class _Model:
    def __init__(self):
        verdicts = {{f"boe_boe_b{{i:05d}}": (i % 3, i % 2, 0, 0, 0) for i in range({ASSERTIONS})}}
        self.errors = ["EBA.2.7", verdicts]


class Session:
    def __init__(self):
        self.models = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def run(self, options, logHandler=None):
        logger = logging.getLogger("arelle")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logHandler)
        logger.warning("unused context c9", extra={{"messageCode": "EBA.2.7"}})
        logger.error("[boe_b00001] 1 = 2", extra={{"messageCode": "message:boe_boe_b00001"}})
        self.models = [_Model()]
        return True

    def get_models(self):
        return self.models

    def close(self):
        logging.getLogger("arelle").warning("closing", extra={{"messageCode": "late:close"}})
        sys.stderr.write("session closed\\n")
"""
RUNTIME_OPTIONS_SOURCE = """
class RuntimeOptions:
    def __init__(self, **options):
        self.options = options
"""
PACKAGE_SOURCE = """
import atexit, sys
atexit.register(lambda: sys.stderr.write("interpreter teardown ran\\n"))
"""


@pytest.fixture
def spec(tmp_path: Path) -> dict[str, Any]:
    return {
        "instance": str(tmp_path / "instance.xbrl"),
        "packages": [],
        "plugin": None,
        "disclosure_system": None,
        "function_plugins": [],
        "repairs": [],
        "formula": True,
        "run_ids": None,
        "skip_loading": None,
        "xdg": str(tmp_path / "xdg"),
        "max_examples": 2,
        "chunk": 0,
    }


@pytest.fixture
def fake_arelle(tmp_path: Path) -> Path:
    """A directory holding a stand-in ``arelle`` package, for a worker subprocess."""
    root = tmp_path / "fake"
    files = {
        "arelle/__init__.py": PACKAGE_SOURCE,
        "arelle/api/__init__.py": "",
        "arelle/api/Session.py": SESSION_SOURCE,
        "arelle/RuntimeOptions.py": RUNTIME_OPTIONS_SOURCE,
    }
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def run_script(spec: dict[str, Any], fake_arelle: Path, tmp_path: Path) -> tuple[int, bytes, str]:
    """Run worker.py as the runner does, but with the stand-in Arelle on its path.

    Not isolated (``-I``), so that ``PYTHONPATH`` can name the stand-in.
    """
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    out_path = tmp_path / "result.json"
    env = {**os.environ, "PYTHONPATH": str(fake_arelle)}
    with spec_path.open("rb") as stdin, out_path.open("wb") as stdout:
        done = subprocess.run(  # noqa: S603 - this interpreter, the package's own script
            [sys.executable, worker.__file__],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    return done.returncode, out_path.read_bytes(), done.stderr.decode("utf-8", "replace")


def install_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same stand-in, as modules of this process — without the atexit hook."""
    session_module = types.ModuleType("arelle.api.Session")
    exec(SESSION_SOURCE, session_module.__dict__)  # noqa: S102 - the test's own source
    options_module = types.ModuleType("arelle.RuntimeOptions")
    exec(RUNTIME_OPTIONS_SOURCE, options_module.__dict__)  # noqa: S102 - the test's own source
    monkeypatch.setitem(sys.modules, "arelle", types.ModuleType("arelle"))
    monkeypatch.setitem(sys.modules, "arelle.api", types.ModuleType("arelle.api"))
    monkeypatch.setitem(sys.modules, "arelle.api.Session", session_module)
    monkeypatch.setitem(sys.modules, "arelle.RuntimeOptions", options_module)


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------


def test_the_script_writes_its_whole_result_and_exits_cleanly(
    spec: dict[str, Any], fake_arelle: Path, tmp_path: Path
) -> None:
    # Act
    code, out, _stderr = run_script(spec, fake_arelle, tmp_path)

    # Assert — parseable to the last byte, every assertion in it.
    assert code == 0
    result = json.loads(out)
    assert len(result["assertions"]) == ASSERTIONS
    assert result["assertions"]["boe_boe_b00004"] == [1, 0]
    assert result["messages"] == [
        {"code": "EBA.2.7", "level": "WARNING", "text": "unused context c9"}
    ]


def test_the_script_neither_closes_the_session_nor_tears_the_interpreter_down(
    spec: dict[str, Any], fake_arelle: Path, tmp_path: Path
) -> None:
    """Both would run after the result is written, and both cost time only."""
    # Act
    code, _out, stderr = run_script(spec, fake_arelle, tmp_path)

    # Assert
    assert code == 0
    assert "session closed" not in stderr
    assert "interpreter teardown ran" not in stderr


def test_a_usage_error_still_exits_2(fake_arelle: Path, tmp_path: Path) -> None:
    # Act
    done = subprocess.run(  # noqa: S603 - this interpreter, the package's own script
        [sys.executable, worker.__file__, "spec.json"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(fake_arelle)},
        check=False,
    )

    # Assert
    assert done.returncode == 2
    assert done.stdout == b""
    assert b"usage:" in done.stderr


# ---------------------------------------------------------------------------
# In-process callers
# ---------------------------------------------------------------------------


def test_main_in_process_returns_and_closes_the_session(
    spec: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    install_in_process(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(spec)))

    # Act
    code = worker.main([])
    captured = capfd.readouterr()

    # Assert
    assert code == 0
    assert len(json.loads(captured.out)["assertions"]) == ASSERTIONS
    assert "session closed" in captured.err


def test_the_script_and_the_in_process_path_write_the_same_result(
    spec: dict[str, Any],
    fake_arelle: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Harvested before the session closes, so what the close logs is in neither."""
    # Arrange
    install_in_process(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(spec)))

    # Act
    _code, script_out, _stderr = run_script(spec, fake_arelle, tmp_path)
    worker.main([])
    in_process_out = capfd.readouterr().out

    # Assert
    assert in_process_out.encode("utf-8") == script_out
    assert "late:close" not in in_process_out
