"""
What a ``# NOSONAR`` in rwa-filer may mark: an XBRL identifier, and nothing else.

Why this file exists: SonarCloud's clear-text-protocol rule (python:S5332)
reports every string that starts ``http://`` and does not name one of the hosts
it knows to be a namespace (www.w3.org, schemas.openxmlformats.org, ...). XBRL
names its namespaces, link roles and arcroles that way — ``http://www.xbrl.org/
2003/instance``, ``http://xbrl.org/int/dim/arcrole/all`` — and so does the Bank
of England for its dictionary and its entry points. Those strings are names,
compared character for character and never fetched; ``https://`` would be a
DIFFERENT name, and an instance written with it is refused. There is no fix to
make, so each such line carries ``# NOSONAR``.

A suppression that can silence one rule on one line can silence any rule on it.
This test holds every ``# NOSONAR`` in the package to the one case it is
allowed for: a line whose string literals are ``http://`` identifiers, and that
carries nothing else a rule could object to — no call, no path, no other
string.

References:
- XML Namespaces 1.0 §2.3 (names are compared as strings)
- XBRL 2.1 §3.5; XBRL Dimensions 1.0 §2 (the arcrole names)
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import rwa_filer

SOURCE = Path(rwa_filer.__file__).resolve().parent
SCHEME = "http://"


def _suppressed_lines(path: Path) -> list[int]:
    text = path.read_text(encoding="utf-8")
    return [
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT and "NOSONAR" in token.string
    ]


def _nodes_on(tree: ast.Module, line: int) -> list[ast.AST]:
    return [node for node in ast.walk(tree) if getattr(node, "lineno", None) == line]


def test_every_nosonar_marks_an_identifier_literal_and_nothing_else() -> None:
    # Arrange
    offenders: list[str] = []
    marked = 0

    # Act
    for path in sorted(SOURCE.rglob("*.py")):
        lines = _suppressed_lines(path)
        if not lines:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line in lines:
            marked += 1
            nodes = _nodes_on(tree, line)
            strings = [
                node.value
                for node in nodes
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            ]
            calls = [node for node in nodes if isinstance(node, ast.Call)]
            where = f"{path.relative_to(SOURCE)}:{line}"
            if not strings or any(not value.startswith(SCHEME) for value in strings):
                offenders.append(f"{where}: not an http:// identifier literal")
            elif calls:
                offenders.append(f"{where}: a call shares the line")

    # Assert
    assert offenders == []
    assert marked > 0, "nothing is marked: this test has stopped looking at anything"
