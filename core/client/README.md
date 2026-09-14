# Sofia's Assistant Desktop Client

The first Desktop Client is a PySide6/Qt Widgets Windows-first application.
It is a presentation client only:

```text
Qt UI → ClientApplicationService → CoreApiClient
     → authenticated Local Client Boundary → Sofia Core
```

The Client never opens SQLite, imports Core repositories, invokes Tools, calls
Policy, talks to AI providers, or reads the SecretStore. The bearer credential
is supplied by `SOFIA_CLIENT_CREDENTIAL` or an explicit startup prompt and is
held only in memory. It is never logged or rendered.

## Development

From `core/`:

```powershell
uv sync --group client
$env:SOFIA_CORE_URL = "http://127.0.0.1:8989"
$env:SOFIA_CLIENT_CREDENTIAL = "<credential delivered by LocalClientBoundary>"
uv run --group client python -m sofias_assistant.client_app
```

`--smoke` starts the application without prompting for a credential and exits
after a short startup interval. It is intended for packaging/startup checks;
real Core connection smoke requires the credential delivered by the Core-owned
Local Client Boundary.

## Windows package baseline

```powershell
uv run --group client python -m PyInstaller --noconfirm client/SofiaAssistant.spec
```

The baseline executable is written to `dist/SofiaAssistant.exe`. Code signing,
installer UX, auto-start and auto-update are intentionally future work.
