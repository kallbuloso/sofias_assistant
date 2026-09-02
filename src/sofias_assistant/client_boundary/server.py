"""Lifecycle owner for the loopback ASGI server used by the local boundary."""

import asyncio
import socket

import uvicorn
from fastapi import FastAPI

LOCAL_API_HOST = "127.0.0.1"
DEFAULT_LOCAL_API_PORT = 8989
_STARTUP_TIMEOUT_SECONDS = 5.0


class LocalApiBindError(RuntimeError):
    """Raised when the Local API cannot bind its requested loopback port."""

    def __init__(self, port: int) -> None:
        super().__init__(f"Local API could not bind {LOCAL_API_HOST}:{port}")


class LocalHttpServer:
    """Bind, start, and stop one Uvicorn ASGI server on loopback only."""

    def __init__(self, app: FastAPI, *, port: int = DEFAULT_LOCAL_API_PORT) -> None:
        if not 0 <= port <= 65535:
            raise ValueError("Local API port must be between 0 and 65535")

        self._app = app
        self._requested_port = port
        self._bound_port: int | None = None
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._start_attempted = False

    @property
    def host(self) -> str:
        """Return the only address this server is permitted to bind."""

        return LOCAL_API_HOST

    @property
    def requested_port(self) -> int:
        """Return the explicitly requested port, including an injected zero."""

        return self._requested_port

    @property
    def bound_port(self) -> int | None:
        """Return the actual OS-bound port while this server is active."""

        return self._bound_port

    async def start(self) -> None:
        """Bind loopback and await Uvicorn's completed startup latch."""

        if self._start_attempted:
            raise RuntimeError("LocalHttpServer can only be started once")
        self._start_attempted = True

        try:
            self._socket = self._bind_loopback_socket()
            self._bound_port = int(self._socket.getsockname()[1])
            config = uvicorn.Config(
                self._app,
                host=LOCAL_API_HOST,
                port=self._bound_port,
                log_config=None,
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
            await self._await_startup()
            self._started = True
        except BaseException:
            await self._cleanup_after_failed_start()
            raise

    async def stop(self) -> None:
        """Request Uvicorn shutdown and release the owned socket and task."""

        if not self._started:
            raise RuntimeError("LocalHttpServer can only stop after a successful start")

        server = self._server
        task = self._task
        if server is None or task is None:
            self._started = False
            self._close_socket()
            self._clear_references()
            raise RuntimeError("LocalHttpServer is missing active server resources")

        try:
            server.should_exit = True
            await task
        finally:
            self._close_socket()
            self._clear_references()
            self._started = False

    def _bind_loopback_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((LOCAL_API_HOST, self._requested_port))
            sock.listen()
            sock.setblocking(False)
        except OSError as error:
            sock.close()
            raise LocalApiBindError(self._requested_port) from error
        return sock

    async def _await_startup(self) -> None:
        server = self._server
        task = self._task
        if server is None or task is None:
            raise RuntimeError("LocalHttpServer startup resources are missing")

        deadline = asyncio.get_running_loop().time() + _STARTUP_TIMEOUT_SECONDS
        while not server.started:
            if task.done():
                task.result()
                raise RuntimeError("Uvicorn stopped before completing startup")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for Local API startup")
            await asyncio.sleep(0)

    async def _cleanup_after_failed_start(self) -> None:
        server = self._server
        task = self._task
        if server is not None:
            server.should_exit = True
        if task is not None:
            try:
                await task
            except BaseException:
                pass
        self._close_socket()
        self._clear_references()

    def _close_socket(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _clear_references(self) -> None:
        self._server = None
        self._task = None
        self._bound_port = None
