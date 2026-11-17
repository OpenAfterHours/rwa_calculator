"""
A stand-in referee worker, and the tiny taxonomy package and instance it is run on.

Pipeline position:
    (test support) runner.run_referee / runner.run_referees -> FAKE_WORKER

``runner.WORKER_SCRIPT`` names the script each worker process runs. Tests point
it at ``FAKE_WORKER``, which reads its spec exactly as the real worker does and
answers from a script the test wrote — canned verdicts for the assertions it
was handed, canned messages, or a failure: a non-zero exit, no result, a
result cut short, a sleep past the timeout, more memory than the cap. What a worker does is keyed by
``"every"``, by ``"chunk<N>"`` and by ``"<instance stem>/chunk<N>"``, the more
specific winning; every launch is appended to ``launches.txt`` beside the
script, as ``<instance stem>/chunk<N>``, and its process id to ``pids.txt``.

The module, ``tst001``, files against templates T01 and T02 and has four rules:
- ``boe_b0001`` (400 bytes of XML) needs T01 — the workers report 3 satisfied.
- ``boe_b0002`` (300) needs T01 — 1 satisfied, 2 unsatisfied, with an example.
- ``v0003_m`` (300) needs T01 and T02 — never fires.
- ``boe_b0004`` (200) needs T03, which the instance does NOT file.

Under a 600-byte chunk limit that is two workers: ``boe_b0001`` alone, then
``boe_b0002`` with ``v0003_m``.

References:
- packages/rwa-filer/src/rwa_filer/referee/runner.py — ``WORKER_SCRIPT``
- packages/rwa-filer/src/rwa_filer/referee/worker.py — the real worker it stands in for
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rwa_filer.referee import RefereeResult, run_referee, runner

if TYPE_CHECKING:
    import pytest

ENTRY_POINT = "http://www.example.test/xbrl/fws/tst/2027-01-01/mod/tst001.xsd"
FRAMEWORK = "tst-package/www.example.test/xbrl/fws/tst/2027-01-01"
XMLNS = 'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"'
PRECONDITION_ARCROLE = "http://xbrl.org/arcrole/2008/variable-set-precondition"

#: name -> (bytes of assertion XML, filing-indicator precondition)
RULES = {
    "boe_b0001": (400, "$find:tT01"),
    "boe_b0002": (300, "$find:tT01"),
    "v0003_m": (300, "($find:tT01 and $find:tT02)"),
    "boe_b0004": (200, "$find:tT03"),
}
FILED = ("T01", "T02")
CHUNK_MB = 600 / 1e6

#: What Arelle would count for each ASSERTION id. An untrimmed run loads every
#: assertion and counts 0 / 0 for the one whose precondition is false.
VERDICTS = {
    "boe_boe_b0001": [3, 0],
    "boe_boe_b0002": [1, 2],
    "boe_v0003_m": [0, 0],
    "boe_boe_b0004": [0, 0],
}
EXAMPLES = {
    "boe_boe_b0002": [
        {
            "level": "ERROR",
            "text": "[boe_b0002];[(t: T01, c: 0010) reported as 5 = 7]",
            "facts": [{"assertion_test": "$a = $b"}, {"line": 12, "value": "5"}],
        }
    ]
}

UNUSED_PREFIX = {"code": "EBA.3.4", "level": "WARNING", "text": "unused prefix eba_GA"}
INVALID_FACT = {"code": "xbrldie:invalid", "level": "ERROR", "text": "fact not valid"}
REWRITE_OVERLAP = {"code": "tpe:packageRewriteOverlap", "level": "WARNING", "text": "overlap"}
SINGLE_CURRENCY = {"code": "EBA.3.1", "level": "ERROR", "text": "only one currency"}

FAKE_WORKER = '''
"""A stand-in for the referee worker: reads the same spec, needs no Arelle."""
import json, os, re, sys, time, zipfile
from pathlib import Path

if not sys.flags.isolated:
    sys.exit("a worker must be launched isolated (python -I)")
if sys.argv[1:]:
    sys.exit("a worker takes its spec on standard input, not as an argument")
spec = json.load(sys.stdin)
script = json.loads(Path(__file__).with_name("script.json").read_text(encoding="utf-8"))
chunk = f"chunk{spec['chunk']}"  # "chunk0", "chunk1", ...
launch = f"{Path(spec['instance']).stem}/{chunk}"
behaviour = {**script.get("every", {}), **script.get(chunk, {}), **script.get(launch, {})}
with Path(__file__).with_name("launches.txt").open("a", encoding="utf-8") as log:
    log.write(launch + "\\n")
with Path(__file__).with_name("pids.txt").open("a", encoding="utf-8") as log:
    log.write(f"{os.getpid()}\\n")

# The assertions handed over: the ones the overlay's preconditions name or,
# against the official entry point, all of them (less a run-id restriction).
overlays = spec["packages"][1:]
if not spec["formula"]:
    handed = set()
elif overlays:
    with zipfile.ZipFile(overlays[0]) as archive:
        name = next(n for n in archive.namelist() if n.endswith("-find-prec.xml"))
        handed = set(re.findall(r'#([^"]+)"', archive.read(name).decode("utf-8")))
else:
    handed = set(script["verdicts"])
    if spec["run_ids"]:
        handed &= set(spec["run_ids"].split("|"))

ballast = bytearray(b"x") * (behaviour.get("allocate_mb", 0) << 20)
time.sleep(behaviour.get("sleep", 0))
sys.stderr.write(behaviour.get("stderr", ""))
if behaviour.get("garbage"):
    sys.stdout.write('{"assertions": {"cut short')
elif behaviour.get("exit", 0) == 0 and not behaviour.get("silent"):
    omitted = set(behaviour.get("omit", []))
    counted = {a: c for a, c in script["verdicts"].items() if a in handed and a not in omitted}
    result = {
        "assertions": counted | behaviour.get("also", {}),
        "examples": {a: e for a, e in script["examples"].items() if a in handed},
        "messages": behaviour.get("messages", []),
        "timings": {"loaded_s": 1.5, "validated_s": 2.5},
    }
    json.dump(result, sys.stdout)
sys.exit(behaviour.get("exit", 0))
'''


def build_package(path: Path) -> Path:
    """A taxonomy package with one entry point, its preconditions and assertion files."""
    refs = "".join(
        f'<link:linkbaseRef xlink:href="../val/vr-{name}-err-en.xml" xlink:type="simple" />\n'
        for name in RULES
    )
    xsd = (
        f'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" {XMLNS}>\n'
        f"<xsd:annotation><xsd:appinfo>\n{refs}"
        '<link:linkbaseRef xlink:href="tst001-find-prec.xml" xlink:type="simple" />\n'
        "</xsd:appinfo></xsd:annotation>\n</xsd:schema>\n"
    )
    arcs = "".join(
        f'<variable:precondition xlink:type="resource" xlink:label="p_{name}" test="{test}" />\n'
        f'<link:loc xlink:type="locator" xlink:href="../val/vr-{name}.xml#boe_{name}"'
        f' xlink:label="loc_{name}" />\n'
        f'<gen:arc xlink:type="arc" xlink:arcrole="{PRECONDITION_ARCROLE}"'
        f' xlink:from="loc_{name}" xlink:to="p_{name}" />\n'
        for name, (_size, test) in RULES.items()
    )
    preconditions = (
        f'<link:linkbase {XMLNS} xmlns:gen="http://xbrl.org/2008/generic"'
        ' xmlns:variable="http://xbrl.org/2008/variable">\n'
        f'<gen:link xlink:type="extended">\n{arcs}</gen:link>\n</link:linkbase>\n'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{FRAMEWORK}/mod/tst001.xsd", xsd)
        archive.writestr(f"{FRAMEWORK}/mod/tst001-find-prec.xml", preconditions)
        for name, (size, _test) in RULES.items():
            archive.writestr(f"{FRAMEWORK}/val/vr-{name}.xml", "x" * size)
    return path


def write_instance(path: Path) -> Path:
    indicators = "".join(
        f'<find:filingIndicator contextRef="c0">{code}</find:filingIndicator>' for code in FILED
    )
    path.write_text(
        f'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" {XMLNS}'
        ' xmlns:find="http://www.eurofiling.info/xbrl/ext/filing-indicators">\n'
        f'<link:schemaRef xlink:type="simple" xlink:href="{ENTRY_POINT}"/>\n'
        f"<find:fIndicators>{indicators}</find:fIndicators>\n</xbrli:xbrl>\n",
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class Referee:
    """One instance, one package, and a fake worker whose answers a test scripts."""

    instance: Path
    package: Path
    workdir: Path
    script: Path

    def run(self, script: dict[str, Any] | None = None, **options: Any) -> RefereeResult:
        """Run the referee; ``script`` says how the workers behave (see ``FAKE_WORKER``)."""
        scripted = {"verdicts": VERDICTS, "examples": EXAMPLES} | (script or {})
        self.script.write_text(json.dumps(scripted), encoding="utf-8")
        options.setdefault("python", Path(sys.executable))
        options.setdefault("workdir", self.workdir)
        options.setdefault("chunk_mb", CHUNK_MB)
        return run_referee(self.instance, self.package, **options)

    def spec(self, index: int) -> dict[str, Any]:
        """The spec worker ``index`` was launched with."""
        return json.loads((self.workdir / f"chunk{index}.spec.json").read_text(encoding="utf-8"))

    def handed(self, index: int) -> set[str]:
        """The assertion ids the overlay of worker ``index`` names."""
        with zipfile.ZipFile(self.workdir / f"overlay{index}.zip") as archive:
            text = archive.read("overlay/files/tst001-find-prec.xml").decode("utf-8")
        return set(re.findall(r'\.xml#([^"]+)"', text))


def make_referee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Referee:
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKER_SCRIPT", fake)
    return Referee(
        instance=write_instance(tmp_path / "instance.xbrl"),
        package=build_package(tmp_path / "taxonomy.zip"),
        workdir=tmp_path / "work",
        script=tmp_path / "script.json",
    )


def counts(result: RefereeResult) -> dict[str, tuple[int, int]]:
    return {rule: (v.satisfied, v.unsatisfied) for rule, v in result.rules.items()}
