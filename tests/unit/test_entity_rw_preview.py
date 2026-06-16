"""
Unit pins — entity-level SA-RW preview expression (``build_entity_rw_expr``).

Pipeline position:
    data/tables/guarantor_rw.py::build_entity_rw_expr — compiled by the
    hierarchy facility-share selection
    (engine/stages/hierarchy/facility_undrawn.py::
    _derive_facility_share_counterparty) to rank candidate counterparties
    by SA-equivalent risk weight.

Key assertion:
    The shared builder closes the branches the old hierarchy preview
    (``_preview_sa_rw_expr``, deleted in this slice) lacked — PSE Table 2A,
    RGLA Table 1B with the GB→20%/else→100% unrated approximation,
    international organisation 0%, named MDB 0% — while keeping the
    pre-existing branches (corporate et al.) value-identical and the
    conservative 1.0 default for unmatched entity types.

    All expected values are hand-derived from the regulatory table
    constants in ``data/tables/crr_risk_weights.py`` — never from running
    the engine.

References:
    - CRR Art. 116(2) Table 2A (PSE_RISK_WEIGHTS_OWN_RATING): PSE CQS 2 = 50%
    - CRR Art. 115(5) (RGLA_DOMESTIC_CURRENCY_RW): unrated GB RGLA → 20%
      (the documented SA-side GB-vs-other approximation)
    - CRR Art. 118 (IO_ZERO_RW): international organisations — 0%
    - CRR Art. 117(2) (MDB_NAMED_ZERO_RW): named MDBs — 0% unconditional
    - CRR Art. 122 Table 5 (CORPORATE_RISK_WEIGHTS): corporate CQS 2 = 50%
      (unchanged-branch regression pin)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.crr_risk_weight_tables import CORPORATE_RISK_WEIGHTS
from rwa_calc.engine.sa.guarantor_rw import build_entity_rw_expr

# ---------------------------------------------------------------------------
# Hand-pinned expectations (from the data tables, NOT from the engine)
# ---------------------------------------------------------------------------

EXPECTED_PSE_CQS2_RW: float = 0.50  # PSE_RISK_WEIGHTS_OWN_RATING[CQS2] — Art. 116(2) Table 2A
EXPECTED_RGLA_UNRATED_GB_RW: float = 0.20  # RGLA_DOMESTIC_CURRENCY_RW — Art. 115(5)
EXPECTED_IO_RW: float = 0.0  # IO_ZERO_RW — Art. 118 unconditional
EXPECTED_NAMED_MDB_RW: float = 0.0  # MDB_NAMED_ZERO_RW — Art. 117(2) unconditional
EXPECTED_UNMATCHED_RW: float = 1.0  # conservative preview default (otherwise-branch)
EXPECTED_UNRATED_NO_COUNTRY_RW: float = 1.0  # PSE_UNRATED_DEFAULT_RW when country unknown
EXPECTED_CORPORATE_CQS2_RW: float = float(CORPORATE_RISK_WEIGHTS[CQS.CQS2])  # 0.50 — Art. 122


def _evaluate_entity_rw(
    entity_type: str,
    cqs: int | None,
    *,
    is_basel_3_1: bool = False,
    country_code: str | None = None,
    pass_country_col: bool = True,
) -> float:
    """Evaluate ``build_entity_rw_expr`` against a single-row frame."""
    frame = pl.LazyFrame(
        {
            "entity_type": [entity_type],
            "cqs": [cqs],
            "country_code": [country_code],
        },
        schema_overrides={"cqs": pl.Int8, "country_code": pl.String},
    )
    expr = build_entity_rw_expr(
        entity_type_col="entity_type",
        cqs_col="cqs",
        is_basel_3_1=is_basel_3_1,
        country_code_col="country_code" if pass_country_col else None,
    )
    return frame.select(expr.alias("preview_rw")).collect()["preview_rw"][0]


class TestEntityRwPreviewNewBranches:
    """Branches the old hierarchy preview lacked (fell to the flat-1.0 default)."""

    def test_pse_cqs2_routes_to_table_2a(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("pse_institution", 2)

        # Assert — Art. 116(2) Table 2A own-rating, not the old flat 1.0.
        assert rw == pytest.approx(EXPECTED_PSE_CQS2_RW)

    def test_rgla_unrated_gb_gets_domestic_currency_treatment(self) -> None:
        # Arrange / Act — unrated (null CQS) GB RGLA with a country column.
        rw = _evaluate_entity_rw("rgla_institution", None, country_code="GB")

        # Assert — GB → 20% domestic-currency treatment (Art. 115(5) approximation).
        assert rw == pytest.approx(EXPECTED_RGLA_UNRATED_GB_RW)

    def test_rgla_unrated_non_gb_gets_conservative_default(self) -> None:
        # Arrange / Act — unrated non-GB RGLA with a country column.
        rw = _evaluate_entity_rw("rgla_institution", None, country_code="DE")

        # Assert — other-country side of the GB-vs-other approximation: 100%.
        assert rw == pytest.approx(EXPECTED_UNRATED_NO_COUNTRY_RW)

    def test_rgla_unrated_without_country_column_falls_back_to_default(self) -> None:
        # Arrange / Act — country_code_col=None (minimal lookups without the column).
        rw = _evaluate_entity_rw("rgla_institution", None, pass_country_col=False)

        # Assert — conservative 100% unrated default applies unconditionally.
        assert rw == pytest.approx(EXPECTED_UNRATED_NO_COUNTRY_RW)

    def test_international_org_zero(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("international_org", None)

        # Assert — Art. 118: 0% unconditional.
        assert rw == pytest.approx(EXPECTED_IO_RW)

    def test_named_mdb_zero(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("mdb_named", None)

        # Assert — Art. 117(2): 0% unconditional (old preview gave Table 2B 50%).
        assert rw == pytest.approx(EXPECTED_NAMED_MDB_RW)

    def test_unmatched_entity_type_keeps_conservative_default(self) -> None:
        # Arrange / Act — an entity type with no SA-class bucket.
        rw = _evaluate_entity_rw("unknown_entity_type", None)

        # Assert — the final otherwise stays the conservative preview 1.0.
        assert rw == pytest.approx(EXPECTED_UNMATCHED_RW)


class TestEntityRwPreviewUnchangedBranches:
    """Regression pin — pre-existing preview branches stay value-identical."""

    def test_corporate_cqs2_crr_matches_corporate_table(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("corporate", 2, is_basel_3_1=False)

        # Assert — Art. 122 Table 5 CQS 2 (read from CORPORATE_RISK_WEIGHTS).
        assert rw == pytest.approx(EXPECTED_CORPORATE_CQS2_RW)
