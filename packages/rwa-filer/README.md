# rwa-filer

Validate regulatory returns against the published supervisory rules and write
them in the format the regulator accepts.

`rwa-filer` is a standalone package. It lives in the
[rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator) repository as a
uv workspace member and is released separately from `rwa-calc`: it depends on
Polars alone and never imports `rwa_calc`. `rwa-calc` uses it to validate the
returns it generates; any other system that can produce template-level figures
can use it the same way.

```bash
pip install rwa-filer
```

```bash
rwa-filer --help
```

> The regulator's own validation on upload is authoritative. A clean result
> from `rwa-filer` is evidence a return is well-formed, not a guarantee that it
> will be accepted.

See [CHANGELOG.md](CHANGELOG.md) for release notes.
