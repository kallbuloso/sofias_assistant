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
uv sync
```

## Run

```powershell
uv run python -m sofias_assistant
```

## Quality commands

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

Format files with:

```powershell
uv run ruff format .
```

## Documentation

- `docs/product/` — product requirements and engineering conventions.
- `docs/adr/` — architectural decisions and amendments.
- `docs/exec-plans/active/` — active technical backlog slices.
