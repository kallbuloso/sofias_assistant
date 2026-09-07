# Architecture Review Amendment 0002

**Project:** Sofia's Assistant  
**Status:** Accepted  
**Decision date:** 2026-09-04  
**Applies to:** ADR-0002, ADR-0005, ADR-0011, ADR-0012, and Technical Backlog
Slice 02  
**Origin:** Sofias Memory v0.3–v0.5 architecture alignment review

---

# 1. Context

The approved Sofias Memory roadmap separates v0.3 Sessions, v0.4 Skills, and
v0.5 Agent Management. Sofia's Assistant must preserve those separate
boundaries while building durable Conversations in Slice 02, without creating
an integration before its APIs and runtime need are approved.

# 2. Decision

Operational execution state remains owned by Sofia's Assistant. Durable
cognitive knowledge, procedures, and provenance remain owned by Sofias Memory.
The roadmap informs stable identity and extension seams; it does not authorize
premature repositories, synchronization, or runtime integrations.

# 3. Authority Matrix

| Authority | Sofia's Assistant | Sofias Memory |
| --- | --- | --- |
| Conversation/Turn | identity, lifecycle, user-visible transcript, provider correlation | no authority over operational transcript |
| Runtime execution | planning/orchestration, provider invocation, streaming, Tool and Skill execution, Agent runtime | no runtime execution authority |
| Context | final ContextBuilder projection | semantic/procedural memory, Recall/provenance, cognitive Session/SessionEntry, knowledge projection |
| Skills | selection, interpretation, execution, Tool/Policy enforcement | definition, revisions, durable storage, semantic resolution, provenance |
| Agents | instantiate/run, Task routing, planning, Tool calls, subagent coordination, provider lifecycle | durable cognitive/profile identity, profile data, Skill/Session/Dataset associations |

# 4. Identity Separation

The following are permanently distinct:

```text
Sofia Conversation != Sofias Memory Session != Provider Session
```

Conversation and Turn UUIDs are Core-owned SQLite identities. A Sofias Memory
Session is cognitive temporal context owned by Sofias Memory. Provider session,
thread, and request IDs are discardable operational correlation owned by a
provider. Neither external identity replaces a Conversation or Turn identity.

# 5. Conversation / Memory Session Correlation

The future external Sofias Memory `session_id` for an ordinary Conversation is
reserved as the deterministic, provider-independent convention:

```text
sofias-assistant:conversation:{conversation_uuid}
```

It is derivable solely from the Conversation UUID, stable across restart, and
calculable while Memory is unavailable. Slice 02 must not add redundant
`memory_session_id`, `memory_session_uuid`, MemorySessionRecord, or repository
storage for that derived value.

# 6. Turn vs SessionEntry

```text
Turn != SessionEntry
```

Turn is authoritative operational runtime history in SQLite. SessionEntry is
selected cognitive context in Sofias Memory. Future integration may explicitly
project committed user input, final assistant output, or selected facts into
SessionEntry; it must not automatically mirror partial streams, failures,
provider/routing events, internal reasoning, Tool traces, or every Turn state.
No one-to-one relationship is assumed.

# 7. Transaction Boundary

Local Conversation/Turn creation, persistence, retrieval, and continuation
must not depend on Sofias Memory availability. An operation whose explicit
semantics require Memory may fail, degrade, or defer under future policy; a
Memory outage must never corrupt or invalidate authoritative SQLite
Conversation/Turn state. No Memory transaction is required to create either
entity and no distributed transaction is introduced. The required future
ordering is:

```text
SQLite transaction
    ↓ commit Sofia operational state
    ↓ close local UoW
    ↓ optional external cognitive operation
```

A Memory call while a SQLite UoW is open is prohibited. Future durable
cross-system operations must use a stable Sofia-owned operation
correlation/idempotency identity derived from durable Sofia identity as
appropriate. A Turn ID may participate in that identity, but this Amendment
does not define the final idempotency-key format. This does not add an outbox,
sync state, or worker now.

# 8. Skills Boundary

Sofias Memory owns Skill definition, revision/versioning, durable storage,
semantic resolution, procedural memory, and provenance. Sofia's Assistant owns
runtime Skill selection, interpretation, execution, Tool invocation, Policy
enforcement, and Task/Agent orchestration.

```text
Skill declared_tools != runtime Tool authorization
```

Skill metadata never grants Tool authority. Slice 02 introduces no Skill
repository, record, runtime, or execution engine.

No `Skill -> exactly one Dataset` ownership is assumed. A future Dataset
association, if any, is optional and does not define Skill identity.

# 9. Agent Profile Boundary

Sofias Memory Agent Profile is durable cognitive/provenance identity and may
contain profile instructions, Skill/Dataset associations, status, and safe
metadata. It is not a Sofia runtime Agent instance. Sofia's Assistant owns
instantiation, execution, planning, Task routing, Tool calls, subagent
coordination, and provider lifecycle.

`agent_id` is cognitive/provenance/composition identity, not cryptographic
identity; it does not imply one API key per Agent or redefine Memory-instance
authentication. An Agent may have an optional default Dataset and multiple
Dataset associations; neither `Conversation -> one Dataset` nor `Agent -> one
Dataset` is assumed. Future presence, heartbeat, or current-session state is
runtime state separate from a durable Memory Agent Profile.

# 10. ContextBuilder Implications

ContextBuilder remains Sofia-owned and produces the final projection. Gate I2
uses current request and eligible recent SQLite Turns. Future explicit seams may
admit Recall, optional Memory Session context, selected Skill procedure, and
Agent Profile instructions alongside Working Memory, Task state, and ToolResults.
Memory augments ContextBuilder; it neither assembles the final prompt nor
replaces Conversation Runtime. No MemoryProvider, Recall/Session/Skill/Profile
client, or generic contributor registry is introduced in Slice 02.

# 11. Idempotency / Correlation Requirement

When an approved future integration writes durable cognitive state after a
local commit, the operation must use a stable Sofia-owned operation
correlation/idempotency identity derived from durable Sofia identity as
appropriate. A Turn ID may participate in that identity, but this Amendment
does not define the final idempotency-key format. This preserves a recovery seam
for a successful external write followed by a crash before local
acknowledgement. Implementation of `memory_synced`, external entry IDs, outbox,
synchronization status, or workers remains deferred.

# 12. Anti-Premature-Abstraction Rule

Knowing the Sofias Memory roadmap does not authorize `SkillRepository`,
`AgentRepository`, `MemorySessionRepository`, or a generic Memory integration
framework in Sofia's Assistant. Prepare stable Core identities, clean
boundaries, deterministic correlation, and small ContextBuilder seams; implement
an integration only when its runtime contract is approved and needed.

# 13. Impact on Current Backlog

SA-B008.1 persists only Sofia-authoritative Conversation/Turn operational
state. SA-B010.1 reserves explicit future ContextBuilder seams. Gate I2 does
not include Memory Session APIs, SessionEntry mirroring, Skills, Agent Profiles,
or any cross-system synchronization.

# 14. Supersession / Precedence

This Amendment complements ADR-0002, ADR-0005, ADR-0011, and ADR-0012; it does
not invalidate their correct existing decisions. For future conflicts concerning
Sofias Memory Sessions, Skills, or Agent Profiles, this Amendment takes
precedence for these refinements.
