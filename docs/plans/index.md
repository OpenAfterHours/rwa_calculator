# Project Plans

This section contains project planning documents and phase tracking for the RWA Calculator.

## Overview

The project follows a **phased, test-first approach** prioritising CRR (Basel 3.0) implementation before extending to Basel 3.1.

## Documents

- [**Implementation Plan**](implementation-plan.md) - Detailed acceptance test scenarios, contract definitions, and regulatory parameters
- [**Target Architecture & Migration Plan**](target-architecture-migration.md) - Architecture review findings, the rulepack target architecture, and the phased (0-8) strangler migration plan
- [**Engine Defensiveness — Boundary Hardening**](engine-defensiveness-boundary-hardening.md) - Producer-enforced stage-contract investigation; folded into migration Phase 3 (includes the binding KEEP-guard triage)
- [**Single-Lazy-Plan Refactor**](single-lazy-plan-refactor.md) - SUPERSEDED by migration Phase 1; preserves the Polars plan-depth SIGSEGV evidence and the irreducible-barrier finding
- [**UI Output Folder**](ui-output-folder.md) - Let a UI user write calculation outputs to a chosen local folder (server-side write, run-stamped subfolder, network guard); phased TDD plan

## Development Philosophy

The project adheres to these core principles:

1. **Test-Driven Development (TDD)** - Tests are written before implementation
2. **Phased Delivery** - Features are delivered incrementally with clear milestones
3. **Regulatory Accuracy** - All calculations are validated against regulatory specifications
4. **Performance First** - LazyFrame operations and vectorized calculations throughout

