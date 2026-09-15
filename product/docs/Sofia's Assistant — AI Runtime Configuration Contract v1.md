# Sofia's Assistant — AI Runtime Configuration Contract v1

**Project:** Sofia's Assistant  
**Contract:** AI Runtime Configuration Contract  
**Version:** 1  
**Status:** Proposed — Ready for Approval  
**Date:** 2026-09-15  
**Depends on:** ADR-0004 + Architecture Review Amendment 0003  
**Primary consumers:** Runtime host, AI Configuration Service, CapabilityRouter composition, Local Client Boundary, future Dashboard  
**Initial implementation target:** Technical Backlog Slice 09 — Gates I14 and I15

---

# 1. Purpose

This Contract freezes the operational semantics required to move Sofia's Assistant from the published `v0.1.0` kernel to a configurable post-MVP AI runtime.

It defines:

- runtime configuration input and precedence;
- secret bridging into `SecretService`;
- canonical provider/model bootstrap;
- production Core-host expectations;
- persisted non-secret provider/model configuration;
- model capability provenance;
- inference profiles and ordered bindings;
- deterministic routing and fallback;
- runtime reconfiguration;
- authenticated AI configuration APIs;
- routing diagnostics/Audit semantics.

It does not redefine Sofia identity, Conversation ownership, Policy, Tool authority, Memory authority or Agent authority.

---

# 2. Normative Language

The words `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative.

When this Contract conflicts with lower-precedence implementation behavior, the approved active execution plan and Architecture Review Amendment 0003 prevail according to repository source-of-truth rules.

---

# 3. Core Invariants

All implementations of this Contract MUST preserve:

```text
Provider != Sofia identity
Model != Sofia identity
Profile != authority
Routing preference != authority
Configuration != authority
Memory != authority

AI proposes.
Runtime authorizes.
Executor acts.
```

Conversation/Turn identity remains Core-owned and provider-independent.

`CapabilityRouter` remains the final deterministic compatibility boundary for model selection.

---

# 4. Configuration Layers

Runtime bootstrap configuration has exactly three precedence layers:

```text
process environment
    > explicitly selected env file
    > code defaults
```

Persisted AI configuration is a separate runtime layer used after storage is available. It MUST NOT silently mutate the raw bootstrap configuration object.

A `.env` file MUST NOT be discovered by searching parent directories, the user profile, application-data folders or arbitrary working directories.

The production host MAY accept an explicit option equivalent to:

```text
sofia-core --env-file .env
```

If no env file is explicitly selected, no env file is loaded.

---

# 5. Runtime Bootstrap Keys

The v1 bootstrap key set is:

```env
# Core
SOFIA_CORE_HOST=127.0.0.1
SOFIA_CORE_PORT=8989
SOFIA_DATA_DIR=

# Canonical/default AI provider
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=

# Sofias Memory
SOFIAS_MEMORY_ENABLED=true
SOFIAS_MEMORY_BASE_URL=
SOFIAS_MEMORY_API_KEY=
```

Additional implementation-only tuning keys MAY exist for bounded timeouts or logging, but they MUST NOT change the semantics defined here without a Contract revision.

---

# 6. Core Host Validation

`SOFIA_CORE_HOST` defaults to:

```text
127.0.0.1
```

Contract v1 is local-boundary only.

The production host MUST reject non-loopback binds by default. Public/LAN binding requires a future trust/network decision and is outside this Contract.

`SOFIA_CORE_PORT` defaults to:

```text
8989
```

Valid range:

```text
1..65535
```

Invalid ports MUST fail startup before binding.

`SOFIA_DATA_DIR`, when blank, resolves through the existing application default. When supplied, it MUST resolve to a valid writable application data directory according to current persistence rules.

---

# 7. Canonical Provider Bootstrap

`LLM_PROVIDER` is the stable provider identity used for bootstrap.

For v1 Run 1, the required production adapter type is the existing OpenAI adapter boundary.

The initial canonical provider identity is expected to be:

```text
openai
```

A custom `LLM_BASE_URL` MAY point the same adapter at a compatible endpoint. This does not imply that every OpenAI-compatible service is semantically identical.

Provider-specific protocol differences remain adapter responsibilities.

`LLM_MODEL` is required when the canonical AI provider is enabled for text inference.

It means:

```text
bootstrap/default model
```

It does NOT mean:

```text
model used for every inference workload
```

---

# 8. Secret Mapping

Raw secret values MUST NOT become ordinary `RuntimeConfig` fields exposed through representation, diagnostics or API serialization.

Known environment/bootstrap keys map to stable `SecretRef` identities.

Normative mappings:

```text
LLM_API_KEY
    -> providers/{LLM_PROVIDER}/api-key

SOFIAS_MEMORY_API_KEY
    -> integrations/sofias-memory/api-key
```

The bridge MAY normalize `LLM_PROVIDER` for the secret reference only if the same normalization is used for persisted provider identity.

Adapters MUST request the `SecretRef` through `SecretService`.

Adapters MUST NOT read `LLM_API_KEY`, `SOFIAS_MEMORY_API_KEY` or arbitrary environment variables directly.

---

# 9. Secret Source Precedence

Secret source resolution is composition-owned and deterministic.

For well-known bootstrap refs, the v1 precedence is:

```text
process environment secret
    > explicitly selected env-file secret
    > configured platform SecretStore
```

A missing higher-priority source falls through to the next configured source.

No source may enumerate arbitrary environment variables and expose them as secrets.

Only explicitly mapped keys are bridged.

Secret values MUST NOT be persisted into normal SQLite configuration tables.

---

# 10. Secret Redaction

The following outputs MUST redact or omit secret values:

- startup logs;
- exception messages where possible;
- Audit metadata;
- health/readiness responses;
- configuration APIs;
- routing preview;
- object `repr` used by ordinary diagnostics.

A safe diagnostic may expose:

```text
configured: true|false
source: environment|env_file|platform_store|missing
```

It MUST NOT expose the secret value.

---

# 11. Sofias Memory Bootstrap

`SOFIAS_MEMORY_ENABLED` is a strict boolean configuration value.

Accepted normalized values MAY include the implementation's existing boolean syntax, but invalid values MUST fail configuration validation rather than silently default.

When disabled:

- no Memory adapter call is attempted;
- Memory health reports disabled/not configured according to existing health semantics;
- Core startup continues.

When enabled:

- `SOFIAS_MEMORY_BASE_URL` MUST be a structurally valid HTTP(S) URL;
- the API key is resolved through `SecretService`;
- contract probing follows the existing Cognitive Memory integration rules.

An unavailable Sofias Memory service degrades Memory but does not by itself kill the Core unless an independently approved compatibility rule makes startup unsafe.

---

# 12. Production Core Host Contract

The production host command is conceptually:

```text
sofia-core
```

Its lifecycle is:

```text
parse bootstrap inputs
↓
load explicit env file, if selected
↓
overlay process environment
↓
validate RuntimeConfig
↓
construct SecretService
↓
construct canonical AI composition
↓
construct Memory composition
↓
construct SofiaCore
↓
Core.start()
↓
LocalClientBoundary.start()
↓
READY
↓
wait for shutdown
↓
LocalClientBoundary.stop()
↓
Core.stop()
↓
exit
```

The host MUST NOT contain Conversation, Tool, Agent, routing or Memory domain logic.

It MAY contain composition, signal handling, lifecycle coordination and safe startup diagnostics.

---

# 13. Shutdown Contract

The host MUST support clean shutdown for the platform mechanisms available to it.

Windows-first support MUST include Ctrl+C / `KeyboardInterrupt` behavior.

Portable support SHOULD include `SIGINT` and `SIGTERM` where available.

A normal user-requested shutdown returns exit code `0` after bounded cleanup.

Structural startup/configuration failure returns non-zero.

Failed-start cleanup MUST release acquired single-instance/bind resources.

---

# 14. Single-instance and Local Boundary

Existing single-instance semantics remain in force.

The production host MUST preserve the current Core instance-ownership boundary.

The Local Client Boundary remains authenticated even when bound to loopback.

The ephemeral/local client credential MUST NOT be sourced from `LLM_API_KEY` or stored in AI provider configuration.

Contract v1 does not define final human pairing/attach UX.

---

# 15. First-boot AI State

After persistence becomes available, bootstrap AI configuration MAY seed persistent AI state idempotently.

First boot MUST be capable of producing a usable routing snapshot from the canonical bootstrap provider/model before any future Dashboard configuration exists.

Seeding MUST NOT overwrite an existing explicit user configuration on subsequent boots.

The canonical provider/model is a fallback/default preference only when compatible.

---

# 16. ProviderConfiguration

The persistent v1 semantic model is:

```text
ProviderConfiguration
├── id
├── display_name
├── adapter_type
├── base_url
├── enabled
├── execution_location
├── credential_ref
├── created_at
└── updated_at
```

Normative rules:

- `id` is stable and unique;
- `display_name` is mutable presentation metadata;
- `adapter_type` selects a Core-supported adapter family;
- `base_url` is non-secret;
- `enabled=false` makes every model of that provider ineligible;
- `execution_location` is `local` or `cloud`;
- `credential_ref` contains a `SecretRef` identity, never a secret value;
- persisted configuration MUST be validated before runtime publication.

---

# 17. ModelCatalogEntry

The persistent v1 semantic model is:

```text
ModelCatalogEntry
├── provider_id
├── model_id
├── display_name
├── context_window
├── execution_location
├── availability
├── enabled
├── discovery_source
├── last_seen_at
└── metadata
```

Stable identity is:

```text
(provider_id, model_id)
```

`display_name` MUST NOT be used as identity.

A model may remain persisted while unavailable or not recently seen.

Temporary discovery absence MUST NOT physically delete user bindings.

---

# 18. Model Availability

The minimum v1 availability vocabulary is:

```text
AVAILABLE
UNAVAILABLE
```

An implementation MAY retain an internal unknown/not-seen state if needed for reconciliation, but routing MUST treat unproven availability conservatively.

One transient timeout MUST NOT permanently disable a model unless an explicit health policy says so.

---

# 19. Capability Provenance

Every capability claim used for hard compatibility MUST have provenance.

The v1 provenance vocabulary is:

```text
BUILTIN_METADATA
PROBED
USER_OVERRIDE
DISCOVERED
```

Semantics:

- `BUILTIN_METADATA`: trusted project-maintained knowledge for a specific provider/model identity;
- `PROBED`: capability demonstrated by a bounded compatible probe;
- `USER_OVERRIDE`: explicit user/operator declaration accepted by validation;
- `DISCOVERED`: provider advertised the model/metadata but did not prove capability semantics.

`DISCOVERED` alone MUST NOT satisfy a hard capability requirement unless the specific discovery adapter contract explicitly proves that capability.

---

# 20. Discovery Boundary

Model discovery is provider-neutral at the Core boundary.

Conceptually:

```text
ProviderConfiguration
↓
ModelDiscoveryAdapter
↓
provider listing
↓
normalized identities/metadata
↓
Catalog reconciliation
```

Discovery MUST be bounded by timeout/result-size rules appropriate to the provider.

Discovery MUST NOT run aggressive continuous polling by default.

Providers without discovery support may use validated manual catalog entries.

---

# 21. InferenceProfile

The persistent v1 semantic model is:

```text
InferenceProfile
├── key
├── display_name
├── description
├── required_capabilities
├── preferred_capabilities
├── locality
├── enabled
└── fallback_policy
```

Profile key is stable identity.

Baseline profile keys with current real consumers are:

```text
chat.general
coding
research
vision
realtime
```

`utility` MAY be added only when a concrete runtime consumer uses it.

Profile capabilities do not replace per-request hard requirements. Effective hard requirements are the safe combination of the consumer's request and profile requirements.

---

# 22. Baseline Profile Intent

The initial semantic expectations are:

```text
chat.general
    required: TEXT_GENERATION

coding
    required: TEXT_GENERATION + TOOL_CALLING

research
    required: TEXT_GENERATION + TOOL_CALLING

vision
    required: IMAGE_INPUT

realtime
    required: REALTIME + AUDIO_INPUT + AUDIO_OUTPUT
```

A concrete consumer MAY require additional capabilities, such as streaming or structured output.

The runtime MUST use the union of hard requirements, never the weaker set.

---

# 23. ProfileModelBinding

The persistent v1 semantic model is:

```text
ProfileModelBinding
├── profile_key
├── provider_id
├── model_id
├── priority
├── enabled
└── source
```

For one profile, lower numeric `priority` means earlier preference unless the implementation explicitly documents an equivalent ordering convention.

Priorities MUST be deterministic and unique enough to produce a stable order.

A binding is preference, not authority.

An incompatible binding MUST be rejected on write when incompatibility is deterministic from known data.

---

# 24. FallbackPolicy

The baseline v1 fallback policy is intentionally conservative.

Supported semantic policies are:

```text
ORDERED_ONLY
ORDERED_THEN_CANONICAL
```

`ORDERED_ONLY`:

- consider enabled profile bindings by priority;
- fail if none is eligible.

`ORDERED_THEN_CANONICAL`:

- consider enabled profile bindings by priority;
- if none is eligible, consider the canonical bootstrap/default model;
- fail if canonical is also incompatible/unavailable.

Contract v1 does not authorize arbitrary selection from every compatible catalog model when the user has not configured that behavior.

A future contract may add broader discovery-based fallback explicitly.

---

# 25. Routing Resolution Order

For one inference request, v1 resolution is:

```text
1. explicit per-call override, if supplied
2. ordered enabled bindings for the selected profile
3. canonical/default model only if profile fallback policy permits
4. routing failure
```

At every step, the candidate MUST independently pass:

- provider enabled;
- model enabled;
- required capabilities;
- effective data locality;
- adapter/interface compatibility;
- availability rules.

An explicit override that is incompatible MUST fail clearly. It MUST NOT silently fall through to a different model unless the caller explicitly requests fallback semantics.

---

# 26. Data Locality

Existing values remain normative:

```text
LOCAL_ONLY
CLOUD_ALLOWED
CLOUD_PREFERRED
```

Candidate eligibility rules:

- `LOCAL_ONLY`: only `ExecutionLocation.LOCAL` candidates are eligible;
- `CLOUD_ALLOWED`: local or cloud candidates may be eligible; configured order decides;
- `CLOUD_PREFERRED`: cloud may be preferred, but hard capability/availability rules still apply.

A profile MUST NOT widen the request's locality policy.

No fallback may convert `LOCAL_ONLY` to cloud execution.

---

# 27. Routing Snapshot

Dynamic configuration MUST not make `CapabilityRouter` directly persistence-aware.

The AI Configuration Service builds an immutable or equivalently stable routing snapshot containing all validated data required for routing.

Publication rules:

```text
persist validated change
↓
build complete candidate snapshot
↓
validate snapshot
↓
atomically publish
```

A request captures one snapshot for its resolution.

Configuration changes after request start do not mutate that request's in-flight routing view.

If snapshot build/publication fails, the previous valid snapshot remains active.

---

# 28. Runtime Reconfiguration

The following changes SHOULD take effect without Core restart when they can be validated safely:

- provider enable/disable;
- model enable/disable;
- model availability reconciliation;
- profile binding order;
- profile fallback policy;
- non-secret provider base URL when adapter recreation is safe.

Changes that require rebuilding adapter instances MUST do so before publishing the new snapshot.

No request may observe a partially rebuilt provider binding.

---

# 29. Consumer Integration

The initial required profile mapping is:

```text
Conversation text            -> chat.general
DevelopmentAnalysisAgent     -> coding
ResearchAgent                -> research
VisionCapability             -> vision
RealtimeConversationRuntime  -> realtime
```

Consumers MUST continue supplying their hard `AIRequestRequirements`.

Profiles add preference/configuration; they do not erase the consumer contract.

Agents MUST NOT hardcode provider/model identities after Gate I15.

---

# 30. Configuration API

The authenticated Local Client Boundary v1 API surface is:

```text
GET  /api/v1/ai/providers
GET  /api/v1/ai/models
POST /api/v1/ai/models/refresh

GET  /api/v1/ai/profiles
GET  /api/v1/ai/profiles/{key}
PATCH /api/v1/ai/profiles/{key}

POST /api/v1/ai/routing/preview
```

Provider CRUD MAY be added in the same Gate only if implementation requires it and preserves the semantics below.

All endpoints require the existing authenticated client session boundary.

No generic endpoint accepts or returns raw secret values in Contract v1.

---

# 31. Provider API Representation

Provider responses may expose:

```json
{
  "id": "openai",
  "display_name": "OpenAI",
  "adapter_type": "openai",
  "base_url": "https://api.openai.com/v1",
  "enabled": true,
  "execution_location": "cloud",
  "credential": {
    "ref": "providers/openai/api-key",
    "configured": true
  }
}
```

They MUST NOT expose the API key.

The exact envelope may follow existing Local Client Boundary conventions.

---

# 32. Model API Representation

Model responses SHOULD expose at least:

```text
provider_id
model_id
display_name
execution_location
availability
enabled
context_window
capabilities with provenance
last_seen_at
```

Unknown capability MUST remain unknown/unproven rather than being emitted as supported.

---

# 33. Profile API Semantics

`PATCH /api/v1/ai/profiles/{key}` MAY update:

- enabled state;
- preferred capabilities where product policy permits;
- locality restriction where compatible with invariant rules;
- fallback policy;
- ordered model bindings.

The write MUST be rejected if the resulting configuration is deterministically invalid.

Examples:

- binding a cloud-only model to a profile constrained to `LOCAL_ONLY`;
- binding a model without `IMAGE_INPUT` as the only valid `vision` candidate;
- binding a text-only model to `realtime` without required realtime/audio capabilities.

---

# 34. Routing Preview

Request shape is conceptually:

```json
{
  "profile": "coding",
  "required_capabilities": ["text_generation", "tool_calling"],
  "preferred_capabilities": [],
  "locality": "cloud_allowed",
  "override": null
}
```

Response shape is conceptually:

```json
{
  "profile": "coding",
  "selected": {
    "provider_id": "openai",
    "model_id": "example-model"
  },
  "fallback": false,
  "reason_code": "PROFILE_BINDING_SELECTED",
  "reason": "Highest-priority eligible profile binding selected."
}
```

Preview MUST execute deterministic routing only.

It MUST NOT invoke a model.

---

# 35. Routing Reason Codes

The baseline machine-readable reason vocabulary is:

```text
EXPLICIT_OVERRIDE_SELECTED
PROFILE_BINDING_SELECTED
CANONICAL_FALLBACK_SELECTED
NO_COMPATIBLE_MODEL
PROVIDER_DISABLED
MODEL_DISABLED
MODEL_UNAVAILABLE
MISSING_REQUIRED_CAPABILITY
LOCALITY_INCOMPATIBLE
ADAPTER_INCOMPATIBLE
INVALID_PROFILE
```

Implementations MAY add more specific codes while preserving these meanings.

Human-readable reasons are bounded explanations of deterministic rules, not chain-of-thought.

---

# 36. Audit Events

The implementation SHOULD emit safe Audit actions equivalent to:

```text
AI_PROVIDER_CONFIG_CHANGED
AI_MODEL_CATALOG_REFRESHED
AI_PROFILE_CHANGED
AI_ROUTING_SELECTED
AI_ROUTING_FALLBACK
AI_ROUTING_FAILED
```

Safe metadata MAY include:

- profile key;
- provider id;
- model id;
- locality;
- required capability names;
- reason code;
- fallback flag;
- availability state.

Audit MUST NOT contain raw secrets, prompt contents, recalled Memory content or hidden reasoning.

---

# 37. Provider/Model Usage Evidence

When inference completes, existing normalized usage/evidence SHOULD retain enough metadata to correlate:

```text
profile
provider_id
model_id
fallback_used
```

This Contract does not require monetary cost accounting.

---

# 38. Catalog Reconciliation

On discovery refresh:

1. normalize returned model identities;
2. upsert current models;
3. update `last_seen_at`;
4. update safe discovered metadata;
5. mark previously known but absent models unavailable/not-seen according to implementation policy;
6. preserve profile bindings and user preferences;
7. rebuild routing snapshot only after reconciliation is valid.

Physical deletion of a missing model is not the normal reconciliation path.

---

# 39. Bootstrap Seeding

With an empty AI configuration store, the canonical bootstrap provider/model is seeded idempotently.

The seed MUST include enough trusted metadata for the canonical model to satisfy only capabilities the project can actually assert.

If hard capability knowledge is unavailable, the seed MUST remain conservative rather than inventing capabilities.

A bootstrap model that cannot satisfy `chat.general` MUST cause clear AI readiness degradation/failure rather than being silently treated as compatible.

---

# 40. Health / Readiness Contract

Core health SHOULD make the following distinguishable:

```text
Core host alive
AI configuration structurally valid
canonical provider configured
canonical secret configured/missing
canonical model registered
routing snapshot available
Sofias Memory enabled/disabled/degraded
```

Raw secret values are never returned.

Provider outage may mark AI execution degraded/unavailable without making persistence, Scheduler or unrelated Core subsystems corrupt.

Readiness semantics MUST remain consistent with the existing health model.

---

# 41. Failure Semantics

Structural configuration errors fail before normal READY state.

Examples:

- invalid port;
- invalid loopback host contract;
- malformed required URL;
- blank provider id;
- blank required model id;
- invalid persisted profile configuration that prevents a coherent routing snapshot.

External runtime outages produce degraded/unavailable health when safe.

Routing with no eligible model fails explicitly; it MUST NOT silently relax capabilities/locality.

---

# 42. Migration Contract

New persistence introduced by Gate I15 uses incremental migrations after the current published migration head.

Published migrations MUST NOT be rewritten.

Required migration evidence:

```text
fresh database -> latest schema
v0.1.0 database -> latest schema
latest schema -> migration no-op
```

Any default profile/provider/model seeding MUST be idempotent.

---

# 43. Concurrency Contract

Concurrent reads may continue using the currently published routing snapshot while a new configuration is being prepared.

Only a complete validated snapshot may replace the active one.

Two concurrent configuration writes MUST serialize or conflict deterministically through the application's persistence/update boundary.

No mixed snapshot assembled partly from old and partly from new configuration is allowed.

---

# 44. Security Contract

Contract v1 preserves:

- loopback-only default binding;
- authenticated Local Client Boundary;
- secret values outside plaintext operational configuration;
- SecretService-only adapter secret access;
- Policy/Grant/Confirmation for protected Tools;
- Memory as untrusted contextual input;
- Agent authority narrowing;
- recovery fail-closed behavior;
- Audit redaction.

AI routing configuration does not grant filesystem, shell, network or desktop authority.

---

# 45. Non-goals

Contract v1 does not define:

- public remote Core API;
- TLS termination;
- multi-user tenancy;
- OAuth provider-account flows;
- payment/billing/cost budget engine;
- arbitrary provider marketplace;
- Dashboard UX;
- automatic semantic classification of every user message;
- plugin marketplace;
- wake word;
- continuous perception;
- distributed routing control plane.

---

# 46. Gate I14 Conformance

Gate I14 conforms to this Contract when it proves at least:

```text
explicit env-file loading
process-env precedence
secret bridge through SecretService
canonical provider/model bootstrap
Sofias Memory bootstrap
production Core host
loopback authenticated boundary
readiness/health
gracious shutdown
failed-start cleanup
single-instance preservation
Windows smoke
portable signal design
```

A conforming human smoke is equivalent to:

```powershell
cd core
copy .env.example .env
# edit values
uv run sofia-core --env-file .env
```

The exact CLI syntax may vary if documented, but env-file selection MUST remain deterministic and explicit.

---

# 47. Gate I15 Conformance

Gate I15 conforms to this Contract when it proves at least:

```text
persistent non-secret provider config
persistent model catalog
capability provenance
discovery reconciliation
inference profiles
ordered bindings
strict compatibility validation
profile-aware fallback
canonical fallback only when compatible
LOCAL_ONLY blocks cloud
runtime snapshot reconfiguration
Conversation profile integration
DevelopmentAnalysisAgent coding profile
ResearchAgent research profile
Vision profile
Realtime profile
authenticated AI configuration API
routing preview
routing Audit
multi-provider deterministic vertical
fresh/upgrade/no-op migrations
no secret leakage
```

---

# 48. Compatibility

This is Contract version `1`.

Breaking changes to:

- bootstrap key meanings;
- secret mapping identities;
- profile identity semantics;
- routing order/fallback semantics;
- locality guarantees;
- public authenticated AI configuration API semantics

require a Contract revision or an explicitly compatible transition plan.

Implementation details that preserve these semantics do not require a new version.

---

# 49. Approval Effect

Once approved together with Architecture Review Amendment 0003, this Contract satisfies the documentary prerequisite for Slice 09 implementation.

Gate I14 must still be implemented and closed before Gate I15 starts unless the user explicitly changes the execution order.
