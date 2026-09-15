# Architecture Review Amendment 0003

**Project:** Sofia's Assistant  
**Status:** Accepted  
**Decision date:** 2026-09-15  
**Applies to:** ADR-0001, ADR-0002, ADR-0004, ADR-0005, ADR-0011, Architecture Review Amendment 0001, Technical Backlog Slice 09  
**Origin:** Post-MVP architecture review after `v0.1.0`  
**Purpose:** freeze the architecture for runtime configuration, secret sources, production Core hosting, persistent AI configuration and profile-aware dynamic routing

---

# 1. Context

`v0.1.0` proved the technical kernel of Sofia's Assistant: provider-neutral AI contracts, capability routing, authenticated local clients, Conversation/Turn ownership, Sofias Memory integration, Tools, Tasks, Agents, recovery and Audit.

The MVP deliberately left two operational gaps:

1. the complete Core composition still required manual wiring instead of a production process host;
2. provider/model selection was valid architecturally but too process-local and static for a future human configuration surface.

Post-MVP work must close those gaps without weakening the accepted architecture.

The required direction is:

```text
stable Sofia identity
+
stable Core contracts
+
real runtime configuration
+
persistent non-secret AI configuration
+
dynamic validated routing
+
secrets behind SecretService
```

This Amendment does not replace ADR-0004. It makes its dynamic-provider intent operationally precise.

---

# 2. Precedence

When this Amendment conflicts with the documents listed in **Applies to**, this Amendment prevails only for the topics explicitly refined here.

All non-conflicting decisions remain valid.

The historical `v0.1.0` release notes continue to describe the behavior of that release. They are not rewritten retroactively when post-MVP behavior changes.

---

# 3. Fundamental Rule

The accepted AI architecture becomes operationally:

```text
Domain requests capabilities + workload/profile.
        ↓
Routing policy resolves preferences/configuration.
        ↓
CapabilityRouter validates hard compatibility.
        ↓
Provider adapter performs inference.
```

Provider and model remain execution mechanisms.

They never become Sofia's identity, Conversation authority, authorization authority, or Memory authority.

---

# 4. Core Runtime Configuration Ownership

Runtime configuration is Core-owned.

It may receive deployment inputs from:

- code defaults;
- one explicitly selected `.env` file;
- process environment;
- persisted non-secret operational configuration where this Amendment/Contract explicitly permits it.

For bootstrap configuration, precedence is:

```text
process environment
    overrides
explicit env file
    overrides
code defaults
```

The Core must not search arbitrary directories for `.env` files.

A caller/entrypoint may opt into one specific env file path. This is explicit configuration, not implicit discovery.

Configuration parsing/validation occurs before subsystem composition whenever possible.

---

# 5. Secret Architecture Amendment

`SecretService` remains the only Core-wide contract through which adapters and integrations obtain secret values.

The following remains prohibited:

```text
Provider Adapter -> os.getenv()
Memory Adapter   -> os.getenv()
Domain Service   -> plaintext secret row
```

Post-MVP deployments may supply secrets through environment-backed sources.

The architecture is:

```text
process environment / explicitly selected env file / platform secret store
                         ↓
                  Secret source bridge
                         ↓
                    SecretService
                         ↓
              Provider / Integration Adapter
```

An environment-backed source is a deployment mechanism, not a new secret authority.

Requirements:

- secret values are not persisted as plaintext in SQLite;
- secret values are excluded from `repr`, logs, Audit and diagnostics;
- `SecretRef` remains the stable identifier used by Core components;
- environment-backed secrets are process-scoped and may disappear on restart;
- platform stores such as Windows Credential Manager remain supported;
- future encrypted stores may replace or compose with current sources without changing provider contracts.

This explicitly relaxes the `v0.1.0` operational limitation that API keys could only come from the platform secret store. It does **not** relax the `SecretService` boundary.

---

# 6. Secret Source Resolution

Secret source composition must be deterministic.

When an environment-backed bootstrap secret is present for a well-known `SecretRef`, it may override the same reference from a lower-priority configured source for that process.

The source order must be explicit in composition and testable.

There is no implicit environment scan for arbitrary secret names.

Only known configuration keys may be bridged to known `SecretRef` identities.

---

# 7. Production Core Host

Sofia Core must be runnable as a real long-lived process independent from the Desktop Client.

The production host is an outer composition/lifecycle layer, not domain logic.

Responsibilities are limited to:

```text
load/validate configuration
construct SecretService
construct AI/provider composition
construct Memory composition
construct SofiaCore
start SofiaCore
start authenticated LocalClientBoundary
publish readiness/health
wait for shutdown
stop boundary
stop SofiaCore
return coherent exit status
```

The default network boundary remains loopback-only.

```text
localhost != trusted identity
```

Authentication remains mandatory.

Supporting Linux/VPS does not authorize binding to `0.0.0.0`, LAN exposure, public API exposure or a remote trust model in this Amendment.

---

# 8. Client Credential Boundary

The Local Client Boundary credential is not an LLM provider credential and is not a generic deployment API key.

It remains a Core/client authentication concern.

Slice 09 must not:

- persist it as provider configuration;
- expose it through generic AI configuration APIs;
- weaken authentication for local convenience;
- conflate it with `LLM_API_KEY` or integration credentials.

Human-friendly pairing/attach UX may be designed later without changing this authority boundary.

---

# 9. Canonical / Bootstrap Model

The bootstrap model configured through runtime configuration is a **canonical/default bootstrap model**.

It is not a universal routing decision.

It may be used for:

- first boot before persisted AI configuration exists;
- deterministic seeding of an initial provider/model entry;
- a default profile binding;
- diagnostics;
- a compatible fallback when routing policy permits it.

It may never bypass hard requirements.

A canonical model is ineligible when it violates:

- required capabilities;
- data locality;
- provider/interface compatibility;
- enabled state;
- availability rules.

---

# 10. Persistent AI Configuration

Post-MVP AI configuration is split into non-secret persistent configuration and external secret material.

The Operational Store may persist non-secret entities equivalent to:

```text
ProviderConfiguration
ModelCatalogEntry
InferenceProfile
ProfileModelBinding
```

It must not persist provider API keys in plaintext.

Stable model identity is:

```text
provider_id / model_id
```

Display names are not identity.

Persisted configuration is user/product preference and runtime input. It is not authorization authority.

---

# 11. Model Discovery Is Evidence, Not Capability Truth

A provider listing a model proves only that the provider advertised that model identity at that time.

It does not automatically prove support for Tool Calling, Vision, Realtime, Audio, Structured Output, reasoning or other hard capabilities.

Capability claims require provenance equivalent to:

```text
BUILTIN_METADATA
PROBED
USER_OVERRIDE
DISCOVERED
```

`DISCOVERED` alone must not invent hard capabilities.

Unknown mandatory compatibility fails closed.

A temporarily missing model is marked unavailable/not-seen rather than physically deleting the user's persisted preference.

---

# 12. Inference Profiles

A `Capability` answers:

> What can a model do?

An `InferenceProfile` answers:

> What type of workload is the Core executing and what preferences should apply?

Profiles do not replace hard capability requirements.

Baseline post-MVP workloads include profiles only where a real consumer exists, initially expected to cover:

```text
chat.general
coding
research
vision
realtime
```

Additional profiles require a real runtime consumer or a separately approved contract requirement.

---

# 13. Routing Policy Boundary

`CapabilityRouter` remains deterministic and provider-neutral.

Persistent configuration must not be queried ad hoc from inside it on every decision.

Preferred architecture:

```text
Operational Store
      ↓
AI Configuration Service
      ↓
validated immutable Routing Snapshot
      ↓
Routing Policy
      ↓
CapabilityRouter
```

Configuration changes are validated before publication.

A new snapshot is published atomically.

Requests already in flight may finish with the snapshot with which they started. New requests use the new snapshot.

If a rebuild fails, the previous valid snapshot remains active.

---

# 14. Routing Resolution and Fallback

Routing preference never weakens hard requirements.

The resolution contract must be deterministic and explainable.

It may consider:

- explicit per-call override;
- ordered profile bindings;
- profile fallback policy;
- compatible canonical/default binding;
- provider/model availability.

Fallback is allowed only to another candidate that independently satisfies every hard requirement.

This is forbidden:

```text
request locality = LOCAL_ONLY
local model unavailable
↓
silent cloud fallback
```

Routing failures must be explicit and diagnosable.

Fallback and failure must generate safe Audit/diagnostic evidence.

---

# 15. Data Locality

Existing `DataLocality` remains a hard request policy:

```text
LOCAL_ONLY
CLOUD_ALLOWED
CLOUD_PREFERRED
```

Profiles and user preferences may narrow or rank candidates but may not widen locality beyond the request.

`LOCAL_ONLY` categorically excludes cloud execution.

A profile that prefers cloud does not override a local-only operation.

---

# 16. Agents, Conversation, Vision and Realtime

Consumers request a profile plus their own hard capability requirements.

Expected integration:

```text
Conversation            -> chat.general
DevelopmentAnalysisAgent -> coding
ResearchAgent             -> research
VisionCapability          -> vision + IMAGE_INPUT required
Realtime runtime          -> realtime + REALTIME/AUDIO_INPUT/AUDIO_OUTPUT required
```

Agents do not hardcode provider/model identities.

Profile selection does not modify Agent context narrowing, Tool subset, authority narrowing, Policy or Audit semantics.

Conversation remains Core-owned across provider/model changes.

---

# 17. Runtime Reconfiguration

Safe non-secret AI configuration changes should take effect without Core restart where practical.

Required semantic sequence:

```text
validate proposed change
↓
persist transactionally
↓
build complete routing snapshot
↓
atomically publish snapshot
↓
Audit configuration change
```

A failed snapshot build must not leave the runtime partially updated.

Secrets are not returned by generic configuration APIs.

---

# 18. Configuration API Boundary

The authenticated Local Client Boundary may expose AI configuration/readiness/routing APIs for a future Dashboard.

These APIs are client surfaces over Core application services, not direct database access.

They may expose:

- non-secret provider configuration;
- model catalog and availability;
- inference profiles and bindings;
- model refresh actions;
- deterministic routing preview;
- safe health/diagnostic data.

They must not expose:

- raw API keys;
- SecretService internals;
- hidden chain-of-thought;
- unrestricted provider SDK objects;
- direct write access to SQLite.

---

# 19. Routing Preview

Routing preview is deterministic evidence, not LLM reasoning.

It explains the result of the same compatibility/routing rules that a real request would use, without performing inference.

It may safely return:

- profile;
- required locality/capabilities;
- selected provider/model;
- fallback flag;
- machine-readable reason code;
- bounded human-readable explanation.

It must not include prompts, recalled Memory content, secrets or private reasoning.

---

# 20. Health and Availability

Provider/model health influences eligibility but must not become uncontrolled permanent state from one transient failure.

The initial availability contract may remain small, such as:

```text
AVAILABLE
UNAVAILABLE
```

More elaborate cooldown/circuit-breaker semantics require evidence of need.

A missing optional provider may degrade AI capability without corrupting Core lifecycle.

Core readiness must clearly distinguish structural configuration failure from an optional external provider outage.

---

# 21. Audit and Observability

Routing/configuration must preserve enough evidence to answer:

```text
which profile?
which provider?
which model?
which locality policy?
was fallback used?
why was the candidate accepted/rejected?
```

Safe Audit events may represent provider configuration changes, model refreshes, profile changes, routing selections, fallbacks and failures.

Never persist secret values or hidden chain-of-thought.

Provider-reported token/usage metadata may continue to be normalized, but this Amendment does not create a billing engine.

---

# 22. Persistence and Migration

Published migrations remain immutable.

New AI configuration storage must use incremental migrations and preserve upgrade from the `v0.1.0` database.

At minimum, migration evidence must cover:

```text
fresh DB -> new HEAD
v0.1.0 DB -> new HEAD
new HEAD -> no-op
```

Default seeding must be idempotent.

---

# 23. Security Invariants Preserved

This Amendment does not alter:

```text
AI proposes. Runtime authorizes. Executor acts.
```

Nor does it alter:

- deterministic Policy;
- Grant/confirmation semantics;
- least-privilege Agent/Tool authority;
- authenticated localhost boundary;
- Memory as untrusted context rather than authority;
- recovery fail-closed semantics;
- Audit redaction requirements.

Provider/model routing never grants Tool or system authority.

---

# 24. Non-goals

This Amendment does not authorize:

- public/VPS API exposure;
- multi-user authentication;
- OAuth provider account systems;
- provider billing engine;
- generic model marketplace;
- plugin marketplace;
- semantic LLM classifier for every request;
- Dashboard redesign;
- secret plaintext storage;
- direct provider SDK usage from domain code;
- routing that bypasses `CapabilityRouter` compatibility.

---

# 25. Consequences

Positive consequences:

- the Core can become a real standalone process;
- Windows, Linux, Docker and systemd deployments share one configuration model;
- provider/model choice can evolve without changing Sofia identity;
- a future Dashboard can configure routing through stable Core contracts;
- secret delivery can adapt to deployment environment while preserving `SecretService`.

Costs:

- AI configuration becomes durable domain-adjacent operational state;
- capability provenance and catalog reconciliation require explicit modeling;
- routing snapshot publication adds consistency responsibilities;
- configuration validation becomes part of startup/runtime correctness.

These costs are accepted because they remove post-MVP hardcodes without weakening existing authority boundaries.

---

# 26. Implementation Contract

The exact wire/configuration semantics for this Amendment are defined by:

```text
Sofia's Assistant — AI Runtime Configuration Contract v1
```

The Contract may refine names, fields, reason codes and endpoint payloads while preserving the architectural decisions in this Amendment.

---

# 27. Approval Effect

Once this Amendment and the corresponding Contract v1 are approved, the documentation prerequisites for Slice 09 Run 1 / Gate I14 are satisfied.

Approval does not itself close Gate I14 or authorize skipping its implementation, testing, remote CI or independent review requirements.
