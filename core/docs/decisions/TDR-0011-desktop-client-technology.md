# TDR-0011 — Desktop Client technology

Status: ACCEPTED for Gate I11

Date: 2026-09-13

## Decision

Use **PySide6 / Qt Widgets** for the first Windows-first Desktop Client.

The Client remains a separate application package. It talks only to the
authenticated Local Client Boundary over loopback HTTP/NDJSON and WebSocket.
PySide6 is a presentation/runtime dependency of the Client and is not imported
by Core domain, persistence, execution, policy or provider modules.

## Comparison

| Criterion | PySide6 / Qt Widgets | Tauri 2 | Electron |
| --- | --- | --- | --- |
| Windows startup/tray | Native Qt Widgets and `QSystemTrayIcon`; direct fit | Strong, but Rust/plugin composition required | Strong, but Chromium main-process composition |
| Native notifications | Qt tray balloon baseline; explicit OS behavior | Notification plugin; Windows installed-app caveat | Native Notification API |
| Audio/realtime feasibility | Qt Multimedia and Python WebSocket adapter; same language as Core | Strong, but Rust/JS audio bridge | Strong, but Node/renderer audio bridge |
| Local authenticated HTTP/WS | Python `httpx2`/`websockets`; no new protocol | Straightforward, adds Rust command/permission bridge | Straightforward, adds preload/IPC boundary |
| Renderer privilege model | No web renderer; widgets receive view-model data only | Strong capability model, but must configure it | Strong only with sandbox, context isolation, CSP and allowlisted preload |
| Footprint | Qt runtime, lower integration complexity for this Python codebase | Usually smallest binary, Rust toolchain overhead | Largest runtime and memory footprint |
| Packaging | `pyside6-deploy`/Nuitka baseline; Windows executable | Tauri Windows bundle; Rust toolchain | Electron Forge/builder; signing/update complexity |
| Testability | Pure Python service/view-model tests plus Qt offscreen tests | JS/Rust split and WebDriver/IPC tests | Renderer/main/preload integration tests |
| Maintainability | One language and existing Python contracts | Two application languages | JS/Node plus Python Core |
| License | PySide6 LGPLv3/GPLv3/commercial; acceptable for this project | MIT/Apache ecosystem; acceptable | MIT ecosystem; Chromium distribution obligations |
| Future auto-start/update | Add Windows startup/update adapter later; outside Gate | Official plugins available later | Mature Windows updater path, but signing/distribution required |

## Why this is the smallest safe choice

The existing Core is Python and already exposes transport-safe HTTP/NDJSON and
WebSocket contracts. PySide6 permits the Client Application Services and
transport adapter to remain typed Python without exposing Core internals. A
Qt widget has no filesystem, shell, SQLite, Policy, Tool or SecretStore access
by default; actions call the central adapter, which requires the authenticated
session on every request.

The MVP uses an in-memory credential supplied by an explicit launch/configuration
boundary. It is never logged, rendered as UI text, hardcoded, or persisted as
domain state. A future Windows Credential Manager adapter can be added without
changing Core contracts. UI-local preferences are limited to presentation state.

Native notification presentation is best-effort; the durable Core notification
list and acknowledgment remain authoritative. Realtime voice controls use the
existing Core WebSocket protocol. Actual microphone/provider smoke remains
opt-in when hardware or provider credentials are unavailable.

## Rejected alternatives

Tauri was rejected for this Gate, not as a future option: its security and
footprint are attractive, but the Rust/frontend/permission bridge would add a
second application stack before the first product flow is proven. Electron was
rejected because its Chromium/Node main-renderer-preload model, package size and
security checklist add structural cost without improving the Python Core seam.

Reference harvest was directed to official documentation:

- [Qt for Python system tray](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)
- [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Qt Multimedia on Windows](https://doc.qt.io/qtforpython-6.10/overviews/qtmultimedia-windows.html)
- [Tauri capabilities](https://tauri.app/security/capabilities/)
- [Tauri notifications](https://v2.tauri.app/plugin/notification/)
- [Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security)
- [Electron distribution](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)

No Core architecture was copied from any candidate and no candidate changes the
frozen `Core != Client` or `Client != authority` contracts.
