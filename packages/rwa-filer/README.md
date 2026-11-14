# rwa-filer

Validate regulatory returns against the published supervisory rules and write
them in the format the regulator accepts.

It carries the Bank of England's validation rules for banking taxonomy v4.1.1
and evaluates them as the Bank's gateway does, for 14 reporting modules
(`PRA001`, `PRA116`, Capital+, leverage, MREL and financial statements).

**Documentation:** <https://openafterhours.github.io/rwa_calculator/rwa-filer/>

`rwa-filer` is a standalone package. It lives in the
[rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator) repository as a
uv workspace member and is released separately from `rwa-calc`: it depends on
Polars alone and never imports `rwa_calc`. `rwa-calc` uses it to validate the
returns it generates; any other system that can produce template-level figures
can use it the same way.

Run it with [uv](https://docs.astral.sh/uv/), naming `@latest`:

```bash
uvx rwa-filer@latest --help
```

`@latest` makes each run check PyPI and use the newest release, so a return is
always checked with the newest rules and taxonomy `rwa-filer` carries. Without
it, `uvx` may run a copy it already has: one it fetched recently, or one
installed with `uv tool install`, for as long as that stays installed. Extras go
in quotes, so the shell leaves the brackets alone: a command that reads or
writes a workbook runs as `uvx "rwa-filer[excel]@latest" ...`.

The manifest `build` writes records the version that wrote it. To repeat a run
on that version, name it in place of `latest`: `uvx rwa-filer@0.1.0 ...`.

```bash
# As a library in a uv project (then run the command as `uv run rwa-filer`).
# The lock file holds it at one version; `uv lock --upgrade-package rwa-filer`
# moves it to the newest release
uv add rwa-filer

# As a command on your PATH, for a machine that has to run it offline. It
# stays on the version installed until you upgrade it
uv tool install rwa-filer
uv tool upgrade rwa-filer
```

```bash
# Check a return: structure against the taxonomy, then the published rules
uvx rwa-filer@latest validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# Validate it and write the XBRL submission file, with a manifest
uvx rwa-filer@latest build return.parquet --out filing/ \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# Record an approval against the file's checksum, and check it before upload
uvx rwa-filer@latest signoff filing/<name>.manifest.json --approver "C. Approver" --role "Head of Reporting"
uvx rwa-filer@latest verify filing/<name>.manifest.json

# What changed since the version already filed
uvx rwa-filer@latest diff filed.xbrl resubmission.xbrl

# A second opinion: have the Arelle XBRL processor check the written file
# against the Bank's taxonomy package, and compare its verdict on every rule
# with this package's own (needs the Bank's package)
uvx "rwa-filer[arelle]@latest" referee filing/<name>.xbrl --taxonomy-package boe-banking-v411.zip

# A blank workbook in the template layout, to fill in and validate
uvx "rwa-filer[excel]@latest" template --module PRA001 --reference-date 2027-03-31 --out return.xlsx

uvx rwa-filer@latest --help
```

A return is a table with one row per reported cell (`table`, `sheet`,
`open_key`, `row`, `column`, `value`), read from Parquet or CSV, or an Excel
workbook in the template layout (needs `rwa-filer[excel]`), or an XBRL instance
written by any system.

> The regulator's own validation on upload is authoritative. A clean result
> from `rwa-filer` is evidence a return is well-formed, not a guarantee that it
> will be accepted.

See [CHANGELOG.md](CHANGELOG.md) for release notes.
