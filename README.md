# Sofia's Assistant

Sofia's Assistant is a local-first, single-user personal AI assistant focused
on real human use: text and realtime voice, persistent cognitive memory,
tools, tasks, agents, proactive events and protected execution.

The project is moving from a previously implemented two-process Desktop/Core
runtime to an **APPROVED source-first modular-monolith baseline**.

## Current direction

The source-first developer flow is now anchored inside `core/`, the only Python
application root:

```powershell
cd core
py setup.py
py main.py
```

`core/setup.py` creates/updates `core/.venv` and installs runtime dependencies
from `core/requirements.txt`. `core/main.py` starts Sofia directly from the
working tree. Python 3.13 and 3.14 are supported; the repository development
baseline currently targets Python 3.14.

`core/main.py` starts `SofiaApplication` as the normal Desktop composition
root. The old process-supervision path is no longer used by canonical startup.
Desktop conversation, configuration and realtime voice use direct in-process
application services. Normal Desktop startup no longer opens localhost port
8989, creates a bearer credential, or creates a Desktop client session.

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


## Product principles

- local-first and single-user per installation;
- provider-independent Sofia identity;
- Sofias Memory as long-term cognitive-memory authority;
- SQLite for operational persistence;
- deterministic authorization before protected actions;
- least privilege for Tools and Agents;
- source-first development;
- human validation before architectural expansion.

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
├── product/
└── core/
    ├── main.py
    ├── setup.py
    ├── requirements.txt
    ├── pyproject.toml
    ├── uv.lock
    ├── .python-version
    ├── .env.example
    ├── scripts/
    ├── src/
    └── tests/
```

## Development today

For normal source-first use:

```powershell
cd core
py setup.py
py main.py
```

For contributor tooling, the existing workflow remains available:

```powershell
cd core
uv sync
uv run pytest
```

Sofia's Assistant is a Python application run from source. Native executable
packaging is not a product target. PyInstaller, `build/` and `dist/` are not
part of the runtime or validation path.

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


Voice is part of Chat, not a separate conversation surface. Text and voice use
the same selected Conversation and durable history; stopping voice only closes
the temporary realtime audio session.
