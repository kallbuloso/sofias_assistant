"""Controlled explicit-argv subprocess capability."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sofias_assistant.capabilities.filesystem import canonicalize_path, file_resource
from sofias_assistant.execution.models import (
    GrantLifetime,
    SubprocessInvocation,
    ToolExecutionMode,
    ToolSideEffect,
    ToolSpec,
)

_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "PYTHONIOENCODING",
        "LANG",
        "LC_ALL",
        "SOFIA_TEST",
    }
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def resolve_executable(value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("executable must be a non-empty string")
    candidate = value.strip()
    resolved_name = (
        candidate if Path(candidate).is_absolute() else shutil.which(candidate)
    )
    if not resolved_name:
        raise ValueError("executable is not available")
    path = canonicalize_path(resolved_name, must_exist=True)
    if not path.is_file():
        raise ValueError("executable must identify a file")
    return path


class ShellCapability:
    """Build a dynamic subprocess ToolSpec without invoking a process itself."""

    def __init__(self, *, output_limit_bytes: int = 64 * 1024) -> None:
        if output_limit_bytes <= 0:
            raise ValueError("output_limit_bytes must be positive")
        self.output_limit_bytes = output_limit_bytes

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="shell.execute",
            version="1",
            description="Execute one explicit executable and argv under subprocess isolation",
            capability="shell.execute",
            handler=lambda _: None,
            resource_resolver=self.resource,
            input_validator=self.validate,
            side_effect=ToolSideEffect.MUTATING,
            confirmation_lifetime=GrantLifetime.ONE_SHOT,
            execution_mode=ToolExecutionMode.SUBPROCESS,
            timeout_seconds=30.0,
            idempotent=False,
            subprocess_resolver=self.resolve_invocation,
            subprocess_output_limit_bytes=self.output_limit_bytes,
        )

    def validate(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        executable = resolve_executable(arguments.get("executable"))
        raw_argv = arguments.get("argv", arguments.get("arguments", ()))
        if not isinstance(raw_argv, (list, tuple)) or any(
            not isinstance(argument, str) for argument in raw_argv
        ):
            raise ValueError("argv must be a list of strings")
        if len(raw_argv) > 128 or any(len(argument) > 4096 for argument in raw_argv):
            raise ValueError("argv exceeds the supported bound")
        cwd = canonicalize_path(arguments.get("cwd"), must_exist=True)
        if not cwd.is_dir():
            raise ValueError("cwd must identify a directory")
        timeout = arguments.get("timeout_seconds", 30.0)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 300
        ):
            raise ValueError("timeout_seconds is outside the supported bound")
        overrides = arguments.get("environment_overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("environment_overrides must be an object")
        filtered: dict[str, str] = {}
        for key, value in overrides.items():
            if not isinstance(key, str) or not _ENVIRONMENT_NAME.fullmatch(key):
                raise ValueError("environment variable name is invalid")
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError("environment variable value is invalid")
            if key in _ENVIRONMENT_ALLOWLIST:
                filtered[key] = value
        return {
            "executable": str(executable),
            "argv": tuple(raw_argv),
            "cwd": str(cwd),
            "timeout_seconds": float(timeout),
            "environment_overrides": filtered,
        }

    def resource(self, arguments: Mapping[str, Any]) -> str:
        executable = resolve_executable(arguments["executable"])
        cwd = canonicalize_path(arguments["cwd"], must_exist=True)
        return "subprocess://execute?executable={}&cwd={}".format(
            quote(file_resource(executable), safe=""),
            quote(file_resource(cwd), safe=""),
        )

    def resolve_invocation(self, arguments: Mapping[str, Any]) -> SubprocessInvocation:
        validated = self.validate(arguments)
        environment = {
            key: value
            for key, value in dict(validated["environment_overrides"]).items()
            if key in _ENVIRONMENT_ALLOWLIST
        }
        return SubprocessInvocation(
            executable=str(validated["executable"]),
            argv=tuple(validated["argv"]),
            cwd=str(validated["cwd"]),
            environment=environment,
            timeout_seconds=float(validated["timeout_seconds"]),
        )
