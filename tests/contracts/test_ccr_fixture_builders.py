"""Contract tests for CCR trade-level fixture builders (P8.40).

Pins the public surface of the four fixture builder modules:
    tests/fixtures/ccr/trade_builder.py
    tests/fixtures/ccr/netting_set_builder.py
    tests/fixtures/ccr/margin_builder.py
    tests/fixtures/ccr/golden_ccr_a1.py

Also verifies:
    - golden_ccr_a1.save_golden_fixtures() writes the four expected parquets
    - the canonical parquets in tests/fixtures/ccr/ match the CCR-A1 scenario
    - the golden parquets round-trip through ParquetLoader into RawCCRBundle
    - the legacy generate_p8_5_minimal shim exports the expected names

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement)
    - CRR Art. 275(1) (RC = max(V - C, 0) — V = mtm_value, at-par gives V=0)
    - CRR Art. 279a(1) (supervisory delta = 1.0 for non-option trades)
    - CRR Art. 285(2)(b) (10-day minimum MPOR for standard margined netting sets)
    - CRR Art. 295-297 (netting agreement recognition — conservative default False)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Canonical fixture parquet paths (test 8 reads from here — NOT regenerated).
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ccr"

_TRADES_PARQUET = _FIXTURE_DIR / "trades.parquet"
_NETTING_SETS_PARQUET = _FIXTURE_DIR / "netting_sets.parquet"
_MARGIN_AGREEMENTS_PARQUET = _FIXTURE_DIR / "margin_agreements.parquet"
_CCR_COLLATERAL_PARQUET = _FIXTURE_DIR / "ccr_collateral.parquet"


# ===========================================================================
# 1. Trade dataclass round-trip through Polars DataFrame
# ===========================================================================


def test_trade_dataclass_to_dict_round_trips_through_pl_dataframe() -> None:
    """make_trade(CCR-A1 defaults) -> create_trades([t]) -> 1 row, schema matches TRADE_SCHEMA."""
    # Arrange
    from tests.fixtures.ccr.trade_builder import create_trades, make_trade

    from rwa_calc.data.column_spec import dtypes_of
    from rwa_calc.data.schemas import TRADE_SCHEMA

    expected_schema = dtypes_of(TRADE_SCHEMA)

    # Act
    t = make_trade()
    df = create_trades([t])

    # Assert — row count
    assert df.height == 1, f"Expected 1 row, got {df.height}"

    # Assert — schema matches TRADE_SCHEMA dtypes
    for col_name, expected_dtype in expected_schema.items():
        assert col_name in df.columns, (
            f"Column '{col_name}' missing from trades DataFrame. "
            f"Expected columns: {list(expected_schema.keys())}"
        )
        actual_dtype = df.schema[col_name]
        assert actual_dtype == expected_dtype, (
            f"Column '{col_name}': expected dtype {expected_dtype}, got {actual_dtype}"
        )


# ===========================================================================
# 2. NettingSet dataclass round-trip through Polars DataFrame
# ===========================================================================


def test_netting_set_dataclass_to_dict_round_trips_through_pl_dataframe() -> None:
    """make_netting_set(CCR-A1 defaults) -> create_netting_sets([ns]) -> 1 row, schema matches."""
    # Arrange
    from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set

    from rwa_calc.data.column_spec import dtypes_of
    from rwa_calc.data.schemas import NETTING_SET_SCHEMA

    expected_schema = dtypes_of(NETTING_SET_SCHEMA)

    # Act
    ns = make_netting_set()
    df = create_netting_sets([ns])

    # Assert — row count
    assert df.height == 1, f"Expected 1 row, got {df.height}"

    # Assert — schema matches NETTING_SET_SCHEMA dtypes
    for col_name, expected_dtype in expected_schema.items():
        assert col_name in df.columns, f"Column '{col_name}' missing from netting_sets DataFrame."
        actual_dtype = df.schema[col_name]
        assert actual_dtype == expected_dtype, (
            f"Column '{col_name}': expected dtype {expected_dtype}, got {actual_dtype}"
        )


# ===========================================================================
# 3. Margin dataclass round-trip through Polars DataFrame
# ===========================================================================


def test_margin_dataclass_to_dict_round_trips_through_pl_dataframe() -> None:
    """make_margin(CCR-A1 defaults) -> create_margin_agreements([m]) -> 1 row, schema matches."""
    # Arrange
    from tests.fixtures.ccr.margin_builder import create_margin_agreements, make_margin

    from rwa_calc.data.column_spec import dtypes_of
    from rwa_calc.data.schemas import MARGIN_AGREEMENT_SCHEMA

    expected_schema = dtypes_of(MARGIN_AGREEMENT_SCHEMA)

    # Act
    m = make_margin()
    df = create_margin_agreements([m])

    # Assert — row count
    assert df.height == 1, f"Expected 1 row, got {df.height}"

    # Assert — schema matches MARGIN_AGREEMENT_SCHEMA dtypes
    for col_name, expected_dtype in expected_schema.items():
        assert col_name in df.columns, (
            f"Column '{col_name}' missing from margin_agreements DataFrame."
        )
        actual_dtype = df.schema[col_name]
        assert actual_dtype == expected_dtype, (
            f"Column '{col_name}': expected dtype {expected_dtype}, got {actual_dtype}"
        )


# ===========================================================================
# 4. make_trade() optional field defaults
# ===========================================================================


def test_make_trade_defaults_match_trade_schema_defaults() -> None:
    """make_trade() must produce delta=1.0, mtm_value=0.0, is_long_settlement=False."""
    # Arrange
    from datetime import date

    from tests.fixtures.ccr.trade_builder import make_trade

    # Act — supply only required fields so that all optional fields use defaults
    t = make_trade(
        trade_id="T_TEST",
        netting_set_id="NS_TEST",
        asset_class="interest_rate",
        transaction_type="derivative",
        notional=1_000_000.0,
        currency="GBP",
        maturity_date=date(2030, 1, 1),
        start_date=date(2025, 1, 1),
    )

    # Assert — CRR Art. 279a(1): delta = 1.0 for non-option directional trades
    assert t.delta == 1.0, f"make_trade().delta expected 1.0, got {t.delta!r}"

    # Assert — CRR Art. 275: V = mtm_value, at-par trade => 0.0
    assert t.mtm_value == 0.0, f"make_trade().mtm_value expected 0.0, got {t.mtm_value!r}"

    # Assert — is_long_settlement defaults to False (SA-CCR standard settlement)
    assert t.is_long_settlement is False, (
        f"make_trade().is_long_settlement expected False, got {t.is_long_settlement!r}"
    )


# ===========================================================================
# 5. NettingSet dataclass conservative defaults per Art. 295
# ===========================================================================


def test_make_netting_set_defaults_conservative_per_art_295() -> None:
    """NettingSet dataclass defaults: is_legally_enforceable=False, is_margined=False.

    These are the dataclass-level conservative defaults (CRR Art. 295 requires
    positive confirmation of legal enforceability before netting is recognised).
    The make_netting_set() factory overrides these with CCR-A1 scenario values
    (enforceable=True, since NS_001 satisfies Art. 295).
    """
    # Arrange
    from tests.fixtures.ccr.netting_set_builder import NettingSet

    # Act — construct with required fields only; optional fields take dataclass defaults
    ns = NettingSet(netting_set_id="NS_TEST", counterparty_reference="CP_TEST")

    # Assert — CRR Art. 295: conservative default until enforceability is confirmed
    assert ns.is_legally_enforceable is False, (
        f"NettingSet.is_legally_enforceable dataclass default expected False "
        f"(conservative per Art. 295), got {ns.is_legally_enforceable!r}"
    )

    # Assert — unmargined by default
    assert ns.is_margined is False, (
        f"NettingSet.is_margined dataclass default expected False, got {ns.is_margined!r}"
    )


# ===========================================================================
# 6. make_margin() defaults: mpor_days = 10 per Art. 285(2)(b)
# ===========================================================================


def test_make_margin_defaults_mpor_10_per_art_285_2_b() -> None:
    """make_margin().mpor_days must default to 10 per CRR Art. 285(2)(b)."""
    # Arrange
    from tests.fixtures.ccr.margin_builder import make_margin

    # Act
    m = make_margin(margin_agreement_id="MA_TEST", counterparty_reference="CP_TEST")

    # Assert — CRR Art. 285(2)(b): 10-day minimum MPOR for standard margined netting sets
    assert m.mpor_days == 10, (
        f"make_margin().mpor_days expected 10 (regulatory minimum per Art. 285(2)(b)), "
        f"got {m.mpor_days!r}"
    )


# ===========================================================================
# 7. save_golden_fixtures() emits four parquet files with expected row counts
# ===========================================================================


def test_golden_ccr_a1_emits_four_parquet_files_with_expected_row_counts(
    tmp_path: Path,
) -> None:
    """save_golden_fixtures(tmp_path) must write 4 parquets: 1/1/0/0 row counts."""
    # Arrange
    from tests.fixtures.ccr.golden_ccr_a1 import save_golden_fixtures

    # Act
    saved = save_golden_fixtures(tmp_path)

    # Assert — trades: 1 row (T_001)
    trades_df = pl.read_parquet(saved["trades"])
    assert trades_df.height == 1, (
        f"trades.parquet must contain 1 row (T_001), got {trades_df.height}"
    )

    # Assert — netting_sets: 1 row (NS_001)
    ns_df = pl.read_parquet(saved["netting_sets"])
    assert ns_df.height == 1, (
        f"netting_sets.parquet must contain 1 row (NS_001), got {ns_df.height}"
    )

    # Assert — margin_agreements: 0 rows (CCR-A1: no CSA)
    ma_df = pl.read_parquet(saved["margin_agreements"])
    assert ma_df.height == 0, (
        f"margin_agreements.parquet must contain 0 rows (CCR-A1: unmargined), got {ma_df.height}"
    )

    # Assert — ccr_collateral: 0 rows (CCR-A1: no collateral)
    coll_df = pl.read_parquet(saved["ccr_collateral"])
    assert coll_df.height == 0, (
        f"ccr_collateral.parquet must contain 0 rows (CCR-A1: no collateral), got {coll_df.height}"
    )


# ===========================================================================
# 8. Canonical parquet fixture values match CCR-A1 scenario constants
# ===========================================================================


def test_golden_ccr_a1_trade_row_has_v_equal_zero_mtm_and_unmargined_netting_set() -> None:
    """Canonical tests/fixtures/ccr/ parquets encode the CCR-A1 scenario correctly."""
    # Arrange — load from the canonical fixture dir (NOT regenerated)
    assert _TRADES_PARQUET.exists(), (
        f"Canonical trades fixture not found: {_TRADES_PARQUET}. "
        "Run: uv run python tests/fixtures/generate_all.py"
    )
    assert _NETTING_SETS_PARQUET.exists(), (
        f"Canonical netting_sets fixture not found: {_NETTING_SETS_PARQUET}."
    )

    # Act
    trades = pl.read_parquet(_TRADES_PARQUET)
    netting_sets = pl.read_parquet(_NETTING_SETS_PARQUET)

    # Assert — trade fields match CCR-A1 scenario (CRR Art. 275: V=0.0 => at-par swap)
    assert trades["mtm_value"][0] == 0.0, (
        f"trades['mtm_value'][0] expected 0.0 (at-par swap, Art. 275 V=0), "
        f"got {trades['mtm_value'][0]!r}"
    )
    assert trades["notional"][0] == 100_000_000.0, (
        f"trades['notional'][0] expected 100_000_000.0 (GBP 100m), got {trades['notional'][0]!r}"
    )
    assert trades["currency"][0] == "GBP", (
        f"trades['currency'][0] expected 'GBP', got {trades['currency'][0]!r}"
    )
    assert trades["asset_class"][0] == "interest_rate", (
        f"trades['asset_class'][0] expected 'interest_rate', got {trades['asset_class'][0]!r}"
    )

    # Assert — netting set fields match CCR-A1 scenario (unmargined, Art. 295 enforceable)
    assert netting_sets["is_margined"][0] is False, (
        f"netting_sets['is_margined'][0] expected False (unmargined CCR-A1), "
        f"got {netting_sets['is_margined'][0]!r}"
    )
    assert netting_sets["is_legally_enforceable"][0] is True, (
        f"netting_sets['is_legally_enforceable'][0] expected True (Art. 295 condition met), "
        f"got {netting_sets['is_legally_enforceable'][0]!r}"
    )


# ===========================================================================
# 9. Loader round-trip: save_golden_fixtures -> ParquetLoader -> RawCCRBundle
# ===========================================================================


def _write_minimal_crr_dataset(base_dir: Path) -> object:
    """Write minimum mandatory CRR files; return a DataSourceConfig.

    Mirrors the helper in tests/integration/test_ccr_loader.py so this
    test is self-contained without importing from that file.
    """
    from rwa_calc.engine.loader import DataSourceConfig

    cp_df = pl.DataFrame(
        {
            "counterparty_reference": ["CP_001"],
            "counterparty_name": ["Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [100_000_000.0],
            "total_assets": [500_000_000.0],
            "default_status": [False],
        }
    )
    fac_df = pl.DataFrame({"facility_reference": ["FAC_001"], "counterparty_reference": ["CP_001"]})
    loan_df = pl.DataFrame(
        {
            "loan_reference": ["LN_001"],
            "counterparty_reference": ["CP_001"],
            "drawn_amount": [0.0],
        }
    )
    fm_df = pl.DataFrame({"parent_facility_reference": ["FAC_001"], "child_reference": ["LN_001"]})
    lm_df = pl.DataFrame({"member_counterparty_reference": pl.Series([], dtype=pl.String)})

    base_dir.mkdir(parents=True, exist_ok=True)
    cp_path = base_dir / "counterparties.parquet"
    fac_path = base_dir / "facilities.parquet"
    loan_path = base_dir / "loans.parquet"
    fm_path = base_dir / "facility_mappings.parquet"
    lm_path = base_dir / "lending_mappings.parquet"

    cp_df.write_parquet(cp_path)
    fac_df.write_parquet(fac_path)
    loan_df.write_parquet(loan_path)
    fm_df.write_parquet(fm_path)
    lm_df.write_parquet(lm_path)

    return DataSourceConfig(
        counterparties_file=cp_path,
        facilities_file=fac_path,
        loans_file=loan_path,
        facility_mappings_file=fm_path,
        lending_mappings_file=lm_path,
    )


def test_golden_ccr_a1_round_trips_through_raw_ccr_bundle_via_loader(
    tmp_path: Path,
) -> None:
    """save_golden_fixtures -> ParquetLoader.load() -> bundle.ccr is RawCCRBundle with 1/1/0/0 rows."""
    # Arrange
    import dataclasses as _dc

    from tests.fixtures.ccr.golden_ccr_a1 import save_golden_fixtures

    from rwa_calc.contracts.bundles import RawCCRBundle
    from rwa_calc.engine.loader import ParquetLoader

    # Write CCR parquets into a subdirectory
    ccr_dir = tmp_path / "ccr"
    saved = save_golden_fixtures(ccr_dir)

    # Build base CRR dataset config
    config = _write_minimal_crr_dataset(tmp_path / "crr")

    # Verify DataSourceConfig has the four CCR fields (guard so failure is AssertionError)
    existing_fields = {f.name for f in _dc.fields(config)}  # type: ignore[arg-type]
    for field_name in (
        "ccr_trades_file",
        "ccr_netting_sets_file",
        "ccr_margin_agreements_file",
        "ccr_collateral_file",
    ):
        assert field_name in existing_fields, (
            f"DataSourceConfig has no field '{field_name}'. "
            f"Add the four ccr_* fields to DataSourceConfig in "
            f"src/rwa_calc/engine/loader.py (P8.5)."
        )

    config = _dc.replace(  # type: ignore[call-overload]
        config,
        ccr_trades_file=saved["trades"],
        ccr_netting_sets_file=saved["netting_sets"],
        ccr_margin_agreements_file=saved["margin_agreements"],
        ccr_collateral_file=saved["ccr_collateral"],
    )

    # Act
    loader = ParquetLoader(tmp_path / "crr", config=config)
    bundle = loader.load()

    # Assert — ccr is not None
    assert bundle.ccr is not None, (
        "bundle.ccr must not be None when all four CCR files are configured."
    )
    assert isinstance(bundle.ccr, RawCCRBundle), (
        f"bundle.ccr must be a RawCCRBundle instance, got {type(bundle.ccr).__name__}"
    )

    # Assert — trade count = 1 (T_001)
    assert bundle.ccr.trades.trades.collect().height == 1, (
        f"bundle.ccr.trades must contain 1 row (T_001), "
        f"got {bundle.ccr.trades.trades.collect().height}"
    )

    # Assert — netting set count = 1 (NS_001)
    assert bundle.ccr.netting_sets.netting_sets.collect().height == 1, (
        f"bundle.ccr.netting_sets must contain 1 row (NS_001), "
        f"got {bundle.ccr.netting_sets.netting_sets.collect().height}"
    )

    # Assert — margin agreements = 0 (CCR-A1: unmargined)
    assert bundle.ccr.margin_agreements.margin_agreements.collect().height == 0, (
        "bundle.ccr.margin_agreements must contain 0 rows (CCR-A1: no CSA)"
    )

    # Assert — CCR collateral = 0 (CCR-A1: no collateral)
    assert bundle.ccr.ccr_collateral.ccr_collateral.collect().height == 0, (
        "bundle.ccr.ccr_collateral must contain 0 rows (CCR-A1: no collateral)"
    )


# ===========================================================================
# 10. Legacy generate_p8_5_minimal shim exports expected names
# ===========================================================================


# ===========================================================================
# 11. make_fx_trade() golden defaults match CCR-A2 scenario (Art. 279b(1)(b))
# ===========================================================================


def test_make_fx_trade_defaults_match_ccr_a2_scenario() -> None:
    """make_fx_trade() must produce the CCR-A2 1y USD/GBP outright-forward defaults.

    CCR-A2 inputs (CRR Art. 279b(1)(b) FX adjusted-notional acceptance):
        asset_class="fx", currency="USD"/notional=100m (leg1 = bought currency),
        currency_leg2="GBP"/notional_leg2=80m (leg2 = sold currency),
        1-year forward, at-par (MtM=0), delta=1.0.
    """
    # Arrange + Act
    from tests.fixtures.ccr.trade_builder import make_fx_trade

    t = make_fx_trade()

    # Assert — asset_class is "fx" so the engine routes to the FX branch
    assert t.asset_class == "fx", (
        f"make_fx_trade().asset_class expected 'fx', got {t.asset_class!r}"
    )

    # Assert — leg1 = bought currency (USD 100m)
    assert t.currency == "USD", f"leg1 currency expected 'USD', got {t.currency!r}"
    assert t.notional == 100_000_000.0, f"leg1 notional expected 100m, got {t.notional!r}"

    # Assert — leg2 = sold currency (GBP 80m). Forward rate = 100m USD / 80m GBP = 1.25.
    assert t.currency_leg2 == "GBP", f"leg2 currency expected 'GBP', got {t.currency_leg2!r}"
    assert t.notional_leg2 == 80_000_000.0, f"leg2 notional expected 80m, got {t.notional_leg2!r}"

    # Assert — at-par delta=1.0, MtM=0 (RC=0 expected at reporting_date=start_date)
    assert t.delta == 1.0, f"delta expected 1.0, got {t.delta!r}"
    assert t.mtm_value == 0.0, f"mtm_value expected 0.0, got {t.mtm_value!r}"


def test_make_fx_trade_round_trips_through_pl_dataframe() -> None:
    """make_fx_trade() output must serialise into TRADE_SCHEMA via create_trades()."""
    # Arrange
    from tests.fixtures.ccr.trade_builder import create_trades, make_fx_trade

    from rwa_calc.data.column_spec import dtypes_of
    from rwa_calc.data.schemas import TRADE_SCHEMA

    expected_schema = dtypes_of(TRADE_SCHEMA)

    # Act
    df = create_trades([make_fx_trade()])

    # Assert — single row, schema matches, leg2 columns populated
    assert df.height == 1, f"Expected 1 row, got {df.height}"
    for col_name, expected_dtype in expected_schema.items():
        assert col_name in df.columns, f"Column '{col_name}' missing from FX-trade DataFrame."
        assert df.schema[col_name] == expected_dtype, (
            f"Column '{col_name}': expected dtype {expected_dtype}, got {df.schema[col_name]}"
        )

    # Assert — leg2 columns populated with the CCR-A2 values
    assert df["notional_leg2"][0] == 80_000_000.0
    assert df["currency_leg2"][0] == "GBP"


def test_make_trade_ir_leaves_leg2_columns_null() -> None:
    """make_trade() (IR default) must emit null leg2 fields so non-FX trades stay clean.

    The validator at the FX adjusted-notional consumption point (P8.9) requires
    leg2 fields populated only when ``asset_class == "fx"``; for IR rows they
    must be null so the schema accommodates a mixed trade book.
    """
    # Arrange + Act
    from tests.fixtures.ccr.trade_builder import create_trades, make_trade

    df = create_trades([make_trade()])

    # Assert — IR row has null leg2 fields
    assert df["notional_leg2"][0] is None, (
        f"IR trade must have null notional_leg2, got {df['notional_leg2'][0]!r}"
    )
    assert df["currency_leg2"][0] is None, (
        f"IR trade must have null currency_leg2, got {df['currency_leg2'][0]!r}"
    )


# ===========================================================================
# 12. Legacy generate_p8_5_minimal shim exports expected names
# ===========================================================================


def test_legacy_p8_5_module_constants_still_exported() -> None:
    """generate_p8_5_minimal must export TRADE_ID, NETTING_SET_ID, COUNTERPARTY_REF,
    and save_p85_minimal_fixtures cleanly — protects test_ccr_loader.py's shim layer."""
    # Arrange + Act — all four names must import without error
    from tests.fixtures.ccr.generate_p8_5_minimal import (  # noqa: F401
        COUNTERPARTY_REF,
        NETTING_SET_ID,
        TRADE_ID,
        save_p85_minimal_fixtures,
    )

    # Assert — constants are non-empty strings
    assert isinstance(TRADE_ID, str) and TRADE_ID, (
        f"TRADE_ID must be a non-empty string, got {TRADE_ID!r}"
    )
    assert isinstance(NETTING_SET_ID, str) and NETTING_SET_ID, (
        f"NETTING_SET_ID must be a non-empty string, got {NETTING_SET_ID!r}"
    )
    assert isinstance(COUNTERPARTY_REF, str) and COUNTERPARTY_REF, (
        f"COUNTERPARTY_REF must be a non-empty string, got {COUNTERPARTY_REF!r}"
    )

    # Assert — save_p85_minimal_fixtures is callable
    assert callable(save_p85_minimal_fixtures), (
        f"save_p85_minimal_fixtures must be callable, got {type(save_p85_minimal_fixtures)!r}"
    )
