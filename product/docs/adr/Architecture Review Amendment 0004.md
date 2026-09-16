# Architecture Review Amendment 0004

**Project:** Sofia's Assistant  
**Status:** Proposed — Ready for Approval  
**Decision date:** 2026-09-16  
**Applies to:** ADR-0001, ADR-0002, ADR-0005, ADR-0006, ADR-0015, Architecture Review Amendments 0001/0003, TDR-0011, Technical Backlog Slice 10  
**Origin:** Post-Slice-09 human desktop architecture review  
**Purpose:** freeze durable architecture for Desktop/Core lifecycle, secure local attach, Core shutdown, human credential UX, Conversation History and inference privacy/locality

---

# 1. Context

After Slice 09, Sofia's Assistant has a production Core host, authenticated loopback API, persistent AI configuration, dynamic model routing and a PySide6 Desktop Client.

The remaining product gap is no longer primarily capability. It is human operation.

Today, a technically informed operator can start the Core, obtain local access material and operate the Desktop. A normal user should not need to understand:

```text
sofia-core
loopback ports
bearer credentials
SecretRef
runtime_session_id
CapabilityRouter
routing snapshots
```

Improving that experience must not collapse the accepted Core/Client trust boundary.

The target architecture is:

```text
human launches Desktop
        ↓
Desktop supervises discovery/start/attach
        ↓
Core remains an independent process
        ↓
Local Client authentication remains real
        ↓
Desktop renders and sends user intent
        ↓
Core remains authority for domain state, routing, lifecycle and protected actions
```

This Amendment defines the durable boundaries needed by Slice 10.

---

# 2. Precedence

When this Amendment conflicts with an earlier decision for the topics explicitly refined here, this Amendment prevails.

It does not replace non-conflicting decisions in the affected ADRs, Amendments, TDR-0011 or the AI Runtime Configuration Contract v1.

The normative wire/lifecycle details are delegated to:

```text
Sofia's Assistant — Desktop/Core Interaction Contract v1
```

---

# 3. Fundamental Rule

The human experience may hide architectural complexity, but it may not remove architectural boundaries.

```text
Invisible to user
    !=
removed from architecture
```

Therefore:

```text
Desktop != Core
Desktop != authority
localhost != identity
attach material != provider credential
UI preference != authorization authority
Conversation History != Cognitive Memory
```

And the project-wide invariant remains:

```text
AI proposes.
Runtime authorizes.
Executor acts.
```

---

# 4. Desktop May Start Core, But Does Not Own Core

The Desktop Client may supervise the Core for product ergonomics.

It may:

- discover the expected local Core instance;
- start the packaged Core when the expected instance is absent;
- wait for readiness;
- obtain secure attach material;
- authenticate normally;
- reconnect after bounded interruption;
- request explicit graceful shutdown.

It does not become Core owner in the domain or authority sense.

The Core remains an independent process capable of continuing:

- Scheduler;
- Reminders;
- background Tasks;
- Notifications;
- Recovery;
- operational persistence;

without an open Desktop window or a running Desktop process.

---

# 5. Window Close, Desktop Quit and Stop Sofia Are Different Operations

The product semantics are frozen as:

```text
Close main window
    -> hide/minimize to tray
    -> Desktop process remains alive
    -> Core remains alive

Quit Desktop
    -> Desktop process exits
    -> Core remains alive

Stop Sofia
    -> explicit human lifecycle action
    -> authenticated request to Core
    -> graceful Core shutdown
    -> Desktop may exit afterwards when appropriate
```

No ordinary close/quit path may silently terminate the Core.

---

# 6. PID Is Evidence, Not Authority

The Desktop must not implement Core lifecycle through arbitrary process termination.

Forbidden product behavior includes:

```text
find process by name/PID
kill process
assume lifecycle completed
```

A PID may be used as bounded diagnostic evidence or for child-process observation when the Desktop itself launched that process.

Core shutdown remains Core-owned and occurs through a dedicated authenticated lifecycle command.

Operating-system forced termination remains an exceptional recovery/diagnostic concern, not normal UX.

---

# 7. Core Supervision Is an Application Boundary

Desktop/Core supervision belongs in a dedicated application service, conceptually:

```text
DesktopCoreSupervisor
```

It does not belong in individual Qt widgets.

The supervisor owns orchestration of:

```text
expected instance
→ discovery
→ attach or launch
→ bounded readiness wait
→ authentication
→ connection state
→ bounded reattach/recovery
```

Qt widgets consume supervisor/application state and issue user intents.

---

# 8. Logical Instance Identity

An open loopback port is not sufficient identity.

The expected Core instance must be tied to the same logical data identity used by Core single-instance ownership.

The stable attach lookup identity must therefore derive from the canonical Core data-directory identity, using the same normalization semantics as single-instance ownership or a shared equivalent helper.

This stable identity is an `instance_key`.

It is:

- stable for the same configured data identity;
- non-secret;
- safe to use as a lookup key;
- not itself authentication authority.

Each Core start also has a lifecycle identity. The existing Core `runtime_session_id` is the preferred lifecycle identity when sufficient.

The Desktop must verify both expected logical instance and current lifecycle before treating an attach as valid.

---

# 9. Secure Attach Does Not Weaken Local Authentication

The existing `LocalClientBoundary` ephemeral credential remains real.

Human UX removes manual token handling, not authentication.

The architecture becomes:

```text
Core starts LocalClientBoundary
        ↓
Core owns freshly generated runtime credential
        ↓
Core publishes bounded attach record through protected local-user storage
        ↓
Desktop reads record for expected instance
        ↓
Desktop authenticates through existing LocalClientBoundary flow
        ↓
Desktop verifies Core instance/lifecycle identity
        ↓
normal authenticated client session
```

The attach store is a credential-delivery mechanism.

It is not a second authenticator and does not replace `LocalClientAuthenticator` / `ClientSessionRegistry`.

---

# 10. ClientAttachStore

A dedicated abstraction equivalent to:

```text
ClientAttachStore
```

owns attach-record publication and retrieval.

Windows-first implementation should use an OS-protected local-user credential mechanism, with Windows Credential Manager as the preferred baseline unless implementation evidence requires an equivalent protected mechanism.

The abstraction must permit future platform-specific implementations without changing Desktop/Core contracts.

It must not use as plaintext storage:

- Operational Store / SQLite;
- `.env`;
- QSettings;
- ordinary JSON/config files;
- stdout;
- logs;
- Audit.

A deterministic in-memory implementation is required for tests.

---

# 11. Attach Record Semantics

The protected attach record contains only the bounded material necessary to attach to one current Core lifecycle.

Semantically it includes:

```text
contract_version
instance_key
runtime_session_id
loopback host
port
LocalClientBoundary credential
Core/application version
created_at
optional PID/process evidence
```

The bearer credential remains secret and redacted from representation.

The record must be bounded and versioned.

A new Core lifecycle rotates the credential and `runtime_session_id` and replaces the previous record for that `instance_key`.

---

# 12. Attach Record Publication and Cleanup

Publication occurs only after:

1. Core has acquired exclusive instance ownership;
2. Core has started successfully;
3. LocalClientBoundary is listening;
4. the current runtime credential exists;
5. identity information for the running lifecycle is available.

Human-attach readiness is not declared before the protected record is published successfully.

On graceful shutdown, the Core removes the record for its own lifecycle before or as part of boundary teardown.

Cleanup must be compare-by-lifecycle / delete-if-current semantics so an older process cannot delete a newer lifecycle's record.

If a crash leaves stale material behind, that record is not trusted merely because it exists.

---

# 13. Stale Attach Records Fail Closed

The Desktop validates attach material through real authentication and an authenticated Core identity response.

A record is stale/invalid when, for example:

- the endpoint is not reachable;
- authentication fails;
- protocol/contract version is incompatible;
- returned `instance_key` differs;
- returned `runtime_session_id` differs;
- the endpoint is not the expected Sofia Core protocol.

No mutating request is sent before attach verification completes.

The Desktop may remove a stale record only with compare/delete semantics for the record it actually observed.

A stale record must never cause attachment to an arbitrary service merely because it owns the expected port.

---

# 14. Threat Model for Local Attach

Contract v1 protects against:

- accidental cross-instance attachment;
- an unrelated service listening on the expected port;
- stale runtime credentials;
- plaintext token persistence in application settings/logs;
- cross-user exposure when the platform protected store provides user isolation.

It does not claim to defend against malware already executing with equivalent privileges under the same operating-system user and able to access that user's protected credential store/process memory.

That is outside the local Desktop trust model of this phase.

This limitation must not be misrepresented as network-grade hostile-host isolation.

---

# 15. Core Launch

Packaged human startup must create a separate Core OS process.

The concrete distribution may use:

- a sibling packaged `sofia-core` executable; or
- an equivalent packaged executable mode that starts a distinct Core process.

The Desktop uses an explicit executable path and explicit argv.

It must not use:

```text
shell=True
cmd.exe /c <arbitrary string>
PowerShell -Command <arbitrary user-controlled string>
```

Development launch helpers may differ, but acceptance for the packaged product must not require Python, `uv`, or an open terminal.

---

# 16. Duplicate Core Prevention

Desktop supervision does not replace Core single-instance ownership.

If attach material is absent or stale, the Desktop may attempt to start the expected Core, but the Core remains responsible for exclusive ownership of its data identity.

If another matching Core wins the race, a new launch must fail safely and the Desktop must retry discovery/attach instead of creating a second operational owner.

No Desktop-side PID registry becomes a parallel ownership system.

---

# 17. Crash and Reconnect Behavior

Unexpected Core loss transitions the Desktop into reconnect/degraded state.

Automatic recovery must be bounded.

The Desktop may:

- retry connection for a bounded period;
- re-read protected attach material;
- launch one or more explicitly bounded restart attempts according to implementation policy.

It must not create an unbounded restart storm.

After the bounded policy is exhausted, human retry is required.

The Desktop must never automatically replay mutating user requests whose completion is uncertain.

Core Recovery remains authoritative for Tasks and side-effect uncertainty.

---

# 18. Graceful Stop Sofia Is a Core Lifecycle Command

`Stop Sofia` is implemented through a purpose-specific authenticated Core lifecycle surface.

It is not a Tool and does not create a second Tool/Policy authorization model.

Requirements:

- authenticated local client session;
- explicit human intent in the UI;
- request scoped to the current Core lifecycle;
- safe Audit evidence without credentials;
- asynchronous/bounded graceful shutdown;
- normal instance ownership cleanup;
- LocalClientBoundary/session revocation through ordinary shutdown.

The exact API is defined by the Desktop/Core Interaction Contract v1.

---

# 19. PySide6 Remains the Desktop Technology

TDR-0011 remains accepted.

Slice 10 evolves the existing PySide6/Qt Widgets client.

Tauri/Electron/PySide technology selection is not reopened unless a material blocker proves the accepted choice unable to satisfy a required contract.

---

# 20. Dashboard Remains a Client

The human Dashboard is a presentation/application layer over authenticated Core services.

It may:

- display Core state;
- send configuration intents;
- display validation errors;
- show provider/model/profile state;
- show Tasks, Notifications, Conversation History and health;
- submit secure secret writes through purpose-specific endpoints.

It must not:

- access SQLite directly;
- import repositories as UI authority;
- execute Tools directly;
- select a routing result locally as authoritative;
- persist Core domain state in QSettings as truth;
- bypass LocalClientBoundary authentication.

---

# 21. Human Provider Credential UX

Editing `.env` is a deployment mechanism, not the final human credential UX.

The Desktop may submit a provider/integration credential only through a purpose-specific authenticated write surface.

The Core receives the secret transiently and immediately hands it to `SecretService` / the configured writable platform secret store.

The Core never returns the stored secret.

Generic secret enumeration/dump APIs remain prohibited.

---

# 22. Environment Secrets Remain Deployment-Owned

The precedence established by Amendment 0003 remains:

```text
process/environment-backed secret
    > writable platform secret store
```

Human Dashboard writes target the writable durable platform store.

The Dashboard does not mutate the process environment or the explicitly selected env file.

If a higher-priority environment-backed secret shadows a newly written platform-store value, the Core must expose safe status indicating the effective source/shadowing without exposing either value.

Deleting a durable platform secret does not magically remove a higher-priority environment secret.

---

# 23. Conversation History Is Operational Data

Conversation/Turn history remains Core-owned Operational Store data.

```text
Conversation History != Sofias Memory
```

Displaying, paginating, resuming or deriving deterministic previews from Conversation/Turn rows does not create a second Cognitive Memory subsystem.

Desktop must not persist a duplicate authoritative transcript.

Conversation History APIs must be bounded/paginated for product use.

---

# 24. Inference Privacy Becomes Explicit Human Intent

Desktop must no longer silently hardcode one locality policy for all inference.

The human-facing baseline is:

```text
Local only
Allow cloud
Prefer cloud
```

mapped to the existing `DataLocality` contract.

Separately, permission to send recalled cognitive memory/context to cloud models remains explicit and begins disabled.

```text
cloud_context_eligible = false
```

until the user opts in.

Profiles/routing may narrow or rank eligible candidates but may never widen the request's privacy/locality policy.

---

# 25. Privacy Preference Is Not Authorization Authority

Desktop may persist the user's default inference privacy choice as local UI/application preference because it is request policy, not system authority.

Every relevant request must carry the effective values explicitly to Core.

Core validates and enforces them.

Changing a preference does not create a Grant and does not authorize Tool execution.

No real human inference should be initiated by the Desktop before first-run locality choice is resolved.

---

# 26. Realtime Voice Uses the Same Privacy Contract

Voice is not a separate privacy universe.

Realtime session requests carry the user's effective locality and cloud-context eligibility.

The `realtime` profile continues to enforce its hard model capabilities.

The Desktop may own microphone/speaker device selection and audio I/O presentation, but it does not create a second Realtime domain runtime.

Microphone capture is user-initiated and bounded to the active voice session.

No continuous background listening or wake word is authorized by this Amendment.

---

# 27. State Ownership

State remains separated as:

```text
Core-owned authoritative state
    Conversation / Turn
    Task
    Notification
    Confirmation / Grant
    ProviderConfiguration
    ModelCatalog
    InferenceProfile / Binding
    Schedule
    Audit

OS-protected attach state
    current runtime attach material

Desktop-local presentation/preferences
    window geometry
    selected page
    theme
    notification presentation preference
    default inference privacy preference
    preferred audio device identifiers
```

QSettings must not become an Operational Store.

---

# 28. Audit

New lifecycle and human-configuration actions should emit safe Audit evidence equivalent to:

```text
CLIENT_CORE_ATTACH
CLIENT_CORE_START_REQUESTED
CORE_SHUTDOWN_REQUESTED
PROVIDER_CREDENTIAL_UPDATED
PROVIDER_CREDENTIAL_DELETED
PRIVACY_POLICY_APPLIED
```

Concrete names may follow existing Audit conventions.

Audit must never contain:

- LocalClientBoundary credential;
- provider/integration credential;
- raw audio by default;
- unnecessary full conversation content;
- hidden reasoning.

---

# 29. Packaging Boundary

The packaged Windows experience must be self-sufficient for normal launch:

```text
Desktop executable
    ↓
find/start separate packaged Core
    ↓
secure attach
    ↓
authenticated product UX
```

The packaging format may evolve without changing this ownership boundary.

Code signing, commercial installer, login auto-start and self-update remain separate future decisions.

---

# 30. Cross-platform Direction

Windows is the first fully supported human Desktop target.

The architecture must keep these seams portable:

- `ClientAttachStore`;
- Core executable locator/launcher;
- process observation;
- secure credential storage;
- audio device abstraction.

Linux/macOS implementations may follow later without changing Core application contracts.

---

# 31. Security Invariants Preserved

This Amendment does not alter:

- deterministic Policy;
- Grant/Confirmation semantics;
- Tool authorization;
- Agent authority narrowing;
- authenticated LocalClientBoundary;
- loopback-only default network boundary;
- SecretService as secret access boundary;
- Sofias Memory ownership/trust rules;
- recovery fail-closed behavior;
- provider-neutral routing.

Human convenience is never a reason to bypass these boundaries.

---

# 32. Non-goals

This Amendment does not authorize:

- public or LAN Core exposure;
- TLS termination/public API;
- multi-user authentication;
- mobile/web remote client;
- OAuth provider accounts;
- generic secret management UI/API;
- billing engine;
- plugin marketplace;
- distributed Core;
- wake word;
- continuous microphone/camera/screen monitoring;
- code signing/installer/update system;
- direct UI Tool execution;
- arbitrary process-kill authority.

---

# 33. Consequences

Positive consequences:

- normal users can launch Sofia without terminal/token handling;
- Core remains independently operational in background;
- localhost authentication remains meaningful;
- provider credentials can be configured safely from product UX;
- Conversation History becomes usable without being confused with Cognitive Memory;
- privacy/locality becomes visible human intent rather than hidden client hardcode.

Accepted costs:

- secure attach requires platform-specific protected-store implementation;
- Core host lifecycle gains attach publication/cleanup responsibilities;
- Desktop gains a real supervisor state machine;
- package layout must include a launchable Core target;
- secret-source precedence must be represented clearly in UX;
- bounded history APIs and privacy preference plumbing require additional Core/Client contracts.

---

# 34. Implementation Contract

The exact v1 semantics for:

- attach records;
- instance/lifecycle verification;
- supervisor states;
- Core lifecycle endpoints;
- credential write endpoints;
- secret-source reporting;
- Conversation History APIs;
- inference privacy mapping;
- packaging/start behavior;

are defined by:

```text
Sofia's Assistant — Desktop/Core Interaction Contract v1
```

---

# 35. Approval Effect

Once this Amendment, the Desktop/Core Interaction Contract v1 and Slice 10 are approved, the documentary prerequisites for Slice 10 Run 1 / Gate I16 are satisfied.

Approval does not close I16/I17/I18 and does not authorize implementation to skip tests, packaging evidence, remote CI or Gate closure requirements.
