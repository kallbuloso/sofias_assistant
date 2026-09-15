"""Standalone production Core host: composition and process lifecycle.

This package is the outer composition/lifecycle layer described by
Architecture Review Amendment 0003 SS7 and the AI Runtime Configuration
Contract v1 SS12: it loads and validates bootstrap configuration, bridges
known deployment secrets into `SecretService`, composes the canonical AI
provider and `SofiaCore`, and owns the `sofia-core` process lifecycle. It
intentionally contains no Conversation, Tool, Agent, routing, or Memory
domain logic of its own.
"""
