# Taxonomy release selection in rwa-filer

**Status:** Proposed 2026-11-15. D2, D3, D7 and D8 were revised the same day: there is
no cap on the number of releases, the data stays inside rwa-filer, and any release other
than the live one is chosen by its version number. Nothing is implemented. Written against `f52dba0`
(rwa-filer 0.1.2), which ships one release: Bank of England banking taxonomy 4.1.1.
Scope is `packages/rwa-filer`; [§9](#9-effect-on-rwa-calc) lists the knock-on in
rwa-calc.

## 1. The change in one paragraph

The user chooses, per run, which taxonomy release a return is validated, built and
compared against, by naming its version: `--taxonomy 4.1.1`. With no choice, the run uses
the live release. A run always takes its taxonomy pack and its rule
book from the same release, and its first line of output says which release it used and
why. rwa-filer ships as many releases as firms need, named in one committed file. The
default is worked out per module, so returns whose rules come into force on different
dates each get the release in force for them. Packaging the next release is a single
script run followed by a review of the diff.

## 2. Decisions

Agreed 2026-11-15.

| # | Decision |
|---|---|
| D1 | The user picks the release for a run. The return's reference date never picks it. |
| D2 | With no choice, the default is the **live** release: the newest shipped release in force for the module on the run date. If the module has no live release, the default is its future release when there is exactly one. With several, the run stops and asks for a version. |
| D3 | rwa-filer ships **as many releases as are needed**, each named explicitly. There is no fixed cap: reporting modules come into force on different dates, so firms may need several releases at once. Growth is watched by a size budget ([§7.1](#71-releasesjson)), not a count. |
| D4 | Live, future and superseded are worked out **per module**, from the dates in each pack, against the date of the run. |
| D5 | A run's pack and rule book always come from the same release. |
| D6 | For now only 4.1.1 ships. It is built for the Basel 3.1 rules that go live on 1 January 2027. |
| D7 | Every shipped release stays inside the rwa-filer package. It is not split into separately installed packages, and rwa-filer does not download taxonomy data itself ([§11](#11-considered-and-not-taken)). |
| D8 | Any release other than the default is chosen by its **version number**. There are no `live` or `future` shortcuts: once several releases are shipped, "the future one" can mean more than one, so the user says which they want. |

## 3. Today

What the code does at `f52dba0`, and why it cannot carry a second release.

- **Packs are chosen by reference date.** `resolve_pack(module, reference_date)`
  (`taxonomy/pack.py:386`) picks the pack whose dates cover the return's reference date,
  and stops with `PackNotFoundError` when none does. Callers: `cli.py:633` (`template`),
  `xbrl/writer.py:200`, `validate/returns.py:249`, `workflow/compare.py:431` and
  `dash/reference_pages.py:83`.
- **Rule books are chosen by file name.** `rulebook_for_module` (`boe/catalogue.py:245`)
  returns the first file, in alphabetical order, that lists the module. Rule books carry
  no dates. Callers: `validate/returns.py:254`, `workflow/compare.py:437` and
  `dash/views.py:345`.
  A copy of `banking_reporting-4.1.1.json` relabelled 4.2.0, and then 4.10.0, was
  simulated beside the real one. PRA001 got the 4.1.1 rules both times. A second release
  would therefore silently pair the new pack with the old rules, or the reverse.
- **XBRL files are matched on their entry point** (`xbrl/reader.py:349`). The reader takes
  the last match from a list sorted on the version **as text**, so 4.10.0 would sort below
  4.9.0. Entry points are dated by framework, not by release: in 4.1.1 the
  financial-statements modules still name `financialstatements/2021-07-31`. Two releases
  can therefore share an entry point.
- **Live and future differ within one release.** In 4.1.1 only PRA001 and PRA116 apply
  from 1 January 2027. The other modules already apply:
    - LVR001 and PRA112–PRA118 from 27 February 2026;
    - MRL001 and MRL003 from 22 June 2026;
    - LVR002 from 11 May 2023;
    - the three financial-statements modules from 31 July 2021.

  One label for the whole release would be wrong for 12 of its 14 modules.
- **Packaging a release takes about 25 hand-run commands**: `taxonomy compile` for each of
  14 modules and `rulebook import --taxonomy-package` for each of 11 return families. It
  also needs hand edits to tests that pin 4.1.1 numbers:
    - `tests/boe/test_packaged_rulebooks.py:42-94`;
    - `tests/test_cli_rules.py:174-176`;
    - `tests/xbrl/test_boe_sample.py:44-46`;
    - `tests/taxonomy/test_compiler_integration.py`;
    - the Arelle oracles in `tests/boe/data/`.
- **The template-level engine (`rwa_filer.rules`) holds one version by construction.** Its
  version, URL and workbook name are constants in `rules/importer.py:89-100`, each
  framework maps to one file in `rules/catalogue.py:73`, and it reads the Bank's sheet by
  column position (`rules/importer.py:106-123`).

Some of the groundwork is already there:

- Every pack records `info.version` and every rule book records `source.taxonomy`, so
  releases can be indexed without moving any files.
- The JSON report already records `taxonomy.version` (`validate/report.py:51`), and the
  build manifest copies that block (`filing.py:239`).
- The compiler and the rule-book importer give byte-identical output from the same
  inputs.
- A rule written in syntax the parser does not know comes back `NOT_EVALUATED`
  (`unsupported`) rather than with a guessed verdict.

## 4. Terms

- **Release**: one Bank of England banking taxonomy version as rwa-filer ships it. That is
  a pack per module (`taxonomy/data/<module>-<version>/`) and a rule book per return
  family (`boe/data/<family>-<version>.json`).
- **Shipped releases**: the releases named in `src/rwa_filer/releases.json`
  ([§7.1](#71-releasesjson)). There can be as many as are needed.
- **Run date**: the date the run happens. On the command line it is `date.today()`; in the
  library it is a `today=` argument, so that tests are fixed.
- **Status of a module in a release** comes from that pack's `valid_from` and `valid_to`,
  always against the run date:

| Status | When |
|---|---|
| future | the run date is before `valid_from` |
| live | `valid_from` ≤ run date ≤ `valid_to` (open-ended when there is no `valid_to`) |
| superseded | the run date is after `valid_to` |

The return's reference date is used only for the warning in
[§5.4](#54-a-reference-date-outside-the-releases-dates).

## 5. What users see

### 5.1 Choosing a release

`--taxonomy VALUE` goes on every command that reads a return. `validate`, `build`, `diff`,
`compare` and `dash` share `_add_header_arguments` (`cli.py:202`), so the option is
defined once for those. `template` (`cli.py:600`) and `referee` need it added separately.

| VALUE | Release used for the return's module |
|---|---|
| *(none)* | the live release: the newest shipped release in which the module is live. If the module has no live release and exactly one future release, that one. |
| a version, e.g. `4.1.1` | that release |

Every other release is chosen by its version number (D8).

The default is worked out per module. A firm filing several returns therefore gets, for
each one, the release in force for that module, even when the modules come into force on
different dates. Nobody needs to choose unless they want something other than the live
release.

A problem is always an error, never a fallback:

- **No version given, no live release, and more than one future release for the
  module.** The run stops and lists the future releases with their applies-from dates.
  For example: `PRA001 has no live release; choose one: --taxonomy 4.2.0 (from 1 January
  2028), --taxonomy 4.3.0 (from 1 July 2028)`.
- **A version that is not shipped.** If `retired.json` ([§7.2](#72-retiredjson)) records
  it, the message names the last rwa-filer version that shipped it, e.g.
  `uvx rwa-filer@0.4.0 ...`. Otherwise it lists what is shipped.
- **A shipped version that has no pack for the module.**

The library gains `taxonomy: str | None = None` and `today: date | None = None` on
`validate_return`, `build_filing`, `write_instance`, `read_instance`, the readers and the
comparison. The existing `pack=` and `rulebook=` arguments stay for tests and advanced
use. Passing `pack` alone takes the rule book from that pack's release.

### 5.2 What this means today

With only 4.1.1 shipped, on 15 November 2026:

| Module | Default | Why |
|---|---|---|
| PRA001, PRA116 | 4.1.1 | no live release is shipped; in 4.1.1 they are future, from 1 January 2027 |
| the other 12 | 4.1.1 | live |

On 1 January 2027 the PRA001 default is still 4.1.1, now as live, with no change to any
install. If a second future release for PRA001 were shipped before then, a PRA001 run
with no `--taxonomy` would stop and ask which one to use.

### 5.3 XBRL files

A file names its entry point, so the candidates are the shipped releases whose pack for
the module has that entry point. The rules in [§5.1](#51-choosing-a-release) then choose
among them.

`--taxonomy` naming a release with a different entry point is an error that names both
entry points, because the Bank's gateway checks a file against the taxonomy the file
names. A file whose entry point no shipped release has is also an error. If a retired
release had that entry point, the message names the rwa-filer version that shipped it.

### 5.4 A reference date outside the release's dates

This replaces today's hard stop. It becomes a **Warning** with the proposed code
`STR011`, the next free code in the STR series. For example: "reference date 2026-12-31
is before PRA001 applies in taxonomy 4.1.1 (1 January 2027)". A Warning does not block
`build`, because `Finding.is_blocking` is true for Errors only
(`validate/checker.py:225`).

### 5.5 Saying what was used

1. **The first line of text output** for `validate`, `build`, `diff`, `compare` and
   `template`. Today, for example:

    ```text
    Taxonomy 4.1.1 (default) — PRA001 future: applies from 1 January 2027; no live release shipped
    ```

    And during 2027 with three releases shipped (4.2.0, 4.3.0 and their dates are
    illustrative):

    ```text
    Taxonomy 4.1.1 (default) — PRA001 live since 1 January 2027
    Also shipped for PRA001: 4.2.0 future from 1 January 2028 (--taxonomy 4.2.0)
                             4.3.0 future from 1 July 2028 (--taxonomy 4.3.0)
    ```

2. **The JSON report and the build manifest.** The existing `taxonomy` block gains fields:

    ```json
    "taxonomy": {
      "module": "PRA001",
      "version": "4.1.1",
      "entry_point": "http://www.bankofengland.co.uk/data/xbrl/fws/banking/banking_reporting/2026-08-17/mod/pra001.xsd",
      "status": "future",
      "applies_from": "2027-01-01",
      "applies_to": null,
      "run_date": "2026-11-15",
      "chosen_by": "default",
      "covers_reference_date": false,
      "shipped": ["4.1.1"]
    }
    ```

    `chosen_by` is `default` or `version`. A filed return then
    records which release it used and why.

3. **`taxonomy list`** shows one row per shipped release and module: its status on the
   run date, its applies-from and applies-to dates, and which release the default picks.
4. **The dashboard** shows the release and status in the header of every page. A switch
   between the shipped releases re-runs the open return, and `rwa-filer dash` takes
   `--taxonomy`.
5. **`rwa-filer --version`** lists the shipped releases next to the package version.

## 6. The resolver

One new module, `src/rwa_filer/release.py`:

```python
@dataclass(frozen=True)
class Release:
    """The release a run uses for one module, and why."""

    version: str
    module: str
    pack: TaxonomyPack
    rulebook: RuleBook
    status: str       # "live", "future" or "superseded", on run_date
    chosen_by: str    # "default" or "version"
    run_date: date


class ReleaseNotFoundError(LookupError):
    """No shipped release satisfies the request; the message says what would."""


def shipped_releases() -> tuple[str, ...]:
    """The shipped release versions, newest first, compared as numbers."""


def resolve_release(
    module: str,
    taxonomy: str | None = None,
    *,
    today: date | None = None,
    entry_point: str | None = None,
) -> Release:
    """The release for ``module``, by the rules of §5.1 (and §5.3 with ``entry_point``)."""
```

It replaces `resolve_pack`, `select_pack`, `rulebook_for_module` and the reader's
`_pack_for`. Every catch site in `cli.py` and `dash/` catches `ReleaseNotFoundError` in
place of `PackNotFoundError` and `RuleBookNotFoundError`. Versions are compared as
numbers: `(4, 10, 0)` sorts above `(4, 9, 0)`.

`rulebook` is not optional. All 14 packaged modules have a rule book in 4.1.1, and the
contract tests in [§7.1](#71-releasesjson) keep it that way.

## 7. Making a release quick on our side

### 7.1 `releases.json`

This is package data at `packages/rwa-filer/src/rwa_filer/releases.json`. It is the only
file we edit by hand, and `shipped_releases()` reads it.

```json
{
  "format": 1,
  "releases": [
    {
      "version": "4.1.1",
      "published": "2026-08-27",
      "applies_from": {"PRA001": "2027-01-01", "PRA116": "2027-01-01"}
    }
  ]
}
```

`applies_from` holds only the exceptions to the entry-point date
([§7.3](#73-scriptsbuild_filer_releasepy) step 4).

New contract tests in `packages/rwa-filer/tests/test_releases.py`:

- no version is listed twice;
- the packs and rule books on disk are exactly those of the listed releases, with nothing
  extra and nothing missing;
- every module with a pack has a rule book in the same release;
- the packaged taxonomy data stays within the size budget below.

There is no cap on the number of releases, so the budget is a size, not a count. One
release adds about 1.6 MB, compressed, to the wheel today: 1.36 MB of packs and 0.23 MB
of rule books, measured on 4.1.1. The proposed budget is 50 MB of compressed package
data, roughly 30 releases at today's size and well below PyPI's default 100 MB limit per
file. Passing it is a prompt to retire releases or to revisit
[§11](#11-considered-and-not-taken), not a hard limit.

### 7.2 `retired.json`

This is a committed record of releases no longer shipped. For each it holds the version,
the last rwa-filer version that shipped it, and the entry points of its modules. The
build script writes it, and the error messages in [§5.1](#51-choosing-a-release) and
[§5.3](#53-xbrl-files) read it. It is package data as well.

### 7.3 `scripts/build_filer_release.py`

This is a repository script, not a published command. It writes into the checkout, and
it is built on the public `compile_pack` and `import_workbook`.

```bash
uv run python scripts/build_filer_release.py 4.2.0 --from ~/downloads/boe-4.2.0
uv run python scripts/build_filer_release.py 4.2.0 --from ~/downloads/boe-4.2.0 --check
```

A build does nine things:

1. It refuses unless the version is listed in `releases.json`.
2. It finds the Bank's files in `--from` by name pattern: the taxonomy package, the
   annotated templates, the DPM dictionary, the validation workbooks and the sample
   files. `tests/taxonomy/test_compiler_integration.py` already finds the PRA001 files
   this way.
3. It reads the module list from the taxonomy package's entry points.
4. It compiles every pack. `valid_from` is the entry point's folder date unless
   `applies_from` overrides it.
5. It imports every rule book with the taxonomy package, so each rule records what its
   formula fixes.
6. It checks each module's sample file against its pack. This is today's packaging rule:
   a module ships only when every fact in the Bank's sample file is a data point of its
   pack. A module that fails is not packaged, and the reason is reported.
7. For each module the new release changes, it sets `valid_to` on the previous release's
   pack for that module (the newest older shipped release that has it) to the day before
   the new `valid_from`.
8. It removes every shipped release that is not in `releases.json` (its packs, rule
   books, measurements and oracles) and records it in `retired.json`.
9. It writes the release's measurement file ([§7.4](#74-tests-per-release)) and prints a
   summary: modules packaged, modules refused and why, rules per module, and rules
   marked `unsupported`.

`--check` rebuilds into a temporary directory and fails on any difference. The Bank's
files are not redistributed, so the script runs on an owner's machine and never in CI.
CI checks what it committed.

### 7.4 Tests per release

- The tests of packaged data run across `shipped_releases()` instead of a pinned version.
- The numbers pinned today as 4.1.1 literals (listed in [§3](#3-today)) move to
  `packages/rwa-filer/tests/releases/<version>/measurements.json`. The build script
  writes that file, so the numbers are re-measured and never typed, the same way the
  repository's ratchets work.
- The Arelle oracles move to `tests/boe/data/<version>/`, and one command per release
  produces them. It needs Arelle and the Bank's package, so it runs locally; CI checks the
  committed result.
- The opt-in tests against the Bank's files (`RWA_FILER_BOE_DIR`) read the release
  version from the downloads instead of assuming 4.1.1.

### 7.5 The routine

| Event | What we do |
|---|---|
| The Bank publishes a future release | Add it to `releases.json`, run the build script, run the Arelle oracles, review the diff, release rwa-filer. |
| A future release goes live | Nothing. Status and the default move on the date by themselves, on every install. |
| The Bank corrects a release (e.g. 4.2.0 → 4.2.1) | Replace the version in `releases.json` and rebuild. The corrected release takes the slot. |
| An old release is no longer needed | Remove it from `releases.json`, run the build script, release rwa-filer. |
| A retired release is needed again | Add it back to `releases.json` and rebuild it from the Bank's files. The build is reproducible, so it comes back exactly as it was. |

Judgement is only needed when the build reports something: a refused module, rules
marked `unsupported`, or a `RefereePlanError` from the Arelle comparison planner.

## 8. Slices

Each slice ends green on `uv run pytest packages/rwa-filer` and the static gates, and
adds an entry to `packages/rwa-filer/CHANGELOG.md`.

| # | Slice | Done when |
|---|---|---|
| 1 | **Resolver** ([§6](#6-the-resolver)) with a minimal `releases.json` listing 4.1.1. Numeric ordering; status on the run date; default live, else the only future release, else ask for a version. Every caller in [§3](#3-today) moves to it. | No code picks a pack by date or a rule book by file name. The simulation in [§3](#3-today) is a test that fails on today's code. The three date-selection tests in `tests/taxonomy/test_pack.py` (lines 202, 221 and 235) are replaced by release tests. |
| 2 | **Choosing** ([§5.1](#51-choosing-a-release), [§5.3](#53-xbrl-files), [§5.4](#54-a-reference-date-outside-the-releases-dates)): `--taxonomy`, `taxonomy=` and `today=`, the XBRL entry-point rule, and `STR011`. | Every command in [§5.1](#51-choosing-a-release) accepts `--taxonomy`, and each error has a test. A 2026-12-31 PRA001 return validates against 4.1.1 with one `STR011` warning, and `build` still writes it. |
| 3 | **Saying what was used** ([§5.5](#55-saying-what-was-used)), plus the docs. | Every text output starts with the release line. The report and manifest carry the new fields. `taxonomy list` and the dashboard show status. `docs/rwa-filer/index.md` ("Reading an XBRL file", "Taxonomy packs") and `docs/rwa-filer/dash.md` describe choosing a release, not dates. |
| 4 | **`retired.json` and the contract tests** ([§7.1](#71-releasesjson), [§7.2](#72-retiredjson)). | The contract tests pass for 4.1.1, and fail when a stray pack or rule book is added or when the data passes the size budget. |
| 5 | **The build script** ([§7.3](#73-scriptsbuild_filer_releasepy)). | `--check` against the Bank's 4.1.1 downloads reproduces today's packaged data byte for byte. |
| 6 | **Tests per release** ([§7.4](#74-tests-per-release)). | No test names 4.1.1 except through a measurement file. A second listed release would be tested with no test edits. |
| 7 | **The template-level engine** reads the Bank's sheet by header name, and the build script regenerates its extract. It stays on one release, the newest shipped, and users cannot select it. | A Bank workbook with an extra column inserted imports correctly. |

Slices 1–3 deliver the feature. Slices 4–6 make the next release quick, and must land
before a second release ships. Slice 7 can go at any time.

Slices 1 and 2 change rwa-filer's public API, so they ship as rwa-filer 0.2.0.

## 9. Effect on rwa-calc

- Three callers of `resolve_pack(module, reference_date)` move to the resolver:
  `src/rwa_calc/reporting/filing/canonical.py:205`, `scripts/referee_differential.py:214`
  and `scripts/filing_mapping_report.py:188`. Their results do not change while only
  4.1.1 ships, because PRA001 resolves to 4.1.1.
- The API change makes this rwa-filer 0.2.0. rwa-calc's dependency (`pyproject.toml:54`,
  `rwa-filer>=0.1,<0.2`) moves to `>=0.2,<0.3`, and rwa-filer is released first.
  `python scripts/deploy.py --package all` does both, in that order.
- Not in scope: golden sets per release on the rwa-calc side (`IMPLEMENTATION_PLAN.md`
  P6.53).

## 10. Open questions

1. **A module whose entry point does not change between releases.** Its pack dates come
   from the entry point's folder, so every release that carries it would show it live from
   the same day, and the default would pick the newest. That holds even if the newer
   release changes the module's rules from a later date. The dates alone cannot say when
   the newer rules take effect; the Bank's release note does. Proposal: record that date
   in the release's `applies_from` in `releases.json`. This must be settled before a
   second release ships, but it does not block slices 1–3.
2. **A return for a period before a changeover, run after it**, e.g. a 31 December 2026
   PRA001 return validated in February 2027. The default is the release live on the run
   date, 4.1.1, and the return gets `STR011`. The user then needs `--taxonomy` naming the
   earlier release, which works only while that release is shipped. With no cap on
   releases (D3), it can stay shipped for as long as late or corrected returns need it.
   Today no earlier release is shipped, by choice (D6).
3. **Whether the Bank's file names are stable enough to find by pattern.** If they are
   not, the build script takes a small per-release list of which file is which.
4. **The Bank's known-issues log.** Between releases the Bank downgrades or deactivates
   rules (`IMPLEMENTATION_PLAN.md` P2.59). In this design that becomes an overlay shipped
   with the release it amends, which the resolver applies. P2.59 still names a rwa-calc
   path, `src/rwa_calc/reporting/validations/rules/`, that no longer exists now that the
   rules live in rwa-filer.

## 11. Considered and not taken

- **A separate data package per release, installed as an extra**
  (`uvx "rwa-filer[4.1.1]"`), so that users download only the releases they use. It
  works with uv. On a toy package built with hatchling, the build tool rwa-filer uses:
    - the extra was stored as `4-1-1`, the standard spelling;
    - `uvx --from "demo-core[4.1.1]"` installed the data package;
    - the core found it at run time through an entry point.

  It was not taken because one release is about 1.6 MB compressed, which does not
  justify the costs: a new package to publish for every release, a core release to add
  each extra, and format compatibility between separately versioned packages. Revisit
  it if the size budget in [§7.1](#71-releasesjson) is approached.
- **rwa-filer downloading taxonomy data itself at run time.** Not taken. Banks' networks
  usually reach PyPI through an internal mirror but block other downloads. It would also
  end the guarantee that validation needs no network access, and make runs harder to
  audit.
