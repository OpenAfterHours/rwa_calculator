"""
Unit tests for the rulepack reporting metadata (Phase 7 S6).

Pins:
- The ``ReportingTemplateSet`` rule shape (citation required, non-empty
  inventories, frozen).
- ``resolve(regime, date).reporting()`` returns the cited per-regime template
  set: the B31 set adds the PS1/26 templates (OF 02.01 output floor, CMS1/2)
  to the shared CRR inventory; the variant token matches the regime id.
- The content hash covers the entry (deterministic + sensitive to membership),
  so a template-set change is a new pack version.
- ``ReportingContext`` (reporting/metadata.py) carries the resolved template
  set + the out-of-frame side inputs without importing above contracts/.

References:
- CRR Art. 430 (reporting obligation; Reg (EU) 2021/451 Annex I templates)
- PRA PS1/26 (output-floor OF templates + CMS disclosures)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.rulebook.model import Citation, ReportingTemplateSet, ScalarParam
from rwa_calc.rulebook.resolve import _content_hash, resolve

_DATE = date(2025, 12, 31)
_B31_DATE = date(2027, 6, 1)


class TestReportingTemplateSetShape:
    def test_citation_is_required(self) -> None:
        with pytest.raises(TypeError):
            ReportingTemplateSet(  # type: ignore[call-arg]  # ty: ignore[missing-argument]
                name="x", corep=("c07_00",), pillar3=("ov1",), variant="crr"
            )

    def test_empty_inventory_rejected(self) -> None:
        with pytest.raises(ValueError, match="corep"):
            ReportingTemplateSet(
                name="x",
                corep=(),
                pillar3=("ov1",),
                variant="crr",
                citation=Citation("CRR", "430"),
            )

    def test_empty_variant_rejected(self) -> None:
        with pytest.raises(ValueError, match="variant"):
            ReportingTemplateSet(
                name="x",
                corep=("c07_00",),
                pillar3=("ov1",),
                variant="",
                citation=Citation("CRR", "430"),
            )


class TestResolvedReportingAccessor:
    def test_crr_reporting_set(self) -> None:
        reporting = resolve("crr", _DATE).reporting()
        assert reporting.variant == "crr"
        assert "c07_00" in reporting.corep
        assert "c_02_00" in reporting.corep
        assert "ov1" in reporting.pillar3
        # PS1/26-only templates are NOT in the CRR set.
        assert "of_02_01" not in reporting.corep
        assert "cms1" not in reporting.pillar3
        assert "cms2" not in reporting.pillar3

    def test_b31_reporting_set_adds_the_ps126_templates(self) -> None:
        reporting = resolve("b31", _B31_DATE).reporting()
        assert reporting.variant == "b31"
        assert "of_02_01" in reporting.corep
        assert "cms1" in reporting.pillar3
        assert "cms2" in reporting.pillar3

    def test_b31_superset_of_crr_inventory(self) -> None:
        """B31 reporting = the CRR inventory plus the PS1/26 additions."""
        crr = resolve("crr", _DATE).reporting()
        b31 = resolve("b31", _B31_DATE).reporting()
        assert set(crr.corep) <= set(b31.corep)
        assert set(crr.pillar3) <= set(b31.pillar3)

    def test_inventory_matches_the_bundle_fields(self) -> None:
        """Every declared template id is a real field on the template bundles —
        the pack names the code's actual inventory, not an aspirational one."""
        import dataclasses

        from rwa_calc.reporting.corep.generator import COREPTemplateBundle
        from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

        corep_fields = {f.name for f in dataclasses.fields(COREPTemplateBundle)}
        p3_fields = {f.name for f in dataclasses.fields(Pillar3TemplateBundle)}
        b31 = resolve("b31", _B31_DATE).reporting()
        assert set(b31.corep) <= corep_fields
        assert set(b31.pillar3) <= p3_fields


class TestContentHash:
    def test_hash_is_deterministic(self) -> None:
        entry = ReportingTemplateSet(
            name="reporting_template_set",
            corep=("c07_00",),
            pillar3=("ov1",),
            variant="crr",
            citation=Citation("CRR", "430"),
        )
        h1 = _content_hash("crr", _DATE, {"reporting_template_set": entry})
        h2 = _content_hash("crr", _DATE, {"reporting_template_set": entry})
        assert h1 == h2

    def test_hash_is_sensitive_to_membership(self) -> None:
        base = ReportingTemplateSet(
            name="reporting_template_set",
            corep=("c07_00",),
            pillar3=("ov1",),
            variant="crr",
            citation=Citation("CRR", "430"),
        )
        grown = ReportingTemplateSet(
            name="reporting_template_set",
            corep=("c07_00", "of_02_01"),
            pillar3=("ov1",),
            variant="crr",
            citation=Citation("CRR", "430"),
        )
        assert _content_hash("crr", _DATE, {"reporting_template_set": base}) != _content_hash(
            "crr", _DATE, {"reporting_template_set": grown}
        )

    def test_resolved_pack_hashes_differ_between_regimes(self) -> None:
        """Sanity: both regime packs resolve (the new entry survives _value_repr)
        and their content hashes differ."""
        assert resolve("crr", _DATE).id != resolve("b31", _B31_DATE).id

    def test_scalar_entries_unaffected(self) -> None:
        """Control: the new shape does not disturb existing hashing."""
        scalar = ScalarParam(
            name="x", value=Decimal("1.06"), citation=Citation("CRR", "153", "scaling")
        )
        assert _content_hash("crr", _DATE, {"x": scalar}) == _content_hash(
            "crr", _DATE, {"x": scalar}
        )


class TestReportingContext:
    def test_context_carries_the_resolved_set_and_side_inputs(self) -> None:
        from rwa_calc.reporting.metadata import ReportingContext

        reporting = resolve("crr", _DATE).reporting()
        ctx = ReportingContext(template_set=reporting)
        assert ctx.template_set is reporting
        assert ctx.output_floor_summary is None
        assert ctx.previous_period_results is None
        assert ctx.reporting_basis is None
        assert ctx.institution_type is None

    def test_context_is_frozen(self) -> None:
        from rwa_calc.reporting.metadata import ReportingContext

        ctx = ReportingContext(template_set=resolve("crr", _DATE).reporting())
        with pytest.raises(AttributeError):
            ctx.reporting_basis = "consolidated"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
