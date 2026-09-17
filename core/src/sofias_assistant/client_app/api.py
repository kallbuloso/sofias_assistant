"""Central authenticated adapter for the Desktop Client."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx2
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as connect_websocket


class CoreApiError(RuntimeError):
    """Safe transport error that never includes credentials or response bodies."""


class CoreValidationError(CoreApiError):
    """A Core-rejected write, carrying only its bounded deterministic reason.

    Populated exclusively from `detail` on a `404`/`422` AI-configuration
    response, which Contract v1 guarantees is a safe, secret-free,
    deterministic validation message (e.g. "Unknown provider", "Binding
    does not satisfy the profile's required capabilities") -- never a
    credential, prompt or hidden reasoning. Ordinary transport failures
    still raise the generic `CoreApiError`.
    """


class CoreApiClient:
    """One authenticated, transport-only Client adapter.

    This object is the only place where the Desktop Client knows Core endpoints.
    It never opens SQLite, imports repositories, invokes Tools or evaluates Policy.
    """

    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        timeout: float = 8.0,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        if not credential.strip():
            raise ValueError("Client credential must not be blank")
        self._credential = credential
        self._timeout = timeout
        self._http = http_client or httpx2.Client(
            base_url=self.base_url, timeout=timeout
        )
        self.session_id: UUID | None = None

    def __repr__(self) -> str:
        return f"<CoreApiClient base_url={self.base_url!r} credential=redacted>"

    def connect(self) -> dict[str, Any]:
        self.session_id = None
        try:
            response = self._http.post(
                "/api/v1/client-sessions", headers=self._auth_headers()
            )
            payload = self._decode(response)
            self.session_id = UUID(str(payload["id"]))
            return self.sync()
        except Exception as error:
            self.session_id = None
            if isinstance(error, CoreApiError):
                raise
            raise CoreApiError("Core connection failed") from error

    def close(self) -> None:
        if self.session_id is not None:
            try:
                self._http.delete("/api/v1/client-session", headers=self._headers())
            except Exception:
                pass
        self.session_id = None
        close = getattr(self._http, "close", None)
        if close is not None:
            close()

    def sync(self) -> dict[str, Any]:
        self._require_session()
        return {
            "core": self._get("/api/v1/core"),
            "notifications": self._get("/api/v1/notifications?limit=100"),
            "tasks": self._get("/api/v1/tasks?limit=50"),
        }

    def create_conversation(self) -> UUID:
        return UUID(str(self._post("/api/v1/conversations", {})["id"]))

    def get_conversation(self, conversation_id: UUID) -> dict[str, Any]:
        return cast(
            dict[str, Any], self._get(f"/api/v1/conversations/{conversation_id}")
        )

    def stream_text(self, conversation_id: UUID, text: str) -> Iterator[dict[str, Any]]:
        self._require_session()
        if not text.strip():
            raise ValueError("Text must not be blank")
        response = self._http.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=self._headers(),
            json={
                "text": text,
                "locality": "local_only",
                "cloud_context_eligible": False,
            },
        )
        with response as stream:
            if stream.status_code >= 400:
                self._raise_response(stream)
            for line in stream.iter_lines():
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except (TypeError, json.JSONDecodeError) as error:
                    raise CoreApiError("Core returned malformed stream data") from error
                if not isinstance(value, dict):
                    raise CoreApiError("Core returned malformed stream data")
                yield value

    def acknowledge(self, notification_id: UUID) -> bool:
        value = self._post(f"/api/v1/notifications/{notification_id}/acknowledge", {})
        return bool(value.get("acknowledged"))

    def get_confirmation(self, confirmation_id: UUID) -> dict[str, Any]:
        return cast(
            dict[str, Any], self._get(f"/api/v1/confirmations/{confirmation_id}")
        )

    def approve_confirmation(self, confirmation_id: UUID) -> dict[str, Any]:
        return self._post(
            f"/api/v1/confirmations/{confirmation_id}/approve", {"lifetime": "ONE_SHOT"}
        )

    def deny_confirmation(self, confirmation_id: UUID) -> None:
        response = self._http.post(
            f"/api/v1/confirmations/{confirmation_id}/deny", headers=self._headers()
        )
        self._decode(response)

    def cancel_task(self, task_id: UUID) -> dict[str, Any]:
        return self._post(f"/api/v1/tasks/{task_id}/cancel", {})

    def get_runtime_identity(self) -> dict[str, Any]:
        """Return the authenticated runtime identity used for attach verification."""

        return cast(dict[str, Any], self._get("/api/v1/runtime/identity"))

    def request_runtime_shutdown(
        self, runtime_session_id: UUID, *, reason: str = "user_requested"
    ) -> bool:
        """Request an explicit authenticated graceful Core shutdown.

        Returns whether the current lifecycle accepted the request; a
        lifecycle mismatch (`409`) returns `False` instead of raising, since
        it is an expected outcome the caller (`DesktopCoreSupervisor`) must
        be able to distinguish without exception-driven control flow.
        """

        response = self._http.post(
            "/api/v1/runtime/shutdown",
            headers=self._headers(),
            json={"runtime_session_id": str(runtime_session_id), "reason": reason},
        )
        if response.status_code == 409:
            return False
        self._decode(response)
        return True

    # -- AI configuration / routing (Gate I17) --------------------------

    def list_ai_providers(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._get("/api/v1/ai/providers"))

    def list_ai_models(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._get("/api/v1/ai/models"))

    def update_ai_provider(
        self, provider_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._patch_validated(f"/api/v1/ai/providers/{provider_id}", patch),
        )

    def refresh_ai_models(self, provider_id: str) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self._post_validated(
                "/api/v1/ai/models/refresh", {"provider_id": provider_id}
            ),
        )

    def list_ai_profiles(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._get("/api/v1/ai/profiles"))

    def get_ai_profile(self, key: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._get(f"/api/v1/ai/profiles/{key}"))

    def update_ai_profile(self, key: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply a sparse profile patch; `patch["bindings"]`, when present,

        replaces the full ordered binding list in one atomic Core call
        (Contract v1 SS33) -- callers must never emulate reorder through a
        sequence of single-binding updates.
        """

        return cast(
            dict[str, Any], self._patch_validated(f"/api/v1/ai/profiles/{key}", patch)
        )

    def preview_ai_routing(self, request: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any], self._post_validated("/api/v1/ai/routing/preview", request)
        )

    def set_ai_provider_credential(
        self, provider_id: str, value: str
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._put_validated(
                f"/api/v1/ai/providers/{provider_id}/credential", {"value": value}
            ),
        )

    def delete_ai_provider_credential(self, provider_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._delete_validated(f"/api/v1/ai/providers/{provider_id}/credential"),
        )

    # -- Memory / integrations (Gate I17) -------------------------------

    def get_memory_integration(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._get("/api/v1/integrations/sofias-memory"))

    def set_memory_credential(self, value: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._put_validated(
                "/api/v1/integrations/sofias-memory/credential", {"value": value}
            ),
        )

    def delete_memory_credential(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._delete_validated("/api/v1/integrations/sofias-memory/credential"),
        )

    def realtime(self) -> RealtimeVoiceConnection:
        self._require_session()
        if self.session_id is None:
            raise CoreApiError("Client session is unavailable")
        return RealtimeVoiceConnection(
            self._websocket_url(), self._credential, self.session_id
        )

    def _websocket_url(self) -> str:
        parsed = urlparse(self.base_url)
        return urlunparse(("ws", parsed.netloc, parsed.path, "", "", ""))

    def _get(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        response = self._http.get(path, headers=self._headers())
        return self._decode(response)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(path, headers=self._headers(), json=body)
        return self._decode(response)

    def _post_validated(self, path: str, body: dict[str, Any]) -> Any:
        response = self._http.post(path, headers=self._headers(), json=body)
        return self._decode_validated(response)

    def _patch_validated(self, path: str, body: dict[str, Any]) -> Any:
        response = self._http.patch(path, headers=self._headers(), json=body)
        return self._decode_validated(response)

    def _put_validated(self, path: str, body: dict[str, Any]) -> Any:
        response = self._http.put(path, headers=self._headers(), json=body)
        return self._decode_validated(response)

    def _delete_validated(self, path: str) -> Any:
        response = self._http.delete(path, headers=self._headers())
        return self._decode_validated(response)

    @staticmethod
    def _decode_validated(response: Any) -> Any:
        """Decode a Core-config write response, surfacing a safe rejection reason.

        `404`/`422` from the AI-configuration and integration-credential
        surfaces always carry a bounded, secret-free `detail` string
        (Contract v1); every other status keeps the generic transport-only
        `_decode` behavior.
        """

        if response.status_code in (404, 422):
            raise CoreValidationError(CoreApiClient._safe_detail(response))
        return CoreApiClient._decode(response)

    @staticmethod
    def _safe_detail(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            return "Core rejected the request"
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, str) and detail.strip():
            return detail
        return "Core rejected the request"

    def _headers(self) -> dict[str, str]:
        self._require_session()
        assert self.session_id is not None
        return {
            **self._auth_headers(),
            "X-Sofia-Client-Session-ID": str(self.session_id),
        }

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credential}"}

    def _require_session(self) -> None:
        if self.session_id is None:
            raise CoreApiError("Client is not connected")

    @staticmethod
    def _decode(response: Any) -> Any:
        if response.status_code >= 400:
            CoreApiClient._raise_response(response)
        try:
            value = response.json()
        except Exception as error:
            raise CoreApiError("Core returned malformed JSON") from error
        if not isinstance(value, (dict, list)):
            raise CoreApiError("Core returned malformed JSON")
        return value

    @staticmethod
    def _raise_response(response: Any) -> None:
        if response.status_code == 401:
            raise CoreApiError("Core authentication failed")
        raise CoreApiError(f"Core request failed ({response.status_code})")


class RealtimeVoiceConnection:
    """Small adapter for the existing authenticated realtime protocol."""

    def __init__(self, url: str, credential: str, session_id: UUID) -> None:
        self._url, self._credential, self._client_session_id = (
            url,
            credential,
            session_id,
        )
        self._socket: ClientConnection | None = None
        self._sequence = 0
        self.session_id: UUID | None = None
        self.interaction_id: UUID | None = None
        self.committed = False

    def open(self, conversation_id: UUID) -> None:
        self._socket = connect_websocket(self._url, open_timeout=5, close_timeout=2)
        self._send(
            {
                "protocol_version": "realtime.v1",
                "type": "authenticate",
                "sequence": 0,
                "credential": self._credential,
                "client_session_id": str(self._client_session_id),
            },
            sequence_override=0,
        )
        authenticated = self._receive_json()
        if authenticated.get("type") != "authenticated":
            raise CoreApiError("Realtime authentication failed")
        self._send(
            {
                "protocol_version": "realtime.v1",
                "type": "session.open",
                "conversation_id": str(conversation_id),
                "locality": "local_only",
                "cloud_context_eligible": False,
                "input_audio_format": {
                    "encoding": "pcm16",
                    "sample_rate_hz": 24000,
                    "channels": 1,
                },
                "output_audio_format": {
                    "encoding": "pcm16",
                    "sample_rate_hz": 24000,
                    "channels": 1,
                },
            }
        )
        opened = self._receive_json()
        if opened.get("type") != "session.opened":
            raise CoreApiError("Realtime session could not be opened")
        self.session_id = UUID(str(opened["realtime_session_id"]))

    def start(self) -> UUID:
        session_id = self._require_open()
        self._send({"type": "input_started", "realtime_session_id": str(session_id)})
        while True:
            event = self._receive_json()
            if event.get("type") == "interaction_started":
                self.interaction_id = UUID(str(event["realtime_interaction_id"]))
                self.committed = False
                return self.interaction_id
            if event.get("type") == "error":
                raise CoreApiError("Realtime interaction could not be started")

    def send_audio(self, audio: bytes) -> None:
        if self._socket is None or self.interaction_id is None or self.committed:
            raise CoreApiError("Realtime input is not active")
        self._socket.send(audio)

    def commit(self) -> None:
        session_id = self._require_open()
        if self.interaction_id is None:
            raise CoreApiError("Realtime interaction is not active")
        self._send(
            {
                "type": "input_committed",
                "realtime_session_id": str(session_id),
                "realtime_interaction_id": str(self.interaction_id),
            }
        )
        self.committed = True

    def interrupt(self) -> None:
        session_id = self._require_open()
        if self.interaction_id is None or not self.committed:
            raise CoreApiError("Realtime response is not active")
        self._send(
            {
                "type": "response.interrupt",
                "realtime_session_id": str(session_id),
                "realtime_interaction_id": str(self.interaction_id),
            }
        )
        self.committed = False

    def stop(self) -> None:
        if self._socket is None:
            return
        session_id = self._require_open()
        if self.interaction_id is not None and not self.committed:
            self._send(
                {
                    "type": "input_cancelled",
                    "realtime_session_id": str(session_id),
                    "realtime_interaction_id": str(self.interaction_id),
                }
            )
        self._send({"type": "session.close", "realtime_session_id": str(session_id)})
        self._socket.close()
        self._socket = None
        self.session_id = self.interaction_id = None
        self.committed = False

    def _require_open(self) -> UUID:
        if self._socket is None or self.session_id is None:
            raise CoreApiError("Realtime session is not open")
        return self.session_id

    def _send(
        self, value: dict[str, Any], *, sequence_override: int | None = None
    ) -> None:
        if self._socket is None:
            raise CoreApiError("Realtime socket is closed")
        sequence = self._sequence if sequence_override is None else sequence_override
        self._socket.send(
            json.dumps(
                {"protocol_version": "realtime.v1", **value, "sequence": sequence}
            )
        )
        if sequence_override is None:
            self._sequence += 1
        else:
            self._sequence = 1

    def _receive_json(self) -> dict[str, Any]:
        if self._socket is None:
            raise CoreApiError("Realtime socket is closed")
        value = self._socket.recv(timeout=8)
        if not isinstance(value, str):
            raise CoreApiError("Realtime returned an unexpected frame")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise CoreApiError("Realtime returned malformed data") from error
        if not isinstance(parsed, dict):
            raise CoreApiError("Realtime returned malformed data")
        return parsed


def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("Desktop Client only supports authenticated loopback HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Core URL must not contain credentials or query state")
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
