# Upstream

Vendored third-party skill. `SKILL.md` is a verbatim copy; keep it that way so a
refresh is a clean diff.

- Source: https://github.com/latent-spaces/brag, path `skills/brag-slim/SKILL.md`
- Commit: `669ab9286aa28b6c3ee30e75f181ee74319d012a` (2026-10-24)
- Licence: MIT, see `LICENSE` in this folder.
- Local changes: none.

The full `/brag` skill (bundled music, SFX and render scripts) is not vendored.

Output lands in `brag-output*/` at the current directory, which the root
`.gitignore` excludes so a rendered video is never committed by accident.

To refresh: copy the upstream `SKILL.md` over this one, update the commit above,
then run `uv run python scripts/sync_agent_skills.py`.
