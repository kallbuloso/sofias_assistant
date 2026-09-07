"""Immutable value objects for Core-owned context projection."""

from dataclasses import dataclass

from sofias_assistant.ai.contracts import AIMessage


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class CoreSystemContext:
    """Explicitly injected Core-owned identity and system principles."""

    text: str
    cloud_context_eligible: bool

    def __post_init__(self) -> None:
        _require_non_blank(self.text, "text")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")


@dataclass(frozen=True, slots=True)
class ContextProjection:
    """Provider-independent messages selected by the Core for one operation."""

    messages: tuple[AIMessage, ...]
    cloud_context_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, AIMessage) for message in self.messages
        ):
            raise ValueError("messages must be a tuple of AIMessage values")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")
