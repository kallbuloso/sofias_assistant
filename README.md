# Sofia's Assistant

Sofia's Assistant is a local-first personal AI assistant under early development.
The repository currently provides the implementation foundation: project metadata,
the installable Python package, and its initial quality checks.

The Product Requirements Document (PRD) and Architecture Decision Records (ADRs)
are the project's architectural baseline.

## Requirements

- Python `>=3.13,<3.14`
- [uv](https://docs.astral.sh/uv/)

## Setup

```powershell
cd core
uv sync
```

## Run

```powershell
cd core
uv run python -m sofias_assistant
```

## Development configuration (Sofias Memory)

Local, non-secret configuration lives in `core/.env` (git-ignored):

```powershell
cd core
copy .env.example .env
# edit .env if your Sofias Memory URL/timeouts differ from the defaults
```

The Sofias Memory API key is never stored in `.env`. Store it via the
Secret CLI, which prompts interactively and never echoes or logs the value:

```powershell
uv run python -m sofias_assistant.secrets set integrations/sofias-memory/api-key
uv run python -m sofias_assistant.secrets exists integrations/sofias-memory/api-key
uv run python -m sofias_assistant.secrets delete integrations/sofias-memory/api-key
```

With `.env` configured and the key stored, the opt-in live Sofias Memory
smoke can run against a real instance:

```powershell
uv run pytest tests/integration/memory/test_memory_live_smoke.py -v
```

It stays SKIPPED by default (including in CI) unless
`SOFIAS_ASSISTANT_RUN_MEMORY_INTEGRATION_TESTS=1` is set in `.env` or the
real environment.

## Quality commands

```powershell
cd core
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

Format files with:

```powershell
cd core
uv run ruff format .
```

## Documentation

- `product/docs/` — product requirements and engineering conventions.
- `product/docs/adr/` — architectural decisions and amendments.
- `core/docs/exec-plans/active/` — active technical backlog slices.
