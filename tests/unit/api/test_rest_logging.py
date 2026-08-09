"""Unit tests for REST-layer log-injection defences (CWE-117).

``get_template_bundles`` (src/rwa_calc/api/rest.py) logs ``run_id`` — a
route-parameter string reachable from an HTTP path/query param, so it is
tainted from a static-analysis standpoint regardless of what it happens to
contain at runtime (SonarCloud flags this even when the value is, in
practice, always a server-minted uuid4 hex string).

Two defences stack, and the tests below cover both:

- ``_safe_log_token`` strips control characters (CR/LF included), so no id
  can carry a line break into the log.
- ``_registered_run_key`` goes further and never logs the caller's string at
  all: it returns the matching key held in ``_RUNS`` — a value the server
  minted — and a placeholder for an id that is not registered. Filtering
  characters narrows what an attacker can inject; substituting our own
  literal removes the caller's bytes from the record entirely.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest

from rwa_calc.api.models import CalculationResponse
from rwa_calc.api.rest import (
    _RUNS,
    _UNREGISTERED_RUN_ID,
    _registered_run_key,
    _safe_log_token,
)


def _stub_response() -> CalculationResponse:
    """A registry value that is never read — only the KEY matters to these tests."""
    return cast("CalculationResponse", object())


@pytest.fixture
def registered_run() -> Iterator[str]:
    """Register a run under a server-minted id, then restore the registry."""
    run_id = "5a965687c8b34f1a9e2d0c7b1234abcd"
    _RUNS[run_id] = _stub_response()
    try:
        yield run_id
    finally:
        _RUNS.pop(run_id, None)


class TestRegisteredRunKey:
    """Tests for the ``_registered_run_key`` canonicalising lookup."""

    def test_returns_the_registry_key_for_a_known_run(self, registered_run: str) -> None:
        """A registered id logs unchanged — the value read is the stored key."""
        assert _registered_run_key(registered_run) == registered_run

    def test_content_comes_from_the_registry_not_the_argument(self, registered_run: str) -> None:
        """A near-miss argument does not leak: only an exact key is echoed.

        The point of the helper is that the logged characters are sourced from
        the registry, so an id that merely resembles a registered one produces
        the placeholder rather than any part of itself.
        """
        near_miss = registered_run + "\nWARNING:forged"

        assert _registered_run_key(near_miss) == _UNREGISTERED_RUN_ID

    def test_unregistered_id_is_never_echoed_back(self) -> None:
        """An unknown id is replaced wholesale, so nothing of it reaches a log."""
        assert _registered_run_key("unknown-run-id") == _UNREGISTERED_RUN_ID

    def test_forged_log_line_is_not_echoed_back(self) -> None:
        """An id carrying a CRLF payload is unregistered, so it is discarded."""
        forged = "abcd\nINFO:rwa_calc.api.rest:calculation approved"

        assert _registered_run_key(forged) == _UNREGISTERED_RUN_ID

    def test_registered_key_is_still_control_character_stripped(self) -> None:
        """Defence in depth: even a key registered with a line break logs flat.

        ``register_run_with_id`` accepts a caller-supplied id, so the registry's
        own keys are not unconditionally clean — the sanitiser still applies.
        """
        dirty = "job\nid"
        _RUNS[dirty] = _stub_response()
        try:
            assert _registered_run_key(dirty) == "jobid"
        finally:
            _RUNS.pop(dirty, None)


class TestSafeLogToken:
    """Tests for the ``_safe_log_token`` log-injection sanitiser."""

    def test_strips_newline(self) -> None:
        """A "\\n"-bearing id must not be able to forge a new log line."""
        assert _safe_log_token("abc\ndef") == "abcdef"

    def test_strips_carriage_return(self) -> None:
        assert _safe_log_token("abc\rdef") == "abcdef"

    def test_strips_crlf_pair(self) -> None:
        assert _safe_log_token("abc\r\ndef") == "abcdef"

    def test_strips_other_control_characters(self) -> None:
        """Tabs, ANSI escapes, and other control chars are also non-printable."""
        assert _safe_log_token("abc\tdef\x1bghi") == "abcdefghi"

    def test_preserves_ordinary_printable_content(self) -> None:
        """A normal run_id (uuid4 hex, the common case) round-trips unchanged."""
        run_id = "5a965687c8b34f1a9e2d0c7b1234abcd"
        assert _safe_log_token(run_id) == run_id

    def test_preserves_unicode_printable_characters(self) -> None:
        """Non-ASCII printable text is not conflated with control characters."""
        assert _safe_log_token("café") == "café"

    def test_empty_string_stays_empty(self) -> None:
        assert _safe_log_token("") == ""
