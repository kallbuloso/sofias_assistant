# Sofia's Assistant — Desktop/Core Interaction Contract v1

**Project:** Sofia's Assistant  
**Contract:** Desktop/Core Interaction Contract  
**Version:** 1  
**Status:** APPROVED  
**Date:** 2026-09-16  
**Depends on:** ADR-0001 + ADR-0005 + Architecture Review Amendments 0001/0003/0004 + AI Runtime Configuration Contract v1 + TDR-0011  
**Primary consumers:** `sofia-core` host, LocalClientBoundary, DesktopCoreSupervisor, CoreApiClient, ClientApplicationService, PySide6 Desktop, future packaging/runtime services  
**Initial implementation target:** Technical Backlog Slice 10 — Gates I16, I17 and I18

---

# 1. Purpose

This Contract freezes the v1 interaction semantics required to turn the existing technical Desktop Client into a human-usable Sofia desktop experience while preserving the accepted Core/Client boundary.

It defines:

- logical Core instance identity;
- secure local attach material;
- attach-store semantics;
- Desktop Core supervision;
- packaged Core launch and reconnect behavior;
- explicit graceful Core shutdown;
- secure provider/integration credential writes;
- safe secret-source status;
- bounded Conversation History APIs;
- human inference privacy/locality mapping;
- Desktop-local preference ownership;
- realtime voice/device responsibilities;
- lifecycle/security/Audit evidence required by Slice 10.

It does not redefine Policy, Tool authority, AI routing, Sofias Memory ownership, Task recovery or provider contracts.

---

# 2. Normative Language

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT` and `MAY` are normative.

For topics covered here, precedence is:

```text
explicit user instruction
> approved active Slice
> Architecture Review Amendment 0004
> this Contract
> Architecture Review Amendment 0003
> AI Runtime Configuration Contract v1
> accepted ADRs / TDR-0011
> existing implementation
```

---

# 3. Core Invariants

All implementations MUST preserve:

```text
Desktop != Core
Desktop != authority
localhost != identity
attach record != authentication authority
attach credential != provider credential
UI preference != authorization authority
Conversation History != Cognitive Memory
Profile != authority

AI proposes.
Runtime authorizes.
Executor acts.
```

The Desktop is a trusted local client only after successful authentication to the expected Core lifecycle.

---

# 4. Process Topology

The normal packaged topology is:

```text
Desktop process
    │
    ├── DesktopCoreSupervisor
    │       │
    │       ├── protected ClientAttachStore
    │       └── explicit Core launch target
    │
    └── CoreApiClient
            │ authenticated loopback
            ▼
       Sofia Core process
```

Desktop and Core remain distinct operating-system processes.

Running the Core inside the Qt process as an in-process service is not conformant with v1.

---

# 5. Logical Instance Key

The Desktop and Core MUST agree on a stable non-secret `instance_key` for the expected logical Core instance.

The `instance_key` MUST be derived from the same canonical data-directory identity semantics used by Core single-instance ownership.

Preferred implementation is a shared helper rather than duplicating path normalization/hashing.

Properties:

- deterministic for the same canonical data directory;
- no plaintext data-directory path required in the external key;
- not secret;
- not sufficient to authenticate a client;
- suitable as a protected-store lookup key.

Changing to a different configured data directory means a different logical instance for attach purposes.

---

# 6. Runtime Lifecycle Identity

Each successful Core lifecycle has a unique lifecycle identity.

The existing Core `runtime_session_id` SHOULD be used when it already provides the required semantics.

The lifecycle identity:

- is created/available for one running Core lifecycle;
- changes after Core restart;
- is non-secret;
- is included in attach verification;
- prevents a stale attach record from being confused with a new Core lifecycle.

---

# 7. ClientAttachRecord

The semantic v1 record is:

```text
ClientAttachRecord
├── contract_version
├── instance_key
├── runtime_session_id
├── host
├── port
├── credential
├── application_version
├── created_at
└── process_id?          # optional diagnostic evidence only
```

Normative rules:

- `contract_version` is exactly versioned and validated;
- `host` MUST be loopback for Contract v1;
- `port` MUST be a valid bound port;
- `credential` is the exact runtime-scoped `LocalClientBoundary` credential represented as a redacted secret type as early as possible;
- `credential` MUST be excluded from `repr`, logs, Audit and ordinary diagnostics;
- `runtime_session_id` MUST match the Core identity returned after authenticated attach;
- `process_id`, if present, MUST NOT be used as authority to terminate the Core.

The serialized protected record MUST remain bounded.

---

# 8. ClientAttachStore Contract

The Core and Desktop interact with attach material only through a dedicated abstraction equivalent to:

```text
ClientAttachStore

publish(instance_key, record)
read(instance_key) -> record | None
delete_if_current(instance_key, runtime_session_id) -> bool
```

An equivalent compare-and-delete/compare-and-replace API is acceptable.

The store MUST provide atomic-enough replacement semantics so readers never intentionally observe a record assembled from multiple lifecycles.

A deterministic in-memory fake MUST be available for tests.

---

# 9. Windows Attach Store

The initial Windows implementation MUST use a user-protected OS credential mechanism.

Windows Credential Manager is the preferred baseline and MAY be wrapped by `ClientAttachStore` rather than exposed directly to UI code.

The protected value MAY contain the complete bounded serialized attach record if that preserves atomic lifecycle semantics and stays within platform limits.

The Desktop MUST NOT write/read attach credentials through:

- QSettings;
- SQLite;
- `.env`;
- ordinary plaintext files;
- command-line arguments;
- stdout/stderr.

---

# 10. Core Attach Publication Sequence

The Core host MUST publish attach material only after the current Core is genuinely attachable.

Required order is semantically:

```text
validate configuration
↓
acquire Core single-instance ownership
↓
Core.start()
↓
LocalClientBoundary.start()
↓
obtain LocalClientAccess credential + bound endpoint
↓
build current ClientAttachRecord
↓
publish record to ClientAttachStore
↓
mark human-attach readiness
↓
wait for shutdown
```

If attach publication fails, the product host MUST NOT claim a successful human-ready state.

The host must clean up boundary/Core/ownership according to normal failed-start semantics.

---

# 11. Graceful Attach Cleanup

Graceful shutdown sequence MUST prevent an old lifecycle from deleting a newer lifecycle's attach record.

Semantically:

```text
enter stopping state
↓
delete_if_current(instance_key, current_runtime_session_id)
↓
stop LocalClientBoundary
↓
stop SofiaCore
↓
release Core instance ownership
```

If protected-store cleanup fails, boundary shutdown still revokes the credential and sessions. The leftover record is then stale and must fail later attach verification.

Cleanup failure MAY be reported safely as degraded diagnostic evidence without logging credential contents.

---

# 12. Desktop Attach Algorithm

For one expected logical instance, Desktop startup MUST behave equivalently to:

```text
resolve expected instance_key
↓
read protected attach record
↓
if record exists:
    validate record shape/version/loopback endpoint
    attempt normal LocalClientBoundary authentication
    open client session
    query authenticated runtime identity
    verify instance_key + runtime_session_id
    if all valid -> ATTACHED

otherwise or if stale:
    attempt packaged Core launch
    wait bounded readiness / re-read attach record
    perform same authenticated verification
```

The Desktop MUST NOT treat `port open` or `process exists` as sufficient identity.

---

# 13. Client Authentication Sequence

The attach mechanism does not replace existing authentication.

The expected sequence is:

```text
ClientAttachRecord.credential
↓
POST /api/v1/client-sessions with existing bearer credential
↓
receive non-secret ClientSession id
↓
subsequent requests carry existing bearer + session identity as required
↓
GET /api/v1/runtime/identity
↓
verify current instance/lifecycle
```

Existing authentication semantics MAY retain their exact header names and session behavior.

No new unauthenticated local control API is introduced by this Contract.

---

# 14. Runtime Identity Endpoint

Core MUST expose an authenticated safe identity surface equivalent to:

```text
GET /api/v1/runtime/identity
```

Response semantics:

```json
{
  "instance_key": "non-secret-stable-key",
  "runtime_session_id": "uuid",
  "application_version": "version",
  "protocol_version": 1,
  "state": "running"
}
```

It MUST NOT return:

- bearer credential;
- provider/integration secrets;
- raw data-directory path unless separately justified;
- process environment;
- internal repository/storage handles.

If an existing authenticated Core endpoint can be extended compatibly to provide these semantics, a separate path is not mandatory, but the Contract semantics MUST remain explicit and testable.

---

# 15. Stale Record Handling

A record is stale when any mandatory verification fails.

Examples:

```text
endpoint unreachable
bearer authentication fails
session creation fails
protocol version unsupported
instance_key mismatch
runtime_session_id mismatch
non-loopback endpoint
malformed record
```

On stale material:

- Desktop MUST NOT issue mutating requests;
- Desktop MAY delete only the exact observed lifecycle record via compare/delete semantics;
- Desktop MAY then try launch/rediscovery;
- stale credential contents MUST never be logged.

---

# 16. DesktopCoreSupervisor States

The v1 application-state vocabulary is:

```text
CORE_NOT_FOUND
CORE_STARTING
CORE_READY
CORE_DEGRADED
CORE_RECONNECTING
CORE_STOPPING
CORE_STOPPED
CORE_FAILED
```

The supervisor may internally distinguish more states, but UI mapping MUST preserve these meanings.

Core subsystem health remains authoritative in Core; supervisor state describes Desktop's connection/lifecycle view.

---

# 17. Packaged Core Locator

Desktop MUST use an abstraction equivalent to:

```text
CoreExecutableLocator
```

The packaged product MUST locate an explicit Core launch target distributed with the application.

Acceptable layouts include:

- sibling `sofia-core` executable;
- a product executable with an explicit Core process mode;
- another packaging layout that launches a distinct Core process.

Human packaged startup MUST NOT depend on:

```text
python
uv
terminal window
shell command composition
```

Development-only launch adapters MAY use development tooling outside packaged acceptance tests.

---

# 18. Core Launch Contract

Launching the Core MUST use explicit executable path + explicit argv.

`cwd`, environment and data-directory selection MUST be intentionally constructed.

Forbidden:

```text
shell=True
arbitrary command strings
user-controlled command interpolation
```

Desktop MUST NOT put LocalClientBoundary credentials or provider secrets into command-line arguments.

---

# 19. Duplicate Launch Race

Desktop auto-start is advisory orchestration. Core single-instance ownership remains authoritative.

If two Desktop processes or a Desktop/manual launch race:

1. one Core may acquire ownership;
2. the loser Core exits safely;
3. Desktop re-reads attach material and attaches to the winner when identity matches;
4. no second Operational Store owner is created.

A launch failure caused by `CoreAlreadyRunning` SHOULD be interpreted as a rediscovery signal, not as permission to force-kill the existing Core.

---

# 20. Reconnect and Automatic Restart

Unexpected connection loss MUST NOT trigger mutation replay.

The supervisor SHOULD:

1. enter `CORE_RECONNECTING`;
2. make bounded read-only reattach attempts;
3. re-read protected attach material;
4. when the expected instance is truly absent, MAY perform a bounded automatic Core restart policy;
5. stop automatic attempts after the bounded policy is exhausted and surface `CORE_FAILED`/human retry.

No infinite retry/restart loop is conformant.

Exact retry counts/backoff durations are implementation configuration, but MUST be finite, deterministic under an injected clock/test seam, and resistant to restart storms.

---

# 21. No Automatic Mutation Replay

Desktop MUST NOT automatically retry/replay a mutating request solely because the transport disconnected.

Examples include:

- send chat Turn;
- approve confirmation;
- cancel Task;
- update provider/profile configuration;
- change credential;
- stop Core.

Recovery after uncertain completion must query Core state/evidence or require explicit user action according to the relevant domain contract.

---

# 22. Close, Quit and Stop Semantics

Desktop product behavior is:

```text
window close
    -> hide to tray

Quit Desktop
    -> terminate Desktop process
    -> do not stop Core

Stop Sofia
    -> explicit lifecycle request to Core
    -> Core gracefully stops
    -> Desktop observes CORE_STOPPED
    -> Desktop may remain open or exit according to the initiating UX flow
```

The tray MUST make the distinction understandable to the user.

---

# 23. Core Shutdown API

Core MUST expose a purpose-specific authenticated lifecycle surface equivalent to:

```text
POST /api/v1/runtime/shutdown
```

Request SHOULD carry the expected current lifecycle identity:

```json
{
  "runtime_session_id": "uuid",
  "reason": "user_requested"
}
```

Normative behavior:

- existing bearer/session authentication is required;
- lifecycle mismatch is rejected without shutdown;
- the request schedules/initiates graceful host shutdown rather than killing a process;
- successful acceptance SHOULD return `202 Accepted` or equivalent asynchronous acknowledgement;
- repeated request for the same stopping lifecycle is idempotent enough not to create conflicting shutdown work;
- Core emits safe Audit evidence;
- no raw attach material is returned.

This endpoint is a Core lifecycle command, not a Tool invocation.

---

# 24. Stop Sofia Human Confirmation

Desktop MUST require an explicit human action for `Stop Sofia`.

The UI SHOULD make clear that background reminders/tasks will stop until Sofia Core is started again.

Ordinary window close and `Quit Desktop` MUST NOT call the shutdown API.

---

# 25. Purpose-Specific Provider Credential API

Human provider credential configuration MUST use a dedicated authenticated write-only secret surface.

Baseline v1 API semantics are:

```text
PUT    /api/v1/ai/providers/{provider_id}/credential
DELETE /api/v1/ai/providers/{provider_id}/credential
```

`PUT` request conceptually contains only the new raw credential value plus transport metadata required by validation.

The raw value MUST be converted to the project's redacted secret type as early as practicable and written through `SecretService` to the configured writable platform store.

There is no corresponding GET of the raw value.

---

# 26. Provider Credential Response

A provider credential write/delete response MAY expose only safe state equivalent to:

```json
{
  "credential_ref": "providers/provider-id/api-key",
  "configured": true,
  "effective_source": "platform_store",
  "writable_source": "platform_store",
  "shadowed": false
}
```

Safe source vocabulary may include:

```text
environment
env_file
platform_store
missing
```

If implementation has already merged process environment and explicit env-file into one source, it MAY expose `environment` as the effective deployment source while retaining enough internal evidence for tests. It MUST NOT expose values.

---

# 27. Secret Source Precedence and Shadowing

Amendment 0003 precedence remains in force.

Dashboard credential writes MUST NOT mutate environment variables or the selected env file.

Writes target the writable durable platform store.

Therefore:

```text
higher-priority deployment secret exists
+
user writes platform-store credential
↓
write succeeds durably
but current effective secret remains deployment source
```

The response/UI MUST surface this as safe shadowing state.

Similarly, deleting a platform-store credential while a deployment secret exists leaves the effective credential configured through that higher-priority source.

---

# 28. Provider Credential Security Requirements

Credential endpoints MUST NOT:

- log request bodies containing the secret;
- place raw secret into Audit metadata;
- return raw secret;
- persist raw secret to SQLite;
- place raw secret in QSettings;
- include raw secret in exception text/repr;
- provide a generic secret-enumeration API.

Audit MAY record:

```text
provider_id
credential_ref
configured state
safe source
operation = update|delete
```

---

# 29. Integration Credential API

The same architecture MAY expose a purpose-specific credential write path for approved integrations such as Sofias Memory.

Baseline semantic path:

```text
PUT    /api/v1/integrations/sofias-memory/credential
DELETE /api/v1/integrations/sofias-memory/credential
```

It uses the existing integration `SecretRef` and follows the same no-echo/no-plaintext rules.

This does not create a generic integration secret vault API.

---

# 30. Core vs UI Settings Ownership

Core-authoritative configuration remains in Core persistence/services.

Examples:

```text
ProviderConfiguration
ModelCatalogEntry
InferenceProfile
ProfileModelBinding
Memory integration non-secret config when Core-owned
```

Desktop-local UI/application preferences MAY use QSettings, including:

- window geometry;
- selected page;
- theme/presentation;
- native notification presentation preference;
- Desktop launch preference;
- default inference privacy preference;
- preferred microphone/speaker device identifiers.

QSettings MUST NOT store:

- attach credential;
- provider/integration secret;
- authoritative Conversation transcript;
- Task/Notification/Core configuration truth.

---

# 31. Inference Privacy Preference

Desktop defines a human-facing choice mapped exactly to existing `DataLocality`:

```text
Local only   -> LOCAL_ONLY
Allow cloud  -> CLOUD_ALLOWED
Prefer cloud -> CLOUD_PREFERRED
```

The UI MUST NOT expose internal enum names as the primary human wording.

The selected value is request policy, not a Grant or authority token.

---

# 32. Cloud Cognitive Context Preference

A second independent human preference controls whether recalled cognitive memory/context may be included in cloud-model context:

```text
Allow cognitive memory/context to be sent to cloud models
```

The default is:

```text
false
```

No implicit opt-in is permitted.

Changing locality to `Allow cloud` or `Prefer cloud` MUST NOT automatically enable cloud cognitive context.

---

# 33. First-Run Privacy Rule

Before the Desktop initiates the first real human inference, it MUST obtain an explicit locality choice.

It MAY perform non-inference setup/readiness/routing-preview operations beforehand.

Until the user opts in, cloud cognitive context remains disabled.

The Desktop MAY persist the chosen defaults locally as UI/application preferences and MUST send the effective values explicitly with each relevant request.

Core remains responsible for enforcing the request values and routing hard constraints.

---

# 34. Text Turn Privacy Contract

Every Desktop text Turn request MUST explicitly include:

```text
locality
cloud_context_eligible
```

No Desktop helper may silently substitute `LOCAL_ONLY` merely because the caller omitted UI preference plumbing.

The existing request contract remains provider-neutral.

Profiles/routing MUST NOT widen the request locality or cloud-context eligibility.

---

# 35. Realtime Privacy Contract

Opening a realtime voice session MUST carry the same effective privacy policy:

```text
locality
cloud_context_eligible
```

Realtime profile capability requirements remain independent hard requirements.

The Desktop MUST NOT silently fall back to an incompatible local/cloud modality when realtime routing fails.

---

# 36. Conversation History Ownership

Conversation and Turn rows remain Core operational data.

Desktop MUST access history only through authenticated Core APIs.

Desktop MUST NOT read the SQLite database directly and MUST NOT maintain a second authoritative transcript database.

Sofias Memory remains a separate Cognitive Memory system.

---

# 37. Conversation List API

Core MUST expose a bounded authenticated list surface equivalent to:

```text
GET /api/v1/conversations?limit=<n>&cursor=<opaque?>
```

V1 rules:

- default `limit`: 50;
- maximum `limit`: 100;
- order: most recently updated first, with deterministic tie-breaking;
- cursor: opaque to Desktop;
- response includes `next_cursor` when more results exist;
- list query must not load all Turns for every Conversation.

A compatible implementation MAY use another bounded cursor shape while preserving these semantics.

---

# 38. Conversation List Item

Each list item SHOULD provide at least:

```text
conversation_id
created_at
updated_at
preview
last_turn_status
last_turn_sequence
```

`preview` MUST be deterministic and bounded.

Baseline algorithm:

- first available non-blank user Turn text;
- whitespace normalized for display;
- safely truncated to at most 120 Unicode code points;
- no LLM call;
- no semantic-memory write.

If no user text exists, a neutral deterministic placeholder is acceptable.

---

# 39. Bounded Turn History API

Core MUST expose a bounded authenticated Turn history surface equivalent to:

```text
GET /api/v1/conversations/{conversation_id}/turns
    ?limit=<n>
    &before_sequence=<optional>
```

V1 rules:

- default `limit`: 50;
- maximum `limit`: 100;
- initial request returns the most recent bounded page;
- `before_sequence` loads an older page;
- each response page is returned in chronological sequence order for rendering;
- response indicates whether older Turns are available;
- Conversation-not-found semantics remain explicit.

An opaque cursor equivalent is acceptable if it preserves deterministic bounded paging.

---

# 40. Existing Conversation State API Compatibility

Existing Conversation endpoints MAY remain for compatibility.

The human history UI MUST use the bounded list/history contract rather than relying on an unbounded whole-conversation state response.

A future version may deprecate the unbounded compatibility path through a separate transition plan.

---

# 41. Create and Resume Conversation

Desktop uses the existing Core-owned create semantics for new Conversations.

Resume semantics are:

```text
select Conversation
↓
load bounded recent Turn page
↓
optionally page older history
↓
send next Turn using same conversation_id
```

Provider/model changes do not change Conversation identity.

ContextBuilder and Memory remain Core-owned.

---

# 42. No Duplicate Turn on Reconnect

Desktop transport reconnection MUST NOT blindly resend a Turn whose acceptance/completion is uncertain.

The client SHOULD correlate visible streaming state with existing Core Turn/processing evidence and either:

- recover the accepted Turn state; or
- require explicit user retry when outcome cannot be proven.

Automatic duplicate Conversation Turn creation is not acceptable reconnect behavior.

---

# 43. Dashboard Contract

The human Dashboard consumes authenticated Core services.

It MUST provide product workflows for:

- readiness/overview;
- providers;
- provider credential configured state/write/delete;
- model catalog/discovery refresh;
- capability provenance;
- profiles/bindings/fallback;
- routing preview;
- Memory/integration health/configuration;
- safe validation error presentation.

All writes are validated again by Core.

UI-side validation improves ergonomics only.

---

# 44. Routing Preview UX Boundary

Dashboard routing preview invokes the existing deterministic Core routing preview.

It MUST NOT implement an independent routing algorithm in Desktop.

UI may render:

```text
profile
selected provider/model
fallback yes/no
bounded deterministic reason
```

It MUST NOT render secrets, prompt content, Memory content or hidden reasoning.

---

# 45. Realtime Audio Ownership

For v1 human voice UX:

```text
Desktop
    owns microphone device capture
    owns speaker/output playback
    owns device-selection presentation preference

Core
    owns realtime Conversation/session domain
    owns provider interaction/routing
    owns Conversation/Turn semantics
```

Desktop audio plumbing MUST reuse the existing Realtime protocol rather than create another AI/realtime runtime.

---

# 46. Audio Privacy and Persistence

Microphone capture begins only after explicit user action to start voice/realtime interaction.

It stops when the voice session stops/interruption semantics require it.

V1 does not authorize continuous background microphone listening or wake word.

Raw audio payloads MUST NOT be written to Audit or ordinary logs by default.

Device identifiers/preferences may be Desktop-local presentation settings.

---

# 47. Device Failure Semantics

Microphone/speaker/device failures MUST be surfaced as safe human errors without crashing the whole Desktop.

A failed audio device does not grant permission to silently choose a privacy-incompatible provider or modality.

Deterministic fake audio devices SHOULD be used for CI correctness; hardware/live tests may remain opt-in.

---

# 48. Notification / Confirmation / Task Ownership

Slice 10 may improve ergonomics, but ownership remains unchanged:

```text
Notification -> Core-owned
Confirmation/Grant -> Core-owned
Task -> Core-owned
Desktop -> presentation + authenticated user intent
```

Desktop must not synthesize authority from a button click beyond sending the existing authenticated decision/request.

Native notification duplicates for the same Core Notification identity SHOULD be suppressed.

---

# 49. Safe Runtime Diagnostics

Human UI SHOULD prefer product-language states such as:

```text
Sofia ready
AI needs configuration
Memory degraded
Core reconnecting
Realtime unavailable
Scheduler degraded
```

Low-level component details may be available in an advanced diagnostics view.

Diagnostic payloads MUST remain secret-free.

---

# 50. Audit Requirements

Core SHOULD emit safe Audit actions equivalent to:

```text
CLIENT_CORE_ATTACH
CLIENT_CORE_START_REQUESTED
CORE_SHUTDOWN_REQUESTED
PROVIDER_CREDENTIAL_UPDATED
PROVIDER_CREDENTIAL_DELETED
PRIVACY_POLICY_APPLIED
```

Safe metadata may include:

- `instance_key`;
- `runtime_session_id`;
- application version;
- provider id;
- credential ref;
- safe credential source;
- locality;
- cloud-context eligibility;
- result/reason code.

Audit MUST NOT include:

- LocalClientBoundary bearer credential;
- provider/integration secret;
- raw audio;
- full conversation content unless separately required by an existing audit contract;
- hidden chain-of-thought.

---

# 51. Desktop Logging

Desktop logs MUST redact:

- attach credential;
- Authorization headers;
- provider/integration credential request values;
- raw audio payloads;
- unnecessary full conversation content.

HTTP debug logging, if used, MUST apply request/response redaction before persistence/output.

---

# 52. Security Boundary of the Protected Local Store

The Windows protected attach store provides local-user isolation according to the OS mechanism.

Contract v1 does not claim protection from malicious code already running under the same effective OS user with equal access to that user's credential store/processes.

This limitation does not permit weakening bearer/session authentication.

---

# 53. Packaging Acceptance

Gate I16 packaged acceptance MUST prove a human launch flow equivalent to:

```text
launch Sofia Desktop executable
↓
Desktop finds or starts packaged Core
↓
no terminal appears as required workflow
↓
secure attach succeeds
↓
authenticated app becomes usable
```

Normal usage MUST NOT require Python, `uv`, manual port entry or token copy/paste.

Code signing and commercial installer are outside v1 acceptance.

---

# 54. Gate I16 Conformance

Gate I16 conforms when it proves at least:

```text
stable instance-key derivation
protected ClientAttachStore
Core-published rotating attach record
authenticated attach verification
stale-record rejection
wrong-service rejection
packaged explicit Core launch
single-instance race safety
Desktop quit leaves Core alive
reopen attaches existing Core
explicit authenticated Stop Sofia
bounded reconnect/restart behavior
no mutation replay
no attach credential leakage
packaged Desktop + Core human smoke
```

Tests MUST use deterministic attach-store/process fakes where possible plus a real packaged Windows smoke for the product path.

---

# 55. Gate I17 Conformance

Gate I17 conforms when it proves at least:

```text
human readiness Home
provider non-secret configuration UX
purpose-specific provider credential update/delete
safe effective-source/shadowing status
model catalog + discovery refresh UX
capability provenance UX
profile/binding/fallback editor
Core-side validation of every write
routing preview UX
Memory/integration health/configuration UX
no direct SQLite/repository access
no secret echo/log/Audit/UI-model leakage
reconnect behavior
```

The Desktop remains a client of Core services.

---

# 56. Gate I18 Conformance

Gate I18 conforms when it proves at least:

```text
bounded Conversation list
bounded Turn paging
new/resume Conversation
first-run locality choice
cloud cognitive context default false
explicit privacy values on text requests
explicit privacy values on realtime requests
no hidden local_only hardcode
no duplicate Turn on reconnect
real/fake microphone capture pipeline
speaker playback pipeline
voice stop/interrupt/device errors
Task/Confirmation/Notification product UX
human degraded states
close-to-tray
Core remains alive without open Desktop
```

---

# 57. Migration and Persistence

This Contract does not require new Core persistence merely for attach state or Desktop preferences.

Attach material belongs in protected runtime/OS storage.

Desktop presentation preferences belong in QSettings or equivalent local preference store.

Conversation History SHOULD reuse existing Conversation/Turn persistence.

New Core migrations are allowed only when a genuinely new Core-owned durable semantic requires them.

Published migrations remain immutable.

---

# 58. Concurrency Requirements

Implementations MUST test at least:

- two Desktop launches racing to start Core;
- Core lifecycle rotation while stale Desktop holds old attach record;
- old Core cleanup racing with new record publication;
- Desktop quitting during Core startup;
- Core crashing during attach;
- reconnect while Notification/Task state changes;
- credential update while provider config is being read;
- user changing privacy preference between Turns.

No concurrency path may cause an old lifecycle to delete or authenticate as a newer one.

---

# 59. Failure Semantics

Expected failures are explicit product states, not silent fallback.

Examples:

```text
protected attach store unavailable -> CORE_FAILED / actionable diagnostic
Core launch target missing -> CORE_FAILED
identity mismatch -> reject attach
Core startup timeout -> CORE_FAILED / retry action
provider credential missing -> AI needs configuration
platform-store write failure -> credential update fails, old effective state preserved
invalid profile update -> Core rejects, Dashboard displays validation
microphone unavailable -> voice unavailable, text remains usable
```

No failure authorizes disabling authentication or widening privacy policy.

---

# 60. Non-goals

Contract v1 does not define:

- public/LAN/VPS Core API exposure;
- TLS/public trust;
- multi-user auth;
- remote web/mobile client;
- OAuth provider-account flows;
- generic secrets browser/editor;
- billing/cost engine;
- plugin marketplace;
- wake word;
- continuous microphone/camera/screen perception;
- code signing;
- commercial installer;
- self-update/auto-update service;
- distributed Core;
- central cloud control plane.

---

# 61. Compatibility

This is Contract version `1`.

Breaking changes to any of these require a Contract revision or explicit compatible transition plan:

- instance-key semantics;
- attach record identity/lifecycle rules;
- protected attach-store trust model;
- normal close/quit/stop semantics;
- shutdown lifecycle contract;
- provider credential no-echo/write-only semantics;
- privacy/locality human mapping;
- cloud cognitive-context default;
- bounded Conversation History semantics.

Internal class names may change when behavior remains compatible.

---

# 62. Approval Effect

Once approved together with Architecture Review Amendment 0004 and the Slice 10 plan, this Contract satisfies the documentary prerequisite for Slice 10 implementation.

Execution order remains:

```text
Gate I16
↓
Gate I17
↓
Gate I18
```

No later Gate is implicitly authorized to start before the previous Gate is `CLOSED — REMOTE VERIFIED`, unless the user explicitly changes that order.
