"""Sign-off: bound to the checksum of what was approved, and checked before upload."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, book, ref, rule
from pack_builders import build_pack, build_return
from rwa_filer.filing import build_filing
from rwa_filer.workflow.signoff import (
    SignOffError,
    read_signoff,
    sign_off,
    signoff_path,
    verify_package,
)
from rwa_filer.xbrl.writer import InstanceOptions

AT = datetime(2027, 4, 20, 9, 30, tzinfo=UTC)
APPROVAL = {"approver": "C. Approver", "role": "Head of Regulatory Reporting", "at": AT}


def package(tmp_path: Path, *, total: float = 100.0, force: bool = False) -> Path:
    """A built package for a T01 return whose total is 100 against parts of 60 + 40."""
    ret = build_return(
        pl.DataFrame(
            {
                "table": [T01] * 3,
                "row": ["0010", "0020", "0030"],
                "column": ["0010"] * 3,
                "value": [total, 60.0, 40.0],
            }
        )
    )
    footing = rule(
        "tst_b0001",
        f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )
    built = build_filing(
        ret,
        tmp_path / "out",
        pack=build_pack(tmp_path / "pack"),
        rulebook=book(footing),
        options=InstanceOptions(monetary_decimals=0),
        always_zip=True,
        allow_rule_breaks=force,
    )
    assert built.manifest_path is not None
    return built.manifest_path


def test_a_sign_off_names_the_approver_and_the_file_approved(tmp_path: Path) -> None:
    # Arrange
    manifest = package(tmp_path)

    # Act
    approval = sign_off(manifest, **APPROVAL, statement=" Reviewed against the ledger. ")
    recorded = json.loads(signoff_path(manifest).read_text())

    # Assert
    assert signoff_path(manifest).name == manifest.name.replace(".manifest.json", ".signoff.json")
    assert recorded["approver"] == "C. Approver"
    assert recorded["at"] == "2027-04-20T09:30:00+00:00"
    assert recorded["instance_sha256"] == json.loads(manifest.read_text())["instance"]["sha256"]
    assert recorded["statement"] == "Reviewed against the ledger."
    assert approval.submittable and not approval.acknowledged_findings
    assert read_signoff(manifest) == approval


def test_a_signed_package_verifies_and_an_unsigned_one_says_so(tmp_path: Path) -> None:
    # Arrange
    manifest = package(tmp_path)

    # Act
    before = verify_package(manifest)
    unsigned_allowed = verify_package(manifest, require_signoff=False)
    sign_off(manifest, **APPROVAL)
    after = verify_package(manifest)

    # Assert
    assert before == ["the package has not been signed off"]
    assert unsigned_allowed == [] and after == []


@pytest.mark.parametrize("suffix", [".xbrl", ".zip"])
def test_a_file_changed_after_sign_off_no_longer_verifies(tmp_path: Path, suffix: str) -> None:
    # Arrange
    manifest = package(tmp_path)
    sign_off(manifest, **APPROVAL)
    target = manifest.with_name(manifest.name.replace(".manifest.json", suffix))

    # Act
    target.write_bytes(target.read_bytes() + b" ")

    # Assert
    (problem,) = verify_package(manifest)
    assert "is not the file the manifest describes" in problem and target.name in problem


def test_a_manifest_changed_after_sign_off_no_longer_verifies(tmp_path: Path) -> None:
    """Editing the recorded validation result after approval is detected."""
    # Arrange
    manifest = package(tmp_path, total=90.0, force=True)
    sign_off(manifest, **APPROVAL, acknowledge_findings=True)
    record = json.loads(manifest.read_text())
    record["validation"]["submittable"] = True

    # Act
    manifest.write_text(json.dumps(record, indent=2) + "\n")

    # Assert
    assert verify_package(manifest) == ["the manifest has changed since the sign-off was given"]


def test_a_rebuilt_instance_is_not_covered_by_the_earlier_sign_off(tmp_path: Path) -> None:
    # Arrange — signed, then built again with a different figure.
    manifest = package(tmp_path)
    sign_off(manifest, **APPROVAL)

    # Act
    package(tmp_path, total=100.4)

    # Assert
    assert "the sign-off was given for a different instance" in verify_package(manifest)


def test_a_package_that_is_not_submittable_is_signed_only_with_acknowledgement(
    tmp_path: Path,
) -> None:
    # Arrange — total 90 against parts of 100: written with the rule break forced.
    manifest = package(tmp_path, total=90.0, force=True)

    # Act / Assert
    with pytest.raises(SignOffError, match="acknowledged explicitly"):
        sign_off(manifest, **APPROVAL)
    assert read_signoff(manifest) is None

    approval = sign_off(manifest, **APPROVAL, acknowledge_findings=True)
    assert (approval.submittable, approval.acknowledged_findings) == (False, True)


def test_a_package_whose_files_do_not_match_is_not_signed(tmp_path: Path) -> None:
    # Arrange
    manifest = package(tmp_path)
    instance = manifest.with_name(manifest.name.replace(".manifest.json", ".xbrl"))
    instance.unlink()

    # Act / Assert
    with pytest.raises(SignOffError, match="does not verify and was not signed"):
        sign_off(manifest, **APPROVAL)


def test_a_sign_off_needs_a_name_and_a_role(tmp_path: Path) -> None:
    with pytest.raises(SignOffError, match="names the approver"):
        sign_off(package(tmp_path), approver="C. Approver", role=" ", at=AT)


def test_what_is_not_a_package_is_reported_not_raised(tmp_path: Path) -> None:
    # Arrange
    junk = tmp_path / "junk.manifest.json"
    junk.write_text("{}")

    # Act / Assert
    assert verify_package(tmp_path / "absent.manifest.json") == [
        "absent.manifest.json does not exist"
    ]
    assert "is not a filing manifest" in verify_package(junk)[0]
