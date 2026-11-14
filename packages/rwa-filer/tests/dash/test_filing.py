"""The write actions through HTTP: draft overrides, build, sign off, verify, download.

The return is the one the CLI workflow tests use: it breaks a published rule as
it comes, and two overrides — zero the exposure, take the adjustment out — make
it fileable. A build from the dashboard must be the build ``rwa-filer build``
makes from the same return and overrides, byte for byte.
"""

from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING

import pytest

from dash_builders import HEADER_ARGS_CLI
from rwa_filer.cli import main
from rwa_filer.dash.filing import parse_value
from rwa_filer.workflow.ledger import EVENT_ADJUSTMENT, EVENT_BUILD, EVENT_SIGNOFF, read_ledger

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn, Workspace

CELL = {"table": "OF07.00.01.01", "sheet": "0008", "key": "", "row": "0010"}
GRID = "/templates?table=OF07.00.01.01&sheet=0008&row=0010&col=0010"
ADJUSTMENTS_CSV = (
    "table,sheet,row,column,value,reason,remove\n"
    "OF07.00.01.01,0008,0010,0010,0,Booked to the wrong class,\n"
    "OF07.00.01.01,0008,0010,0030,,Follows the exposure,yes\n"
)


def _draft(client: TestClient, opened: OpenedReturn, column: str, **fields: str) -> str:
    """Post the cell panel's override form; the page it lands on."""
    base = f"/returns/{opened.return_id}"
    data = {**CELL, "col": column, "data_type": "monetary", "next": base + GRID, **fields}
    return client.post(f"{base}/adjustments", data=data).text


def _make_fileable(client: TestClient, opened: OpenedReturn) -> None:
    _draft(client, opened, "0010", value="0", reason="Booked to the wrong class")
    _draft(client, opened, "0030", remove="yes", reason="Follows the exposure")


def _build(client: TestClient, opened: OpenedReturn, out: Path, **fields: str) -> str:
    data = {"directory": str(out), "author": "A. Preparer", "reproducible": "yes", **fields}
    return client.post(f"/returns/{opened.return_id}/build", data=data).text


# ---------------------------------------------------------------------------
# Drafting overrides
# ---------------------------------------------------------------------------


def test_a_drafted_override_shows_on_the_grid_and_on_the_filing_page(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Act
    grid = _draft(client, broken, "0010", value="0", reason="Booked to the wrong class")
    filing = client.get(f"/returns/{broken.return_id}/filing").text

    # Assert
    cell = re.search(
        r'<td class="([^"]*)"[^>]*><a [^>]*aria-label="Row 0010, column 0010[,"]', grid
    )
    assert cell is not None and "cell-adjusted" in cell.group(1)
    assert "OF07.00.01.01[z0008][r0010][c0010]" in filing
    assert "Booked to the wrong class" in filing


def test_a_value_that_is_not_a_number_is_refused_on_the_grid(
    client: TestClient, workspace: Workspace, broken: OpenedReturn
) -> None:
    # Act
    page = _draft(client, broken, "0010", value="lots", reason="Typo")

    # Assert
    assert 'id="flash"' in page and "is not a number" in unescape(page)
    assert workspace.adjustments(broken.return_id) == ()


def test_removing_a_cell_the_return_does_not_report_is_refused(
    client: TestClient, workspace: Workspace, broken: OpenedReturn
) -> None:
    # Act — column 0040 is empty in this return.
    page = _draft(client, broken, "0040", remove="yes", reason="Not needed")

    # Assert
    assert 'id="flash"' in page
    assert workspace.adjustments(broken.return_id) == ()


def test_a_drafted_override_can_be_withdrawn(
    client: TestClient, workspace: Workspace, broken: OpenedReturn
) -> None:
    # Arrange
    _draft(client, broken, "0010", value="0", reason="Booked to the wrong class")

    # Act
    client.post(f"/returns/{broken.return_id}/adjustments/drop", data={**CELL, "col": "0010"})

    # Assert
    assert workspace.adjustments(broken.return_id) == ()


def test_the_overrides_are_checked_before_anything_is_built(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    _make_fileable(client, broken)

    # Act
    page = client.get(f"/returns/{broken.return_id}/filing?preview=1").text

    # Assert — blocked as opened; nothing blocks with the overrides.
    blocking = len(broken.validation.blocking)
    assert blocking > 0
    assert "With these overrides: nothing blocks submission" in page
    assert f"Blocking findings {blocking} → 0" in page


@pytest.mark.parametrize(
    ("text", "data_type", "expected"),
    [
        ("1,250,000", "monetary", (1_250_000.0, None)),
        ("0.45%", "percentage", (0.0045, None)),
        ("0.0045", "percentage", (0.0045, None)),
        ("eba_GA:GB", "enumeration", (None, "eba_GA:GB")),
    ],
)
def test_a_typed_value_is_read_as_the_cell_states_it(
    text: str, data_type: str, expected: tuple[float | None, str | None]
) -> None:
    # Act
    number, words = parse_value(text, data_type)

    # Assert
    assert words == expected[1]
    if expected[0] is None:
        assert number is None
    else:
        assert number == pytest.approx(expected[0])


def test_an_empty_value_is_refused() -> None:
    with pytest.raises(ValueError, match="Give the value"):
        parse_value("  ", "monetary")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def test_overrides_are_built_only_against_a_name(
    client: TestClient, broken: OpenedReturn, tmp_path: Path
) -> None:
    # Arrange
    _make_fileable(client, broken)

    # Act
    response = client.post(
        f"/returns/{broken.return_id}/build", data={"directory": str(tmp_path / "out")}
    )

    # Assert
    assert response.status_code == 400
    assert "recorded against a name" in response.text
    assert not (tmp_path / "out").exists()


def test_the_dashboard_builds_byte_for_byte_what_the_cli_builds(
    client: TestClient, broken: OpenedReturn, broken_csv: Path, tmp_path: Path
) -> None:
    # Arrange — the same return and overrides, through the CLI.
    (tmp_path / "adjustments.csv").write_text(ADJUSTMENTS_CSV)
    main(
        [
            "build",
            str(broken_csv),
            "--out",
            str(tmp_path / "cli"),
            *HEADER_ARGS_CLI,
            "--no-timestamp",
            "--adjustments",
            str(tmp_path / "adjustments.csv"),
            "--author",
            "A. Preparer",
        ]
    )
    _make_fileable(client, broken)

    # Act
    page = _build(client, broken, tmp_path / "dash")

    # Assert — the same files, and the same instance and manifest bytes.
    assert "Package written" in page
    cli = {path.name: path for path in (tmp_path / "cli").iterdir()}
    dash = {path.name: path for path in (tmp_path / "dash").iterdir()}
    assert sorted(dash) == sorted(cli)
    for name in dash:
        if name.endswith((".xbrl", ".manifest.json")):
            assert dash[name].read_bytes() == cli[name].read_bytes(), name


def test_a_build_records_the_overrides_and_itself_in_the_ledger(
    client: TestClient, broken: OpenedReturn, tmp_path: Path
) -> None:
    # Arrange
    _make_fileable(client, broken)

    # Act
    _build(client, broken, tmp_path / "out")

    # Assert
    (ledger,) = (tmp_path / "out").glob("*.ledger.jsonl")
    entries = read_ledger(ledger)
    assert [entry.event for entry in entries] == [EVENT_ADJUSTMENT, EVENT_BUILD]
    assert {entry.author for entry in entries} == {"A. Preparer"}


def test_a_blocked_return_is_not_written_unless_written_anyway(
    client: TestClient, broken: OpenedReturn, tmp_path: Path
) -> None:
    # Act
    refused = _build(client, broken, tmp_path / "refused")
    forced = _build(client, broken, tmp_path / "forced", force="yes")

    # Assert
    assert "Nothing was written" in refused and not (tmp_path / "refused").exists()
    assert "Package written" in forced and "Written anyway" in forced


# ---------------------------------------------------------------------------
# Sign-off, verification, downloads
# ---------------------------------------------------------------------------


def test_sign_off_then_verify_then_tamper(
    client: TestClient, broken: OpenedReturn, tmp_path: Path
) -> None:
    # Arrange — written despite the break, so sign-off needs the acknowledgement.
    _build(client, broken, tmp_path / "out", force="yes")
    base = f"/returns/{broken.return_id}"
    signing = {"approver": "C. Approver", "role": "Head of Regulatory Reporting"}
    (ledger,) = (tmp_path / "out").glob("*.ledger.jsonl")

    # Act
    refused = client.post(f"{base}/builds/0/signoff", data=signing)
    events_after_refusal = [entry.event for entry in read_ledger(ledger)]
    signed = client.post(f"{base}/builds/0/signoff", data={**signing, "acknowledge": "yes"})
    verified = client.get(f"{base}/filing?verify=1").text
    next((tmp_path / "out").glob("*.xbrl")).write_bytes(b"changed after sign-off")
    tampered = client.get(f"{base}/filing?verify=1").text

    # Assert
    assert refused.status_code == 400 and "acknowledged explicitly" in refused.text
    assert events_after_refusal == [EVENT_BUILD]
    assert "Signed off by" in signed.text
    assert [entry.event for entry in read_ledger(ledger)] == [EVENT_BUILD, EVENT_SIGNOFF]
    assert 'id="verified"' in verified
    assert (
        'id="verify-problems"' in tampered and "is not the file the manifest describes" in tampered
    )


def test_only_a_file_the_build_recorded_is_offered_for_download(
    client: TestClient, broken: OpenedReturn, tmp_path: Path
) -> None:
    # Arrange
    _build(client, broken, tmp_path / "out", force="yes")
    base = f"/returns/{broken.return_id}/builds"

    # Act
    manifest = client.get(f"{base}/0/files/manifest")
    unknown = client.get(f"{base}/0/files/passwd")
    beyond = client.get(f"{base}/7/files/manifest")

    # Assert
    assert manifest.status_code == 200 and manifest.json()["instance"]["facts"] == 2
    assert (unknown.status_code, beyond.status_code) == (404, 404)
