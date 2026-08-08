# Numeric Change-Impact Report

`scripts/impact_report.py` answers one question on every change: **what moved,
and who accounted for it?**

Numbers move in this project and, until now, nothing required anyone to explain
why. A re-key once dropped ~2.0m of RWEA out of the COREP C 02.00 breakdown rows
while the parent total kept counting it; a phantom map key left C 02.00 row 0310
permanently zero; `high_risk` legs were missing from Pillar 3 CR4/CR5 breakdown
rows that their Total row still summed. Every one of those was a moved or wrong
number that no gate asked a human about.

The report is a **regression** gate, not a correctness gate — it compares the
system against its own previous output. Movement is not a failure. **Unexplained**
movement is.

## What it compares

Four grains, all captured from one set of runs:

| Grain | Key | What it catches |
| --- | --- | --- |
| `total` | `regime｜portfolio｜metric` | headline RWA / EAD / leg-count movement; `*ALL*` is the per-regime roll-up |
| `class` | `regime｜portfolio｜approach｜exposure_class` | *where* the movement landed, on the sealed post-substitution basis |
| `cell` | `regime｜portfolio｜template｜sheet｜row｜col` | every generated COREP / Pillar 3 cell — the grain at which reporting defects actually appear |
| `error` | `regime｜portfolio｜category｜severity｜code` | data-quality error histogram |

Each coordinate gets one of five statuses:

- **disappeared** — the coordinate is not produced at all any more;
- **nulled** — the cell still exists but stopped carrying a figure;
- **appeared** / **populated** — the mirror images;
- **changed** — both sides carry a figure and they differ beyond tolerance.

The first two are reported **first and separately**, because absence is this
project's dominant production escape class. A naive value diff hides a vanished
cell as "not in the comparison set" and reports nothing at all.

Floats compare to `rtol=1e-9, atol=1e-6` — the established project tolerance.
Polars' multi-threaded Float64 group-by summation is not deterministic across
processes, so an exact comparison would report movement that no change caused.

## The run matrix

The portfolios are imported from
`tests/acceptance/reporting/test_supervisory_validations.py::RUNS` rather than
restated here, so a portfolio added for the supervisory gate is covered by the
impact report automatically. Today that is six portfolios x two regimes:

`rich`, `off-bs`, `ccr`, `sa-classes`, `irb-classes`, `crm-substitution`
under CRR and Basel 3.1 — **twelve** template-generating runs, plus six
prior-period pipeline runs so the C 08.04 / CR8 RWEA-flow rows carry real
opening balances instead of being null by construction.

Default cost, measured: **~46s wall, ~354 MB peak RSS**, single process.
Coverage: **128,127 template cells** (82,147 under Basel 3.1, 45,980 under CRR),
72 (approach, class) buckets, 56 totals, 11 error-histogram entries.

`--portfolios` and `--regimes` narrow the matrix for a quick local loop. Do not
narrow it in CI: a silently reduced matrix does not make the dropped coordinates
pass, it makes them invisible.

## Capture and compare

```bash
# Snapshot the current tree.
uv run python scripts/impact_report.py capture --out .impact/base

# ... make your change ...

# Re-run the tree and diff it against the snapshot.
uv run python scripts/impact_report.py compare --baseline .impact/base \
    --markdown .impact/impact.md --json .impact/impact.json
```

`compare` re-runs the pipeline by default. To diff two already-captured
snapshots — the usual CI shape, one capture per checkout — pass `--current`:

```bash
uv run python scripts/impact_report.py compare \
    --baseline .impact/base --current .impact/head --stale-check
```

Useful flags: `--top N` (movers listed per section, default 25), `--max-detail N`
(unexplained movements detailed per grain in the JSON, default 2000),
`--stale-check` (see below).

Snapshot directories hold one parquet per grain plus `meta.json`. Parquet is
git-ignored project-wide, so the bulk of a stray snapshot cannot be committed by
accident — but `meta.json` still can, so add `.impact/` to `.gitignore` if you
use that path. Every operator-supplied path is confined to the repository's
parent directory, so a snapshot lives inside the repo or in a sibling baseline
directory and a faulty argument cannot write elsewhere.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | nothing moved, or every movement is allowlisted |
| 1 | **unexplained movement** — the blocking case |
| 2 | usage error, missing baseline, or a malformed allowlist entry |
| 3 | stale allowlist entries (only with `--stale-check`, and only when there is no unexplained movement) |

## The allowlist — a register of recorded decisions

`scripts/impact_allowlist.json` is where a movement gets accounted for. It is
**not a waiver list**: an entry is a written statement that a number moved, why,
and that the new figure is right. Same convention as the reporting goldens'
preserve-or-fix decisions and the supervisory validation register.

```json
{
  "grain": "cell",
  "key": "b31|rich|c07_00|corporate|0010|0110",
  "reason": "PS1/26 Table A1 raises the undrawn conversion factor for this bucket from 20% to 40%, so the exposure value rises by 20% of the undrawn amount; hand-checked against the article and covered by tests/acceptance/basel31/test_p1_111_ccf.py.",
  "accepted_under": "PR #999"
}
```

Rules the tool enforces:

- `grain` must be one of the four; `key` must be non-empty.
- `reason` is **mandatory**, at least 20 characters and 4 words, and must not be
  a placeholder (`TODO`, `n/a`, `refactor`, `unclassified`, …). An entry with no
  written reason is not an entry, and a malformed one fails the run with exit 2
  rather than being skipped — a broken register must never silently pass
  movement.
- `accepted_under` must name the commit or PR the decision was taken under.

A key containing `*`, `?` or `[` is matched with `fnmatch`. Wildcards are
allowed because a legitimate change really can move thousands of cells, but they
widen silently, so the JSON report prints the **matched count** for every entry —
a wildcard's blast radius is always visible. Prefer the narrowest pattern that
covers the change.

### Pruning: `--stale-check`

An allowlist entry survives exactly one baseline refresh. Once the baseline is
re-captured, the movement it accounts for is part of the new baseline and the
entry matches nothing. `--stale-check` reports those entries and exits 3.

A register that is never pruned widens silently over time — the supervisory
validation register documents exactly this failure, where five entries went on
citing a rule that had left the register entirely. Run `--stale-check` whenever
you refresh the baseline, and delete what it names.

## CI wiring

The report needs a baseline from the merge-base, so the natural shape is two
captures and a diff:

```yaml
- name: Capture baseline (merge-base)
  run: |
    git worktree add --detach ../base "$(git merge-base HEAD origin/master)"
    uv run --directory ../base python scripts/impact_report.py capture --out ../base/.impact/snap

- name: Capture head
  run: uv run python scripts/impact_report.py capture --out .impact/head

- name: Change-impact report
  run: |
    uv run python scripts/impact_report.py compare \
      --baseline ../base/.impact/snap --current .impact/head \
      --markdown .impact/impact.md --json .impact/impact.json --stale-check
```

Publish `.impact/impact.md` into the PR description — it is written for exactly
that. At ~46s per capture the whole job is ~2 minutes, so it belongs on every PR
that touches `src/rwa_calc/engine/` or `src/rwa_calc/reporting/`, not on a
nightly cadence.

If the merge-base capture is inconvenient, a committed baseline works too —
capture on `master`, store the snapshot as a build artifact, and refresh it on
every merge. Whichever you choose, refresh the baseline and prune the allowlist
in the **same** commit: a baseline refresh that leaves entries behind converts
the register into decoration.

## What it does not do

- It is a regression gate. It cannot tell you the *baseline* was right — only
  that you have or have not changed it. Correctness lives in the oracle cases,
  the property suite, and the supervisory validation register.
- It covers the reporting fixture portfolios only. A defect that needs a
  portfolio shape none of the six has will not move a cell here. Adding a
  portfolio to `RUNS` for the supervisory gate extends this report too.
- Non-finite (`NaN`/`Inf`) cells are counted and surfaced in the **Reach**
  section of the report, but two `NaN`s compare equal, so a standing `NaN` is
  reported as a defect rather than as movement.

## References

- `docs/plans/independent-validation-system.md` — C1, the component this implements
- `scripts/parity_gate.py` — the sibling harness; proves a refactor moved
  *nothing* over the 10k stress set at per-row grain, and is deliberately left
  untouched
- `tests/acceptance/reporting/test_supervisory_validations.py` — the run matrix
  and the published-rule ratchet
