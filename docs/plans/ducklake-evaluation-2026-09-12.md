# DuckLake evaluation — 2026-09-12

**Verdict: do not adopt.** DuckLake is a well-designed format that solves a
problem this project does not have, and the one problem it *would* solve here is
already solved better by a format Polars supports natively.

The investigation is still worth recording, because it surfaced a real gap:
the durable fix for **P6.47** is a table-format-shaped problem, and the right
tool for it is Delta, not DuckLake.

---

## 1. What DuckLake is

A lakehouse format (spec + DuckDB extension, MIT, v1.0 since April 2026):

- **Storage layer** — Parquet files on local disk or object storage.
- **Catalog layer** — an ACID SQL database (DuckDB, PostgreSQL or SQLite)
  holding *all* metadata: snapshots, schemas, file lists, column statistics.

Its design bet is that the metadata belongs in a transactional database rather
than in a pile of JSON/Avro log files next to the data (Delta, Iceberg). What
that buys: snapshots and time travel, schema evolution, ACID transactions with
genuine multi-writer concurrency ("multiplayer DuckDB"), and filter pushdown
from catalog statistics without listing object storage.

## 2. What it would have to fit into

This project's persistence surfaces, as they stand:

| Surface | Module | Shape |
|---|---|---|
| Input loading | `engine/loader.py` | `scan_parquet` / `scan_csv` over a data directory, schema-enforced |
| Mid-pipeline spill | `engine/materialise.py` | `sink_parquet` to a temp path, bounded lazy plans |
| Per-run results | `api/results_cache.py` | `sink_parquet` + atomic `os.replace`, scanned lazily |
| Run reuse index | `api/run_index.py` | `run_index.json` + per-run parquet dirs, cap 10, orphan sweep |
| Audit trail | `observability/audit_cache.py` | parquet, atomic write |
| Analyst sign-off | `ui/app/recon_signoff.py` | JSON, atomic write, keyed by workspace hash |
| Export | `api/export.py` | parquet / CSV / Excel |

Two structural facts matter for the assessment:

1. **Writers are partitioned by construction.** `api/batch.py` fans scopes out
   over a `ProcessPoolExecutor`, but each worker writes to *its own* run cache
   directory and returns paths; the shared `run_index` is registered from the
   parent process only. No two writers ever contend for one table.
2. **Execution-engine choice is centralised on purpose.** `arch_check`'s
   `check_no_engine_arg` forbids `engine=` at `.collect()` call sites so the
   choice lives in `materialise.py` alone. Introducing a second query engine is
   therefore a deliberate architectural act here, not a drop-in.

## 3. The match test

| DuckLake capability | Does this project need it? |
|---|---|
| Multi-writer ACID on a shared table | **No.** Writers are partitioned (§2.1). |
| Snapshots / time travel | **Partly — see §5.** The one genuine hit. |
| Schema evolution | **No — actively unwanted.** The estate enforces schemas (`enforce_schemas`) and seals stage edges (`contracts/edges.py`). Silent schema drift is a defect class here, not a feature. |
| Catalog statistics / filter pushdown | **No.** `scan_parquet` already does predicate and projection pushdown against local files. |
| Avoiding slow object-store LIST | **No.** Storage is local disk; the run index is capped at 10 runs. |
| Cross-engine interop (DuckDB / Spark / Trino) | **No.** Polars is the mandated engine; interop is served by `api/export.py`. |

One hit out of six, and that hit is not specific to DuckLake.

## 4. The blocker: there is no production Polars path

This is decisive independently of §3.

- **Polars has no native DuckLake support.** [pola-rs/polars#25557][polars-issue]
  is an open enhancement request filed by DuckDB Labs on 2025-12-01 — unassigned,
  no linked PR, no maintainer commitment, no milestone, nine months on.
- **The pure-Python binding is explicitly not for production.**
  [`ducklake-dataframe`][ddf] (v1.0.0, 2026-05-02) reads DuckLake catalogs and
  scans the Parquet through Polars' own lazy reader with no DuckDB runtime — an
  attractive shape on paper. Its own PyPI page states: *"This project is a proof
  of concept. It was 100% written by Claude Code (Anthropic's AI coding agent).
  It is not intended for production use."* Sole maintainer, Beta classifier.
- **That leaves the DuckDB extension**, which means adding DuckDB as a core
  dependency and marshalling across an engine boundary in a codebase whose
  conventions mandate LazyFrames end-to-end with `.collect()` only at the output
  boundary.

The dependency cost lands badly: the greenfield proposal already criticises the
core dependency list as carrying the UI, web server, workbooks and docs tooling
(`docs/plans/greenfield-architecture-proposal-2026-09-08.md` line 47), and its
Phase E target is explicitly *"minimal core dependencies"*.

A regulatory capital calculator should not put a self-declared proof of concept,
or a second query engine, underneath its filing-relevant run artifacts.

## 5. The real problem it pointed at — P6.47

The evaluation is not a dead end, because DuckLake's one genuine hit maps onto a
filed backlog item.

**P6.47** records that `ResultsCache` writes every run to a *fixed*
`<cache_dir>/last_results.parquet`, so a later run overwrites the file that a
still-registered `CalculationResponse` re-scans lazily — a torn read surfacing as
`polars ComputeError: parquet: File out of specification`. The proposed durable
fix is: unique per-run filenames so every registered response scans an
**immutable snapshot**, a "latest" pointer via a manifest JSON or atomic
copy/symlink, *and* — the caveat the item flags — a **retention/GC policy
(ref-count or TTL)** so a snapshot is never deleted while a live response still
references it.

Immutable snapshots + an atomically-published "latest" pointer + readers pinned
to the version they opened + a retention window before reclamation **is a table
format's entire job description.** P6.47 is a proposal to hand-roll one.

The greenfield proposal reaches the same place from the other direction (§5,
"Treat a completed run as a reproducible artifact"): *"Start with local Parquet
artifacts and an atomic manifest publication step behind a repository protocol.
Add a database or object-store adapter when concurrent deployment and retention
requirements justify it."*

## 6. If a table format is wanted, it is Delta — not DuckLake

Verified against the project's own installed Polars (1.42.1):

```
module-level: ['read_delta', 'scan_delta', 'scan_iceberg']
DataFrame:    ['write_delta', 'write_iceberg']
LazyFrame:    ['sink_delta', 'sink_iceberg']
```

Delta and Iceberg are first-class in the Polars the project already pins.
DuckLake is absent. The mapping onto P6.47 is close to exact:

| P6.47 requirement | Delta, via native Polars |
|---|---|
| Immutable per-run snapshot | Every commit is a version; old files are untouched |
| Reader pinned to its snapshot | `pl.scan_delta(path, version=N)` |
| Atomic "latest" pointer | The commit itself — no manifest JSON to hand-roll |
| Retention/GC without cutting a live reader | `VACUUM` with a retention window (the item's "TTL" option, for free) |
| Streaming write | `LazyFrame.sink_delta` |

Cost: one optional dependency (`deltalake`; not currently installed), behind the
repository protocol the greenfield proposal already calls for — so the in-memory
and plain-parquet modes survive for tests and exploration.

This is a recommendation to *consider when P6.47 is scheduled*, not to adopt now.
Hand-rolling P6.47 as written is still defensible: 10 runs, local disk, one
writer. The point is only that if the answer is "use a format", Polars has
already chosen which formats it supports, and DuckLake is not among them.

## 7. When to revisit

Reopen the question if **all** of these become true:

1. Runs move to object storage with a retention mandate (the greenfield §5
   trigger), **and**
2. Concurrent writers genuinely contend for one table — several app instances,
   not a partitioned process pool, **and**
3. Polars ships native DuckLake support ([#25557][polars-issue] closed and
   released), or DuckDB becomes a dependency this project wants for other
   reasons.

Until (3), the question is moot regardless of (1) and (2): there is no
production-grade way to reach a DuckLake table from a Polars-native codebase.

---

### Sources

- [DuckLake — ducklake.select](https://ducklake.select/) — spec, architecture, v1.0 status
- [`ducklake-dataframe` on PyPI][ddf] — the pure-Python Polars binding and its production disclaimer
- [pola-rs/polars#25557][polars-issue] — native DuckLake support request
- Verified locally: `polars 1.42.1` delta/iceberg surface; absence of any `duckdb` import in `src/`

[ddf]: https://pypi.org/project/ducklake-dataframe/
[polars-issue]: https://github.com/pola-rs/polars/issues/25557
