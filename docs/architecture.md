# Sofia's Assistant — Architecture

**Status:** APPROVED  
**Baseline date:** 2026-10-14  
**Architecture style:** Source-first modular monolith

This document is the current architectural baseline. It supersedes the former
collection of project-level ADRs, architecture amendments, Desktop/Core
contracts and historical execution plans. Git history remains the archive for
those documents.

## 1. Architecture goal

Sofia's Assistant is one application from the operator's point of view and a
modular monolith internally.

The canonical development runtime is:

```text
repository
  ↓
core/
  ↓
py main.py
  ↓
SofiaApplication
  ├── Desktop UI
  ├── Conversation / Context
  ├── AI routing / Providers
  ├── Policy / Grants / Confirmation
  ├── Tools / Execution
  ├── Tasks / Agents / Events / Scheduler
  ├── Memory adapter
  ├── Persistence
  ├── Secrets
  └── Audit
```

`core/` is the only Python application root.

Native `.exe` packaging is not part of the target architecture. Sofia's
Assistant is executed as a Python application from source.

## 2. Runtime ownership

`SofiaApplication` is the application composition root and runtime authority.

The UI is an adapter to the application, not the authority for domain state,
authorization, persistence, routing or tool execution.

The application may expose additional adapters later, such as CLI or HTTP, but
those adapters are optional. A local HTTP/WebSocket boundary is not required
for the Desktop UI to talk to the application.

Same-process execution does not collapse trust boundaries. Policy, Grants,
Secrets, Audit and execution restrictions remain explicit even when modules
share one process.

## 3. Core capabilities

### Conversation and context

Conversation, Turn, Working Memory and context assembly belong to Sofia's
Assistant. Provider-native sessions are optimizations only and never become
the source of truth.

### AI routing

Provider and model are execution mechanisms, not Sofia's identity.

Routing is capability/profile/policy aware and must respect hard requirements
such as data locality. Provider-specific logic stays behind adapters.

### Memory

Sofias Memory is the authority for persistent cognitive long-term memory.

Sofia's Assistant owns operational state, Conversation History, Working Memory,
Tasks, routing and execution state.

```text
Conversation History != Cognitive Memory
```

Recalled memory is context, never authorization.

### Policy and execution

The invariant is:

```text
AI proposes
Runtime authorizes
Executor acts
```

Protected actions pass through Policy and, when needed, Confirmation or Grant
evaluation before an executor runs.

### Operational persistence

SQLite remains the initial authoritative operational store. Migrations are
append-only once published.

Do not hold a database transaction open across remote inference or external
side effects.

### Tasks, agents, events and scheduler

Use the least complex mechanism that correctly solves the work.

Immediate bounded work may execute directly. Durable Tasks are for work that
needs persistence, waiting, scheduling, recovery, progress or multi-step
coordination.

Sofia/root remains the authority that creates AgentRuns. Sub-agents can only
receive narrower context, tools and authority.

### Secrets and audit

Secrets flow through SecretService/SecretStore abstractions.

Audit records decisions, authority, execution facts and outcomes. It does not
persist hidden chain-of-thought or raw credentials.

## 4. Data flow

Typical protected action:

```text
User/UI
  ↓
SofiaApplication
  ↓
Conversation / intent
  ↓
Policy
  ↓
ALLOW | DENY | REQUIRE_CONFIRMATION
  ↓
Tool / Task executor
  ↓
Persistence + Audit
  ↓
Result to UI
```

AI inference and memory retrieval may participate in context construction, but
neither can authorize a protected side effect.

## 5. Integrations

External systems are accessed through adapters or integrations.

Current important boundaries include:

- AI providers;
- Sofias Memory;
- web/search providers;
- OS/filesystem/process capabilities;
- future external integrations.

Adapters normalize external behavior into internal contracts and must not leak
provider-specific authority into the domain.

## 6. Deployment and development context

The approved development model is source-first:

```text
git clone
cd core
py setup.py
py main.py
```

`core/` owns the Python environment, dependencies, entry points, source and
tests. Repository-root Python environments or caches are invalid local state.

Ordinary development and human validation do not use PyInstaller, `build/`,
`dist/` or prebuilt executables.

## 7. Legacy topology

The repository currently contains a previously implemented two-process
Desktop/Core topology with authenticated loopback HTTP/WebSocket transport.

That implementation is valid historical work but no longer defines the target
runtime topology.

During migration:

- preserve domain behavior and security invariants;
- avoid deleting useful services merely because their transport changes;
- remove process supervision and localhost transport from the Desktop critical
  path only when an equivalent in-process application path is working;
- keep an optional API adapter only where it provides concrete value.

## 8. MVP validation gate

The next architectural success condition is not "build succeeds". It is:

> A human can start Sofia from source, use the visual interface, converse,
> approve/deny protected actions, observe errors and execute useful real
> workflows.

Release packaging is not a target of the current product architecture.
