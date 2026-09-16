"""Persistent AI provider/model/profile configuration and dynamic routing.

Materializes Architecture Review Amendment 0003 / AI Runtime Configuration
Contract v1: non-secret ProviderConfiguration, ModelCatalogEntry,
InferenceProfile and ProfileModelBinding, reconciled discovery, capability
provenance, and an atomically-published `RoutingSnapshot` consumed by
`sofias_assistant.ai.routing_policy.RoutingPolicy`.
"""
