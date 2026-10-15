# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- `CONTEXT.md` at the repo root, or `CONTEXT-MAP.md` if it exists.
- `docs/adr/` for decisions that touch the area under work.

If these files do not exist, proceed silently. Do not create them upfront; add them when domain terms or decisions are actually resolved.

## File structure

This is a single-context repo. Domain documentation belongs at the root `CONTEXT.md`, with system decisions under `docs/adr/`.

## Use the glossary's vocabulary

When naming a domain concept in an issue, refactor proposal, or test, use the terminology defined in `CONTEXT.md`. If a needed concept is missing, record that gap for domain modeling rather than inventing a synonym.

## Flag ADR conflicts

If planned work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding it.
