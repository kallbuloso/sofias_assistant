"""Bounded, canonical filesystem capabilities."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sofias_assistant.execution.models import (
    GrantLifetime,
    ToolError,
    ToolResult,
    ToolSideEffect,
    ToolSpec,
)

MAX_READ_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 512
_SUPPORTED_ENCODINGS = {"utf-8", "utf-16", "latin-1"}


def canonicalize_path(value: object, *, must_exist: bool = False) -> Path:
    """Resolve a Windows-first path before it can reach Policy."""

    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty string")
    raw = value.strip()
    if "\x00" in raw or raw.startswith(("\\\\?\\", "\\\\.\\")):
        raise ValueError("device-like paths are not supported")
    path = Path(os.path.abspath(raw)).resolve(strict=False)
    if must_exist and not path.exists():
        raise ValueError("path does not exist")
    return path


def file_resource(path: Path) -> str:
    rendered = path.as_posix()
    if os.name == "nt":
        rendered = rendered.casefold()
    return f"file:///{rendered.lstrip('/')}"


class FilesystemCapability:
    """Production filesystem handlers; no shell dependency is involved."""

    def __init__(
        self,
        *,
        max_read_bytes: int = MAX_READ_BYTES,
        max_list_entries: int = MAX_LIST_ENTRIES,
    ) -> None:
        if max_read_bytes <= 0 or max_list_entries <= 0:
            raise ValueError("filesystem bounds must be positive")
        self.max_read_bytes = max_read_bytes
        self.max_list_entries = max_list_entries

    def specs(self) -> tuple[ToolSpec, ...]:
        return (
            ToolSpec(
                name="filesystem.read",
                version="1",
                description="Read a bounded text file after canonicalization",
                capability="filesystem.read",
                handler=self.read,
                resource_resolver=lambda args: file_resource(
                    canonicalize_path(args["path"], must_exist=True)
                ),
                input_validator=self._validate_read,
            ),
            ToolSpec(
                name="filesystem.write",
                version="1",
                description="Atomically replace a bounded text file",
                capability="filesystem.write",
                handler=self.write,
                resource_resolver=lambda args: file_resource(
                    canonicalize_path(args["path"])
                ),
                input_validator=self._validate_write,
                side_effect=ToolSideEffect.MUTATING,
                confirmation_lifetime=GrantLifetime.ONE_SHOT,
                idempotent=False,
            ),
            ToolSpec(
                name="filesystem.list",
                version="1",
                description="List one bounded directory level",
                capability="filesystem.list",
                handler=self.list_directory,
                resource_resolver=lambda args: file_resource(
                    canonicalize_path(args["path"], must_exist=True)
                ),
                input_validator=self._validate_list,
            ),
        )

    def _validate_read(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        path = canonicalize_path(arguments.get("path"), must_exist=True)
        if not path.is_file():
            raise ValueError("path must identify a regular file")
        maximum = _bounded_int(
            arguments.get("max_bytes", self.max_read_bytes), self.max_read_bytes
        )
        encoding = arguments.get("encoding", "utf-8")
        if encoding not in _SUPPORTED_ENCODINGS:
            raise ValueError("unsupported encoding")
        return {"path": str(path), "max_bytes": maximum, "encoding": encoding}

    def _validate_write(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        path = canonicalize_path(arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be text")
        encoding = arguments.get("encoding", "utf-8")
        if encoding not in _SUPPORTED_ENCODINGS:
            raise ValueError("unsupported encoding")
        overwrite = arguments.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ValueError("overwrite must be boolean")
        if path.exists() and not overwrite:
            raise ValueError("refusing to overwrite an existing file")
        if path.parent != path and not path.parent.exists():
            raise ValueError("parent directory does not exist")
        if len(content.encode(encoding)) > self.max_read_bytes:
            raise ValueError("content exceeds the bounded write size")
        return {
            "path": str(path),
            "content": content,
            "encoding": encoding,
            "overwrite": overwrite,
        }

    def _validate_list(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        path = canonicalize_path(arguments.get("path"), must_exist=True)
        if not path.is_dir():
            raise ValueError("path must identify a directory")
        maximum = _bounded_int(
            arguments.get("max_entries", self.max_list_entries), self.max_list_entries
        )
        return {"path": str(path), "max_entries": maximum}

    def read(self, arguments: Mapping[str, Any]) -> dict[str, Any] | ToolResult:
        path = canonicalize_path(arguments["path"], must_exist=True)
        maximum = int(arguments["max_bytes"])
        data = path.read_bytes()
        if len(data) > maximum:
            return ToolResult(
                status="FAILED",
                call_id=UUID(int=0),
                error=ToolError("READ_LIMIT", "File exceeds the requested read bound"),
            )
        return {
            "path": file_resource(path),
            "content": data.decode(str(arguments["encoding"])),
            "bytes": len(data),
        }

    def write(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        path = canonicalize_path(arguments["path"])
        if path.exists() and not bool(arguments["overwrite"]):
            raise ValueError("refusing to overwrite an existing file")
        content = str(arguments["content"]).encode(str(arguments["encoding"]))
        fd, temporary_name = tempfile.mkstemp(prefix=".sofia-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        return {"path": file_resource(path), "bytes": len(content), "replaced": True}

    def list_directory(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        path = canonicalize_path(arguments["path"], must_exist=True)
        entries = []
        for index, entry in enumerate(os.scandir(path)):
            if index >= int(arguments["max_entries"]):
                raise ValueError("directory exceeds the listing bound")
            kind = (
                "symlink"
                if entry.is_symlink()
                else "directory"
                if entry.is_dir(follow_symlinks=False)
                else "file"
            )
            size = None
            if kind == "file":
                size = entry.stat(follow_symlinks=False).st_size
            entries.append({"name": entry.name, "kind": kind, "size": size})
        entries.sort(key=lambda item: str(item["name"]).casefold())
        return {"path": file_resource(path), "entries": entries}


def _bounded_int(value: object, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise ValueError("requested bound is outside the supported limit")
    return value
