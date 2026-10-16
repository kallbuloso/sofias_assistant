# Sofia's Assistant — Development

**Status:** APPROVED  
**Baseline date:** 2026-10-14

## 1. Development principle

Sofia's Assistant is source-first.

A developer must be able to reach human validation without building an
executable.

Approved canonical flow:

```powershell
cd core
py setup.py
py main.py
```

`core/` is the only Python project root. `setup.py` creates/updates
`core/.venv`, installs `core/requirements.txt`, and `main.py` uses that
environment. Supported runtimes are CPython 3.13.x and 3.14.x; the current
repository baseline uses Python 3.14.

## 2. Dependency interfaces

`requirements.txt` is the human-facing runtime dependency installation interface.
It intentionally excludes release-only tooling such as PyInstaller.

`pyproject.toml` may remain for package metadata, pytest, Ruff, mypy and
other tooling. `uv` may remain an optional contributor tool, but it is not a
conceptual prerequisite for running Sofia.

## 3. Generated artifacts

The repository root must not contain Python environments or tool caches.
`core/.venv` is the only supported local virtual environment.

The following are never source of truth and must stay out of Git anywhere in
the repository:

```text
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.uv-cache/
build/
dist/
*.egg-info/
```

## 4. Execution policy

Sofia's Assistant runs as a Python application from source.

PyInstaller, native executable packaging, `build/` and `dist/` are not part of
the product roadmap or the development workflow.

## 5. Quality

Preserve behavior with focused tests.

Existing contributor commands remain valid during migration where useful:

```powershell
cd core
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

The source-first runtime is independent from those contributor commands; the
migration must not weaken the test baseline merely to simplify startup.

## 6. Human validation

Tests are evidence, not the product.

A slice that changes user interaction is not complete until a human can prove
the promised behavior in the relevant visual/runtime path.

The immediate target is:

```text
setup
  ↓
main.py
  ↓
visual Sofia
  ↓
real conversation
  ↓
confirmation/tool flow
  ↓
observable result/error
```

## 7. Documentation rule

Living documentation is authoritative.

Keep:

- `README.md` — what the project is and how to start;
- `product/docs/Sofia's Assistant — Product Requirements Document.md` — product intent and requirements;
- `docs/architecture.md` — current architecture;
- `docs/security.md` — current security baseline;
- `docs/development.md` — developer workflow.

Historical ADRs, amendments, completed execution plans and gate ledgers belong
to Git history, not the current documentation surface.
