# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout: single-context.** One `CONTEXT.md` at the repo root plus `docs/adr/`.
Peck Deck is one deployable system across several runtimes (Pi client, backend,
inference server, frontend) — not a monorepo of independent packages — so there
is no `CONTEXT-MAP.md` and no per-context ADR directories.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

Neither exists yet in this repo. Until they do, the closest standing sources are
`CLAUDE.md` (conventions and the reasoning behind them), `PRD.md` (scope),
`FLEDGE_ROADMAP.md` (what is built vs open) and `machine_learning/MODELS.md`
(model provenance and measured accuracy). Those are *not* substitutes for a
glossary — they are prose, not defined terms — but they are where the project's
vocabulary currently lives.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-litestar-over-fastapi.md
│   └── 0002-images-as-bytea.md
└── backend/ · raspberry_pi_code/ · inference_server/ · frontend/
```

(ADR filenames above are illustrative — none are written yet.)

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
