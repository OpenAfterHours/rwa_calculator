# Testing a Regulatory Engine

*7,450 tests is not the point. Five layers each catching a different failure mode, and a hash-locked oracle suite that prevents the goldens from becoming a mirror of the engine — that is the point.*

Published 2026-07-21. Code references are pinned to commit [`cceaee4`](https://github.com/OpenAfterHours/rwa_calculator/tree/cceaee4).

---

This is post 7 in the series on building this UK Basel 3.1 RWA calculator. Posts 1–6 covered why the calculator exists, how its pipeline is shaped, what the regulation actually does, how the codebase gets written, what the output floor does, and why the wrong-unit bugs from [post 6](2026-07-07-crm-mofs-and-other-edge-case-archaeology.md) are the recurring shape of regulatory implementation defects. This post is about the testing strategy that makes any of that defensible.

The thing I want to convince you of: the headline test count is irrelevant. What matters is that there are five layers in the test pyramid, each one designed to catch a class of failure that the others cannot. Removing any layer leaves a category of bugs invisible. The interesting layer is not the one with the most tests; it is the one with the fewest, and the one that took the most care to design.

*Update (June 2026): the 2026-06 architecture migration removed `data/tables/` — the data-layer-boundary contract now directs regulatory values to the rulebook packs (`src/rwa_calc/rulebook/packs/*.py`, resolved via `rwa_calc.rulebook.resolve`) rather than to `data/tables/`. The remediation string in the quoted code block below is reproduced verbatim from the contract test, whose message text still says `data/tables/` and is itself pending an update.*

## The structural problem with golden-file testing

A regulatory calculator's natural test shape is the golden file: pick a portfolio, run the engine, record the expected RWA per exposure as JSON, assert the engine reproduces it. Acceptance scenarios in this codebase look exactly like that. Two-hundred-and-thirteen JSON entries under `tests/expected_outputs/{crr,basel31}/` pin the output of approximately five hundred scenarios across both frameworks.

Golden-file testing has a structural weakness most engineering teams accept as a fact of life: the expected values are produced *by the engine* and updated alongside the code in the same commits. The test asserts that the engine reproduces a number it produced last week. It catches regressions. It does not catch bugs that were present *when the golden was recorded* — those bugs become the new reference, and any honest re-derivation that disagrees with them now fails the regression suite. A team that resolves the disagreement by editing the JSON to match the engine has just enshrined the bug.

For most software, this trade-off is fine. Behavioural specifications are loose, "correctness" is what the team agrees it is, and once a feature ships any further drift is — by definition — the new specification. For a regulatory calculator, accepting the trade-off means accepting that you cannot tell whether your numbers match the regulation. You can only tell whether they match an earlier version of yourself. This is a bad position to defend in front of an audit team.

The acceptance suite of ~500 scenarios is real, useful, and central to the calculator's daily operation. It catches per-rule regressions, it pins the framework-comparison numbers, and it is what the agent pipeline from [post 4](2026-06-09-building-with-an-agent-swarm.md) writes into when implementing a new rule. But it is not the layer that defends against the golden-file problem. That defence is a separate, smaller suite.

## The pyramid

Five test layers, in order of breadth:

| Layer | Approximate count | Purpose |
|---|---|---|
| Unit | ~5,300 | Per-function assertions, fast. The bulk of the suite. |
| Acceptance | ~1,449 | Scenario-based regression goldens, organised by framework (CRR / Basel 3.1) and topic (SA, IRB, Slotting, CRM, Output Floor). |
| Contracts | ~375 | Protocol compliance, architectural invariants, observability rules. The "the design is still the design" layer. |
| Integration | ~289 | Cross-component flow tests. The "the pipeline still composes" layer. |
| Oracle | ~3 (scaffolded; ~50 planned) | Hand-derivations from the regulation, locked to the engine by a SHA-256 hash. The "the math is still right" layer. |

Plus benchmarks under `tests/benchmarks/` (held out of the default loop by the `--benchmark-disable` addopt; run them explicitly with `-m benchmark`), and an opt-in stress suite under `tests/acceptance/stress/` — file-level `@pytest.mark.stress`, ~60 correctness-at-scale tests excluded from the default run.

The total is roughly 7,450 test functions — about 8,100 cases once parametrised variants are collected. The unit count is the one most likely to make people whistle. It is also the least interesting number on the page. Unit tests catch broken expressions, broken constants, and broken control flow — necessary, but mechanical. They are produced cheaply by the agent pipeline, they run in seconds, and a calculator with 5,300 of them passing has demonstrated almost nothing about its regulatory correctness. The interesting layers are everywhere else.

## The acceptance suite is the broadest, not the truest

The ~500 acceptance scenarios live under `tests/acceptance/{crr,basel31}/` and are anchored on the JSON expected-output files at `tests/expected_outputs/{crr,basel31}/expected_rwa_{crr,basel31}.json`. Each scenario combines a fixture portfolio (assembled from `tests/fixtures/`) with an expected outcome — RWA per exposure, summary by class, summary by approach, sometimes EL or output-floor numbers. Tolerance is 1%, which sounds loose but is in line with how PRA returns are reconciled in practice.

The discipline says: when a new scenario is added, the expected outputs are *hand-derived* from the regulation by the scenario-architect agent, with full intermediate arithmetic and citations. The discipline cannot stop someone — agent or human — from later editing the JSON to make a test pass. There is a code review wall against this and the changelog discipline that ships every meaningful expected-output change with a regulatory citation, but at the level of the test runner the JSON is just a number. A reasonable-looking engine output dropped into the JSON to fix a broken test is indistinguishable from a hand-derived value. Some fraction of the 500 expected outputs has, somewhere in their history, been touched by someone running the engine and copying the result. I cannot tell which fraction. Neither can the test runner.

The right framing of the acceptance suite is therefore: a broad regression set that catches *changes in behaviour* across the whole calculator, with a discipline-level commitment to hand-derivation that the test infrastructure does not enforce. It is necessary. It is not, by itself, sufficient.

## The oracle suite is the load-bearing layer

The fix for the golden-file problem is to break the loop between expected values and engine output. The oracle suite under `tests/oracle/` does this with four files that must change in lockstep:

- `ORACLE_DERIVATIONS.md` — narrative derivations with paragraph-level citations and full arithmetic, written for a regulatory reader.
- `derive.py` — a Python script that re-computes the expected values using only the standard library. Crucially, it does *not* import any `rwa_calc` code.
- `expected_values.json` — generated by `derive.py`. It carries a SHA-256 hash of `ORACLE_DERIVATIONS.md` so that the document and the JSON cannot drift apart.
- `test_oracle.py` — a pytest module that drives the relevant calculator with the oracle's inputs, asserts the engine output matches the oracle within relative error 1e-6, and asserts the doc-hash lock is intact.

Tolerance is 1e-6, six orders of magnitude tighter than the acceptance suite's 1%. Coverage is narrow — three exposures in the current scaffold (one trivial SA, one SA table-lookup, one full IRB formula), with a roadmap of about ten more covering distinct calculation pathways. The point is not to cover the whole calculator. The point is to anchor a small set of values to the regulation in a way that the engine cannot influence.

Take ORC-001 — an SA corporate exposure of £1,000,000 with no external rating. The derivation in `ORACLE_DERIVATIONS.md` cites CRR Art. 122(2) (unrated corporates receive a risk weight of 100%), shows the arithmetic — `RW = 100% (Art. 122(2)); RWA = 1,000,000 × 1.00 = 1,000,000` — and tabulates the expected output. `derive.py`'s `orc_001()` function performs the same calculation in stdlib Python and writes `risk_weight: 1.00, rwa: 1000000.00` into `expected_values.json` along with the SHA-256 of the markdown document. `test_oracle.py` runs the SA calculator's `calculate_branch` directly on a one-row LazyFrame, asserts the engine returns `risk_weight = 1.00 ± 1e-6`, and asserts the recomputed hash of `ORACLE_DERIVATIONS.md` matches the one in the JSON.

The hash is the contract. If someone edits the markdown without re-running `derive.py`, the hash test fails before any value test runs. If someone edits `expected_values.json` to make a value test pass, the hash test fails because the JSON's recorded hash no longer matches the markdown. If someone wants to bypass the hash check by editing the hash field directly, the test infrastructure is — in principle — in their way, and code review is in principle in their way, and the four-file lockstep update protocol is documented in the README.

The README puts it explicitly: *the hash is the contract. If you find yourself wanting to break it, the correct response is almost always "the engine has a bug" — that's the oracle suite doing its job.*

The oracle suite is small because writing it is expensive. ORC-001 is a one-paragraph derivation; a full IRB oracle (PD, LGD, M, R, K, RWA) is several pages of arithmetic with seven or eight regulation citations. The roadmap of ten exposures covers distinct calculation pathways — SA RRE with LTV split, F-IRB with cash collateral, A-IRB corporate at five-year maturity, A-IRB retail mortgage with the 0.15 correlation, slotting strong with maturity ≥ 2.5y, defaulted exposure with EL deduction, equity simple risk-weight, output floor binding case, and PS1/26 SCRA grade. Each one is a several-day exercise. The audit recommended around fifty exposures for full coverage; the calculator currently has three. Closing that gap is a non-trivial roadmap item, and the structural choice — narrow coverage at extreme tolerance — is more useful than the alternative of broad coverage at moderate tolerance.

## The contract tests catch architectural drift

The contract suite under `tests/contracts/` is the architectural fail-safe. Every test in it asserts a *property* of the codebase rather than a *value* it produces.

Six of the contract modules worth calling out (there are around thirty-four files, ~375 functions, in total):

- `test_protocols.py` — every stage implementation in `engine/` satisfies its corresponding `Protocol` in `contracts/protocols.py`. A new `LoaderProtocol` implementation that fails to declare `def load(self) -> RawDataBundle` fails this test.
- `test_bundles.py` — every bundle in `contracts/bundles.py` is `@dataclass(frozen=True)`. A bundle that becomes mutable fails this test.
- `test_config.py` — `CalculationConfig` factories produce internally-consistent configurations. Regulatory scalars no longer live on the config: the IRB scaling factor resolves from the rulepack scalar `irb_scaling_factor`, keyed on regime and reporting date, so the invariant a factory must satisfy is that it pins the right `regime_id` — not that it carries the right scaling factor.
- `test_errors.py` — `CalculationError` codes are unique, framework-tagged, and properly enumerated.
- `test_logging_contract.py` — every stage module under `engine/` declares `logger = logging.getLogger(__name__)`. A module that omits this fails.
- `test_data_layer_boundary.py` — the architectural enforcer this post is most pleased about.

The data-layer-boundary test reuses the check functions from `scripts/arch_check.py` (the same script that runs as a Claude Code pre-commit hook from [post 4](2026-06-09-building-with-an-agent-swarm.md)) and runs them as pytest assertions:

```python
def test_no_regulatory_scalars_in_engine() -> None:
    arch_check = _load_arch_check()
    violations = arch_check.check_no_regulatory_scalars_in_engine(SRC_ROOT)
    assert not violations, (
        "Regulatory scalar literal declared in engine/** — move to "
        "src/rwa_calc/data/tables/ (or add to REGULATORY_SCALAR_ALLOWLIST in "
        "scripts/arch_check.py with justification):\n" + "\n".join(violations)
    )
```

(From [`tests/contracts/test_data_layer_boundary.py:41`](https://github.com/OpenAfterHours/rwa_calculator/tree/cceaee4/tests/contracts/test_data_layer_boundary.py).)

The same check runs in two places — as a pre-commit gate refusing the commit, and as a contract test failing the build. This is deliberate. The pre-commit gate keeps agent-written code from landing on a branch with a violation. The contract test catches violations that *somehow* made it through anyway — typically because someone bypassed the gate during a hot fix, or because a `git rebase` resurrected an older commit with a violation. The two layers cover each other's blind spots, and they share the same allowlist in `arch_check.py` so the rules and their exceptions live in one place.

## TDD as the primary writing motion

The four-stage agent pipeline from post 4 is structured around the test pyramid the same way the calculator is structured around the regulatory pipeline. scenario-architect produces a hand-derivation that is, in effect, a draft acceptance test. fixture-builder writes the parquet rows the test will load. test-writer writes the actual failing pytest, asserting the architect's hand-derived expected outputs. engine-implementer makes it pass. The discipline is that the order is sacrosanct: a calculator change that lands without a corresponding failing-then-passing test was not built by the agent pipeline.

What this means for testing: every acceptance scenario in the codebase has, at the time of its first commit, a citation chain back to a regulatory paragraph and a hand-derived expected output. The test was failing before the engine change was made, which means the engine change was constrained by the test. The test was authored by an agent that did not have permission to edit `src/`, which means the test could not be retrofitted to pass once the engine change was made. The architect prompt forbids inventing scalars from training data, which means every regulatory term in the derivation is sourced from the `basel31` or `crr` skill (which read the actual PDFs). The order is what gives the acceptance suite the most credibility it has — not because the JSON is harder to fake, but because the social and structural process around producing the JSON makes faking it more expensive than doing it right.

The order is also fragile. If I let the agent pipeline degrade — if I let scenario-architect skip the citation step, or if I let test-writer write tests after the implementation, or if I weaken the role boundaries that prevent engine-implementer from editing tests — the acceptance suite degrades to ordinary golden-file testing within a small number of iterations. The discipline is structural: it lives in the agent prompts and the file-ownership boundaries, not in any individual contributor's memory. Removing the structure removes the credibility.

## What you cannot test

Three things the suite does not catch and never will.

**Regulatory interpretation.** The Standardised Approach contains genuine ambiguity in places — the exact scope of the Art. 124E "material dependence" criterion for income-producing real estate, the boundary between Stage 2 GCRA and Stage 2 SCRA under Reg (EU) 183/2014, the conditions under which Art. 138 implicit government support applies. The calculator implements one defensible interpretation of each. Different firms make different choices, and the PRA's eventual supervisory guidance may align with neither. No test catches this; the test catches the chosen interpretation being implemented correctly. A different interpretation requires a different test.

**Portfolios I have not seen.** The acceptance suite covers roughly five hundred scenarios. Real bank portfolios contain millions of exposures with combinations of attributes I have not enumerated. The calculator passes its tests; that means it is correct on the portfolios the tests cover, plus or minus the edge cases the tests do not. The honest claim about how this generalises is statistical, not absolute. Banks running this in earnest will find scenarios that produce surprising numbers. Some will be bugs. Some will be the engine correctly implementing a rule the user's intuition disagreed with. The test suite cannot tell you which is which without a regulatory citation, and the citation has to come from a human reader.

**Model risk management.** PRA SS1/23 governs how firms are expected to validate, document, and govern the models they use for capital purposes. None of that is calculator math. A firm using this calculator inside a regulated capital-reporting process owes the PRA a model-risk-management framework around it — independent validation, ongoing performance monitoring, change control, model inventory, governance committees. The calculator is one input to that framework. The framework is not in scope for the test suite.

The five layers cover what they cover. Acceptance of that limit is a precondition for shipping a regulatory engine responsibly.

## What 7,450 tests are doing

The point is not the count. The point is that each layer is designed against a different failure mode:

- Unit tests catch broken expressions and broken constants.
- Acceptance tests catch *changes in behaviour* across scenarios.
- Contract tests catch architectural drift — the design no longer being the design.
- Integration tests catch composition failures — the pipeline no longer composing correctly.
- The oracle suite catches the engine drifting from the regulation — the goldens no longer being a check on the math.

Removing any layer leaves a class of bugs invisible. Doubling the unit-test count would change almost nothing about the calculator's regulatory correctness. Doubling the oracle suite, on the other hand, would close the largest remaining structural gap.

The architecture from [post 2](2026-05-12-the-pipeline.md) made the test pyramid possible: frozen bundles let unit tests assert against well-typed inputs and outputs, the data/engine split made the contract enforcers writable, error accumulation produced the data-quality channel the integration tests assert against. The agent workflow from [post 4](2026-06-09-building-with-an-agent-swarm.md) made the pyramid sustainable: every new rule produces a hand-derived expected output, a fixture, a failing test, and a minimum-diff implementation, in that order, because the role boundaries make any other order harder than the right one.

The regulation from posts 3, 5, and 6 is what all of it is testing against. The tests are the link between the rule book and the code. They are the documentation an audit team can actually read.

Post 8 closes the series with the honest retrospective: what I got wrong, what the open backlog looks like, and what is on the roadmap before PS1/26 goes live on 1 January 2027.

---

**Read next:** *What I Got Wrong, What's Next* (in progress).

**Further reading:**

- [`tests/oracle/README.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/tests/oracle/README.md) — the oracle suite's update protocol, including the four-file lockstep rule.
- [`tests/oracle/ORACLE_DERIVATIONS.md`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/tests/oracle/ORACLE_DERIVATIONS.md) — the current scaffold's three derivations with full citations.
- [`tests/contracts/test_data_layer_boundary.py`](https://github.com/OpenAfterHours/rwa_calculator/blob/cceaee4/tests/contracts/test_data_layer_boundary.py) — the contract enforcing that regulatory scalars stay out of `engine/**` (their home is the rulebook packs; see the *Update (June 2026)* note above).
- [PRA SS1/23 — Model Risk Management Principles for Banks](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss) — the framework around the calculator that the test suite does not cover.
