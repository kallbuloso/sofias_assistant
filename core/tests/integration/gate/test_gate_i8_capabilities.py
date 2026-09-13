"""Vertical Gate I8 evidence for real capability seams and deterministic fakes."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from sofias_assistant.ai import (
    Capability,
    CapabilityRouter,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ModelRegistration,
    ModelRegistry,
    NoCompatibleModelError,
    ProviderBinding,
)
from sofias_assistant.ai.fake import FakeVisionProvider
from sofias_assistant.capabilities.desktop import DesktopCapability, FakeDesktopBackend
from sofias_assistant.capabilities.filesystem import (
    FilesystemCapability,
    canonicalize_path,
    file_resource,
)
from sofias_assistant.capabilities.shell import ShellCapability
from sofias_assistant.capabilities.vision import VisionCapability
from sofias_assistant.capabilities.web import FakeSearchBackend, WebReader, validate_url
from sofias_assistant.execution import ExecutionRuntime, GrantLifetime, ToolCall
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


async def _runtime(tmp_path: Path) -> tuple[ExecutionRuntime, Any]:
    database = tmp_path / "operational.sqlite"
    await asyncio.to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    return ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    ), engine


async def _grant(
    runtime: ExecutionRuntime, *, subject: str, capability: str, resource: str
) -> UUID:
    grant = await runtime.create_grant(
        subject=subject,
        capability=capability,
        resource_scope=resource,
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    return grant.id


@pytest.mark.asyncio
async def test_filesystem_is_canonical_bounded_and_audited(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        root = tmp_path / "workspace"
        root.mkdir()
        source = root / "note.txt"
        source.write_text("hello", encoding="utf-8")
        for spec in FilesystemCapability(max_read_bytes=16).specs():
            runtime.register_tool(spec)
        subject = "client:i8"
        resource = file_resource(canonicalize_path(source, must_exist=True))
        grant_id = await _grant(
            runtime, subject=subject, capability="filesystem.read", resource=resource
        )
        call = ToolCall(
            name="filesystem.read",
            arguments={"path": str(root / "." / "note.txt"), "max_bytes": 16},
            subject=subject,
        )
        result = await runtime.invoke(call, grant_id=grant_id)
        assert result.status == "SUCCEEDED"
        assert result.value["content"] == "hello"
        trace = await runtime.audit.trace(call.correlation_id)
        assert any(item.event_type == "POLICY_DECISION" for item in trace)
        assert any(item.resource == resource for item in trace)

        list_resource = file_resource(canonicalize_path(root, must_exist=True))
        list_grant = await _grant(
            runtime,
            subject=subject,
            capability="filesystem.list",
            resource=list_resource,
        )
        listed = await runtime.invoke(
            ToolCall(
                name="filesystem.list", arguments={"path": str(root)}, subject=subject
            ),
            grant_id=list_grant,
        )
        assert listed.status == "SUCCEEDED"
        assert listed.value["entries"][0]["name"] == "note.txt"

        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        escaped = await runtime.invoke(
            ToolCall(
                name="filesystem.read",
                arguments={"path": str(root / ".." / "outside.txt")},
                subject=subject,
            ),
            grant_id=grant_id,
        )
        assert escaped.status == "DENY"

        write = await runtime.invoke(
            ToolCall(
                name="filesystem.write",
                arguments={"path": str(root / "new.txt"), "content": "new"},
                subject=subject,
            )
        )
        assert write.status == "CONFIRMATION_REQUIRED"
        assert write.confirmation_id is not None
        approved = await runtime.approve_confirmation(write.confirmation_id)
        assert approved.status == "SUCCEEDED"
        assert (root / "new.txt").read_text(encoding="utf-8") == "new"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shell_uses_dynamic_explicit_argv_and_filtered_environment(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        capability = ShellCapability(output_limit_bytes=4096)
        spec = capability.spec()
        runtime.register_tool(spec)
        arguments = {
            "executable": sys.executable,
            "argv": [
                "-c",
                "import os; print(os.getenv('SOFIA_TEST', 'missing')); print(os.getenv('SECRET', 'missing'))",
            ],
            "cwd": str(tmp_path),
            "environment_overrides": {"SOFIA_TEST": "allowed", "SECRET": "blocked"},
            "timeout_seconds": 10,
        }
        assert spec.input_validator is not None
        normalized = spec.input_validator(arguments)
        resource = spec.resource_resolver(normalized)
        grant_id = await _grant(
            runtime,
            subject="client:shell",
            capability="shell.execute",
            resource=resource,
        )
        result = await runtime.invoke(
            ToolCall(name="shell.execute", arguments=arguments, subject="client:shell"),
            grant_id=grant_id,
        )
        assert result.status == "SUCCEEDED"
        assert result.value["stdout"] == "allowed\nmissing\n"
        assert "SECRET" not in json.dumps(result.value)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shell_timeout_and_output_limits_are_fail_closed(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        capability = ShellCapability(output_limit_bytes=64)
        runtime.register_tool(capability.spec())
        base = {"executable": sys.executable, "cwd": str(tmp_path)}
        timeout_args = {
            **base,
            "argv": ["-c", "import time; time.sleep(2)"],
            "timeout_seconds": 0.1,
        }
        spec = runtime.registry.resolve("shell.execute")
        assert spec.input_validator is not None
        timeout_resource = spec.resource_resolver(spec.input_validator(timeout_args))
        timeout_grant = await _grant(
            runtime,
            subject="client:shell-limit",
            capability="shell.execute",
            resource=timeout_resource,
        )
        timed_out = await runtime.invoke(
            ToolCall(
                name="shell.execute",
                arguments=timeout_args,
                subject="client:shell-limit",
            ),
            grant_id=timeout_grant,
        )
        assert timed_out.error is not None
        assert timed_out.error.code == "TIMEOUT"

        output_args = {
            **base,
            "argv": ["-c", "print('x' * 1000)"],
            "timeout_seconds": 5,
        }
        output_resource = spec.resource_resolver(spec.input_validator(output_args))
        output_grant = await _grant(
            runtime,
            subject="client:shell-output",
            capability="shell.execute",
            resource=output_resource,
        )
        bounded = await runtime.invoke(
            ToolCall(
                name="shell.execute",
                arguments=output_args,
                subject="client:shell-output",
            ),
            grant_id=output_grant,
        )
        assert bounded.error is not None
        assert bounded.error.code == "OUTPUT_LIMIT"
    finally:
        await engine.dispose()


class _WebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/text")
            self.end_headers()
            return
        body = b"bounded web fixture"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


@pytest.mark.asyncio
async def test_web_fake_search_ssrf_redirect_and_response_bound(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reader = WebReader(search_backend=FakeSearchBackend(), allow_loopback=True)
        for spec in reader.specs():
            runtime.register_tool(spec)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/redirect"
        assert validate_url("https://127.0.0.1", allow_loopback=True)
        with pytest.raises(ValueError, match="private or local"):
            validate_url("http://127.0.0.1")
        read_spec = runtime.registry.resolve("web.read")
        resource = read_spec.resource_resolver({"url": url})
        grant_id = await _grant(
            runtime, subject="client:web", capability="web.read", resource=resource
        )
        result = await runtime.invoke(
            ToolCall(name="web.read", arguments={"url": url}, subject="client:web"),
            grant_id=grant_id,
        )
        assert result.status == "SUCCEEDED"
        assert result.value["text"] == "bounded web fixture"
        search = await reader.search({"query": "sofia", "max_results": 1})
        search_results = cast(tuple[dict[str, str], ...], search["results"])
        assert search_results[0]["title"] == "Sofia fixture"
    finally:
        server.shutdown()
        server.server_close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_desktop_capture_creates_artifact_and_vision_routes_image_model(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        desktop = DesktopCapability(FakeDesktopBackend(), runtime.artifacts)
        for spec in desktop.specs():
            runtime.register_tool(spec)
        subject = "client:desktop"
        open_grant = await _grant(
            runtime,
            subject=subject,
            capability="desktop.open_app",
            resource="desktop.app:notepad",
        )
        opened = await runtime.invoke(
            ToolCall(
                name="desktop.open_app",
                arguments={"application": "notepad"},
                subject=subject,
            ),
            grant_id=open_grant,
        )
        assert opened.status == "SUCCEEDED"
        active_grant = await _grant(
            runtime,
            subject=subject,
            capability="desktop.active_window",
            resource="desktop.window:foreground",
        )
        active = await runtime.invoke(
            ToolCall(name="desktop.active_window", arguments={}, subject=subject),
            grant_id=active_grant,
        )
        assert active.status == "SUCCEEDED"
        assert active.value["title"] == "Fake Desktop"
        grant_id = await _grant(
            runtime,
            subject=subject,
            capability="desktop.capture_screen",
            resource="desktop.screen:primary",
        )
        call = ToolCall(name="desktop.capture_screen", arguments={}, subject=subject)
        result = await runtime.invoke(call, grant_id=grant_id)
        assert result.status == "SUCCEEDED"
        assert len(result.artifact_refs) == 1
        ref, content = await runtime.artifacts.read(result.artifact_refs[0].id)
        assert ref == result.artifact_refs[0]
        assert content == b"FAKE-SOFIA-SCREENSHOT\n"
        trace = await runtime.audit.trace(call.correlation_id)
        assert "FAKE-SOFIA-SCREENSHOT" not in json.dumps(trace, default=str)

        vision_provider = FakeVisionProvider(lambda _: "a deterministic screen")
        registry = ModelRegistry()
        registry.register(
            ModelRegistration(
                ModelDescriptor(
                    ModelIdentity("fake-vision", "screen-1"),
                    frozenset({Capability.IMAGE_INPUT}),
                    ExecutionLocation.LOCAL,
                ),
                ProviderBinding(vision=vision_provider),
            )
        )
        vision = VisionCapability(runtime.artifacts, CapabilityRouter(registry))
        observation = await vision.observe(
            artifact_id=result.artifact_refs[0].id,
            prompt="What is on screen?",
            locality=DataLocality.LOCAL_ONLY,
        )
        assert observation.text == "a deterministic screen"
        assert vision_provider.requests[0].image.artifact_id == ref.id
        text_only = ModelRegistry()
        text_only.register(
            ModelRegistration(
                ModelDescriptor(
                    ModelIdentity("text-only", "model"),
                    frozenset(),
                    ExecutionLocation.LOCAL,
                ),
                ProviderBinding(),
            )
        )
        with pytest.raises(NoCompatibleModelError):
            await VisionCapability(
                runtime.artifacts, CapabilityRouter(text_only)
            ).observe(artifact_id=ref.id, prompt="must fail closed")
    finally:
        await engine.dispose()


def test_windows_path_and_url_baselines_reject_ambiguous_inputs() -> None:
    with pytest.raises(ValueError):
        canonicalize_path("\\\\?\\C:\\secret")
    with pytest.raises(ValueError):
        validate_url("file:///C:/secret")
