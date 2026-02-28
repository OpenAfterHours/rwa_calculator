# Non-Functional Requirements

## NFR-1: Performance

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-1.1 | Full CRR pipeline at 100K exposures | < 2 seconds | Met (~1.7s) |
| NFR-1.2 | Full CRR pipeline at 1M exposures | < 20 seconds | Met |
| NFR-1.3 | Interactive analysis response time | < 500ms | Met |
| NFR-1.4 | Memory efficiency for 1M+ portfolios | < 4 GB | Met |

## NFR-2: Correctness

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-2.1 | CRR acceptance test pass rate | 100% | 96% (71/74, 3 skip) |
| NFR-2.2 | Hand-calculated expected outputs | Full coverage | Done (38 CRR scenarios) |
| NFR-2.3 | Numerical precision vs hand calcs | < 0.01% error | Met |
| NFR-2.4 | Regulatory article traceability | Full coverage | Done |

## NFR-3: Reliability

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-3.1 | Unit test coverage | > 1,000 tests | Met (1,050) |
| NFR-3.2 | Zero data loss (immutable pipeline) | Guaranteed | Met |
| NFR-3.3 | Graceful invalid data handling | All data quality issues | Met |

## NFR-4: Maintainability

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-4.1 | Full type annotations | 100% | Met |
| NFR-4.2 | Protocol-based interfaces | All 6 stages | Met |
| NFR-4.3 | Ruff linting zero violations | CI-enforced | Met |
| NFR-4.4 | Module-level docstrings | All modules | Met |

## NFR-5: Extensibility

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-5.1 | New approaches via Protocol | Pluggable | Met |
| NFR-5.2 | New framework via config factory | Addable | Met |
| NFR-5.3 | Polars namespace extensions | 8 namespaces | Met |

## NFR-6: Documentation

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-6.1 | MkDocs documentation site | Comprehensive | Met (59 pages) |
| NFR-6.2 | Marimo workbooks | All CRR scenarios | Met |
| NFR-6.3 | Regulatory reference links | All calculations | Met |

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| Regulatory Accuracy | 100% acceptance test pass rate | Automated test suite |
| Performance | < 2s/100K, < 20s/1M | pytest-benchmark |
| Test Coverage | > 1,200 tests | `pytest --co -q` |
| Documentation | All public APIs documented | MkDocs site review |
| Transition Readiness | Full Basel 3.1 before 1 Jan 2027 | B31 acceptance tests |
