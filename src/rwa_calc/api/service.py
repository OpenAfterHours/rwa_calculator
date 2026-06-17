"""
RWA Calculator API Service.

CreditRiskCalc is the single entry point for RWA calculations:

    from rwa_calc.api import CreditRiskCalc

    response = CreditRiskCalc(
        data_path="/path/to/data",
        framework="CRR",
        reporting_date=date(2024, 12, 31),
    ).calculate()
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rwa_calc.api.errors import create_load_error
from rwa_calc.api.formatters import ResultFormatter
from rwa_calc.api.models import (
    CalculationResponse,
    ValidationRequest,
    ValidationResponse,
)
from rwa_calc.api.results_cache import ResultsCache
from rwa_calc.api.validation import DataPathValidator

# =============================================================================
# CreditRiskCalc
# =============================================================================


class CreditRiskCalc:
    """
    Single entry point for credit risk RWA calculations.

    Encapsulates all parameters and orchestration needed to run a calculation.
    Handles configuration setup, data loading, pipeline execution, and result
    formatting.

    Permission Modes:
        - **standardised**: All exposures use SA. Model permissions ignored.
        - **irb**: Approach routing is driven by ``model_permissions`` input data.
          Each row grants IRB approval for a model_id + exposure_class, optionally
          scoped by geography and book code exclusions. Exposures without a matching
          model permission fall back to SA. If no ``model_permissions`` file exists,
          all exposures fall back to SA with a warning.

    Usage:
        from datetime import date
        from rwa_calc.api import CreditRiskCalc

        response = CreditRiskCalc(
            data_path="/path/to/data",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="irb",
        ).calculate()

        if response.success:
            print(f"Total RWA: {response.summary.total_rwa:,.0f}")
            print(response.collect_results())
    """

    def __init__(
        self,
        data_path: str | Path,
        framework: Literal["CRR", "BASEL_3_1"],
        reporting_date: date,
        permission_mode: Literal["standardised", "irb"] = "standardised",
        data_format: Literal["parquet", "csv"] = "parquet",
        base_currency: str = "GBP",
        eur_gbp_rate: Decimal = Decimal("0.8732"),
        cache_dir: Path | None = None,
        log_level: str = "INFO",
        log_format: Literal["text", "json"] = "text",
        audit_cache_dir: Path | None = None,
        audit_cache_max_runs: int | None = None,
    ) -> None:
        self.data_path = Path(data_path)
        self.framework = framework
        self.reporting_date = reporting_date
        self.permission_mode = permission_mode
        self.data_format = data_format
        self.base_currency = base_currency
        self.eur_gbp_rate = eur_gbp_rate
        self.log_level = log_level
        self.log_format = log_format
        self.audit_cache_dir = audit_cache_dir
        self.audit_cache_max_runs = audit_cache_max_runs

        if cache_dir is None:
            import tempfile

            cache_dir = Path(tempfile.mkdtemp(prefix="rwa_cache_"))

        self._validator = DataPathValidator()
        self._formatter = ResultFormatter()
        self._cache = ResultsCache(cache_dir)

    def calculate(self) -> CalculationResponse:
        """
        Run the RWA calculation.

        Creates pipeline configuration, loads data, runs calculation,
        and formats results.

        Returns:
            CalculationResponse with results or errors
        """
        started_at = datetime.now()

        validation = self._validator.validate(
            ValidationRequest(
                data_path=self.data_path,
                data_format=self.data_format,
                permission_mode=self.permission_mode,
            )
        )
        if not validation.valid:
            return self._formatter.format_error_response(
                errors=validation.errors,
                cache=self._cache,
                framework=self.framework,
                reporting_date=self.reporting_date,
                started_at=started_at,
            )

        try:
            config = self._create_config()
            from rwa_calc.observability import configure_logging

            configure_logging(config.log_level, config.log_format)
            loader = self._create_loader()
            pipeline = self._create_pipeline(loader)

            result_bundle = pipeline.run(config)

            return self._formatter.format_response(
                bundle=result_bundle,
                cache=self._cache,
                framework=self.framework,
                reporting_date=self.reporting_date,
                started_at=started_at,
            )

        except Exception as e:
            error = create_load_error(str(e))
            return self._formatter.format_error_response(
                errors=[error],
                cache=self._cache,
                framework=self.framework,
                reporting_date=self.reporting_date,
                started_at=started_at,
            )

    def validate(self) -> ValidationResponse:
        """
        Validate the data path for calculation readiness.

        Checks that the directory exists and contains required files.

        Returns:
            ValidationResponse with validation results
        """
        return self._validator.validate(
            ValidationRequest(
                data_path=self.data_path,
                data_format=self.data_format,
                permission_mode=self.permission_mode,
            )
        )

    def reconcile(
        self,
        settings: ReconciliationSettings | str | Path,
    ) -> ReconciliationResponse:
        """
        Reconcile this calculator's results against a legacy calculator's output.

        Runs ``self.calculate()`` for our side, loads and maps the legacy output
        per ``settings``, and reconciles them component by component.

        Args:
            settings: A ``ReconciliationSettings`` object, or a path to a TOML
                reconciliation config file.

        Returns:
            ReconciliationResponse with per-component buckets, summaries, a break
            worklist, and a totals tie-out.
        """
        from rwa_calc.analysis.reconciliation import ReconciliationRunner
        from rwa_calc.api.models import ReconciliationResponse
        from rwa_calc.api.reconciliation import (
            LegacyOutputLoader,
            load_reconciliation_config,
        )
        from rwa_calc.api.reconciliation import (
            ReconciliationSettings as _Settings,
        )

        if not isinstance(settings, _Settings):
            settings = load_reconciliation_config(settings)

        calc_response = self.calculate()
        our_results = calc_response.scan_results()
        legacy_results = LegacyOutputLoader(settings).load()

        bundle = ReconciliationRunner().reconcile(our_results, legacy_results, settings.mapping)
        return ReconciliationResponse.from_bundle(
            bundle,
            legacy_file=settings.legacy_file,
            framework=self.framework,
            reporting_date=self.reporting_date,
        )

    def _create_config(self) -> CalculationConfig:
        """Create CalculationConfig from instance parameters."""
        from rwa_calc.contracts.config import CalculationConfig
        from rwa_calc.domain.enums import PermissionMode

        mode = PermissionMode(self.permission_mode)

        if self.framework == "CRR":
            return CalculationConfig.crr(
                reporting_date=self.reporting_date,
                permission_mode=mode,
                base_currency=self.base_currency,
                eur_gbp_rate=self.eur_gbp_rate,
                log_level=self.log_level,
                log_format=self.log_format,
                audit_cache_dir=self.audit_cache_dir,
                audit_cache_max_runs=self.audit_cache_max_runs,
            )
        else:
            return CalculationConfig.basel_3_1(
                reporting_date=self.reporting_date,
                permission_mode=mode,
                base_currency=self.base_currency,
                log_level=self.log_level,
                log_format=self.log_format,
                audit_cache_dir=self.audit_cache_dir,
                audit_cache_max_runs=self.audit_cache_max_runs,
            )

    def _create_loader(self) -> LoaderProtocol:
        """Create data loader based on data format."""
        from rwa_calc.engine.loader import CSVLoader, ParquetLoader

        if self.data_format == "csv":
            return CSVLoader(base_path=self.data_path)
        else:
            return ParquetLoader(base_path=self.data_path)

    def _create_pipeline(self, loader: LoaderProtocol) -> PipelineOrchestrator:
        """Create pipeline orchestrator with loader."""
        from rwa_calc.engine.pipeline import PipelineOrchestrator

        return PipelineOrchestrator(loader=loader)


# =============================================================================
# Type Hints for Internal Use
# =============================================================================


if TYPE_CHECKING:
    from rwa_calc.api.models import ReconciliationResponse
    from rwa_calc.api.reconciliation import ReconciliationSettings
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.protocols import LoaderProtocol
    from rwa_calc.engine.pipeline import PipelineOrchestrator


# =============================================================================
# Module-Level Utilities
# =============================================================================


def get_supported_frameworks() -> list[dict[str, str]]:
    """
    Get list of supported regulatory frameworks.

    Returns:
        List of framework descriptors with id, name, and description
    """
    return [
        {
            "id": "CRR",
            "name": "CRR (Basel 3.0)",
            "description": "Capital Requirements Regulation - effective until Dec 2026",
        },
        {
            "id": "BASEL_3_1",
            "name": "Basel 3.1",
            "description": "PRA PS1/26 UK implementation - effective from Jan 2027",
        },
    ]


def get_default_config(
    framework: Literal["CRR", "BASEL_3_1"],
    reporting_date: date,
) -> dict:
    """
    Get default configuration values for a framework.

    Args:
        framework: Regulatory framework
        reporting_date: As-of date for calculation

    Returns:
        Dictionary of default configuration values
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook import RulepackV0

    if framework == "CRR":
        config = CalculationConfig.crr(reporting_date=reporting_date)
    else:
        config = CalculationConfig.basel_3_1(reporting_date=reporting_date)
    pack = RulepackV0.from_config(config).pack

    return {
        "framework": config.framework.value,
        "reporting_date": config.reporting_date.isoformat(),
        "base_currency": config.base_currency,
        "scaling_factor": str(pack.scalar("irb_scaling_factor")),
        "eur_gbp_rate": str(config.eur_gbp_rate),
        "pd_floors": {
            "corporate": str(pack.formula("pd_floors").params["corporate"]),
            "retail_mortgage": str(pack.formula("pd_floors").params["retail_mortgage"]),
        },
        "supporting_factors_enabled": pack.feature("supporting_factors"),
        "output_floor_enabled": config.output_floor.enabled,
        "output_floor_percentage": str(config.output_floor.get_floor_percentage(reporting_date)),
    }
