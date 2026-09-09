"""Deterministic realtime provider fake used only by tests."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from uuid import uuid4

from sofias_assistant.ai.contracts import (
    AssistantAudioChunk,
    AssistantTranscriptFinal,
    AssistantTranscriptPartial,
    AudioFormat,
    AudioInputFrame,
    ModelIdentity,
    ProviderError,
    RealtimeInteractionId,
    RealtimeProviderEvent,
    RealtimeResponseCompleted,
    RealtimeResponseFailed,
    RealtimeSessionFailed,
    RealtimeSessionId,
    RealtimeSessionRequest,
    UserTranscriptFinal,
    UserTranscriptPartial,
)


@dataclass(frozen=True, slots=True)
class FakeUserTranscriptPartial:
    text: str


@dataclass(frozen=True, slots=True)
class FakeUserTranscriptFinal:
    text: str


@dataclass(frozen=True, slots=True)
class FakeAssistantAudioChunk:
    audio: bytes
    audio_format: AudioFormat


@dataclass(frozen=True, slots=True)
class FakeSignaledAssistantAudioChunk:
    """Audio item that signals immediately before yielding its normalized event."""

    ready: asyncio.Event
    audio: bytes
    audio_format: AudioFormat


@dataclass(frozen=True, slots=True)
class FakeAssistantTranscriptPartial:
    text: str


@dataclass(frozen=True, slots=True)
class FakeAssistantTranscriptFinal:
    text: str


@dataclass(frozen=True, slots=True)
class FakeRealtimeCompleted:
    pass


@dataclass(frozen=True, slots=True)
class FakeRealtimeFailed:
    error: ProviderError


@dataclass(frozen=True, slots=True)
class FakeRealtimeSessionFailed:
    error: ProviderError


@dataclass(frozen=True, slots=True)
class FakeRealtimePause:
    release: asyncio.Event


@dataclass(frozen=True, slots=True)
class FakeRealtimeBarrier:
    entered: asyncio.Event
    release: asyncio.Event


@dataclass(frozen=True, slots=True)
class FakeUnknownInteractionEvent:
    text: str


@dataclass(frozen=True, slots=True)
class FakeWrongSessionEvent:
    text: str


type FakeRealtimeItem = (
    FakeUserTranscriptPartial
    | FakeUserTranscriptFinal
    | FakeAssistantAudioChunk
    | FakeSignaledAssistantAudioChunk
    | FakeAssistantTranscriptPartial
    | FakeAssistantTranscriptFinal
    | FakeRealtimeCompleted
    | FakeRealtimeFailed
    | FakeRealtimeSessionFailed
    | FakeRealtimePause
    | FakeRealtimeBarrier
    | FakeUnknownInteractionEvent
    | FakeWrongSessionEvent
)


@dataclass(frozen=True, slots=True)
class FakeRealtimeScript:
    items: tuple[FakeRealtimeItem, ...]
    start_barrier: FakeRealtimeBarrier | None = None
    start_error: str | None = None


@dataclass(frozen=True, slots=True)
class FakeRealtimeOpen:
    model: ModelIdentity
    request: RealtimeSessionRequest


class ScriptedFakeRealtimeProvider:
    """No-I/O realtime fake that injects Core IDs only after receiving them."""

    def __init__(self, scripts: Iterable[FakeRealtimeScript] = ()) -> None:
        self._scripts = deque(scripts)
        self._opens: list[FakeRealtimeOpen] = []
        self._sessions: list[ScriptedFakeRealtimeProviderSession] = []

    async def open_realtime_session(
        self, *, model: ModelIdentity, request: RealtimeSessionRequest
    ) -> "ScriptedFakeRealtimeProviderSession":
        self._opens.append(FakeRealtimeOpen(model, request))
        session = ScriptedFakeRealtimeProviderSession(
            request.realtime_session_id, self._scripts
        )
        self._sessions.append(session)
        return session

    def opens(self) -> tuple[FakeRealtimeOpen, ...]:
        return tuple(self._opens)

    def sessions(self) -> tuple["ScriptedFakeRealtimeProviderSession", ...]:
        return tuple(self._sessions)


class ScriptedFakeRealtimeProviderSession:
    def __init__(
        self, session_id: RealtimeSessionId, scripts: deque[FakeRealtimeScript]
    ) -> None:
        self._session_id, self._scripts = session_id, scripts
        self._events: asyncio.Queue[
            tuple[RealtimeInteractionId, FakeRealtimeScript] | None
        ] = asyncio.Queue(maxsize=32)
        self._started: list[RealtimeInteractionId] = []
        self._frames: list[AudioInputFrame] = []
        self._commits: list[RealtimeInteractionId] = []
        self._interrupts: list[RealtimeInteractionId] = []
        self._close_calls = 0
        self._events_consumers = 0
        self._closed = False

    def started_interactions(self) -> tuple[RealtimeInteractionId, ...]:
        return tuple(self._started)

    def frames(self) -> tuple[AudioInputFrame, ...]:
        return tuple(self._frames)

    def commits(self) -> tuple[RealtimeInteractionId, ...]:
        return tuple(self._commits)

    def interrupts(self) -> tuple[RealtimeInteractionId, ...]:
        return tuple(self._interrupts)

    @property
    def close_calls(self) -> int:
        return self._close_calls

    @property
    def events_consumers(self) -> int:
        return self._events_consumers

    async def start_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        if self._closed:
            raise RuntimeError("fake session is closed")
        if not self._scripts:
            raise AssertionError("No realtime script is available")
        script = self._scripts.popleft()
        if script.start_barrier is not None:
            script.start_barrier.entered.set()
            await script.start_barrier.release.wait()
        if script.start_error is not None:
            raise RuntimeError(script.start_error)
        self._started.append(realtime_interaction_id)
        await self._events.put((realtime_interaction_id, script))

    async def send_audio(self, *, frame: AudioInputFrame) -> None:
        self._frames.append(frame)

    async def commit_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        self._commits.append(realtime_interaction_id)

    async def interrupt(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        self._interrupts.append(realtime_interaction_id)

    async def close(self) -> None:
        self._close_calls += 1
        self._closed = True
        await self._events.put(None)

    async def events(self) -> AsyncIterator[RealtimeProviderEvent]:
        self._events_consumers += 1
        if self._events_consumers > 1:
            raise AssertionError("Fake provider session has multiple event consumers")
        sequence = 0
        while True:
            item = await self._events.get()
            if item is None:
                return
            interaction_id, script = item
            for scripted in script.items:
                if isinstance(scripted, FakeRealtimePause):
                    await scripted.release.wait()
                    continue
                if isinstance(scripted, FakeRealtimeBarrier):
                    scripted.entered.set()
                    await scripted.release.wait()
                    continue
                if isinstance(scripted, FakeSignaledAssistantAudioChunk):
                    scripted.ready.set()
                    scripted = FakeAssistantAudioChunk(
                        scripted.audio, scripted.audio_format
                    )
                event = _event(self._session_id, interaction_id, sequence, scripted)
                sequence += 1
                yield event


def _event(
    session_id: RealtimeSessionId,
    interaction_id: RealtimeInteractionId,
    sequence: int,
    item: FakeRealtimeItem,
) -> RealtimeProviderEvent:
    if isinstance(item, FakeUserTranscriptPartial):
        return UserTranscriptPartial(session_id, interaction_id, sequence, item.text)
    if isinstance(item, FakeUserTranscriptFinal):
        return UserTranscriptFinal(session_id, interaction_id, sequence, item.text)
    if isinstance(item, FakeAssistantAudioChunk):
        return AssistantAudioChunk(
            session_id, interaction_id, sequence, item.audio, item.audio_format
        )
    if isinstance(item, FakeAssistantTranscriptPartial):
        return AssistantTranscriptPartial(
            session_id, interaction_id, sequence, item.text
        )
    if isinstance(item, FakeAssistantTranscriptFinal):
        return AssistantTranscriptFinal(session_id, interaction_id, sequence, item.text)
    if isinstance(item, FakeRealtimeCompleted):
        return RealtimeResponseCompleted(session_id, interaction_id, sequence)
    if isinstance(item, FakeRealtimeFailed):
        return RealtimeResponseFailed(session_id, interaction_id, sequence, item.error)
    if isinstance(item, FakeRealtimeSessionFailed):
        return RealtimeSessionFailed(session_id, sequence, item.error)
    if isinstance(item, FakeUnknownInteractionEvent):
        return UserTranscriptPartial(
            session_id, RealtimeInteractionId(uuid4()), sequence, item.text
        )
    if isinstance(item, FakeWrongSessionEvent):
        return UserTranscriptPartial(
            RealtimeSessionId(uuid4()), interaction_id, sequence, item.text
        )
    raise AssertionError("Pause is not an event")
