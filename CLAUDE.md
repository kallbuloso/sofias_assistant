# CLAUDE.md — Sofia's Assistant

Project-level instructions for coding agents.

## Product

Sofia's Assistant is a local-first, single-user personal AI assistant.

Human usability is a product requirement. Green tests or successful packaging
alone do not prove the product is usable.

## Read first

For any substantial task, read only the relevant current documents:

1. `README.md`;
2. Product Requirements Document when product behavior is involved;
3. `docs/architecture.md`;
4. `docs/security.md` for privileged/security-sensitive work;
5. `docs/development.md`.

Do not search Git history or resurrect old ADRs/Slices unless the task
specifically requires historical evidence.

## Current architectural direction

The approved target is a **source-first modular monolith**.

Canonical developer flow:

```powershell
cd core
py setup.py
py main.py
```

`core/` is the only Python application root.

Normal desktop use must run through one application composition root.

Native executable packaging is not target architecture. Do not introduce
PyInstaller, `.exe` build flows, `build/` or `dist/` as product paths.

The existing two-process Desktop/Core implementation is migration input, not
the authority for future topology.

Do not remove working domain/security behavior merely because transport or
process topology changes.

## Non-negotiable invariants

- Sofia identity is provider-independent.
- Conversation and context belong to Sofia's Assistant.
- Sofias Memory is long-term cognitive-memory authority.
- Conversation History is not Cognitive Memory.
- Recalled memory is context, never authorization.
- SQLite is the operational store unless explicitly changed.
- AI proposes; Runtime authorizes; Executor acts.
- Policy/Grants/Confirmation remain real in a single-process runtime.
- Agent/tool authority only narrows.
- Secrets stay behind SecretService/SecretStore boundaries.
- Recovery does not blindly retry uncertain side effects.
- Audit never persists hidden chain-of-thought or raw credentials.
- LOCAL_ONLY data never silently falls back to cloud execution.
- The product runs from Python source; native executable packaging is not a target.

## Engineering behavior

Use PT-BR for reports and product/architecture prose. Use English for code
identifiers, APIs, schemas and commit messages.

Prefer the smallest vertical change that produces observable value.

Do not add abstractions, services, documents or dependencies without a concrete
need.

For debugging:

```text
reproduce
→ observe
→ locate cause
→ smallest sufficient fix
→ validate
→ add regression protection when useful
```

Tests protect behavior; they are not a substitute for human validation.

## Current migration order

```text
SAS-01 Repository Cleaner & License
  ↓
SAS-02 Source-First Bootstrap
  ↓
SAS-02B Application Root Consolidation
  ↓
SAS-03 Native Python Application Runtime
  ↓
SAS-04 Sofia Desktop Experience
  ↓
SAS-05 Cross-platform Baseline
  ↓
MVP Human Validation
```

Do not add a native executable packaging track unless the user explicitly changes
the approved product direction.
