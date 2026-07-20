"""Unit tests for REST-layer log-injection defences (CWE-117).

``get_template_bundles`` (src/rwa_calc/api/rest.py) logs ``run_id`` — a
route-parameter string reachable from an HTTP path/query param, so it is
tainted from a static-analysis standpoint regardless of what it happens to
contain at runtime (SonarCloud flags this even when the value is, in
practice, always a server-minted uuid4 hex string). ``_safe_log_token``
strips control characters (CR/LF included) so a caller-supplied id can never
forge a fake log line.
"""

from __future__ import annotations

from rwa_calc.api.rest import _safe_log_token


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
