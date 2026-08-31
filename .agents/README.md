# `.agents/`

Vendor-neutral agent configuration, alongside `AGENTS.md` at the repo root.

## `.agents/skills/` is a generated mirror — do not hand-edit it

Every file under `.agents/skills/` is a byte-for-byte copy of `.claude/skills/`,
which is **canonical**. Edits belong in `.claude/skills/`; an edit made in the
mirror is silently reverted by the next sync.

Rebuild it after any change under `.claude/skills/`:

```
uv run python scripts/sync_agent_skills.py
```

`--check` verifies the mirror without writing, and is what
`tests/contracts/test_agent_skills_mirror.py` runs.

## Why the mirror exists

The skills only reach an agent from a root that agent looks in. Claude Code
reads `.claude/skills/`; OpenAI Codex CLI reads `<repo>/.codex/skills` and
`<repo>/.agents/skills`, and nothing else repo-local. Without this copy, Codex
runs against this repo with no regulatory skills at all — and a silently-absent
skill looks exactly like a skill that had nothing to say.

It is a real copy rather than a symlink because `git config core.symlinks` is
`false` here, so a committed symlink would materialise as a text file holding a
path. The copy is committed for the same reason: a fresh clone must give every
agent working skills.

Byte-identity is the contract. `scripts/generate_regulatory_tables.py` writes
pack values into the source files and `scripts/check_skill_values.py` polices
the prose around them; neither reads the mirror, so the mirror only inherits
those guarantees while it is an exact copy. That is also why no
"generated file — do not edit" header is injected into the mirrored files, and
why this notice lives here instead, outside `.agents/skills/` where the sync's
prune step can never reach it.
