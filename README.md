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
