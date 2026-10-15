# Sofia's Assistant — Security Baseline

**Status:** APPROVED  
**Baseline date:** 2026-10-14

This is the living security baseline for Sofia's Assistant.

## 1. Authority

The LLM is never authorization authority.

```text
AI proposes
Runtime authorizes
Executor acts
```

User intent may justify a requested action, but it does not bypass Policy,
resource scope, confirmation or current runtime restrictions.

## 2. Least privilege

Effective authority can only narrow:

```text
Tool authority
  ⊆ AgentRun authority
  ⊆ Task/originating authority
  ⊆ Root effective authority
```

Sub-agents cannot create uncontrolled agent trees or widen their own scope.

## 3. Same process is not same authority

The source-first modular monolith runs UI and application modules in one
process, but security boundaries remain explicit.

The UI must not:

- bypass Policy;
- execute protected Tools directly;
- read/write operational persistence as an authority shortcut;
- become the source of truth for AI routing;
- gain unrestricted authority because it is local.

## 4. Confirmation and grants

Protected actions are evaluated deterministically.

Supported outcomes include:

- ALLOW;
- DENY;
- REQUIRE_CONFIRMATION;
- REQUIRE_ELEVATION where implemented.

Persistent Grants must be explicit, auditable, scoped and revocable.

## 5. Filesystem and shell

Filesystem operations must canonicalize paths and enforce resource/workspace
bounds.

Shell/process execution must use an explicit executable plus argv. Do not pass
untrusted model output as a shell command string.

Use bounded output, timeout and filtered environment rules.

`SUBPROCESS` is not a security sandbox. Sandbox execution must fail closed
when no real sandbox backend exists.

## 6. Web access

Web reads must preserve SSRF protections and bounded behavior.

Private, loopback, link-local and metadata-network destinations are denied by
default unless an explicit trusted integration requires otherwise.

## 7. Secrets

Provider and integration credentials must use SecretService/SecretStore
boundaries.

Do not persist plaintext credentials in normal SQLite configuration, logs,
Audit, source files or committed environment files.

`.env.example` contains placeholders only. Real `.env` files remain ignored.

## 8. Memory and context

Sofias Memory content is untrusted contextual input.

Memory cannot grant permissions, create Grants or override Policy.

Cloud context use must respect locality/privacy policy. LOCAL_ONLY data must
never silently fall back to a cloud provider.

## 9. Recovery

Do not blindly retry uncertain mutating side effects.

Automatic retry requires positive evidence that retry is safe. Otherwise fail
closed, reconcile evidence or ask the user.

Process IDs are evidence, not authority to adopt or kill arbitrary processes.

## 10. Audit

Audit should capture:

- requester/origin;
- relevant Task/AgentRun;
- Policy decision;
- Grant/confirmation used;
- Tool/action;
- affected resource;
- outcome/error.

Never persist hidden chain-of-thought or raw credentials.

## 11. Optional local API

If an HTTP/WebSocket adapter is enabled, localhost is not automatically
trusted identity.

Keep loopback-only defaults and real authentication unless a future approved
trust model explicitly replaces them.
