# Sofia's Assistant — Technical Backlog Slice 02

**Scope:** SA-B007, SA-B008 and SA-B010  
**Target Gate:** I2 — Sofia Can Converse  
**Status:** Proposed execution plan  
**Source:** Approved Technical Backlog Map  
**Architecture baseline:** ADR-0001, ADR-0002, ADR-0004, ADR-0005, ADR-0006,
ADR-0008, Architecture Review Amendments 0001 and 0002, and completed Slice 01

---

# 1. Objective

This slice establishes Sofia's first durable, provider-independent text
conversation kernel. It materializes the technical foundations of:

```text
SA-B007 — AI Provider Framework
SA-B008 — Conversation Runtime
SA-B010 — Context Builder
```

At the end of the slice, an authenticated local client must be able to create
and continue a text Conversation through the existing loopback boundary. The
Conversation Runtime must build Core-owned context, route a capability request
to a compatible provider adapter, receive normalized streaming events, and
durably record the resulting Turn without making a provider or its session the
authority for Sofia's Conversation.

The deterministic Fake Provider is the primary correctness mechanism for CI.
An opt-in real-provider smoke path will demonstrate adapter integration later,
but will not be required by the default test suite.

---

# 2. Gate I2 — Sofia Can Converse

Gate I2 is eligible for closure only when all of the following are proven:

1. a text Conversation belongs to Sofia Core and has a Core-owned identity;
2. an authenticated local client can start and continue it;
3. the Conversation remains valid independently of any provider session;
4. providers are reached only through internal adapter contracts;
5. provider/model selection can change without changing Conversation Runtime
   semantics or Conversation identity;
6. ContextBuilder, not the provider, is authoritative for the context sent;
7. the default context is not the full conversation transcript;
8. Conversations and relevant Turns are durable in the Operational Store;
9. text streaming is represented by normalized internal events;
10. provider failure leaves the Conversation valid and does not falsely mark a
    Turn as completed;
11. CI is deterministic and does not call external provider APIs; and
12. an explicit, opt-in smoke path exists for one approved real provider.

Expected closure verdict after evidence is collected:

```text
GATE I2: PASS
```

---

# 3. Inherited Architectural Decisions

## 3.1 AI execution direction

The mandatory direction from ADR-0004 is:

```text
Domain requests capabilities.
Router selects execution.
Provider performs inference.
```

Consequently, the following dependencies are prohibited:

```text
ConversationRuntime -> OpenAI SDK / Gemini SDK / provider-native objects
ContextBuilder      -> provider-native objects
Core domain         -> FastAPI, Uvicorn, or provider SDK mechanics
```

Only a provider adapter may import and translate a concrete provider SDK. A
provider and model are execution mechanisms; neither is Sofia's identity.

## 3.2 Conversation and provider-session ownership

```text
Conversation belongs to Sofia.
Provider sessions belong to providers.
```

`conversation_id` and `turn_id` are Core-owned durable identifiers. Provider
request IDs, server-side session IDs, cache IDs, and resumption tokens are
optional operational correlations only. Losing a provider session must never
delete, replace, or make unrecoverable a Sofia Conversation.

## 3.3 Context ownership and locality

```text
Context != full transcript.
```

ContextBuilder is a Core-owned service. It selects and projects eligible data
before a request reaches a provider adapter. A provider never decides by itself
which history, identity principles, or future memory/task/tool material enters
the request.

The request's locality requirement is an input to both projection and routing:
ContextBuilder excludes context that may not leave the permitted locality, and
the Router selects only a model/provider satisfying that requirement. Ambiguity
must fail closed; `LOCAL_ONLY` never silently falls back to cloud.

## 3.4 Authorization and ToolCall boundary

This slice may normalize a provider's ToolCall proposal because it is part of a
complete AI contract. It must explicitly preserve:

```text
normalized ToolCall != authorized Tool execution
```

No Policy Engine, Grants, Delegations, Tool Registry, Tool Runtime, handler, or
Tool execution is introduced in this slice. Provider proposals are only data
that remains compatible with the later ADR-0006/ADR-0008 boundaries.

## 3.5 Existing Core and local-boundary separation

SofiaCore may compose new domain/application services, repositories, and
provider boundaries. It must remain transport-agnostic: it must not import
FastAPI, Uvicorn, `LocalClientBoundary`, or transport mechanics. The HTTP
adapter remains responsible for Pydantic schemas and translates requests into
Core-facing conversation operations.

---

# 4. Scope and Non-goals

## In scope

- Provider-independent AI contracts, routing, model metadata, and normalized
  errors/events;
- deterministic Fake Provider and provider-boundary contract tests;
- durable text Conversation and Turn domain/persistence;
- Core-owned context projection, locality filtering, and deterministic budget;
- text Conversation Runtime and normalized streaming lifecycle;
- authenticated local HTTP conversation routes using the existing Bearer plus
  ClientSession authentication dependency;
- a later approved first real-provider adapter and an opt-in smoke test;
- integration hardening and Gate I2 audit evidence.

## Explicit non-goals / deferred items

The following remain outside Slice 02:

- realtime voice, audio input/output, VAD, wake word, and audio barge-in;
- WebSocket realtime transport;
- Sofias Memory integration, including Memory Session APIs, SessionEntry
  mirroring, Skills integration, Agent Profile integration, Memory Orchestrator,
  Cognitive Memory, recall, MemoryCandidate, or cognitive-memory persistence;
- Policy Engine, Grants, Delegations, and Tool execution;
- Tasks, Agents, Scheduler, filesystem/shell/web tools;
- Desktop Client, CORS, remote/LAN API, TLS, and a plugin framework;
- advanced provider health, polling, cost routing, and sophisticated fallback;
- advanced context summarization/compression; and
- crash-recovery hardening for interrupted work.

Process host and signal ownership also remain deferred from Slice 01. Nothing
in this slice creates a second Core lifecycle owner.

---

# 5. Planned Internal Contracts

The concrete module layout will be selected during implementation, keeping
coherent responsibilities rather than creating empty packages prematurely. All
domain/application contracts remain typed Python models (for example frozen
dataclasses and enums), never HTTP/Pydantic or provider SDK shapes.

## 5.1 AI contracts and identifiers

SA-B007.1 defines the minimum provider-independent vocabulary:

```text
Capability
DataLocality
ModelIdentity
ModelDescriptor
AIRequestRequirements (required capabilities, preferred capabilities, locality)
AIRequest
TextResponse
StructuredOutput request/result contract
UsageMetadata
Correlation identifiers
Normalized ToolCall proposal
Normalized ProviderError
```

`ModelDescriptor` contains only `identity`, `capabilities`,
`execution_location`, and optional `context_window`. `ModelRegistration`
contains the descriptor, provider binding, `enabled`, and `availability`.
`DataLocality` is request policy/requirement; `ExecutionLocation` is a model
characteristic. Unknown capability is unsupported, never assumed supported.
The initial interfaces will be specialized—for example a text generation stream
contract and structured-output capability—rather than a universal
`AIProvider.chat/embed/realtime/...` interface. Realtime gets only a future
extension seam; no `RealtimeProvider` is materialized in this text slice.

Structured-output requests remain internal contracts. Each adapter will choose
the provider-native mechanism (such as native schema, constrained generation,
or an explicitly supported translation) without exposing that mechanism to
Conversation Runtime.

## 5.2 Normalized provider streaming

The baseline uses this small, ordered stream taxonomy, frozen in SA-B007.1:

```text
TextDelta
ToolCallProposed
UsageUpdated
ProviderCompleted
ProviderFailed
```

`TextDelta` is partial, ordered text and is not a final Turn result.
`ProviderCompleted` is the unique successful terminal event.
`ProviderFailed` is the unique failure terminal event and carries a normalized
`ProviderError`. No event follows either terminal. ToolCall proposals and usage
may occur before completion but never authorize execution.

Raw SDK events stay inside adapters. Deltas are normally ephemeral delivery
events. Final output, final Turn status, and safe error/correlation/usage
metadata needed for durable operational history are persisted deliberately;
partial output is never silently persisted as final. The exact retention of
partial output will be explicit in the Turn model, not accidental.

## 5.3 Conversation contracts

The domain will expose explicit concepts for `Conversation`, `Turn`, Turn
status, text content, and safe provider correlation metadata where needed. A
`ContextProjection` (or an equally precise name) will be a Core-owned input to
an `AIRequest`, not a provider-native prompt object.

Conversation-facing operations will use explicit commands/results/events
instead of HTTP payloads. The HTTP adapter receives and serializes transport
schemas only at its outer boundary.

---

# 6. Subpasses

Each subpass is a small, reviewable, commit-ready unit. It must preserve the
quality gates in section 12 before approval. The listed commit subjects are
recommended intent only and will not be created by this plan.

## SA-B007.1 — AI Contracts & Normalized Types

**Goal:** establish provider-neutral contracts before choosing a provider SDK.

**Implementation scope:**

- Define capabilities, required versus preferred requirements, data locality,
  model identity/descriptors, availability baseline, request/correlation IDs,
  text and structured-output contracts, usage metadata, normalized ToolCall
  proposals, and normalized error categories.
- Define specialized provider protocols for the text/streaming and structured
  output capabilities needed by this slice. Do not create an all-purpose
  provider interface or a concrete realtime implementation.
- Define ordered normalized stream events and terminal semantics described in
  section 5.2.
- Keep provider SDK imports absent from the Core and these contracts.

**Acceptance/tests:** unit tests cover value invariants, capability matching
inputs, locality values, correlation propagation, normalized error safety, and
event ordering/terminal rules. Tests prove ToolCall is proposal data only.

**Recommended commit:** `feat(ai): add provider contracts`

## SA-B007.2 — Model Registry & Capability Router

**Goal:** select an eligible execution target predictably.

**Implementation scope:**

- Add a deterministic Model Registry of explicitly registered model/provider
  descriptors and their adapter binding.
- Add an AI Router that considers required capabilities, preferred
  capabilities, data locality, enabled/available candidates, and an explicit
  override when supplied.
- Use simple deterministic ordering, not scoring heuristics, background health
  probes, or speculative cost optimization.
- Reject an unknown requirement, no eligible candidate, and an incompatible
  explicit override with clear internal errors.
- Represent only the minimum provider/model availability state needed by
  routing and compatible with existing health concepts. Do not add polling,
  background probes, or a separate health subsystem.

**Mandatory rules:** required capabilities cannot be relaxed; preferences may
be relaxed only through documented deterministic selection; `LOCAL_ONLY` may
never choose cloud; routing has no Tool-execution authority.

**Acceptance/tests:** registry collision/enablement tests; required/preferred
selection tests; unavailable-model handling; override incompatibility;
unknown-capability rejection; and locality adversarial tests.

**Recommended commit:** `feat(ai): add capability routing`

## SA-B007.3 — Deterministic Fake/Test Provider

**Goal:** make all normal CI conversation behavior independent of external
services.

**Implementation scope:** provide a scripted, in-memory Fake Provider that
implements the same specialized contracts and can deterministically produce:

- a final text response;
- ordered streaming text deltas followed by completion;
- a normalized terminal provider error;
- structured output;
- normalized ToolCall proposal(s); and
- usage metadata where applicable.

**Acceptance/tests:** provider contract tests run the same expected behaviors
against the fake; no test prints credentials or contacts a provider network.
The Fake is a test boundary, not a provider-specific shortcut in Conversation
Runtime, Router, or ContextBuilder.

**Recommended commit:** `test(ai): add deterministic fake provider`

## SA-B008.1 — Conversation Domain & Operational Persistence

**Goal:** make Sofia-owned Conversations and text Turns durable before adding
inference.

**Implementation scope:**

- Introduce the minimum explicit `Conversation` and `Turn` durable models with
  UUID Core-owned identities and UTC-aware timestamps.
- Add Alembic migration(s), persistence mappings, repositories, and explicit
  Unit-of-Work operations. Alembic remains the only schema authority; no
  `create_all` or implicit commits.
- Define explicit Turn lifecycle states semantically equivalent to processing,
  completed, interrupted, and failed. A partial provider output cannot be
  represented as a completed final output merely for convenience.
- Preserve a small multimodal evolution seam: text is the only supported
  modality now, while the model distinguishes content/modality and lifecycle
  explicitly enough to add voice/attachments later. Do not build a generic JSON
  event store or speculative attachment system.
- Permit safe provider request/session correlation metadata only as operational
  information; it never replaces Conversation or Turn identity.
- Preserve `Turn.cloud_context_eligible` as a durable, conservative eligibility
  for historical Turn content to be reused in a cloud-bound ContextProjection.
  It is distinct from `DataLocality`, which remains a per-operation
  routing/locality requirement.
- Keep Conversation and Turn SQLite-authoritative. Reserve the future,
  deterministic external Memory Session correlation
  `sofias-assistant:conversation:{conversation_uuid}` without persisting a
  redundant `memory_session_id` in this slice.
- Preserve `Turn != SessionEntry`: no automatic Turn-to-Memory mirroring is in
  scope, and partial streams, failed output, provider/routing events, reasoning,
  and Tool traces are not implied future SessionEntry content.
- Keep Core/Turn identities suitable as stable future correlation/idempotency
  inputs for a post-commit external cognitive operation.

**Transaction rule:** repository/UoW boundaries are explicit and short. The
later inference network call must not occur in the same transaction that marks
a Turn processing. No Memory call may occur inside a SQLite UoW; any approved
future cognitive operation is optional and occurs only after local commit/UoW
closure.

**Acceptance/tests:** Alembic upgrade on temporary SQLite, persistence round
trip, Turn invariant/state-transition tests, UTC tests, repository/UoW no
implicit-commit tests, and reconstruction after recreating store/runtime
objects.

**Recommended commit:** `feat(conversation): add durable conversation model`

## SA-B010.1 — Context Projection Baseline

**Goal:** make the Core, not a provider, authoritative for text context.

**Implementation scope:**

- Add `ContextProjection` and a ContextBuilder service that receives Core-owned
  identity/system principles through an explicit injectable boundary.
- Project current user request, the appropriate current Turn, and a bounded
  set of recent relevant finalized Turns; never default to the entire
  transcript.
- Receive operation `DataLocality`, the selected `ModelDescriptor` (including
  execution location and context constraint), and eligible persisted Turns as
  inputs while keeping provider-native prompt objects out of the service.
- Establish small explicit future seams for Working Memory, Task context,
  ToolResults, Long-Term Memory, Recall, optional Memory Session context,
  selected Skill procedure, and Agent Profile instructions. None of those
  integrations is implemented in Slice 02. Do not create a generic contributor
  registry, plugin framework, Fake Memory, or Memory client.

**Locality rule:** ContextBuilder is authoritative for which context elements
are eligible to include. For a cloud execution target it must exclude every
persisted Turn whose `cloud_context_eligible` is false; for a local target that
flag alone does not exclude a Turn. Router is the first protection: it enforces
that the selected execution target is compatible with operation `DataLocality`.
ContextBuilder must not silently compensate for invalid routing or weaken
`LOCAL_ONLY`.

**Acceptance/tests:** recent-finalized-turn selection; excluded failed/
interrupted/non-eligible material as appropriate; no full-history default;
identity injection; locality exclusion; and domain/provider-object separation.

**Recommended commit:** `feat(context): add context projection`

## SA-B008.2 — Text Conversation Runtime

**Goal:** connect durable Conversation, ContextBuilder, Router, and provider
contracts in a Core-owned text service.

**Implementation scope:**

1. create or open a Conversation;
2. receive a user text command;
3. persist a processing Turn in a short transaction;
4. close that UoW;
5. construct AI request requirements;
6. Router selects a compatible model/provider;
7. ContextBuilder builds a ContextProjection using operation locality, the
   selected ModelDescriptor/execution location/context constraint, and eligible
   persisted Turns;
8. construct an AI request from that projection;
9. invoke the selected provider adapter;
10. persist final result, interruption, or normalized failure in a new short
   transaction; and
11. return application-level result/events to a transport adapter.

Conversation Runtime must not invoke a provider SDK, execute ToolCalls, or
hold SQLite transaction/session resources across network inference.

**Failure semantics:** a normalized provider failure marks the affected Turn
failed (or interrupted where cancellation semantics require it), never falsely
completed. The Conversation remains readable and may receive another Turn.
No blind retry framework is added. Any later fallback must remain compatible
with requirements and locality.

**Concurrency baseline:** Slice 01 guarantees a single Core process per
Operational Store; Slice 02 will implement the smallest explicit protection
needed against two processors finalizing the same Turn (for example an
optimistic state transition or conversation-level serialization). It will not
claim distributed consensus. The chosen boundary and its limitation will be
tested and documented in the subpass.

**Acceptance/tests:** Fake Provider plus real temporary Operational Store:
create, continue, successful final response, failure preserving Conversation,
provider/model substitution, and transaction scope around provider calls.

**Recommended commit:** `feat(conversation): add text runtime`

## SA-B010.2 — Context Budget / Locality / Projection Hardening

**Goal:** bound context deterministically and harden safe projection after the
first runtime path exists.

**Implementation scope:**

- Define a provider-independent baseline context budget and deterministic
  selection/omission policy, favoring current request and recent eligible final
  Turns.
- Do not rely on a provider-specific tokenizer in Core. Exact adapter token
  accounting may be exposed as optional descriptor metadata, but it cannot be
  required for baseline correctness.
- Reject or reduce an over-budget projection explicitly; never send everything
  and let a provider silently truncate it.
- Strengthen locality tests from ContextBuilder through Router selection.

Advanced summarization/compression remains deferred; this subpass does not
pretend that omission is semantic summarization.

**Acceptance/tests:** deterministic budget selection, stable omission order,
current-request preservation, no full-history expansion, context-limit error
handling, and `LOCAL_ONLY` no-cloud-fallback tests.

**Recommended commit:** `feat(context): harden projection budget`

## SA-B008.3 — Streaming & Turn Lifecycle

**Goal:** expose text streaming internally without coupling the domain stream
to an HTTP response.

**Implementation scope:**

```text
Provider normalized stream
    ↓
Conversation Runtime normalized Conversation events
    ↓
future transport adapter
```

- Translate provider events into Conversation-level events carrying stable
  Conversation/Turn/correlation identity.
- Ensure partial deltas are ordered and delivered as partial; only the terminal
  success path writes a completed final result.
- Define text cancellation/interruption baseline and persistence of the
  interrupted state without treating `CancelledError` as success.
- Persist final status/output and safe operational metadata after stream end;
  keep transport delivery mechanics and raw SDK events ephemeral.

B009 owns audio/realtime sessions, barge-in, and WebSocket behavior.

**Acceptance/tests:** scripted deltas, completion, normalized provider error,
interruption/cancellation, no finalization of partial output, and durable final
state after restart.

**Recommended commit:** `feat(conversation): add streaming lifecycle`

## SA-B008.4 — Authenticated Local HTTP Conversation Adapter

**Goal:** provide the smallest authenticated local vertical slice through the
existing FastAPI/Uvicorn boundary.

**Implementation scope:**

- Add only the routes required to create a Conversation, submit a text Turn,
  and retrieve the Conversation/Turn state needed to prove durability.
- Reuse the existing `require_session` authentication dependency exactly:

  ```text
  Authorization: Bearer <runtime credential>
      +
  X-Sofia-Client-Session-ID: <open UUID>
  ```

  No second authentication mechanism, unauthenticated Core route, or client
  lifecycle control is added.
- Keep Pydantic request/response/event models exclusively in the HTTP adapter.
  Do not expose provider-native metadata, raw provider exceptions, credentials,
  filesystem/configuration values, or internal Core representations.
- Use `StreamingResponse` with `application/x-ndjson` as the baseline for a
  streaming text-turn POST. NDJSON preserves ordered, transport-only records
  over a client POST without prematurely introducing WebSocket or SSE.
  Expected transport semantics are equivalent to `turn_started`, `text_delta`,
  `turn_completed`, `turn_failed`, and `turn_interrupted`; final wire names are
  confirmed with the normalized event contract in SA-B007.1.

**Acceptance/tests:** authentication failures for missing Bearer, missing
session, and session UUID alone; successful create/submit/retrieve flow;
NDJSON ordering/final record; safe error redaction; adapter with Core service
injection; and no global FastAPI app or new CORS behavior.

**Recommended commit:** `feat(client): expose authenticated conversation API`

## SA-B007.4 — Initial Real Provider Adapter

**Goal:** prove the generic boundary can host one external provider without
letting an SDK dictate the architecture.

**Precondition:** this subpass begins only after a separate implementation
review chooses the first provider and approves its SDK/dependency. Candidates
may include OpenAI, an OpenAI-compatible provider, Gemini, or another approved
option; no provider is selected by this plan.

**Selection criteria:** text generation, async Python support, streaming,
structured output, ToolCall proposal support, SDK/API isolation quality,
credential handling through SecretService, and suitability for adapter
contract tests.

**Implementation scope:** add the approved SDK only when justified, isolate it
inside one adapter, obtain its credential through `SecretService`, translate
all requests/events/errors/usage/structured output/ToolCalls to the internal
contracts, and avoid SDK imports elsewhere.

**Smoke test:** add a clearly marked opt-in test that uses SecretService, never
stores an API key in a fixture or file, never prints it, and is excluded from
default CI. It validates adapter wiring but is not the primary source of Gate
I2 correctness.

**Recommended commit:** `feat(ai): add initial provider adapter`

## Integration Hardening and Gate I2 Audit/Smoke

After the implementation commits are approved, run cross-boundary persistence,
HTTP, real loopback, redaction, and restart/reload tests. Perform the opt-in
real-provider smoke only with approved credentials and explicitly record its
result separately from deterministic CI. Then audit the implementation against
sections 2–5 and issue the Gate verdict.

---

# 7. Persistence and Transaction Plan

Conversation history is Operational Store data, not cognitive memory and not a
provider transcript. Persistence is SQLite file-backed through the existing
Operational Persistence architecture, with Alembic as sole migration authority,
UTC-aware timestamps, explicit repositories/UoW, and no global engine/session
maker.

The initial durable schema must be deliberately small. It will contain the
minimum Conversation and Turn tables/relationships necessary for Core-owned
identity, user and assistant text semantics, timestamps, lifecycle status, and
safe correlation metadata. It will not create Task, Agent, Memory, Tool,
provider-native event-store, or generic blob schemas prematurely.

The critical transaction sequence is mandatory:

```text
persist Turn PROCESSING
    ↓ close UoW
provider inference / stream (no open SQLite transaction)
    ↓
persist completed output OR failed/interrupted terminal state in a new UoW
```

Streaming must never retain an `AsyncSession`/UoW for the duration of a network
response. Persistence integration tests use actual Alembic-migrated SQLite in
`tmp_path`, never the user's Operational Store.

---

# 8. Security and Privacy Plan

- Existing local authentication remains mandatory for every Conversation HTTP
  route: a loopback connection or session UUID alone is insufficient.
- Runtime credentials and provider credentials remain `SecretValue`/SecretService
  values at the narrowest needed scope; neither is persisted in Conversation
  tables, configuration, responses, logs, exceptions, or repr output.
- Raw provider SDK exceptions are normalized internally and converted to
  client-safe errors at the HTTP boundary.
- Provider-specific identifiers/metadata are operational-only and are not
  serialized unless an explicitly safe transport field is later justified.
- Locality is enforced twice with distinct responsibility: ContextBuilder
  excludes disallowed material; Router rejects an incompatible execution
  target. This redundancy does not duplicate authority because each protects a
  different boundary.
- A ToolCall proposal remains inert data. No request path executes a tool or
  creates authorization.

---

# 9. Test Strategy and Integration Ordering

## Unit tests

Cover capabilities, required/preferred requirements, locality, model registry,
router selection/error paths, normalized errors/events, ContextProjection,
budget behavior, and Conversation/Turn invariants.

## Provider contract tests

Run the specialized provider contracts against the deterministic Fake Provider:
final text, streaming deltas, completion, normalized error, structured output,
ToolCall proposal, and usage metadata.

## Persistence and runtime integration

Use real Alembic migrations and SQLite under `tmp_path`, Fake Provider, real
repositories/UoW, ContextBuilder, Router, and Conversation Runtime. Verify
that a completed Conversation/Turn survives reconstruction of runtime/store
objects and that provider failure preserves the Conversation.

## HTTP and real-socket integration

Use the real `LocalClientBoundary`, Uvicorn, and a loopback-only ephemeral
`port=0`. Exercise:

```text
authenticated client
    ↓
real Uvicorn loopback socket
    ↓
Conversation HTTP route
    ↓
Conversation Runtime
    ↓
ContextBuilder
    ↓
Router
    ↓
Fake Provider
    ↓
streamed and final response
```

No test binds `0.0.0.0`, depends on port 8989 being free, calls a provider
network by default, touches Credential Manager, or opens a user's Operational
Store.

## Security acceptance tests

At minimum prove:

- credentials never appear in log/response/repr assertions;
- provider credentials come from SecretService in the real-adapter smoke path;
- `LOCAL_ONLY` cannot choose cloud;
- missing Bearer fails;
- session UUID alone fails;
- provider-specific metadata does not leak unnecessarily; and
- raw provider exceptions never reach the client.

---

# 10. Execution Order and Recommended Commits

The dependency order is intentionally:

```text
SA-B007.1 AI Contracts & Normalized Types
    ↓
SA-B007.2 Model Registry & Capability Router
    ↓
SA-B007.3 Deterministic Fake/Test Provider
    ↓
SA-B008.1 Conversation Domain & Operational Persistence
    ↓
SA-B010.1 Context Projection Baseline
    ↓
SA-B008.2 Text Conversation Runtime
    ↓
SA-B010.2 Context Budget / Locality / Projection Hardening
    ↓
SA-B008.3 Streaming & Turn Lifecycle
    ↓
SA-B008.4 Authenticated Local HTTP Conversation Adapter
    ↓
SA-B007.4 Initial Real Provider Adapter
    ↓
Integration Hardening
    ↓
Gate I2 audit/smoke
```

This order intentionally establishes contracts and a deterministic provider
before durable runtime behavior, establishes durable state before inference,
and exposes HTTP only after the domain stream exists. The real provider comes
after the fake-backed vertical slice so it validates an adapter rather than
driving the design.

Recommended commit units are listed in each subpass. Additional test-only
commits may accompany the coherent implementation commit when they improve
reviewability; no commit should mix unrelated refactoring or deferred scope.

---

# 11. Quality Gates

Every subpass must run and pass:

```text
uv sync --locked
uv run python -m sofias_assistant
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

When a dependency is legitimately approved for SA-B007.4, run `uv sync` before
the quality suite and `uv sync --locked` afterwards to prove lock consistency.
No provider SDK or other dependency is added before that explicit decision.

---

# 12. Gate I2 Final Acceptance Scenario

The final deterministic integration evidence must demonstrate this sequence:

1. SofiaCore starts.
2. LocalClientBoundary starts on loopback with an ephemeral test port.
3. A client authenticates using the runtime credential and ClientSession.
4. The client creates a Conversation.
5. The client sends text.
6. Conversation Runtime creates and persists a processing Turn.
7. ContextBuilder produces the Core-owned projection.
8. Router selects a compatible provider/model.
9. Fake Provider (or separately approved smoke provider) responds through
   normalized stream events.
10. The client receives ordered deltas and a terminal result.
11. The Turn is durably `COMPLETED` only after final output is persisted.
12. Boundary stops before Core stops.
13. The Operational Store is reopened through recreated runtime/store objects.
14. The same Conversation and completed Turn remain recoverable.
15. Replacing the adapter/provider does not alter Conversation identity.
16. ContextBuilder remains the owner of the projection; a provider receives a
    request, not authority over the transcript/context.

Failure-path evidence must additionally show that a provider failure leaves the
Conversation valid and the affected Turn non-completed, and that authentication
and locality fail closed.

Only after deterministic tests, real socket coverage, persistence/reload
evidence, and the documented opt-in smoke path are satisfactory may the Gate be
audited as:

```text
GATE I2: PASS
```

---

# 13. Risks and Deferred Follow-up

The primary implementation risks are accidentally letting an SDK dictate Core
contracts, retaining a database transaction across network streaming, treating
partial output as final, and allowing full transcript growth to bypass a
context budget. Reviews must focus on those invariants before optimizing model
choice, token accounting, or provider health.

The deferred items in section 4 are intentional and non-blocking for I2. In
particular, no real-time voice/WebSocket behavior, cognitive memory, policy or
tool execution, Desktop Client, process host, broad network exposure, or crash
recovery hardening is implied by this plan.

---

# 14. Implementation Decisions to Freeze During Slice 02

The ADRs already resolve the architectural direction. The following
implementation-level decisions remain intentionally deferred to the subpass
that owns their contract. They do not block approval or the start of Slice 02.

Each decision must be frozen before implementation proceeds beyond its
designated subpass and must not reopen the accepted ADRs.

SA-B007.1 already froze the normalized stream taxonomy:

```text
TextDelta
ToolCallProposed
UsageUpdated
ProviderCompleted
ProviderFailed
```

1. **First real provider selection (before SA-B007.4):** choose the adapter and
   SDK only after evaluating the stated contract, SecretService, and smoke-test
   criteria.
2. **Exact minimum Conversation/Turn relational shape (SA-B008.1):** select the
   smallest migration-backed schema satisfying the stated text/lifecycle and
   future modality seam, without prebuilding an event store.
3. **NDJSON wire record names (SA-B008.4):** retain HTTP POST streaming with
   `application/x-ndjson` unless implementation discovers a concrete conflict
   with the approved normalized stream contract; WebSocket and realtime remain
   out of scope regardless.
