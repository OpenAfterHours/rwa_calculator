# Upstream

Vendored third-party skill. `SKILL.md`, `SKILL-MECHANICS.md` and
`agents/openai.yaml` are verbatim copies; keep them that way so a refresh is a
clean diff.

- Source: https://github.com/mattpocock/skills, path `skills/productivity/writing-for-agents/`
- Commit: `5863806dd4e15c63174bee4e7515a4256792ecfa` (2026-11-12)
- Licence: MIT, see `LICENSE` in this folder.
- Local changes: none.

Repository rules that sit on top of this skill live in `CLAUDE.md`, not here:
`AGENTS.md` is generated from `CLAUDE.md`, `.agents/skills/` is a generated
mirror of `.claude/skills/`, and skill prose states no regulatory values.

To refresh: copy the three upstream files over these, update the commit above,
then run `uv run python scripts/sync_agent_skills.py`.
