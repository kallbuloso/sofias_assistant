"""Core-owned execution isolation dispatcher."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Mapping
from typing import Any

from sofias_assistant.execution.models import (
    SubprocessInvocation,
    ToolError,
    ToolExecutionMode,
    ToolResult,
    ToolSpec,
)


class ExecutionDispatcher:
    """Dispatch already-authorized work without creating authority."""

    async def dispatch(
        self,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
        *,
        call_id: Any,
        subprocess_invocation: SubprocessInvocation | None = None,
    ) -> ToolResult:
        if spec.execution_mode is ToolExecutionMode.IN_PROCESS:
            value = spec.handler(arguments)
            if inspect.isawaitable(value):
                value = await value
            return ToolResult(status="SUCCEEDED", call_id=call_id, value=value)
        if spec.execution_mode is ToolExecutionMode.SUBPROCESS:
            return await self._subprocess(
                spec, arguments, call_id=call_id, invocation=subprocess_invocation
            )
        return ToolResult(
            status="FAILED",
            call_id=call_id,
            error=ToolError("SANDBOX_UNAVAILABLE", "Sandbox execution is unavailable"),
        )

    async def _subprocess(
        self,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
        *,
        call_id: Any,
        invocation: SubprocessInvocation | None,
    ) -> ToolResult:
        if invocation is None:
            command = spec.subprocess_command
            if not command:
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=ToolError(
                        "SUBPROCESS_INVALID", "Subprocess command is unavailable"
                    ),
                )
            invocation = SubprocessInvocation(
                executable=command[0],
                argv=command[1:],
                cwd=spec.subprocess_cwd,
                environment=spec.subprocess_environment,
                stdin=json.dumps(dict(arguments), sort_keys=True).encode("utf-8"),
                expect_json_output=True,
                timeout_seconds=spec.timeout_seconds,
            )
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            **dict(invocation.environment),
        }
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                invocation.executable,
                *invocation.argv,
                cwd=invocation.cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=spec.subprocess_output_limit_bytes + 1,
            )
            if process.stdin is not None:
                if invocation.stdin is not None:
                    process.stdin.write(invocation.stdin)
                    await process.stdin.drain()
                process.stdin.close()
            stdout_task = asyncio.create_task(
                _read_bounded(process.stdout, spec.subprocess_output_limit_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_bounded(process.stderr, spec.subprocess_output_limit_bytes)
            )
            try:
                await asyncio.wait_for(
                    process.wait(), invocation.timeout_seconds or spec.timeout_seconds
                )
                stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            except TimeoutError:
                await _stop_process(process)
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=ToolError("TIMEOUT", "Tool execution timed out"),
                )
            if (
                len(stdout) > spec.subprocess_output_limit_bytes
                or len(stderr) > spec.subprocess_output_limit_bytes
            ):
                await _stop_process(process)
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=ToolError("OUTPUT_LIMIT", "Tool output exceeded its bound"),
                )
            stdout_text = stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
            stderr_text = stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
            if process.returncode != 0:
                return ToolResult(
                    status="FAILED",
                    call_id=call_id,
                    error=ToolError("SUBPROCESS_FAILED", "Subprocess failed"),
                )
            if invocation.expect_json_output:
                try:
                    value: Any = json.loads(stdout_text) if stdout_text else None
                except json.JSONDecodeError:
                    value = stdout_text
            else:
                value = {
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "returncode": process.returncode,
                }
            return ToolResult(status="SUCCEEDED", call_id=call_id, value=value)
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                await _stop_process(process)
            raise
        except (OSError, ValueError):
            return ToolResult(
                status="FAILED",
                call_id=call_id,
                error=ToolError("SUBPROCESS_FAILED", "Subprocess could not be started"),
            )


async def _read_bounded(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    if stream is None:
        return b""
    data = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        remaining = limit + 1 - len(data)
        if remaining > 0:
            data.extend(chunk[:remaining])
    return bytes(data)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Best-effort child termination with a hard-kill fallback."""

    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1.0)
    except TimeoutError:
        process.kill()
        await process.wait()
