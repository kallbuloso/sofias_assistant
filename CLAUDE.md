# CLAUDE.md — Sofia's Assistant

> Project-level operating instructions for Claude Code and other coding agents working in this repository.

## 1. Purpose

This file exists so the user does **not** need to repeat the project introduction, architecture baseline, workflow rules, quality commands, or reporting expectations in every implementation prompt.

When working in this repository:

1. read this file first;
2. discover the real Git root and current repository state;
3. read the active execution plan, when one exists;
4. read only the ADRs/contracts directly relevant to the requested work;
5. implement with senior autonomy;
6. stop only for a genuine human decision or blocker.

Do **not** begin responses with boilerplate such as:

> "You are working on the Sofia's Assistant project..."

Assume that context from this file unless the user explicitly overrides it.

---

# 2. Product

**Sofia's Assistant** is a local-first, single-user personal AI assistant.

The first public technical MVP is `v0.1.0`.

The product is initially **Windows-first**, but the Core must remain portable to **Linux/VPS** and later other desktop/server environments without architectural redesign.

The product is not intended to be merely a chatbot. Sofia is a persistent assistant capable of combining:

- text conversation;
- realtime voice;
- long-term cognitive memory;
- working context;
- multiple AI providers and models;
- tools;
- durable tasks;
- specialized sub-agents;
- scheduling and reminders;
- notifications;
- web research;
- filesystem/shell/desktop capabilities;
- recovery;
- audit;
- future plugins/integrations.

The user-facing product must evolve toward a real, intuitive human experience. Architectural correctness is necessary but not sufficient.

---

# 3. Repository

Repository:

```text
kallbuloso/sofias_assistant
```

Top-level structure:

```text
/
├── CLAUDE.md
├── README.md
├── product/
│   └── docs/
│       ├── Sofia's Assistant — Product Requirements Document.md
│       ├── Sofia's Assistant — Technical Backlog Map.md
│       ├── Sofia's Assistant — Coding & Testing Conventions Baseline.md
│       └── adr/
└── core/
    ├── pyproject.toml
    ├── uv.lock
    ├── .env.example
    ├── src/
    │   └── sofias_assistant/
    ├── tests/
    └── docs/
        ├── exec-plans/
        │   ├── active/
        │   └── completed/
        └── release-notes/
```

Do not assume a fixed local path such as `D:\...` or `C:\...`.

Always discover the actual Git root.

---

# 4. Communication and naming

## 4.1 Human communication

Use **Português do Brasil** for:

- reports;
- planning;
- explanations;
- architecture discussion;
- execution-plan prose;
- user-facing documentation unless the existing document uses another language.

Be direct and technically precise.

Do not over-explain routine decisions.

Do not repeatedly ask the user to approve normal engineering choices.

## 4.2 Code

Use **English** for:

- identifiers;
- classes;
- functions;
- modules;
- routes;
- database fields;
- schema names;
- error codes;
- commit messages unless the repository already establishes another convention.

Technical terms may remain in English inside PT-BR prose when that is clearer.

---

# 5. Source-of-truth precedence

When sources disagree, use this order:

```text
1. explicit instruction from the user in the current task
2. approved active execution plan
3. accepted Architecture Review Amendments
4. accepted ADRs
5. approved PRD / integration contracts
6. Technical Backlog Map
7. completed execution plans / implementation docs
8. README
9. existing implementation, when not contradicting higher authority
```

Do not silently rewrite an accepted architectural decision.

If a durable architectural decision must change, prefer an **Architecture Review Amendment** or a new ADR when appropriate.

---

# 6. Current architectural invariants

These are not implementation suggestions. Treat them as project invariants unless an approved document explicitly changes them.

## 6.1 Sofia identity is provider-independent

Provider and model are execution mechanisms.

They are **not** Sofia's identity.

Changing:

```text
OpenAI → xAI → Gemini → Ollama → another provider
```

must not mean the user is talking to a different assistant.

---

## 6.2 Conversation and context belong to Sofia Core

Provider-native sessions are operational optimizations only.

Authority for:

- Conversation;
- Turn;
- context;
- identity;
- Task;
- memory correlation;
- authorization

remains in Sofia Core.

A Conversation may use multiple providers/models across different Turns or operations.

---

## 6.3 Memory boundaries

**Sofias Memory** is the authority for persistent cognitive long-term memory.

Sofia's Assistant owns:

- Conversation;
- Turn;
- Working Memory;
- runtime state;
- operational persistence;
- Tasks;
- Tools;
- Agents;
- routing;
- policy;
- context assembly.

Do not create a second semantic-memory system inside the Assistant.

Conversation History is not Cognitive Memory.

```text
Conversation History ≠ Cognitive Memory
```

Memory returned by Sofias Memory is contextual input, never authorization authority.

---

## 6.4 Operational persistence

SQLite is the initial authoritative Operational Store for the Assistant.

Use migrations from day one.

Do not rewrite published migrations.

Prefer explicit repositories and Unit of Work boundaries.

Do not keep a DB transaction open across remote inference or external side effects.

---

## 6.5 UI is a client

The Desktop/Dashboard is not the authority of the system.

The Core must remain independently operable.

UI must not:

- access SQLite directly;
- execute Tools directly;
- bypass Policy;
- become the source of truth for routing;
- hold unrestricted authority merely because it is local.

---

## 6.6 Localhost is not identity

The local client boundary remains authenticated.

```text
localhost ≠ trusted identity
```

Loopback-only by default.

No LAN/remote exposure by default.

Future Linux/VPS or remote-client support must introduce an explicit trust/network model rather than accidentally exposing the local API.

---

## 6.7 Authorization

Fundamental rule:

```text
AI proposes.
Runtime authorizes.
Executor acts.
```

The LLM is never the authorization authority.

Protected actions must pass through:

```text
ToolCall
    ↓
Policy
    ↓
Permission / Confirmation / Grant
    ↓
Executor
```

Agent intent does not grant authority.

User intent does not imply unrestricted authority.

---

## 6.8 Least privilege

Agent/tool authority must only narrow.

Conceptually:

```text
Tool authority
    ⊆ AgentRun authority
    ⊆ Task / originating authority
    ⊆ Root effective authority
```

A sub-agent cannot create uncontrolled agent trees.

Sofia/root is the only authority that creates AgentRuns.

---

## 6.9 Task is not a universal wrapper

Use the least complex mechanism capable of solving the work.

Immediate bounded operations may use Direct Invocation.

Use durable Task lifecycle when work needs properties such as:

- background execution;
- waiting;
- scheduling;
- AgentRun;
- recovery;
- retry semantics;
- multi-step coordination;
- progress tracking.

Do not create Tasks merely for architectural uniformity.

---

## 6.10 Recovery

Do not blindly retry uncertain side effects.

Safe automatic retry requires positive evidence of safety, not absence of evidence of danger.

Mutating/non-idempotent uncertain work must fail closed or require reconciliation/user decision.

Do not resume hidden LLM/agent reasoning state after process loss.

Process IDs are evidence, not authority to adopt/kill arbitrary processes after restart.

---

## 6.11 Audit

Audit actions, decisions, authority, execution facts and outcomes.

Do **not** persist hidden chain-of-thought.

Do not leak credentials or sensitive payloads into Audit/logs.

---

# 7. AI provider and routing architecture

The project is intentionally **multi-provider and multi-model**.

The original product design explicitly expects different models/providers for different workloads.

Examples:

```text
fast chat           → small/cheap/low-latency model
general chat        → balanced model
coding              → stronger coding/reasoning model
research            → research-capable model
vision              → vision-capable model
realtime voice      → realtime/native-audio model
transcription       → transcription model
utility extraction  → small structured-output model
embeddings          → embedding model/provider
```

Do not assume one model should handle everything.

---

## 7.1 CapabilityRouter

`CapabilityRouter` is a valid architectural foundation and must not be replaced casually.

Its role is evolving from:

```text
capability/locality compatibility filter
```

toward:

```text
deterministic executor of configurable routing policy
```

The Core requests requirements.

The Router selects compatible execution.

The provider performs inference.

```text
Domain requests capabilities.
Router selects execution.
Provider performs inference.
```

Never scatter provider-specific `if` statements through domain code.

---

## 7.2 Capability vs workload/profile

Keep these concepts distinct.

### Capability

Answers:

> What can this model do?

Examples:

```text
TEXT_GENERATION
TEXT_STREAMING
TOOL_CALLING
STRUCTURED_OUTPUT
IMAGE_INPUT
REALTIME
AUDIO_INPUT
AUDIO_OUTPUT
```

Additional capabilities may be added when needed, such as:

```text
REASONING
TRANSCRIPTION
TEXT_TO_SPEECH
EMBEDDING
VIDEO_INPUT
```

Do not create speculative capability values without a real use case.

### Inference Profile

Answers:

> What kind of work are we executing?

Current post-MVP direction includes profiles conceptually similar to:

```text
chat.fast
chat.general
reasoning
coding
research
vision
realtime
transcription
utility
```

Agents should prefer declaring an inference profile/workload rather than hardcoding a provider/model.

Example:

```text
DevelopmentAnalysisAgent
    ↓
profile = coding
    ↓
routing policy
    ↓
compatible provider/model
```

---

## 7.3 Context continuity across models

Do not preserve continuity by pinning one provider forever.

Continuity is preserved through Core-owned:

- Conversation;
- ContextBuilder;
- Working Memory;
- Sofias Memory;
- Task state;
- selected context;
- tool observations.

Different Turns and operations may use different models without changing Sofia identity.

---

## 7.4 Routing policy

Routing may consider:

- hard required capabilities;
- preferred capabilities;
- data locality;
- inference profile / workload;
- explicit user binding;
- provider/model availability;
- health;
- context size;
- latency preference;
- cost preference;
- quality preference;
- fallback rules.

Hard requirements always win over preferences.

An explicit model choice may bypass preferences but must **never** bypass hard compatibility, locality or policy.

---

## 7.5 Fallback

Fallback is allowed only to a candidate compatible with:

- required capabilities;
- locality;
- policy;
- profile constraints.

Never do this:

```text
LOCAL_ONLY
    ↓ local unavailable
silently send to cloud
```

Never use the canonical/default model as fallback if it does not satisfy hard requirements.

---

# 8. Post-v0.1 configuration direction

The following direction has been explicitly approved by the product owner and is being formalized in upcoming architecture documentation.

Do not implement it merely because it appears here unless the current task/active plan authorizes that implementation.

## 8.1 `.env` / environment

The project will allow installation-level bootstrap configuration and credentials through `.env` / environment variables.

Target style:

```env
# Canonical/default LLM bootstrap
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-change-me
LLM_MODEL=example-model

# Sofias Memory
SOFIAS_MEMORY_ENABLED=true
SOFIAS_MEMORY_BASE_URL=https://example.invalid
SOFIAS_MEMORY_API_KEY=change-me
```

The `.env` file is local and git-ignored.

`.env.example` contains placeholders only.

Real environment variables must remain usable for Linux/VPS/Docker/systemd deployments.

---

## 8.2 Secret abstraction remains

Allowing credentials in `.env` does **not** authorize provider adapters to call `os.getenv()` directly.

Preferred architecture:

```text
.env / process environment
        ↓
Environment-backed SecretStore / configuration boundary
        ↓
SecretService
        ↓
Provider / Integration Adapter
```

`SecretService` remains a Core-wide boundary.

Do not persist plaintext provider API keys in normal SQLite configuration tables.

---

## 8.3 Canonical/default model

`LLM_MODEL` is a bootstrap/default model.

It is **not** the permanent router for every AI operation.

Use it for cases such as:

- initial startup/defaults;
- unconfigured profiles;
- compatible fallback;
- setup/recovery.

It must still satisfy the operation's hard requirements.

---

## 8.4 Dynamic AI configuration belongs in the Operational Store

Frequently changing AI configuration should not require monthly `.env` edits.

The current direction is to persist operational AI configuration in SQLite, such as:

```text
ProviderConfiguration
ModelCatalogEntry
InferenceProfile
ProfileModelBinding
routing preferences
availability / health observations
fallback policy
```

Secrets remain outside normal plaintext operational rows.

---

## 8.5 Model catalog must evolve dynamically

Avoid eternal source-code lists such as:

```python
SUPPORTED_MODELS = [...]
```

Provider model offerings change quickly.

Model existence may be discovered through provider mechanisms when supported.

Do not assume model discovery automatically proves all capabilities.

Capability metadata may come from sources such as:

```text
DISCOVERED
BUILTIN_METADATA
PROBED
USER_OVERRIDE
```

Keep provenance where useful.

---

## 8.6 Dashboard comes after Core contract

The Dashboard must become a client of a stable Core configuration contract.

The intended product flow is:

```text
Dashboard
    ↓
Core AI configuration API
    ↓
Operational AI configuration
    ↓
Routing Policy
    ↓
CapabilityRouter
```

The UI configures.

The Core validates and remains authority.

---

# 9. Human product direction

`v0.1.0` proved the technical MVP/kernel.

Post-MVP work must move toward a product that a human can actually use.

The normal user should not need to understand:

- `LocalClientBoundary`;
- ephemeral bearer credentials;
- port 8989;
- `SecretRef`;
- `CapabilityRouter`;
- internal runtime session IDs.

Target human experience:

```text
launch Sofia
    ↓
Core starts/attaches automatically
    ↓
Desktop authenticates automatically
    ↓
user sees chat/dashboard
    ↓
user interacts
```

Keep Core and UI architecturally separated even if one launcher starts both.

Do not solve UX problems by weakening Core boundaries.

---

# 10. Current post-MVP documentation sequence

Before major post-MVP implementation, the intended documentation sequence is:

```text
1. Architecture Review Amendment 0003
   AI Runtime Configuration, Secrets and Dynamic Routing

2. Sofia's Assistant — AI Runtime Configuration Contract v1

3. Sofia's Assistant — Technical Backlog Slice 09
   Core Runtime Configuration & Intelligent AI Routing

4. implementation Runs/Gates

5. human Core smoke

6. later Slice for Dashboard/Desktop UX
```

If these files exist in the repository, read them before implementing related work.

---

# 11. External reference projects

The project deliberately uses external projects as implementation/UX references, especially:

- Mark LI;
- Brahma AI;
- topoteretes/cognee where relevant to Sofias Memory history/integration.

Reference harvesting is encouraged when useful.

Use references to accelerate:

- UI/UX patterns;
- launcher/runtime patterns;
- provider configuration;
- agent orchestration mechanics;
- model discovery;
- routing;
- workflow ergonomics.

Do not wholesale-copy architecture.

Do not import weaker security/authority assumptions.

Check licensing before adapting meaningful implementation.

Record important decisions as:

```text
REUSED
ADAPTED
REJECTED
```

when an execution plan requests a Reference Harvest.

---

# 12. Pre-flight for implementation work

Before modifying code:

```powershell
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
```

If needed:

```powershell
git fetch origin
```

Do not assume the local checkout path.

Do not use destructive commands merely to obtain a clean tree.

Never automatically:

```text
git reset --hard
git clean -fd
git checkout -- .
automatic stash
```

Preserve user work.

If there are unrelated local modifications that conflict with the requested task, stop and report the conflict.

---

# 13. Active execution plans

When `core/docs/exec-plans/active/` contains an approved plan relevant to the task, it is the implementation contract.

Before coding:

1. read the plan;
2. read its referenced ADRs/contracts;
3. inspect the current code paths;
4. perform the required Reference Harvest if specified;
5. implement only the requested Run/Gate unless explicitly authorized to continue.

Do not silently implement the next Gate.

Do not move a Slice to `completed/` until its closure conditions are actually met.

---

# 14. Senior autonomy

The user expects senior-level autonomy.

Do not ask for approval for ordinary choices such as:

- file names;
- test organization;
- small refactors;
- internal helper naming;
- fixture design;
- exact decomposition of a coherent implementation package.

Stop for human decision only when there is a genuine product/architecture/security/release choice not already decided.

Examples:

- incompatible accepted ADRs;
- destructive migration requirement;
- security boundary change;
- new public contract with ambiguous semantics;
- feature scope requiring a new product decision;
- credentials or infrastructure unavailable with no deterministic substitute;
- irreversible publication action not already authorized.

---

# 15. Avoid overbuilding

Do not turn every finding into a new framework.

Prefer the smallest coherent implementation that satisfies the approved architecture.

Avoid introducing without clear need:

- universal workflow engines;
- generic plugin frameworks before their Slice;
- distributed worker systems;
- global exactly-once claims;
- saga frameworks;
- process checkpoint/restore;
- generic event sourcing;
- unnecessary abstraction layers.

Use existing project seams before creating new ones.

---

# 16. Python/runtime baseline

Current baseline:

```text
Python >=3.13,<3.14
uv
src layout
SQLite operational store
async-aware runtime
PySide6 Desktop Client
```

Run commands from `core/` unless the command is explicitly repository-root scoped.

Setup:

```powershell
cd core
uv sync
```

Quality:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

Formatting:

```powershell
uv run ruff format .
```

Packaging when relevant:

```powershell
uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec
```

Packaged smoke when relevant:

```powershell
dist\SofiaAssistant.exe --smoke
```

Do not run paid/live provider tests unless the task explicitly requires them.

---

# 17. Testing expectations

Prefer deterministic tests.

Test at the correct boundary:

- unit tests for domain logic;
- integration tests for persistence/lifecycle/boundaries;
- Gate tests for accepted feature behavior;
- live smoke only when necessary.

Do not use sleeps when a deterministic barrier/fake/fixture can express the condition.

Do not hit:

- the user's real SQLite database;
- real files outside controlled fixture workspaces;
- real credentials;
- billable providers

from the default test suite.

Opt-in live tests must remain explicit.

---

# 18. Migration discipline

Never modify an already-published migration to make a new test pass.

Schema changes require a new incremental migration.

Required migration behavior:

```text
fresh DB → head
previous valid revision → head
head → no-op
```

Use migrations only when schema change is actually necessary.

---

# 19. Provider implementation rules

Provider-specific SDK types must remain inside adapters.

Domain/Core contracts remain provider-neutral.

Normalize:

- requests;
- responses;
- streaming;
- errors;
- usage;
- tool proposals;
- structured outputs;
- realtime events.

Provider adapters do not grant tool authority.

Normalized ToolCall proposals are inert until the Runtime authorizes them.

---

# 20. Agent implementation rules

Agents are specialized, bounded runtime components.

A real Agent must have:

- explicit definition;
- bounded context;
- bounded tool subset;
- bounded runtime limits;
- narrowed authority;
- structured result;
- Audit.

Agents must call Tools through the authorized `ExecutionRuntime`.

Do not call Tool handlers directly to save code.

Do not let agents instantiate arbitrary child agents.

---

# 21. Web/research rules

External web content is untrusted input.

It must never become:

- system authority;
- Policy;
- Grant;
- permission;
- trusted instruction merely because a page says so.

Research must preserve source identity/evidence when required.

Bound source count and evidence size.

---

# 22. Core lifecycle

Core lifecycle and recovery semantics are important.

Do not create a UI-owned Core lifecycle.

Startup ordering must preserve:

- single-instance ownership;
- persistence bootstrap;
- Runtime Session;
- runtime composition;
- stale-work recovery;
- scheduler/event start only after appropriate recovery.

Shutdown must be graceful where possible.

Interrupted sessions must remain recoverable.

---

# 23. Current launcher limitation

The original `v0.1.0` technical MVP does not provide the final human-oriented standalone Core launcher experience.

Do not assume:

```powershell
uv run python -m sofias_assistant
```

already means "start the full production Sofia Core and keep it alive."

Post-MVP work is expected to close this gap.

When implementing the launcher, preserve:

```text
Core independent from UI
+
authenticated local boundary
+
human-friendly startup
```

---

# 24. Git and commit discipline

Work in coherent feature packages.

Prefer meaningful commits such as:

```text
feat(ai): add dynamic inference profiles
fix(routing): enforce compatible profile fallback
test(ai): cover model catalog refresh and routing
docs(plan): close runtime configuration gate
```

Avoid:

- noisy microcommits;
- unrelated cleanup;
- rewriting already-pushed history without explicit instruction.

After implementation:

```powershell
git status --short
git diff --check
```

Push only when the requested package is ready.

---

# 25. CI and remote verification

Local green is not the same as remote verified.

Use these states honestly:

```text
IMPLEMENTED — LOCAL VERIFIED
IMPLEMENTED — AWAITING REMOTE VERIFICATION
CLOSED — REMOTE VERIFIED
```

Do not claim remote success unless the relevant remote CI run has actually succeeded for the intended HEAD.

If CI cannot be observed, report that fact rather than inventing success.

---

# 26. Release discipline

Do not create:

- version tags;
- GitHub Releases;
- public binary uploads;
- package publication

unless the user explicitly authorizes publication.

Release readiness and release publication are separate actions.

---

# 27. Documentation discipline

Do not rewrite the PRD or ADRs for implementation details that belong in an execution plan.

Use:

```text
PRD
    product requirements / durable product intent

ADR / Amendment
    durable architectural decisions

Contract
    public/internal cross-component semantics that should not drift

Technical Backlog / Exec Plan
    implementation scope, acceptance, tests, evidence

Implementation docs / release notes
    realized behavior and closure record
```

Prefer amendments over silently changing the historical meaning of an accepted ADR.

---

# 28. Reporting

After a meaningful implementation package, return a compact engineering report.

Default shape:

```text
Scope:
Status:

What changed:
Tests:
Quality:
Migration:
Security/architecture notes:

Commits:
Final HEAD:
origin/main:
CI:
Blockers:
Deferred:
```

For Gate work, include the Gate verdict exactly as required by the active plan.

Do not paste enormous logs unless a failure requires them.

Do not ask the user to run another reporting agent merely to repeat information already available from Git/CI.

---

# 29. Findings

Classify findings before acting.

```text
BLOCKER
    prevents acceptance or violates architecture/security

IN-SCOPE HARDENING
    belongs naturally to the current package

DEFERRED
    real but not necessary for current acceptance

OUT-OF-SCOPE
    unrelated to requested work
```

Do not inflate every small observation into a new backlog item.

---

# 30. Definition of done

A package is not done merely because code compiles.

Depending on scope, completion should include:

```text
correct implementation
+
targeted tests
+
full relevant regression
+
ruff
+
format check
+
mypy
+
pytest
+
git diff --check
+
packaging/smoke when affected
+
documentation/ledger when required
+
commit/push
+
remote CI when closure requires it
```

---

# 31. Final working principle

Build Sofia as a **real product**, not only as a collection of technically correct subsystems.

At the same time:

> do not solve product UX by weakening Core boundaries.

The intended evolution is:

```text
strong Core
    ↓
configurable multi-provider/model runtime
    ↓
stable Core API/contracts
    ↓
human-friendly Dashboard/Desktop
```

When a task can be solved by extending an existing architectural seam, do that before inventing a parallel mechanism.
