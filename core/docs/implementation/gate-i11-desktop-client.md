# Gate I11 — Desktop Client implementation note

Status: implementation complete; awaiting remote verification

## Architecture

The Windows-first client is a separate PySide6/Qt Widgets package under
`sofias_assistant.client_app`:

```text
Qt widgets + tray
    ↓
DesktopController / ClientApplicationService
    ↓
CoreApiClient / RealtimeVoiceConnection
    ↓ authenticated Local Client Boundary
Sofia Core
```

The client has no SQLite, repository, Policy, Tool, provider or SecretStore
imports. Core remains authoritative for Conversation, Task, Notification,
Confirmation, Grant and Health state. The only operational API extension is a
bounded authenticated task listing endpoint, scoped to the authenticated
Local Client session.

## Technology decision

`TDR-0011-desktop-client-technology.md` records the directed comparison of
PySide6/Qt, Tauri and Electron. PySide6 was selected because it keeps the
first client in the existing Python seam, provides native Windows tray
support, supports the existing HTTP/NDJSON/WebSocket contracts and avoids a
web renderer privilege boundary for this MVP.

## Product flows

- Chat creates/opens a Core-owned Conversation and renders NDJSON streaming
  deltas.
- Voice exposes start, stop and interrupt over the existing authenticated
  realtime WebSocket protocol; no second voice runtime or wake-word loop is
  created.
- Notifications are synchronized from Core, acknowledged through Core and
  rendered in-app plus best-effort native tray messages. Permission requests
  call the existing approve/deny endpoints and never create local Grants.
- Tasks are bounded, session-scoped, listed through Core and cancellable only
  through the existing Core endpoint.
- Health maps missing AI, Realtime and Memory probes explicitly to
  `unavailable`/`Not configured`; Memory absence does not block the other UI.
- Settings contain only the loopback Core URL and a UI-local native-notification
  preference. No domain state is stored in the client.

## Authentication and reconnect

The Local Client credential is supplied through the existing boundary or an
explicit password prompt, held in memory, excluded from `repr` and error
messages, and never logged or persisted. The adapter validates loopback HTTP
URLs and sends both the bearer credential and authenticated client-session
header. Snapshot refresh reconstructs health, pending notifications, Tasks and
Conversation availability after reconnect. Connection states are
`CONNECTING`, `CONNECTED`, `DEGRADED` and `DISCONNECTED`.

## Packaging and verification

`client/SofiaAssistant.spec` produces a Windows `dist/SofiaAssistant.exe`
baseline. The application was started with the packaged executable, its
disconnected-Core path remained usable, and the explicit `--smoke` startup
path exited successfully. Deterministic offscreen Qt tests cover settings and
tray rendering; Local Client integration tests cover real authenticated
boundary startup, synchronization, Conversation creation and wrong-credential
rejection.

Real microphone/provider audio remains opt-in because it requires hardware or
provider credentials; the client exposes the already-defined Core realtime
control boundary without inventing a local audio authority.
