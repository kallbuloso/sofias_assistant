"""Core-owned execution isolation dispatcher."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Mapping
from typing import Any

from sofias_assistant.execution.models import (
    ToolExecutionMode,
    ToolResult,
    ToolSpec,
)


class ExecutionDispatcher:
    """Dispatch already-authorized work without creating authority."""

    async def dispatch(
        self, spec: ToolSpec, arguments: Mapping[str, Any], *, call_id: Any
    ) -> ToolResult:
        if spec.execution_mode is ToolExecutionMode.IN_PROCESS:
            value = spec.handler(arguments)
            if inspect.isawaitable(value):
                value = await value
            return ToolResult(status="SUCCEEDED", call_id=call_id, value=value)
        if spec.execution_mode is ToolExecutionMode.SUBPROCESS:
            return await self._subprocess(spec, arguments, call_id=call_id)
        return ToolResult(
            status="FAILED",
            call_id=call_id,
            error=_error("SANDBOX_UNAVAILABLE", "Sandbox execution is unavailable"),
        )

    async def _subprocess(
        self, spec: ToolSpec, arguments: Mapping[str, Any], *, call_id: Any
    ) -> ToolResult:
        command = spec.subprocess_command
        if not command:
            return ToolResult(
                status="FAILED",
                call_id=call_id,
                error=_error("SUBPROCESS_INVALID", "Subprocess command is unavailable"),
            )
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            **dict(spec.subprocess_environment),
        }
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=spec.subprocess_cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            payload = json.dumps(dict(arguments), sort_keys=True).encode("utf-8")
            if process.stdin is not None:
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
            stdout_task = asyncio.create_task(
                _read_bounded(process.stdout, spec.subprocess_output_limit_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_bounded(process.stderr, spec.subprocess_output_limit_bytes)
            )
            try:
                await asyncio.wait_for(process.wait(), spec.timeout_seconds)
                stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            except TimeoutError:
                process.terminate()
                await process.wait()
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=_error("TIMEOUT", "Tool execution timed out"),
                )
            if (
                len(stdout) > spec.subprocess_output_limit_bytes
                or len(stderr) > spec.subprocess_output_limit_bytes
            ):
                process.terminate()
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=_error("OUTPUT_LIMIT", "Tool output exceeded its bound"),
                )
            if process.returncode != 0:
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=_error("SUBPROCESS_FAILED", "Subprocess failed"),
                )
            text = stdout.decode("utf-8", errors="replace")
            try:
                value: Any = json.loads(text) if text else None
            except json.JSONDecodeError:
                value = text
            return ToolResult(status="SUCCEEDED", call_id=call_id, value=value)
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()
            raise
        except (OSError, ValueError):
            return ToolResult(
                status="FAILED",
                call_id=call_id,
                error=_error("SUBPROCESS_FAILED", "Subprocess could not be started"),
            )


async def _read_bounded(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    if stream is None:
        return b""
    data = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        if len(data) <= limit:
            remaining = limit + 1 - len(data)
            data.extend(chunk[:remaining])
    return bytes(data)


def _error(code: str, message: str) -> Any:
    from sofias_assistant.execution.models import ToolError

    return ToolError(code, message)
