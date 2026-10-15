# Sofia's Assistant

Sofia's Assistant is a local-first, single-user personal AI assistant focused
on real human use: text and realtime voice, persistent cognitive memory,
tools, tasks, agents, proactive events and protected execution.

The project is moving from a previously implemented two-process Desktop/Core
runtime to an **APPROVED source-first modular-monolith baseline**.

## Current direction

The target developer experience is intentionally simple:

```powershell
py setup.py
py main.py
```

That flow is the next implementation slice. Until it lands, the existing
`core/` package and its `uv` entry points remain as temporary compatibility
paths.

The architectural target is one application process for normal desktop use:

```text
SofiaApplication
├── Desktop UI
├── Conversation / Context
├── AI routing
├── Policy / Grants
├── Tools / Tasks / Agents
├── Memory
├── Persistence
├── Secrets
└── Audit
```

A separate `SofiaCore.exe` is no longer part of the target architecture.

## Product principles

- local-first and single-user per installation;
- provider-independent Sofia identity;
- Sofias Memory as long-term cognitive-memory authority;
- SQLite for operational persistence;
- deterministic authorization before protected actions;
- least privilege for Tools and Agents;
- source-first development;
- human validation before packaging.

The core security invariant is:

```text
AI proposes.
Runtime authorizes.
Executor acts.
```

## Repository

```text
/
├── README.md
├── LICENSE
├── CLAUDE.md
├── docs/
│   ├── architecture.md
│   ├── development.md
│   └── security.md
├── product/
│   └── docs/
│       └── Sofia's Assistant — Product Requirements Document.md
└── core/
    ├── pyproject.toml
    ├── .env.example
    ├── src/
    └── tests/
```

## Development today

The legacy contributor workflow is still available while the source-first
bootstrap is implemented:

```powershell
cd core
uv sync
uv run pytest
```

Do not build executables merely to validate development changes.

Packaging, installer work and a future single `SofiasAssistant.exe` are
**deferred until the MVP is validated humanly**.

## Documentation

Current authority:

1. explicit user decision;
2. Product Requirements Document;
3. `docs/architecture.md`;
4. `docs/security.md`;
5. `docs/development.md`;
6. implementation and tests.

Historical ADRs, amendments, completed Slices and gate ledgers were removed
from the current documentation surface and remain available through Git
history.

## License

Sofia's Assistant is source-available under the **PolyForm Noncommercial
License 1.0.0**.

Non-commercial use, modification and redistribution are allowed subject to the
license terms. Commercial use requires separate authorization from the
licensor.

See `LICENSE` for the official license reference.
