# Sofia's Assistant — Slice 10 Approval Record

**Date:** 2026-09-16  
**Project:** Sofia's Assistant  
**Scope:** Technical Backlog Slice 10 — Human Desktop Experience  
**Approval source:** explicit user approval in project governance conversation

---

## Approved documents

The following documents are approved as the active architectural/product baseline for Slice 10:

```text
Architecture Review Amendment 0004
Human Desktop Lifecycle, Secure Attach and Credential UX
Status: ACCEPTED

Sofia's Assistant — Desktop/Core Interaction Contract v1
Status: APPROVED

Sofia's Assistant — Technical Backlog Slice 10
Status: APPROVED
```

This approval resolves the documentary prerequisite declared by Slice 10 before implementation of Run 1 / Gate I16.

---

## Previous Slice status

```text
Slice 09 — Core Runtime Configuration & Intelligent AI Routing
Status: COMPLETED — REMOTE VERIFIED
```

Its file already resides under `core/docs/exec-plans/completed/`; any stale `APPROVED` header is documentary housekeeping only and does not reopen Slice 09.

---

## Gate state after approval

```text
Slice 10 — APPROVED / ACTIVE

Gate I16 — READY
└── SA-B038 Core Supervision & Secure Attach

Gate I17 — BLOCKED BY I16
└── SA-B039 Human Configuration Dashboard

Gate I18 — BLOCKED BY I17
├── SA-B040 Conversation History & Privacy UX
└── SA-B041 Voice & Operational UX
```

No implementation work is authorized to skip the accepted ordering:

```text
I16
↓
I17
↓
I18
```

---

## Frozen approval effects

Approval freezes the following direction for Slice 10:

- Desktop may start Core but does not own Core;
- Core remains an independent background process;
- close window -> tray;
- Quit Desktop leaves Core alive;
- Stop Sofia is an explicit authenticated graceful Core shutdown request;
- localhost authentication remains real;
- attach credential remains hidden from human UX but real in architecture;
- Core generates and owns the effective LocalClientBoundary credential;
- secure attach uses protected local-user storage behind `ClientAttachStore`;
- PID is evidence, never lifecycle authority;
- PySide6/Qt remains the accepted Desktop technology;
- Dashboard remains a client of authenticated Core services;
- provider/integration credentials use purpose-specific write-only secret surfaces through `SecretService`;
- environment/deployment secrets retain precedence over writable platform-store secrets;
- Conversation History remains Core operational data and is not Sofias Memory;
- inference locality is an explicit human request policy;
- cloud cognitive context remains opt-in and defaults to disabled;
- mutating Desktop requests are never replayed automatically after uncertain transport failure;
- packaged human startup must not require Python, `uv`, terminal use, manual port entry or token copy/paste.

---

## Normative precedence for Slice 10 implementation

For the subjects covered by these documents:

```text
explicit user instruction
↓
this approval record
↓
active Slice 10
↓
Architecture Review Amendment 0004
↓
Desktop/Core Interaction Contract v1
↓
Architecture Review Amendment 0003
↓
AI Runtime Configuration Contract v1
↓
accepted ADRs / TDR-0011
↓
existing implementation
```

This record exists to make approval state unambiguous without rewriting large planning/architecture files solely to change header status lines.

---

## Next action

The next authorized implementation step is:

```text
Run 1
Gate I16 — Seamless Desktop Runtime
SA-B038 — Core Supervision & Secure Attach
```

Gate I17 and Gate I18 remain blocked until the preceding Gate is closed and remotely verified.
