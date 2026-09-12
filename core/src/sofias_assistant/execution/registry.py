"""Authoritative registry for Core-owned Tool specifications."""

from __future__ import annotations

from dataclasses import replace

from sofias_assistant.execution.models import ToolSpec


class ToolRegistry:
    """Keep enabled Tool metadata and handlers behind one authoritative lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def replace(self, spec: ToolSpec) -> None:
        if spec.name not in self._tools:
            raise KeyError(spec.name)
        self._tools[spec.name] = spec

    def disable(self, name: str) -> None:
        spec = self.resolve(name)
        self._tools[name] = replace(spec, enabled=False)

    def enable(self, name: str) -> None:
        spec = self.resolve(name)
        self._tools[name] = replace(spec, enabled=True)

    def resolve(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"Tool is not registered: {name}") from None

    def list(self, *, enabled_only: bool = True) -> tuple[ToolSpec, ...]:
        values = tuple(self._tools.values())
        return (
            tuple(spec for spec in values if spec.enabled) if enabled_only else values
        )
